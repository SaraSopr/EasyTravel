"""
Tourism validation pipeline step.

For each POI fetched from Google Places, decides:
- is_touristic: is this worth visiting as a tourist?
- visit_type: indoor | outdoor | both
- duration_minutes: how long to spend there

Architecture:
- LLM1 always runs and provides a confidence level
- LLM2 only runs when LLM1 confidence = "low" (ambiguous cases)
- Final decision: LLM1 if high confidence, else conservative merge
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.poi import Poi
from app.models.tourism_validation_log import PoiTourismValidationLog

logger = logging.getLogger("pipeline")

# ── Jinja2 ─────────────────────────────────────────────────────────

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_PROMPTS_DIR)),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _render(template_name: str, **kwargs: object) -> str:
    return _jinja_env.get_template(template_name).render(**kwargs).strip()


def _render_llm1_system() -> str:
    return _render("tourism_llm1_system.jinja2")


def _render_llm2_system() -> str:
    return _render("tourism_llm2_system.jinja2")


def _render_poi_user(poi: Poi, city: str) -> str:
    return _render("tourism_poi.jinja2", poi=poi, city=city)


# ── Core validation logic ──────────────────────────────────────────

def _extract_json(raw: str) -> str:
    """Strip markdown fences and extract first JSON object."""
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) > 1 else cleaned
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return cleaned.strip()


async def _call_llm(backend, system_prompt: str, poi: Poi, city_name: str) -> dict:
    """Call LLM and parse JSON response. Returns empty dict on failure."""
    user_message = _render_poi_user(poi, city_name)
    try:
        raw, _in_tok, _out_tok = await backend.complete(system_prompt, user_message)
        return json.loads(_extract_json(raw))
    except Exception as e:
        logger.warning("Tourism LLM call failed for %s: %s", poi.name, e)
        return {}


def _merge_decisions(llm1: dict, llm2: dict) -> tuple[dict, str]:
    """
    Merge LLM1 (low confidence) and LLM2 decisions.
    Returns (final_decision, decision_source).

    Strategy:
    - Both agree → use LLM1 values, average duration
    - Disagree → conservative: not touristic
    """
    t1 = llm1.get("is_touristic")
    t2 = llm2.get("is_touristic")

    # Conservative merge for suitable_for_children: false if either LLM says false
    s1 = llm1.get("suitable_for_children")
    s2 = llm2.get("suitable_for_children")
    suitable = False if (s1 is False or s2 is False) else s1

    if t1 == t2:
        d1 = llm1.get("duration_minutes") or 0
        d2 = llm2.get("duration_minutes") or 0
        duration = int((d1 + d2) / 2) if d1 and d2 else (d1 or d2)
        return {
            "is_touristic": t1,
            "visit_type": llm1.get("visit_type"),
            "duration_minutes": duration,
            "suitable_for_children": suitable,
        }, "llm1"

    # Disagreement → conservative
    return {
        "is_touristic": False,
        "visit_type": None,
        "duration_minutes": None,
        "suitable_for_children": suitable,
    }, "disagreement"


async def validate_poi_tourism(
    poi: Poi,
    city_name: str,
    backend,
) -> tuple[dict, dict, dict | None]:
    """
    Run tourism validation for a single POI.

    Returns:
    - llm1_result: raw LLM1 output dict
    - final_decision: {is_touristic, visit_type, duration_minutes, source}
    - llm2_result: raw LLM2 output dict (None if not called)
    """
    llm1 = await _call_llm(backend, _render_llm1_system(), poi, city_name)

    if not llm1:
        return llm1, {
            "is_touristic": None,
            "visit_type": None,
            "duration_minutes": None,
            "source": "failed",
        }, None

    confidence = llm1.get("confidence", "low")
    llm2 = None
    source = "llm1"

    if confidence == "low":
        logger.debug("  LLM1 low confidence for %s → calling LLM2", poi.name)
        await asyncio.sleep(0.3)  # light rate limiting between LLM1 and LLM2
        llm2 = await _call_llm(backend, _render_llm2_system(), poi, city_name)
        if llm2:
            final, source = _merge_decisions(llm1, llm2)
        else:
            # LLM2 failed → conservative fallback
            final = {"is_touristic": False, "visit_type": None, "duration_minutes": None}
            source = "llm1_fallback"
    else:
        final = {
            "is_touristic": llm1.get("is_touristic"),
            "visit_type": llm1.get("visit_type"),
            "duration_minutes": llm1.get("duration_minutes"),
            "suitable_for_children": llm1.get("suitable_for_children"),
        }

    final["source"] = source
    return llm1, final, llm2


async def validate_tourism_batch(
    session: AsyncSession,
    city_id: UUID,
    city_name: str,
    backend,
    pipeline_run_id: str,
    batch_size: int = 5,
    rate_limit_sleep: float = 0.5,
) -> tuple[int, int, int]:
    """
    Run tourism validation for all unvalidated POIs in a city
    (tourism_validated_at IS NULL).

    Returns (validated, already_done, failed) counts.
    """
    result = await session.execute(
        select(Poi)
        .where(Poi.city_id == city_id)
        .where(Poi.tourism_validated_at.is_(None))
    )
    pois = result.scalars().all()

    if not pois:
        logger.info("  → All POIs already tourism-validated")
        return 0, 0, 0

    logger.info("  → Tourism validating %d POIs for %s...", len(pois), city_name)

    validated = 0
    failed = 0

    for i, poi in enumerate(pois):
        logger.info("  [%d/%d] %s", i + 1, len(pois), poi.name)

        llm1_result, final_decision, llm2_result = await validate_poi_tourism(
            poi=poi,
            city_name=city_name,
            backend=backend,
        )

        source = final_decision.get("source", "failed")

        if source == "failed":
            # LLM1 completely failed → leave tourism_validated_at as None for retry
            failed += 1
            logger.warning("    Tourism validation failed for %s", poi.name)
        else:
            poi.is_touristic = final_decision.get("is_touristic")
            poi.tourism_visit_type = final_decision.get("visit_type")
            poi.tourism_duration_minutes = final_decision.get("duration_minutes")
            poi.suitable_for_children = final_decision.get("suitable_for_children")
            poi.tourism_validated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.add(poi)
            validated += 1

            session.add(PoiTourismValidationLog(
                poi_id=poi.id,
                poi_name=poi.name,
                poi_types=", ".join(poi.types or []),
                poi_rating=poi.rating,
                poi_ratings_total=poi.user_ratings_total,
                city_name=city_name,
                pipeline_run_id=pipeline_run_id,
                llm1_is_touristic=llm1_result.get("is_touristic"),
                llm1_visit_type=llm1_result.get("visit_type"),
                llm1_duration_minutes=llm1_result.get("duration_minutes"),
                llm1_confidence=llm1_result.get("confidence"),
                llm1_reasoning=llm1_result.get("reasoning"),
                llm1_suitable_for_children=llm1_result.get("suitable_for_children"),
                llm2_is_touristic=llm2_result.get("is_touristic") if llm2_result else None,
                llm2_visit_type=llm2_result.get("visit_type") if llm2_result else None,
                llm2_duration_minutes=llm2_result.get("duration_minutes") if llm2_result else None,
                llm2_reasoning=llm2_result.get("reasoning") if llm2_result else None,
                llm2_suitable_for_children=llm2_result.get("suitable_for_children") if llm2_result else None,
                llm2_was_needed=llm2_result is not None,
                final_is_touristic=final_decision.get("is_touristic"),
                final_visit_type=final_decision.get("visit_type"),
                final_duration_minutes=final_decision.get("duration_minutes"),
                final_suitable_for_children=final_decision.get("suitable_for_children"),
                decision_source=source,
            ))

        if (i + 1) % batch_size == 0:
            await session.commit()
            logger.info("  Checkpoint: %d/%d validated", i + 1, len(pois))

        await asyncio.sleep(rate_limit_sleep)

    await session.commit()
    logger.info(
        "  → Tourism validation complete: %d validated, %d failed",
        validated, failed,
    )
    return validated, 0, failed
