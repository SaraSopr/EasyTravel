from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.classification_log import PoiClassificationLog
from app.models.poi import Poi
from pipeline.llm_client import LLMBackend
from pipeline.utils import normalize_vector, validate_vector

logger = logging.getLogger(__name__)

MAX_RETRIES = 2


def _extract_json(raw: str) -> str:
    """Strip <think>...</think> blocks and extract the first JSON object or array.

    Uses a depth counter rather than greedy regex to handle nested structures correctly.
    Handles DeepSeek R1 / r1-1776 responses that prepend chain-of-thought reasoning.
    """
    # Remove <think>...</think> blocks (including multiline)
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    # Find the first JSON object or array using depth-counter scanning
    for start, opener, closer in (
        (cleaned.find("["), "[", "]"),
        (cleaned.find("{"), "{", "}"),
    ):
        if start == -1:
            continue
        depth = 0
        in_string = False
        escape_next = False
        for i, ch in enumerate(cleaned[start:], start=start):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    return cleaned[start : i + 1]
        break  # opener found but unbalanced — fall through to returning cleaned

    return cleaned


# ──────────────────────────────────────────────────────────────
# Jinja2
# ──────────────────────────────────────────────────────────────

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_PROMPTS_DIR)),
    trim_blocks=True,
    lstrip_blocks=True,
)
_jinja_env.filters["tojson"] = json.dumps


def _render(template_name: str, **kwargs: object) -> str:
    return _jinja_env.get_template(template_name).render(**kwargs).strip()


def _render_classify_batch_system() -> str:
    return _render("classify_system.jinja2", batch=True)


# OpenAI structured-output schema for batch classification (root must be an object,
# so the array of per-POI results is wrapped under "results").
_CATEGORY_ENUM = ["culture", "nature", "food", "adventure", "nightlife", "relax", "family"]


def _classify_response_format() -> dict:
    item = {
        "type": "object",
        "properties": {
            "travel_category": {"type": "string", "enum": _CATEGORY_ENUM},
            "feature_vector": {"type": "array", "items": {"type": "number"}},
            "is_indoor_visitable": {"type": "boolean"},
            "reasoning": {"type": "string"},
        },
        "required": ["travel_category", "feature_vector", "is_indoor_visitable", "reasoning"],
        "additionalProperties": False,
    }
    schema = {
        "type": "object",
        "properties": {"results": {"type": "array", "items": item}},
        "required": ["results"],
        "additionalProperties": False,
    }
    return {"type": "json_schema", "name": "poi_classification", "schema": schema, "strict": True}


def _render_arbitrate_system() -> str:
    return _render("arbitrate_system.jinja2")


def _render_classify_batch(pois: list[Poi]) -> str:
    return _render("classify_batch.jinja2", pois=pois)


def _render_arbitrate_batch(
    pois: list[Poi],
    r1_list: list[dict],
    r2_list: list[dict],
) -> str:
    items = [
        {
            "name": poi.name,
            "address": poi.address,
            "types": poi.types,
            "result1": r1,
            "result2": r2,
            "cat1": r1.get("travel_category", "unknown"),
            "cat2": r2.get("travel_category", "unknown"),
        }
        for poi, r1, r2 in zip(pois, r1_list, r2_list)
    ]
    return _render("arbitrate_batch.jinja2", items=items)


def _arbitrate_response_format() -> dict:
    item = {
        "type": "object",
        "properties": {
            "travel_category": {"type": "string", "enum": _CATEGORY_ENUM},
            "feature_vector": {"type": "array", "items": {"type": "number"}},
            "is_indoor_visitable": {"type": "boolean"},
            "confidence": {"type": "string"},
            "reasoning": {"type": "string"},
        },
        "required": ["travel_category", "feature_vector", "is_indoor_visitable", "confidence", "reasoning"],
        "additionalProperties": False,
    }
    schema = {
        "type": "object",
        "properties": {"results": {"type": "array", "items": item}},
        "required": ["results"],
        "additionalProperties": False,
    }
    return {"type": "json_schema", "name": "poi_arbitration", "schema": schema, "strict": True}


# ──────────────────────────────────────────────────────────────
# LLM call logging
# ──────────────────────────────────────────────────────────────

# ContextVar so concurrent pipeline runs for different cities keep separate log paths.
_llm_log_path_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_llm_log_path", default=None
)


def setup_llm_log(city: str, date: str) -> None:
    os.makedirs("logs", exist_ok=True)
    _llm_log_path_var.set(f"logs/llm_calls_{city}_{date}.jsonl")


def _write_llm_log(entry: dict) -> None:
    path = _llm_log_path_var.get()
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _log_llm_call(
    *,
    role: str,
    poi: object,
    backend: LLMBackend,
    system: str,
    user: str,
    response: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    latency_ms: int,
    attempt: int,
    error: str | None,
) -> None:
    _write_llm_log({
        "ts": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "poi": poi,
        "model": backend.model,
        "system": system,
        "user": user,
        "response": response,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
        "attempt": attempt,
        "error": error,
    })


# ──────────────────────────────────────────────────────────────
# Core LLM call
# ──────────────────────────────────────────────────────────────

async def _call_llm(
    backend: LLMBackend,
    system: str,
    user: str,
    role: str = "classifier",
    poi_name: str = "",
) -> dict | None:
    for attempt in range(MAX_RETRIES + 1):
        t0 = time.monotonic()
        raw: str | None = None
        try:
            raw, in_tok, out_tok = await backend.complete(system, user)
            latency_ms = int((time.monotonic() - t0) * 1000)
            _log_llm_call(role=role, poi=poi_name, backend=backend, system=system, user=user,
                          response=raw, input_tokens=in_tok, output_tokens=out_tok,
                          latency_ms=latency_ms, attempt=attempt + 1, error=None)
            return json.loads(_extract_json(raw))

        except json.JSONDecodeError as e:
            _log_llm_call(role=role, poi=poi_name, backend=backend, system=system, user=user,
                          response=raw or "", input_tokens=None, output_tokens=None,
                          latency_ms=int((time.monotonic() - t0) * 1000),
                          attempt=attempt + 1, error=f"JSONDecodeError: {e}")
            logger.warning(f"JSON parse error for '{poi_name}' (attempt {attempt + 1}): {e}")

        except Exception as e:
            _log_llm_call(role=role, poi=poi_name, backend=backend, system=system, user=user,
                          response=None, input_tokens=None, output_tokens=None,
                          latency_ms=int((time.monotonic() - t0) * 1000),
                          attempt=attempt + 1, error=str(e))
            is_rate_limit = "429" in str(e) or "rate_limit" in str(e).lower()
            logger.warning(f"LLM call error for '{poi_name}' (attempt {attempt + 1}): {e}")
            if attempt < MAX_RETRIES:
                sleep_s = 60 if is_rate_limit else 2 ** attempt
                if is_rate_limit:
                    logger.info(f"Rate limit hit — sleeping {sleep_s}s before retry")
                await asyncio.sleep(sleep_s)

    return None


# ──────────────────────────────────────────────────────────────
# Batch LLM call
# ──────────────────────────────────────────────────────────────

async def _call_llm_batch(
    backend: LLMBackend,
    system: str,
    user: str,
    expected_count: int,
    role: str = "classifier_batch",
    poi_names: list[str] | None = None,
    response_format: dict | None = None,
) -> list[dict | None] | None:
    """Call LLM expecting a JSON array of `expected_count` items."""
    for attempt in range(MAX_RETRIES + 1):
        t0 = time.monotonic()
        raw: str | None = None
        try:
            raw, in_tok, out_tok = await backend.complete(system, user, response_format=response_format)
            latency_ms = int((time.monotonic() - t0) * 1000)
            _log_llm_call(role=role, poi=poi_names, backend=backend, system=system, user=user,
                          response=raw, input_tokens=in_tok, output_tokens=out_tok,
                          latency_ms=latency_ms, attempt=attempt + 1, error=None)

            parsed = json.loads(_extract_json(raw))
            # Structured output wraps the array in {"results": [...]} (root must be object).
            if isinstance(parsed, dict) and "results" in parsed:
                parsed = parsed["results"]
            if not isinstance(parsed, list):
                raise ValueError(f"Atteso JSON array, ricevuto {type(parsed).__name__}")

            # pad/trim to expected length
            while len(parsed) < expected_count:
                parsed.append(None)
            return parsed[:expected_count]

        except (json.JSONDecodeError, ValueError) as e:
            _log_llm_call(role=role, poi=poi_names, backend=backend, system=system, user=user,
                          response=raw or "", input_tokens=None, output_tokens=None,
                          latency_ms=int((time.monotonic() - t0) * 1000),
                          attempt=attempt + 1, error=str(e))
            logger.warning(f"Batch parse error (attempt {attempt + 1}): {e}")

        except Exception as e:
            _log_llm_call(role=role, poi=poi_names, backend=backend, system=system, user=user,
                          response=None, input_tokens=None, output_tokens=None,
                          latency_ms=int((time.monotonic() - t0) * 1000),
                          attempt=attempt + 1, error=str(e))
            is_rate_limit = "429" in str(e) or "rate_limit" in str(e).lower()
            logger.warning(f"Batch LLM error (attempt {attempt + 1}): {e}")
            if attempt < MAX_RETRIES:
                sleep_s = 60 if is_rate_limit else 2 ** attempt
                if is_rate_limit:
                    logger.info(f"Rate limit hit — sleeping {sleep_s}s before retry")
                await asyncio.sleep(sleep_s)

    return None


# ──────────────────────────────────────────────────────────────
# Vector metrics
# ──────────────────────────────────────────────────────────────

def _cosine_distance(v1: list[float], v2: list[float]) -> float:
    """Cosine distance between two vectors (0=identical, 1=opposite).
    Returns 1.0 if either vector is invalid or zero-norm.
    """
    try:
        a, b = np.array(v1, dtype=float), np.array(v2, dtype=float)
        norm = np.linalg.norm(a) * np.linalg.norm(b)
        if norm == 0:
            return 1.0
        return float(1.0 - np.dot(a, b) / norm)
    except Exception:
        return 1.0


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

async def classify_batch(
    pois: list[Poi],
    backend: LLMBackend,
    session: AsyncSession | None = None,
    city_name: str | None = None,
    pipeline_run_id: str | None = None,
) -> list[dict]:
    """Classify a batch of POIs with 2 parallel LLM calls + per-POI arbitration on disagreement.

    Returns a list of dicts (same order as input), each with travel_category, feature_vector, confidence.
    If session is provided, saves a PoiClassificationLog row per POI for evaluation.
    """
    if not pois:
        return []

    system = _render_classify_batch_system()
    user = _render_classify_batch(pois)
    n = len(pois)
    poi_names = [p.name for p in pois]

    from app.config import settings as _settings
    response_format = (
        _classify_response_format()
        if _settings.openai_structured_output and _settings.pipeline_llm_backend == "openai"
        else None
    )

    r1_list, r2_list = await asyncio.gather(
        _call_llm_batch(backend, system, user, n, role="llm1_batch", poi_names=poi_names, response_format=response_format),
        _call_llm_batch(backend, system, user, n, role="llm2_batch", poi_names=poi_names, response_format=response_format),
    )

    results: list[dict | None] = [None] * n
    # Per-POI raw LLM outputs — kept for logging
    r1_per_poi: list[dict] = [{}] * n
    r2_per_poi: list[dict] = [{}] * n
    r3_per_poi: list[dict] = [{}] * n

    arb_indices: list[int] = []
    arb_r1: list[dict] = []
    arb_r2: list[dict] = []

    for i, poi in enumerate(pois):
        r1 = (r1_list[i] if r1_list else None) or {}
        r2 = (r2_list[i] if r2_list else None) or {}

        if not r1 and not r2:
            results[i] = {"travel_category": None, "feature_vector": None, "confidence": "failed"}
            continue

        r1 = r1 or r2
        r2 = r2 or r1

        r1_per_poi[i] = r1
        r2_per_poi[i] = r2

        cat1, cat2 = r1.get("travel_category"), r2.get("travel_category")
        vec1, vec2 = r1.get("feature_vector", []), r2.get("feature_vector", [])

        if cat1 == cat2 and validate_vector(vec1) and validate_vector(vec2):
            avg_vec = normalize_vector([(a + b) / 2 for a, b in zip(vec1, vec2)])
            results[i] = {"travel_category": cat1, "feature_vector": avg_vec, "confidence": "high"}
        else:
            logger.debug(f"  Disagreement for '{poi.name}': {cat1} vs {cat2}, queuing arbitration")
            arb_indices.append(i)
            arb_r1.append(r1)
            arb_r2.append(r2)

    if arb_indices:
        arb_pois = [pois[i] for i in arb_indices]
        arb_poi_names = [pois[i].name for i in arb_indices]
        arb_fmt = (
            _arbitrate_response_format()
            if _settings.openai_structured_output and _settings.pipeline_llm_backend == "openai"
            else None
        )
        logger.debug("  Arbitrating %d disagreements in one batch call", len(arb_indices))
        arb_list = await _call_llm_batch(
            backend,
            _render_arbitrate_system(),
            _render_arbitrate_batch(arb_pois, arb_r1, arb_r2),
            len(arb_indices),
            role="llm3_arbitrator_batch",
            poi_names=arb_poi_names,
            response_format=arb_fmt,
        )
        arb_results = arb_list or [None] * len(arb_indices)

        for idx, r3, r1 in zip(arb_indices, arb_results, arb_r1):
            r3 = r3 or r1
            # Guard: LLM may return a list instead of a dict
            if isinstance(r3, list):
                r3 = r3[0] if r3 else {}
            if not isinstance(r3, dict):
                r3 = r1 or {}
            r3_per_poi[idx] = r3
            cat3 = r3.get("travel_category")
            vec3 = r3.get("feature_vector", [])
            if vec3 and not validate_vector(vec3):
                vec3 = normalize_vector(vec3)
            if not vec3 or not validate_vector(vec3):
                results[idx] = {"travel_category": cat3, "feature_vector": None, "confidence": "failed"}
            else:
                results[idx] = {"travel_category": cat3, "feature_vector": vec3, "confidence": "medium"}

    final_results = [r or {"travel_category": None, "feature_vector": None, "confidence": "failed"} for r in results]

    # ── Logging ─────────────────────────────────────────────────────
    if session is not None:
        for poi, r1, r2, r3, final in zip(pois, r1_per_poi, r2_per_poi, r3_per_poi, final_results):
            v1 = r1.get("feature_vector") or []
            v2 = r2.get("feature_vector") or []
            log = PoiClassificationLog(
                poi_id=poi.id,
                poi_name=poi.name,
                llm1_category=r1.get("travel_category"),
                llm1_vector=v1 or None,
                llm1_is_indoor=r1.get("is_indoor_visitable"),
                llm1_reasoning=r1.get("reasoning"),
                llm2_category=r2.get("travel_category"),
                llm2_vector=v2 or None,
                llm2_is_indoor=r2.get("is_indoor_visitable"),
                llm2_reasoning=r2.get("reasoning"),
                llm3_final_category=r3.get("travel_category") if r3 else None,
                llm3_final_vector=r3.get("feature_vector") if r3 else None,
                llm3_final_is_indoor=r3.get("is_indoor_visitable") if r3 else None,
                llm3_confidence=r3.get("confidence") if r3 else None,
                llm3_reasoning=r3.get("reasoning") if r3 else None,
                category_agreement=(
                    r1.get("travel_category") == r2.get("travel_category")
                    if r1 or r2 else None
                ),
                vector_cosine_distance=_cosine_distance(v1, v2) if v1 and v2 else None,
                final_category=final.get("travel_category"),
                final_confidence=final.get("confidence"),
                city_name=city_name,
                pipeline_run_id=pipeline_run_id,
            )
            session.add(log)
        await session.commit()

    return final_results
