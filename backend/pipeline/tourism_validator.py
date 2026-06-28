"""
Tourism validation pipeline step.

For each POI fetched from Google Places, decides:
- is_touristic: is this worth visiting as a tourist?
- visit_type: indoor | outdoor | both
- duration_minutes: how long to spend there

Architecture:
- LLM1 batch: sends up to TOURISM_BATCH_SIZE POIs per call, returns array
- LLM2 batch: second pass only for POIs that came back "low" confidence
- Final decision: LLM1 if high confidence, else conservative merge of LLM1+LLM2
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

TOURISM_BATCH_SIZE = 10

# ── Jinja2 ─────────────────────────────────────────────────────────

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_PROMPTS_DIR)),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _render(template_name: str, **kwargs: object) -> str:
    return _jinja_env.get_template(template_name).render(**kwargs).strip()


def _render_llm1_batch_system() -> str:
    return _render("tourism_batch_system.jinja2")


def _render_llm2_batch_system() -> str:
    return _render("tourism_batch_llm2_system.jinja2")


def _render_batch_pois(pois: list[Poi], city_name: str) -> str:
    return _render("tourism_batch_pois.jinja2", pois=pois, city=city_name)


# ── JSON schema ────────────────────────────────────────────────────

def _batch_response_format(include_confidence: bool = True) -> dict | None:
    from app.config import settings
    if not (settings.openai_structured_output and settings.pipeline_llm_backend == "openai"):
        return None
    item: dict = {
        "type": "object",
        "properties": {
            "is_touristic": {"type": "boolean"},
            "visit_type": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "duration_minutes": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "suitable_for_children": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
            "reasoning": {"type": "string"},
        },
        "required": ["is_touristic", "visit_type", "duration_minutes", "suitable_for_children", "reasoning"],
        "additionalProperties": False,
    }
    if include_confidence:
        item["properties"]["confidence"] = {"type": "string"}
        item["required"] = [*item["required"], "confidence"]
    schema = {
        "type": "object",
        "properties": {"results": {"type": "array", "items": item}},
        "required": ["results"],
        "additionalProperties": False,
    }
    name = "poi_tourism_batch" if include_confidence else "poi_tourism_batch_llm2"
    return {"type": "json_schema", "name": name, "schema": schema, "strict": True}


# ── Core helpers ───────────────────────────────────────────────────

def _extract_json(raw: str) -> str:
    """Strip markdown fences and extract first JSON object."""
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) > 1 else cleaned
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return cleaned.strip()


def _merge_decisions(llm1: dict, llm2: dict) -> tuple[dict, str]:
    """
    Merge LLM1 (low confidence) and LLM2 decisions.
    Returns (final_decision, decision_source).

    - Both agree → use LLM1 values, average duration
    - Disagree → conservative: not touristic
    """
    t1 = llm1.get("is_touristic")
    t2 = llm2.get("is_touristic")

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

    return {
        "is_touristic": False,
        "visit_type": None,
        "duration_minutes": None,
        "suitable_for_children": suitable,
    }, "disagreement"


async def _call_llm_batch(
    backend,
    system_prompt: str,
    pois: list[Poi],
    city_name: str,
    response_format: dict | None,
) -> list[dict]:
    """Send a batch of POIs to the LLM. Returns one dict per POI (empty dict on failure)."""
    n = len(pois)
    user_message = _render_batch_pois(pois, city_name)
    try:
        raw, _in_tok, _out_tok = await backend.complete(
            system_prompt, user_message, response_format=response_format
        )
        data = json.loads(_extract_json(raw))
        results = data if isinstance(data, list) else data.get("results", [])
        if len(results) != n:
            logger.warning("Batch returned %d results for %d POIs — padding/trimming", len(results), n)
        while len(results) < n:
            results.append({})
        return results[:n]
    except Exception as e:
        logger.warning("Tourism batch LLM call failed: %s", e)
        return [{} for _ in range(n)]


def _apply_poi_result(
    poi: Poi,
    decision: dict,
    source: str,
    session: AsyncSession,
    pipeline_run_id: str,
    llm1_result: dict,
    llm2_result: dict | None,
    city_name: str = "",
) -> None:
    poi.is_touristic = decision.get("is_touristic")
    poi.tourism_visit_type = decision.get("visit_type")
    poi.tourism_duration_minutes = decision.get("duration_minutes")
    poi.suitable_for_children = decision.get("suitable_for_children")
    poi.tourism_validated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    session.add(poi)

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
        final_is_touristic=decision.get("is_touristic"),
        final_visit_type=decision.get("visit_type"),
        final_duration_minutes=decision.get("duration_minutes"),
        final_suitable_for_children=decision.get("suitable_for_children"),
        decision_source=source,
    ))

    logger.debug(
        "    → touristic=%s | type=%s | duration=%smin | children=%s (via %s)",
        poi.is_touristic,
        poi.tourism_visit_type,
        poi.tourism_duration_minutes,
        poi.suitable_for_children,
        source,
    )


# ── Public API ─────────────────────────────────────────────────────

async def validate_tourism_batch(
    session: AsyncSession,
    city_id: UUID,
    city_name: str,
    backend,
    pipeline_run_id: str,
    batch_size: int = TOURISM_BATCH_SIZE,
    rate_limit_sleep: float = 0.5,
) -> tuple[int, int, int]:
    """
    Run tourism validation for all unvalidated POIs in a city in batches.

    Each LLM call processes `batch_size` POIs at once.
    Low-confidence POIs from the first pass get a second LLM review.

    Returns (validated, already_done, failed) counts.
    """
    result = await session.execute(
        select(Poi)
        .where(Poi.city_id == city_id)
        .where(Poi.tourism_validated_at.is_(None))
    )
    pois = list(result.scalars().all())

    if not pois:
        logger.info("  → All POIs already tourism-validated")
        return 0, 0, 0

    logger.info("  → Tourism validating %d POIs for %s (batch_size=%d)...", len(pois), city_name, batch_size)

    system_llm1 = _render_llm1_batch_system()
    system_llm2 = _render_llm2_batch_system()
    fmt_llm1 = _batch_response_format(include_confidence=True)
    fmt_llm2 = _batch_response_format(include_confidence=False)

    validated = 0
    failed = 0
    low_confidence: list[tuple[Poi, dict]] = []  # (poi, llm1_result) for second pass

    # ── Pass 1: LLM1 batch ──────────────────────────────────────
    for batch_start in range(0, len(pois), batch_size):
        chunk = pois[batch_start : batch_start + batch_size]
        end_idx = min(batch_start + batch_size, len(pois))
        logger.info("  [%d–%d / %d] LLM1 batch (%d POIs)...", batch_start + 1, end_idx, len(pois), len(chunk))

        llm1_results = await _call_llm_batch(backend, system_llm1, chunk, city_name, fmt_llm1)

        for poi, llm1 in zip(chunk, llm1_results):
            if not llm1:
                failed += 1
                logger.warning("    LLM1 failed for %s", poi.name)
                continue

            confidence = llm1.get("confidence", "low")
            if confidence == "low":
                low_confidence.append((poi, llm1))
                logger.debug("    [low] %s → queued for LLM2", poi.name)
            else:
                final = {
                    "is_touristic": llm1.get("is_touristic"),
                    "visit_type": llm1.get("visit_type"),
                    "duration_minutes": llm1.get("duration_minutes"),
                    "suitable_for_children": llm1.get("suitable_for_children"),
                }
                _apply_poi_result(poi, final, "llm1", session, pipeline_run_id, llm1, None, city_name)
                validated += 1

        await session.commit()
        await asyncio.sleep(rate_limit_sleep)

    # ── Pass 2: LLM2 batch for low-confidence POIs ──────────────
    if low_confidence:
        logger.info("  → Second pass: %d low-confidence POIs", len(low_confidence))

        for batch_start in range(0, len(low_confidence), batch_size):
            chunk_pairs = low_confidence[batch_start : batch_start + batch_size]
            chunk_pois = [p for p, _ in chunk_pairs]
            end_idx = min(batch_start + batch_size, len(low_confidence))
            logger.info(
                "  [%d–%d / %d] LLM2 batch (%d POIs)...",
                batch_start + 1, end_idx, len(low_confidence), len(chunk_pois),
            )

            llm2_results = await _call_llm_batch(backend, system_llm2, chunk_pois, city_name, fmt_llm2)

            for (poi, llm1), llm2 in zip(chunk_pairs, llm2_results):
                if llm2:
                    final, source = _merge_decisions(llm1, llm2)
                else:
                    final = {"is_touristic": False, "visit_type": None, "duration_minutes": None, "suitable_for_children": llm1.get("suitable_for_children")}
                    source = "llm1_fallback"
                    logger.warning("    LLM2 failed for %s — conservative fallback", poi.name)

                _apply_poi_result(poi, final, source, session, pipeline_run_id, llm1, llm2 or None, city_name)
                validated += 1

            await session.commit()
            await asyncio.sleep(rate_limit_sleep)

    logger.info(
        "  → Tourism validation complete: %d validated, %d low-conf second pass, %d failed",
        validated, len(low_confidence), failed,
    )
    return validated, 0, failed
