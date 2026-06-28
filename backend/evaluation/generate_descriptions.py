"""Fill in one-line place descriptions for POIs shown in the evaluation dashboard.

Google's ``editorialSummary`` is empty for ~all of our POIs, so the pairwise cards
have no place description for the human evaluator to read. This script generates a
short Italian tourist description with the pipeline LLM, but ONLY for the POIs that
actually appear in the human-eval data (pairs + Likert itinerary stops) — cheap and
targeted. The text is stored in our own ``Poi.description`` column (separate from
Google's ``editorial_summary`` for provenance).

To keep the LLM cost low it generates in **batches of 15 POIs per call** and forces
a strict JSON schema (OpenAI structured outputs), so one request returns all the
descriptions for the batch. Idempotent: POIs that already have a description are
skipped unless ``--overwrite``.

    PYTHONPATH=. python -m evaluation.generate_descriptions
    PYTHONPATH=. python -m evaluation.generate_descriptions --overwrite
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import uuid

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.city import City
from app.models.evaluation import EvaluationItinerary, EvaluationPair
from app.models.poi import Poi
from pipeline.llm_client import get_backend

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE = 15

_SYSTEM = (
    "Sei una guida turistica esperta. Per ciascun luogo numerato scrivi UNA sola frase "
    "in italiano (massimo 22 parole) che spieghi cos'è e perché vale la pena visitarlo: "
    "concreta, non generica, senza preamboli, senza virgolette e senza ripetere il nome "
    "all'inizio. Rispondi SOLO con il JSON richiesto, una voce per ogni indice ricevuto."
)

# Strict JSON schema (OpenAI structured outputs via the Responses API text.format).
_RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "poi_descriptions",
    "schema": {
        "type": "object",
        "properties": {
            "descriptions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "description": {"type": "string"},
                    },
                    "required": ["index", "description"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["descriptions"],
        "additionalProperties": False,
    },
    "strict": True,
}


def _poi_line(idx: int, poi: Poi, city: str) -> str:
    bits = [f"Nome: {poi.name}", f"Città: {city}"]
    if poi.travel_category:
        bits.append(f"Categoria: {poi.travel_category}")
    if poi.primary_type:
        bits.append(f"Tipo: {poi.primary_type}")
    elif poi.types:
        bits.append(f"Tipo: {poi.types[0]}")
    if poi.address:
        bits.append(f"Indirizzo: {poi.address}")
    return f"{idx}. " + " | ".join(bits)


async def _eval_poi_ids(db) -> set[uuid.UUID]:
    """Distinct POI ids shown anywhere in the human-eval data (pairs + itineraries)."""
    ids: set[uuid.UUID] = set()
    for a, b in (await db.execute(select(EvaluationPair.poi_a_id, EvaluationPair.poi_b_id))).all():
        ids.add(a)
        ids.add(b)
    for payload in (await db.execute(select(EvaluationItinerary.payload_json))).scalars().all():
        for day in (payload or {}).get("days", []):
            for stop in day.get("stops", []):
                pid = stop.get("poi_id")
                if pid:
                    ids.add(uuid.UUID(pid) if isinstance(pid, str) else pid)
    return ids


async def main(overwrite: bool) -> None:
    backend = get_backend(
        settings.pipeline_llm_backend,
        settings.pipeline_llm_model,
        reasoning_effort=settings.pipeline_reasoning_effort,
    )
    async with AsyncSessionLocal() as db:
        ids = await _eval_poi_ids(db)
        if not ids:
            logger.info("No evaluation POIs found — run the harness first (run_eval.py).")
            return
        pois = (await db.execute(select(Poi).where(Poi.id.in_(ids)))).scalars().all()
        cities = {c.id: c.name for c in (await db.execute(select(City))).scalars().all()}

        todo = [p for p in pois if overwrite or not (p.description or "").strip()]
        logger.info(
            "Eval POIs: %d total, %d need a description → %d LLM call(s) of %d.",
            len(pois), len(todo), (len(todo) + BATCH_SIZE - 1) // BATCH_SIZE, BATCH_SIZE,
        )

        in_tok = out_tok = filled = 0
        for start in range(0, len(todo), BATCH_SIZE):
            batch = todo[start:start + BATCH_SIZE]
            user = "Luoghi:\n" + "\n".join(
                _poi_line(i, p, cities.get(p.city_id, "")) for i, p in enumerate(batch, 1)
            )
            try:
                raw, ti, to = await backend.complete(_SYSTEM, user, response_format=_RESPONSE_FORMAT)
                in_tok += ti
                out_tok += to
                by_index = {
                    int(d["index"]): (d["description"] or "").strip().strip('"')
                    for d in json.loads(raw).get("descriptions", [])
                }
                for i, poi in enumerate(batch, 1):
                    desc = by_index.get(i)
                    if desc:
                        poi.description = desc
                        db.add(poi)
                        filled += 1
                        logger.info("  %-30s → %s", poi.name[:30], desc[:64])
                    else:
                        logger.warning("  %-30s → MISSING in response", poi.name[:30])
                await db.commit()
            except Exception as exc:
                logger.warning("  batch starting at %d FAILED: %s", start, exc)
        logger.info("Done. filled=%d tokens in=%d out=%d", filled, in_tok, out_tok)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--overwrite", action="store_true", help="regenerate even if a description exists")
    asyncio.run(main(ap.parse_args().overwrite))
