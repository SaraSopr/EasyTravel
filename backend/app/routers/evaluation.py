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
from evaluation.profiles import PROFILES_BY_KEY

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


def _profile_context(profile_key: str) -> dict:
    p = PROFILES_BY_KEY.get(profile_key)
    if p is None:
        return {"key": profile_key, "label": profile_key}
    return {
        "key": p.key,
        "label": p.label,
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
    db: AsyncSession = Depends(get_db),
):
    """Pairs not yet rated by this evaluator, blinded + randomised."""
    rated_subq = (
        select(EvaluationRating.pair_id)
        .where(EvaluationRating.evaluator_id == evaluator)
        .subquery()
    )
    res = await db.execute(
        select(EvaluationPair).where(EvaluationPair.id.not_in(select(rated_subq)))
    )
    pairs = list(res.scalars().all())
    rng = random.Random(f"{evaluator}")
    rng.shuffle(pairs)
    pairs = pairs[:limit]

    out = []
    for pr in pairs:
        options = [
            {"slot": "a", "poi_id": str(pr.poi_a_id), **pr.poi_a_snapshot},
            {"slot": "b", "poi_id": str(pr.poi_b_id), **pr.poi_b_snapshot},
        ]
        random.Random(f"{evaluator}:{pr.id}").shuffle(options)  # per-pair display order
        out.append({
            "pair_id": str(pr.id),
            "pair_type": pr.pair_type,
            "profile": _profile_context(pr.profile_key),
            "city": pr.city,
            "options": options,
        })
    return {"pairs": out, "remaining": len(pairs)}


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
    db: AsyncSession = Depends(get_db),
):
    """Itineraries not yet Likert-rated by this evaluator. Solver name stripped (blind)."""
    rated_subq = (
        select(EvaluationLikert.itinerary_id)
        .where(EvaluationLikert.evaluator_id == evaluator)
        .subquery()
    )
    res = await db.execute(
        select(EvaluationItinerary).where(EvaluationItinerary.id.not_in(select(rated_subq)))
    )
    itins = list(res.scalars().all())
    rng = random.Random(f"{evaluator}:itin")
    rng.shuffle(itins)
    itins = itins[:limit]

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
    return {"itineraries": out}


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
