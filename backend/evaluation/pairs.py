"""Human-eval pair builder (see docs/evaluation-harness-spec.md §6).

For each generated itinerary, build A(included)–B(excluded) pairs in three flavours,
designed to control the relevance-vs-feasibility confound:

- ``substitutable``  : B excluded but in the SAME area as A (≤ radius) and of a
  DIFFERENT category → logistics controlled, the only difference is fit-to-profile.
  Tests selection/relevance.
- ``famous_skipped`` : B = a famous (high-ratings) POI the trip skipped, vs an
  included POI of lesser fame. Tests must-see coverage.
- ``margin``         : A = lowest-prize included, B = highest-prize excluded. Tests
  the inclusion boundary (the most informative cases).

Pairs are pre-built and frozen with POI snapshots so the dashboard is independent
of live data.
"""
from __future__ import annotations

import random
import uuid

from sqlalchemy import delete, select

from app.models.evaluation import EvaluationItinerary, EvaluationPair
from app.services.itinerary_planner import haversine_m
from evaluation import config as cfg


def _snapshot(cand: dict) -> dict:
    """UI-facing frozen snapshot of a candidate POI."""
    return {
        "poi_id": cand["poi_id"],
        "name": cand["name"],
        "types": cand.get("types"),
        "rating": cand.get("rating"),
        "user_ratings_total": cand.get("user_ratings_total"),
        "photo_reference": cand.get("photo_reference"),
        "travel_category": cand.get("travel_category"),
        "google_maps_url": cand.get("google_maps_url"),
    }


def _pair_kwargs(itin: EvaluationItinerary, pair_type: str, a: dict, b: dict) -> dict:
    return {
        "itinerary_id": itin.id,
        "pair_type": pair_type,
        "poi_a_id": uuid.UUID(a["poi_id"]),
        "poi_b_id": uuid.UUID(b["poi_id"]),
        "poi_a_snapshot": _snapshot(a),
        "poi_b_snapshot": _snapshot(b),
        "profile_key": itin.profile_key,
        "city": itin.city,
    }


def build_pairs_for_itinerary(itin: EvaluationItinerary, rng: random.Random) -> list[dict]:
    cands = itin.candidates_json or []
    included = [c for c in cands if c.get("included")]
    excluded = [c for c in cands if not c.get("included")]
    if not included or not excluded:
        return []

    cap = cfg.PAIRS_PER_TYPE
    used: set[tuple[str, str]] = set()
    out: list[dict] = []

    def _add(pair_type: str, a: dict, b: dict) -> bool:
        key = (a["poi_id"], b["poi_id"])
        if a["poi_id"] == b["poi_id"] or key in used:
            return False
        used.add(key)
        out.append(_pair_kwargs(itin, pair_type, a, b))
        return True

    # --- substitutable: A included, B excluded in the same area (≤ radius) ---
    # Prefer lower-prize included A (more questionable inclusions). B must be a
    # DIFFERENT travel_category than A: two same-category neighbours (e.g. two
    # adjacent monuments) carry no relevance contrast, so the comparison is noise.
    # No contrasting neighbour in range → skip this A rather than pair near-twins.
    sub_count = 0
    for a in sorted(included, key=lambda c: c.get("prize", 0.0)):
        if sub_count >= cap:
            break
        a_cat = (a.get("travel_category") or "").lower()
        near = [
            b for b in excluded
            if (b.get("travel_category") or "").lower() != a_cat
            and haversine_m(a["lat"], a["lng"], b["lat"], b["lng"]) <= cfg.SUBSTITUTABLE_RADIUS_M
        ]
        if not near:
            continue
        # closest contrasting neighbour → most comparable logistics
        b = min(near, key=lambda c: haversine_m(a["lat"], a["lng"], c["lat"], c["lng"]))
        if _add("substitutable", a, b):
            sub_count += 1

    # --- famous_skipped: famous excluded B vs lesser-fame included A ---
    famous_excluded = sorted(
        excluded, key=lambda c: (c.get("user_ratings_total") or 0), reverse=True
    )
    included_by_fame_asc = sorted(included, key=lambda c: (c.get("user_ratings_total") or 0))
    fs_count = 0
    for b in famous_excluded:
        if fs_count >= cap:
            break
        # pair with an included POI of clearly lower fame
        a = next(
            (c for c in included_by_fame_asc
             if (c.get("user_ratings_total") or 0) < (b.get("user_ratings_total") or 0)),
            None,
        )
        if a is None:
            break
        if _add("famous_skipped", a, b):
            fs_count += 1

    # --- margin: lowest-prize included vs highest-prize excluded ---
    inc_low = sorted(included, key=lambda c: c.get("prize", 0.0))
    exc_high = sorted(excluded, key=lambda c: c.get("prize", 0.0), reverse=True)
    mg_count = 0
    for a, b in zip(inc_low, exc_high):
        if mg_count >= cap:
            break
        if _add("margin", a, b):
            mg_count += 1

    rng.shuffle(out)
    return out


async def build_pairs_for_run(db, run_id: uuid.UUID) -> int:
    """(Re)build pairs for every itinerary of a run. Idempotent per itinerary."""
    rng = random.Random(cfg.RANDOM_SEED)
    res = await db.execute(
        select(EvaluationItinerary).where(EvaluationItinerary.run_id == run_id)
    )
    itineraries = list(res.scalars().all())

    total = 0
    for itin in itineraries:
        await db.execute(
            delete(EvaluationPair).where(EvaluationPair.itinerary_id == itin.id)
        )
        for kwargs in build_pairs_for_itinerary(itin, rng):
            db.add(EvaluationPair(**kwargs))
            total += 1
    await db.commit()
    return total
