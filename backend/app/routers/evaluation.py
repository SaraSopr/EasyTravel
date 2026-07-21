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
from sqlalchemy import select
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


async def _calibration_pair_ids(db: AsyncSession) -> set[uuid.UUID]:
    """Fixed subset of pair ids shown to every evaluator who shares a city
    (see evaluation.config). Stratified per (pair_type × city): two evaluators
    who both picked "Roma" always overlap on the same Roma calibration pairs, even
    though a "Madrid" evaluator never sees them and vice versa — overlap only needs
    to hold among raters who can actually judge the same POIs.

    Deterministic and independent of evaluator/request order: same ``CALIBRATION_SEED``
    always yields the same ids, so repeated calls (and every evaluator) agree on
    which pairs are "calibration" without persisting anything.
    """
    res = await db.execute(select(EvaluationPair.id, EvaluationPair.pair_type, EvaluationPair.city))
    by_cell: dict[tuple[str, str], list[uuid.UUID]] = {}
    for pid, ptype, city in res.all():
        by_cell.setdefault((ptype, city), []).append(pid)
    calibration: set[uuid.UUID] = set()
    for (ptype, city), ids in by_cell.items():
        ids = sorted(ids)  # stable order before shuffling
        random.Random(f"{eval_cfg.CALIBRATION_SEED}:{ptype}:{city}").shuffle(ids)
        calibration.update(ids[: eval_cfg.CALIBRATION_PAIRS_PER_CELL])
    return calibration


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
    """
    calibration_ids = await _calibration_pair_ids(db)
    query = select(EvaluationPair.id, EvaluationPair.city)
    if city:
        query = query.where(EvaluationPair.city == city)
    res = await db.execute(query)
    all_ids = sorted((pid for pid, _ in res.all()), key=str)  # stable order before shuffling
    calibration = [pid for pid in all_ids if pid in calibration_ids]
    rest = [pid for pid in all_ids if pid not in calibration_ids]
    random.Random(f"{eval_cfg.CALIBRATION_SEED}:order").shuffle(calibration)
    random.Random(f"{evaluator}").shuffle(rest)
    return (calibration + rest)[:batch_size]


async def _calibration_itinerary_ids(db: AsyncSession) -> set[uuid.UUID]:
    """Fixed subset of itinerary ids shown to every evaluator who shares a city
    (see evaluation.config). Same reasoning as ``_calibration_pair_ids``, stratified
    per city only (Likert has no pair_type dimension).
    """
    res = await db.execute(select(EvaluationItinerary.id, EvaluationItinerary.city))
    by_city: dict[str, list[uuid.UUID]] = {}
    for iid, city in res.all():
        by_city.setdefault(city, []).append(iid)
    calibration: set[uuid.UUID] = set()
    for city, ids in by_city.items():
        ids = sorted(ids)  # stable order before shuffling
        random.Random(f"{eval_cfg.CALIBRATION_SEED}:itin:{city}").shuffle(ids)
        calibration.update(ids[: eval_cfg.CALIBRATION_ITINERARIES_PER_CITY])
    return calibration


async def _assigned_itinerary_ids(
    db: AsyncSession, evaluator: str, batch_size: int, city: str | None = None,
) -> list[uuid.UUID]:
    """This evaluator's fixed assignment of itinerary ids — same reasoning as
    ``_assigned_pair_ids``: shared per-city calibration first, then this
    evaluator's own deterministic shuffle of the rest, truncated to ``batch_size``.
    """
    calibration_ids = await _calibration_itinerary_ids(db)
    query = select(EvaluationItinerary.id, EvaluationItinerary.city)
    if city:
        query = query.where(EvaluationItinerary.city == city)
    res = await db.execute(query)
    all_ids = sorted((iid for iid, _ in res.all()), key=str)  # stable order before shuffling
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

    res = await db.execute(
        select(EvaluationRating.pair_id).where(
            EvaluationRating.evaluator_id == evaluator,
            EvaluationRating.pair_id.in_(assigned_ids),
        )
    )
    already_rated = {r for (r,) in res.all()}
    to_show_ids = [pid for pid in assigned_ids if pid not in already_rated]

    res = await db.execute(select(EvaluationPair).where(EvaluationPair.id.in_(to_show_ids)))
    by_id = {p.id: p for p in res.scalars().all()}
    pairs = [by_id[pid] for pid in to_show_ids if pid in by_id]

    # Counts against THIS evaluator's assignment (e.g. 7/30), not the whole pool.
    rated_total = len(already_rated)
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
    exists = await db.execute(
        select(EvaluationPair.id).where(EvaluationPair.id == body.pair_id)
    )
    if exists.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="pair not found")
    db.add(EvaluationRating(
        pair_id=body.pair_id, evaluator_id=body.evaluator_id, choice=body.choice,
    ))
    await db.commit()
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

    res = await db.execute(
        select(EvaluationLikert.itinerary_id).where(
            EvaluationLikert.evaluator_id == evaluator,
            EvaluationLikert.itinerary_id.in_(assigned_ids),
        )
    )
    already_rated = {r for (r,) in res.all()}
    to_show_ids = [iid for iid in assigned_ids if iid not in already_rated]

    res = await db.execute(select(EvaluationItinerary).where(EvaluationItinerary.id.in_(to_show_ids)))
    by_id = {it.id: it for it in res.scalars().all()}
    itins = [by_id[iid] for iid in to_show_ids if iid in by_id]

    rated_total = len(already_rated)
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

@router.get("/export")
async def export(db: AsyncSession = Depends(get_db)):
    """Single CSV joining ratings to their pair + itinerary (solver, type, profile).

    `system_agreement` = 1 when the human chose slot 'a' (the included POI = the
    system's pick), 0 when 'b', blank for 'equal'.
    """
    res = await db.execute(
        select(EvaluationRating, EvaluationPair, EvaluationItinerary)
        .join(EvaluationPair, EvaluationRating.pair_id == EvaluationPair.id)
        .join(EvaluationItinerary, EvaluationPair.itinerary_id == EvaluationItinerary.id)
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "evaluator_id", "pair_type", "profile_key", "city", "num_days", "solver",
        "choice", "system_agreement", "poi_a", "poi_b",
    ])
    for rating, pair, itin in res.all():
        agreement = "" if rating.choice == "equal" else ("1" if rating.choice == "a" else "0")
        w.writerow([
            rating.evaluator_id, pair.pair_type, itin.profile_key, itin.city,
            itin.num_days, itin.solver, rating.choice, agreement,
            pair.poi_a_snapshot.get("name"), pair.poi_b_snapshot.get("name"),
        ])
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=evaluation_ratings.csv"},
    )
