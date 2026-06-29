"""Evaluation generation harness (see docs/evaluation-harness-spec.md §3).

For every (profile × city × duration × solver × routing) cell:
  1. build an in-memory UserPreference from the frozen profile (no DB user needed —
     the planner only reads the 7-dim vector + travel_mode + age_range),
  2. fetch the same candidate POIs production uses (`fetch_candidate_pois`),
  3. call `itinerary_planner.generate(...)` with the chosen solver and real travel
     times (session passed),
  4. store a frozen JSON snapshot + the scored candidate universe + automatic metrics
     in `evaluation_itineraries` (idempotent per cell).

Usage:
    python -m evaluation.run_eval                 # full 2×2 matrix (both solvers × both routings)
    python -m evaluation.run_eval --pairs         # + build human-eval pairs (real-routing arm only)
    python -m evaluation.run_eval --cities Roma --profiles couple_foodie --durations 2 --solvers toptw
    python -m evaluation.run_eval --routings real # skip the ablation, real routing only
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
import uuid
from datetime import date, timedelta

from sqlalchemy import delete, select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.city import City
from app.models.evaluation import EvaluationItinerary
from app.models.preference import UserPreference
from app.schemas.itinerary import TravelMode
from app.services import itinerary_planner
from app.services.candidate_query import fetch_candidate_pois
from app.services.itinerary_planner import (
    _apply_mode_bias,
    _user_vec,
    compute_popularity_scores,
    haversine_m,
    is_actual_food_poi,
    is_touristic,
    resolve_activity_radius_m,
)
from app.services.toptw_solver import compute_prize
from evaluation import config as cfg
from evaluation import metrics as metrics_mod
from evaluation.profiles import PROFILES_BY_KEY, Profile

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluation")

# Same schedule mapping the production endpoint derives from travel mode.
from app.routers.itineraries import _schedule_for_mode  # noqa: E402


def _build_prefs(profile: Profile) -> UserPreference:
    """In-memory UserPreference from the frozen vector (not persisted)."""
    p = UserPreference()
    for key, val in profile.vector.items():
        setattr(p, key, val)
    return p


def _google_maps_url(poi) -> str | None:
    if poi.google_place_id:
        return f"https://www.google.com/maps/place/?q=place_id:{poi.google_place_id}"
    return None


def _activity_universe(
    candidates: list,
    city_lat: float,
    city_lng: float,
    travel_mode: str,
    num_days: int,
) -> list:
    """Replicate the planner's internal activity filtering so the candidate
    universe (used for metrics + pairs) matches what the solvers actually saw."""
    activity = [p for p in candidates if p.travel_category != "food" and not is_actual_food_poi(p)]
    activity = [p for p in activity if is_touristic(p)]
    max_m = resolve_activity_radius_m(activity, city_lat, city_lng, num_days)
    activity = [p for p in activity if haversine_m(p.lat, p.lng, city_lat, city_lng) <= max_m]
    if travel_mode == "family":
        activity = [p for p in activity if p.travel_category != "nightlife"]
    return activity


def _serialize_stop(stop, position: int) -> dict:
    poi = stop.poi
    return {
        "position": position,
        "poi_id": str(poi.id),
        "name": poi.name,
        "address": poi.address,
        "lat": poi.lat,
        "lng": poi.lng,
        "travel_category": poi.travel_category,
        "rating": poi.rating,
        "photo_reference": poi.photo_reference,
        "google_maps_url": _google_maps_url(poi),
        "arrival_time": stop.arrival.strftime("%H:%M"),
        "departure_time": stop.departure.strftime("%H:%M"),
        "transport_from_previous": stop.transport,
        "travel_minutes_from_previous": round(stop.travel_minutes, 1) if stop.transport else None,
        "visit_mode": stop.visit_mode,
        "visit_duration_minutes": stop.visit_duration_minutes,
        "visit_note": stop.visit_note,
        "is_food": poi.travel_category == "food" or is_actual_food_poi(poi),
    }


async def _run_cell(
    db, run_id: uuid.UUID, profile: Profile, city: City, num_days: int, solver: str,
    routing: str,
) -> bool:
    travel_mode = profile.travel_mode
    travel_with_children = profile.children
    start_str, end_str = _schedule_for_mode(TravelMode(travel_mode))

    # Routing arm of the 2×2: flip the global switch the planners read so this cell
    # plans on real road times ("real") or haversine ("estimated"). The harness is
    # sequential, so mutating the singleton here is safe; run() restores it after.
    settings.routes_api_enabled = (routing == "real")

    candidates = await fetch_candidate_pois(db, city.id, travel_with_children=travel_with_children)
    if len(candidates) < num_days * 3:
        logger.warning("  skip %s/%s/%dd/%s — only %d candidates",
                       profile.key, city.name, num_days, solver, len(candidates))
        return False

    prefs = _build_prefs(profile)
    uvec = _apply_mode_bias(_user_vec(prefs), travel_mode)
    popularity = compute_popularity_scores(candidates)
    activity_pois = _activity_universe(candidates, city.lat, city.lng, travel_mode, num_days)
    prize_by_id = {
        p.id: compute_prize(p, uvec, popularity, settings.toptw_w_sim, settings.toptw_w_pop)[0]
        for p in activity_pois
    }

    t0 = time.monotonic()
    try:
        all_days, warnings = await itinerary_planner.generate(
            user_prefs=prefs,
            num_days=num_days,
            start_time_str=start_str,
            end_time_str=end_str,
            candidate_places=candidates,
            city_lat=city.lat,
            city_lng=city.lng,
            travel_with_children=travel_with_children,
            age_range=profile.age_range,
            travel_mode=travel_mode,
            session=db,
            solver=solver,
        )
    except Exception as exc:  # HTTPException(422) when too few POIs, etc.
        logger.warning("  generate failed %s/%s/%dd/%s: %s",
                       profile.key, city.name, num_days, solver, exc)
        return False
    solve_time_ms = int((time.monotonic() - t0) * 1000)

    # included activity POIs + their day number
    included_day: dict = {}
    for day_idx, day in enumerate(all_days, start=1):
        for stop in day:
            if not (stop.poi.travel_category == "food" or is_actual_food_poi(stop.poi)):
                included_day.setdefault(stop.poi.id, day_idx)
    included_ids = set(included_day.keys())

    # snapshot payload
    today = date.today()
    payload = {
        "city": city.name,
        "num_days": num_days,
        "solver": solver,
        "routing": routing,
        "warnings": warnings,
        "days": [
            {
                "day_number": i + 1,
                "date": (today + timedelta(days=i)).isoformat(),
                "stops": [_serialize_stop(s, pos) for pos, s in enumerate(day, start=1)],
            }
            for i, day in enumerate(all_days)
        ],
    }

    candidates_json = [
        {
            "poi_id": str(p.id),
            "name": p.name,
            "types": p.types,
            "lat": p.lat,
            "lng": p.lng,
            "rating": p.rating,
            "user_ratings_total": p.user_ratings_total,
            "photo_reference": p.photo_reference,
            "travel_category": p.travel_category,
            "google_maps_url": _google_maps_url(p),
            "prize": round(prize_by_id[p.id], 4),
            "included": p.id in included_ids,
            "day": included_day.get(p.id),
        }
        for p in activity_pois
    ]

    cell_metrics = await metrics_mod.compute_metrics(
        db,
        all_days=all_days,
        all_activity_candidates=activity_pois,
        included_activity_ids=included_ids,
        prize_by_id=prize_by_id,
        start_str=start_str,
        end_str=end_str,
        solve_time_ms=solve_time_ms,
        top_n_landmark=cfg.TOP_N_LANDMARK,
        budget_fill_threshold=cfg.BUDGET_FILL_THRESHOLD,
    )

    # idempotent: replace any existing row for this cell
    await db.execute(
        delete(EvaluationItinerary).where(
            EvaluationItinerary.profile_key == profile.key,
            EvaluationItinerary.city == city.name,
            EvaluationItinerary.num_days == num_days,
            EvaluationItinerary.solver == solver,
            EvaluationItinerary.routing == routing,
        )
    )
    db.add(EvaluationItinerary(
        run_id=run_id,
        profile_key=profile.key,
        city=city.name,
        num_days=num_days,
        solver=solver,
        routing=routing,
        payload_json=payload,
        candidates_json=candidates_json,
        metrics_json=cell_metrics,
    ))
    await db.commit()
    logger.info("  ok %s/%s/%dd/%s/%s — %d activity stops, relevance=%.2f, overrun_days=%.0f%%",
                profile.key, city.name, num_days, solver, routing,
                len(included_ids), cell_metrics["total_relevance"],
                100 * (cell_metrics["real_overrun_day_rate"] or 0))
    return True


async def run(args) -> None:
    run_id = uuid.UUID(args.run_id) if args.run_id else uuid.uuid4()
    profiles = [PROFILES_BY_KEY[k] for k in (args.profiles or list(PROFILES_BY_KEY))]
    cities = args.cities or cfg.CITIES
    durations = args.durations or cfg.DURATIONS
    solvers = args.solvers or cfg.SOLVERS
    routings = args.routings or cfg.ROUTINGS

    logger.info(
        "Evaluation run_id=%s | %d profiles × %d cities × %d durations × %d solvers × %d routings",
        run_id, len(profiles), len(cities), len(durations), len(solvers), len(routings),
    )

    # _run_cell mutates settings.routes_api_enabled per cell; restore it afterwards
    # so the harness leaves the process config untouched.
    routes_api_enabled_orig = settings.routes_api_enabled

    ok = fail = 0
    try:
        async with AsyncSessionLocal() as db:
            for city_name in cities:
                res = await db.execute(select(City).where(City.name.ilike(city_name)))
                city = res.scalar_one_or_none()
                if city is None:
                    logger.warning("City %r not found — run the pipeline first. Skipping.", city_name)
                    continue
                for profile in profiles:
                    for num_days in durations:
                        for solver in solvers:
                            for routing in routings:
                                done = await _run_cell(
                                    db, run_id, profile, city, num_days, solver, routing
                                )
                                ok += int(done)
                                fail += int(not done)
    finally:
        settings.routes_api_enabled = routes_api_enabled_orig

    logger.info("Generation done: %d cells generated, %d skipped/failed.", ok, fail)

    if args.pairs:
        from evaluation import pairs as pairs_mod
        async with AsyncSessionLocal() as db:
            n = await pairs_mod.build_pairs_for_run(db, run_id)
        logger.info("Built %d human-eval pairs.", n)


def main() -> None:
    ap = argparse.ArgumentParser(description="EasyTravel itinerary evaluation harness")
    ap.add_argument("--run-id", default=None, help="Reuse an existing run UUID (default: new)")
    ap.add_argument("--cities", nargs="*", default=None)
    ap.add_argument("--profiles", nargs="*", default=None, help="Profile keys (default: all)")
    ap.add_argument("--durations", nargs="*", type=int, default=None)
    ap.add_argument("--solvers", nargs="*", default=None, choices=["greedy", "toptw"])
    ap.add_argument("--routings", nargs="*", default=None, choices=["real", "estimated"],
                    help="Routing arm(s) of the 2×2 ablation (default: both)")
    ap.add_argument("--pairs", action="store_true", help="Also build human-eval pairs after generation")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
