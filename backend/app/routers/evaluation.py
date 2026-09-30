"""Human-evaluation dashboard API (see docs/evaluation-harness-spec.md §7).

No auth — evaluators are identified by a free ``evaluator`` id passed in the query.
Blindness is enforced server-side: pair options are returned in randomised order
and the solver name is never sent to the client.
"""
from __future__ import annotations

import csv
import io
import random
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.evaluation import (
    EvaluationItinerary,
    EvaluationLikert,
    EvaluationPair,
    EvaluationRating,
)
from app.models.poi import Poi
from evaluation import config as eval_cfg
from evaluation.profiles import PROFILES_BY_KEY

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


async def _assigned_pair_ids(
    db: AsyncSession, evaluator: str, batch_size: int, city: str | None = None,
) -> list[uuid.UUID]:
    """This evaluator's fixed assignment: ``batch_size`` pair ids total — the shared
    calibration set first, then this evaluator's own deterministic shuffle of the
    rest. A rater is only ever asked to cover their own assignment, never the whole
    pool: stable across reloads (same inputs → same list) regardless of how many of
    it they've rated so far, so "how many of MY 30" is a fixed, meaningful fraction
    instead of drifting as the pool or rating progress changes.

    ``city``: if given (the evaluator's self-reported "city I know best"), both the
    calibration slice and the personal batch are restricted to that city's pairs —
    a rater who has never been to Porto can't meaningfully judge two Porto POIs
    against each other.

    One DB round trip: the whole table is ~1k tiny rows, cheap to pull in full and
    bucket/filter in Python — each remote-DB round trip costs far more here than
    the extra rows, and this is on the hot path of every ``/pairs`` fetch.
    """
    res = await db.execute(select(EvaluationPair.id, EvaluationPair.pair_type, EvaluationPair.city))
    rows = res.all()

    # Calibration set: per (pair_type × city) cell, computed over the FULL table
    # (not pre-filtered by city) so each city's own slice stays fixed regardless of
    # which city other evaluators picked.
    by_cell: dict[tuple[str, str], list[uuid.UUID]] = {}
    for pid, ptype, c in rows:
        by_cell.setdefault((ptype, c), []).append(pid)
    calibration_ids: set[uuid.UUID] = set()
    for (ptype, c), ids in by_cell.items():
        ids = sorted(ids)  # stable order before shuffling
        random.Random(f"{eval_cfg.CALIBRATION_SEED}:{ptype}:{c}").shuffle(ids)
        calibration_ids.update(ids[: eval_cfg.CALIBRATION_PAIRS_PER_CELL])

    all_ids = sorted((pid for pid, _, c in rows if city is None or c == city), key=str)
    calibration = [pid for pid in all_ids if pid in calibration_ids]
    rest = [pid for pid in all_ids if pid not in calibration_ids]
    random.Random(f"{eval_cfg.CALIBRATION_SEED}:order").shuffle(calibration)
    random.Random(f"{evaluator}").shuffle(rest)
    return (calibration + rest)[:batch_size]


async def _assigned_itinerary_ids(
    db: AsyncSession, evaluator: str, batch_size: int, city: str | None = None,
) -> list[uuid.UUID]:
    """This evaluator's fixed assignment of itinerary ids — same reasoning as
    ``_assigned_pair_ids`` (one round trip, bucket/filter in Python), stratified by
    city only (Likert has no pair_type dimension).
    """
    res = await db.execute(select(EvaluationItinerary.id, EvaluationItinerary.city))
    rows = res.all()

    by_city: dict[str, list[uuid.UUID]] = {}
    for iid, c in rows:
        by_city.setdefault(c, []).append(iid)
    calibration_ids: set[uuid.UUID] = set()
    for c, ids in by_city.items():
        ids = sorted(ids)  # stable order before shuffling
        random.Random(f"{eval_cfg.CALIBRATION_SEED}:itin:{c}").shuffle(ids)
        calibration_ids.update(ids[: eval_cfg.CALIBRATION_ITINERARIES_PER_CITY])

    all_ids = sorted((iid for iid, c in rows if city is None or c == city), key=str)
    calibration = [iid for iid in all_ids if iid in calibration_ids]
    rest = [iid for iid in all_ids if iid not in calibration_ids]
    random.Random(f"{eval_cfg.CALIBRATION_SEED}:itin:order").shuffle(calibration)
    random.Random(f"{evaluator}:itin").shuffle(rest)
    return (calibration + rest)[:batch_size]


def _profile_context(profile_key: str) -> dict:
    p = PROFILES_BY_KEY.get(profile_key)
    if p is None:
        return {"key": profile_key, "label": profile_key}
    return {
        "key": p.key,
        "label": p.label,
        "description": p.description,
        "travel_mode": p.travel_mode,
        "age_range": p.age_range,
        "children": p.children,
        "interests": p.vector,
        "note": p.note,
    }


# ─────────────────────────────────────────────
# Pairwise
# ─────────────────────────────────────────────

@router.get("/pairs")
async def get_pairs(
    evaluator: str = Query(..., min_length=1),
    limit: int = Query(30, ge=1, le=200),
    city: str | None = Query(None, description="Evaluator's self-reported best-known city"),
    db: AsyncSession = Depends(get_db),
):
    """This evaluator's fixed assignment of ``limit`` pairs (not the whole pool),
    minus whichever of those they've already rated — blinded + randomised.

    ``limit`` sizes the assignment itself, so re-fetching always resolves to the
    same ``limit`` pairs (see ``_assigned_pair_ids``): a rater only ever sees and is
    scored against their own batch, never the full pool. ``city``, if given,
    restricts the whole assignment to that city.
    """
    assigned_ids = await _assigned_pair_ids(db, evaluator, limit, city)

    # One round trip for both "is it already rated" and "fetch the pair object":
    # LEFT JOIN this evaluator's own rating (NULL when unrated) instead of two
    # separate queries.
    res = await db.execute(
        select(EvaluationPair, EvaluationRating.id)
        .outerjoin(
            EvaluationRating,
            and_(
                EvaluationRating.pair_id == EvaluationPair.id,
                EvaluationRating.evaluator_id == evaluator,
            ),
        )
        .where(EvaluationPair.id.in_(assigned_ids))
    )
    by_id = {pr.id: (pr, rating_id) for pr, rating_id in res.all()}
    pairs = [by_id[pid][0] for pid in assigned_ids if pid in by_id and by_id[pid][1] is None]

    # Counts against THIS evaluator's assignment (e.g. 7/30), not the whole pool.
    rated_total = sum(1 for _, rating_id in by_id.values() if rating_id is not None)
    pool_total = len(assigned_ids)

    # Live place descriptions for the shown POIs — the frozen snapshots predate the
    # field, so enrich from the POI rows. Generated by evaluation/generate_descriptions.py.
    poi_ids = {pr.poi_a_id for pr in pairs} | {pr.poi_b_id for pr in pairs}
    desc_by_id: dict = {}
    if poi_ids:
        rows = await db.execute(select(Poi.id, Poi.description).where(Poi.id.in_(poi_ids)))
        desc_by_id = {pid: summary for pid, summary in rows.all()}

    out = []
    for pr in pairs:
        options = [
            {"slot": "a", "poi_id": str(pr.poi_a_id), "description": desc_by_id.get(pr.poi_a_id), **pr.poi_a_snapshot},
            {"slot": "b", "poi_id": str(pr.poi_b_id), "description": desc_by_id.get(pr.poi_b_id), **pr.poi_b_snapshot},
        ]
        random.Random(f"{evaluator}:{pr.id}").shuffle(options)  # per-pair display order
        out.append({
            "pair_id": str(pr.id),
            "pair_type": pr.pair_type,
            "profile": _profile_context(pr.profile_key),
            "city": pr.city,
            "options": options,
        })
    return {"pairs": out, "rated_total": rated_total, "pool_total": pool_total}


class RatingIn(BaseModel):
    pair_id: uuid.UUID
    evaluator_id: str
    choice: str  # "a" | "b" | "equal"  (slot of the chosen option, or equal)


@router.post("/ratings", status_code=status.HTTP_201_CREATED)
async def post_rating(body: RatingIn, db: AsyncSession = Depends(get_db)):
    if body.choice not in ("a", "b", "equal"):
        raise HTTPException(status_code=400, detail="choice must be 'a', 'b' or 'equal'")
    # No pre-check SELECT: pair_id already has a DB-level foreign key onto
    # evaluation_pairs, so an invalid id fails at INSERT — one round trip instead
    # of two, which matters here since every submission pays for it.
    db.add(EvaluationRating(
        pair_id=body.pair_id, evaluator_id=body.evaluator_id, choice=body.choice,
    ))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=404, detail="pair not found")
    return {"ok": True}


# ─────────────────────────────────────────────
# Likert (whole itinerary)
# ─────────────────────────────────────────────

@router.get("/itineraries")
async def get_itineraries(
    evaluator: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=100),
    city: str | None = Query(None, description="Evaluator's self-reported best-known city"),
    db: AsyncSession = Depends(get_db),
):
    """This evaluator's fixed assignment of ``limit`` itineraries (not the whole
    pool), minus whichever of those they've already Likert-rated. Solver name
    stripped (blind). Same fixed-assignment + per-city calibration reasoning as
    ``get_pairs`` above (see ``_assigned_itinerary_ids``).
    """
    assigned_ids = await _assigned_itinerary_ids(db, evaluator, limit, city)

    # One round trip for both "is it already rated" and "fetch the itinerary" —
    # same LEFT JOIN pattern as get_pairs above.
    res = await db.execute(
        select(EvaluationItinerary, EvaluationLikert.id)
        .outerjoin(
            EvaluationLikert,
            and_(
                EvaluationLikert.itinerary_id == EvaluationItinerary.id,
                EvaluationLikert.evaluator_id == evaluator,
            ),
        )
        .where(EvaluationItinerary.id.in_(assigned_ids))
    )
    by_id = {it.id: (it, likert_id) for it, likert_id in res.all()}
    itins = [by_id[iid][0] for iid in assigned_ids if iid in by_id and by_id[iid][1] is None]

    rated_total = sum(1 for _, likert_id in by_id.values() if likert_id is not None)
    pool_total = len(assigned_ids)

    out = []
    for it in itins:
        payload = dict(it.payload_json)
        payload.pop("solver", None)  # keep blind
        out.append({
            "itinerary_id": str(it.id),
            "profile": _profile_context(it.profile_key),
            "city": it.city,
            "num_days": it.num_days,
            "payload": payload,
        })
    return {"itineraries": out, "rated_total": rated_total, "pool_total": pool_total}


class LikertIn(BaseModel):
    itinerary_id: uuid.UUID
    evaluator_id: str
    realism: int
    completeness: int
    profile_fit: int
    overall: int


@router.post("/likert", status_code=status.HTTP_201_CREATED)
async def post_likert(body: LikertIn, db: AsyncSession = Depends(get_db)):
    for v in (body.realism, body.completeness, body.profile_fit, body.overall):
        if not 1 <= v <= 5:
            raise HTTPException(status_code=400, detail="ratings must be 1..5")
    db.add(EvaluationLikert(
        itinerary_id=body.itinerary_id, evaluator_id=body.evaluator_id,
        realism=body.realism, completeness=body.completeness,
        profile_fit=body.profile_fit, overall=body.overall,
    ))
    await db.commit()
    return {"ok": True}


# ─────────────────────────────────────────────
# Export (for analysis)
# ─────────────────────────────────────────────

def _anonymize(evaluator_id: str, mapping: dict[str, int]) -> int:
    if evaluator_id not in mapping:
        mapping[evaluator_id] = len(mapping) + 1
    return mapping[evaluator_id]


@router.get("/export")
async def export(db: AsyncSession = Depends(get_db)):
    """Single CSV joining ratings to their pair + itinerary (solver, type, profile).

    `system_agreement` = 1 when the human chose slot 'a' (the included POI = the
    system's pick), 0 when 'b', blank for 'equal'. `evaluator_id` is anonymized
    to a sequential number, assigned in the order evaluators first appear in
    this query.
    """
    res = await db.execute(
        select(EvaluationRating, EvaluationPair, EvaluationItinerary)
        .join(EvaluationPair, EvaluationRating.pair_id == EvaluationPair.id)
        .join(EvaluationItinerary, EvaluationPair.itinerary_id == EvaluationItinerary.id)
    )
    mapping: dict[str, int] = {}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "evaluator_id", "pair_type", "profile_key", "city", "num_days", "solver",
        "choice", "system_agreement", "poi_a", "poi_b",
    ])
    for rating, pair, itin in res.all():
        agreement = "" if rating.choice == "equal" else ("1" if rating.choice == "a" else "0")
        w.writerow([
            _anonymize(rating.evaluator_id, mapping), pair.pair_type, itin.profile_key,
            itin.city, itin.num_days, itin.solver, rating.choice, agreement,
            pair.poi_a_snapshot.get("name"), pair.poi_b_snapshot.get("name"),
        ])
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=evaluation_ratings.csv"},
    )


@router.get("/export/likert")
async def export_likert(db: AsyncSession = Depends(get_db)):
    """CSV of whole-itinerary Likert ratings, joined to itinerary metadata.

    `evaluator_id` is anonymized to a sequential number, assigned independently
    of the `/export` endpoint's own numbering.
    """
    res = await db.execute(
        select(EvaluationLikert, EvaluationItinerary)
        .join(EvaluationItinerary, EvaluationLikert.itinerary_id == EvaluationItinerary.id)
    )
    mapping: dict[str, int] = {}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "evaluator_id", "profile_key", "city", "num_days", "solver",
        "realism", "completeness", "profile_fit", "overall",
    ])
    for likert, itin in res.all():
        w.writerow([
            _anonymize(likert.evaluator_id, mapping), itin.profile_key, itin.city,
            itin.num_days, itin.solver, likert.realism, likert.completeness,
            likert.profile_fit, likert.overall,
        ])
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=evaluation_likert.csv"},
    )
