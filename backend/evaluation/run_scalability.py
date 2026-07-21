"""RQ1c scalability experiment — varies candidate pool size and num_days.

Sweeps CANDIDATE_COUNTS for both TOPTW and greedy over a grid of cities ×
profiles × durations so the scalability claim rests on multiple instances
rather than a single (city, profile) pair.

For each N, both solvers receive the same top-N activity POIs plus the full food
pool. This keeps the comparison fair: TOPTW no longer starts from a different
number of POIs than the greedy baseline.

Each (city, profile, duration) is one "instance"; the plot aggregates across
instances (mean + IQR band), exposing how robust the N-trend is.

Output: scalability_results.csv (path configurable via --out)

Usage (from backend/):
    python -m evaluation.run_scalability                       # default grid
    python -m evaluation.run_scalability --out scalability_results.csv
    python -m evaluation.run_scalability --cities Roma,Madrid  # subset
    python -m evaluation.run_scalability --profiles all        # every profile
    python -m evaluation.run_scalability --cities Roma --profiles couple_museums
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import time

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.city import City
from app.models.preference import UserPreference
from app.routers.itineraries import _schedule_for_mode
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
from app.services.toptw_solver import compute_prize, select_candidates
from evaluation import config as cfg
from evaluation.metrics import compute_metrics
from evaluation.profiles import PROFILES_BY_KEY

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("scalability")

# ── experiment axes ──────────────────────────────────────────────────────────
CANDIDATE_COUNTS = [20, 40, 60, 80, 100, 120]
DURATIONS = [2, 4]

# Default grid: every ingested city × every frozen profile, so the scalability
# claim spans the whole preference space, not a hand-picked subset. Override with
# --cities / --profiles (comma-separated, or "all") to run a faster slice.
DEFAULT_CITIES = list(cfg.CITIES)                       # ["Roma", "Madrid", "Porto"]
DEFAULT_PROFILES = [p.key for p in PROFILES_BY_KEY.values()]  # all 9

FIELDS = [
    "profile_key", "city", "num_days", "solver", "num_candidates",
    "total_relevance", "avg_relevance", "num_activities_included",
    "real_overrun_day_rate", "real_overrun_min_avg",
    "idle_minutes_per_day", "stops_per_day", "solve_time_ms",
]


def _build_prefs(profile) -> UserPreference:
    p = UserPreference()
    for key, val in profile.vector.items():
        setattr(p, key, val)
    return p


async def _run_cell(db, profile, city, num_days: int, solver: str, num_candidates: int) -> dict | None:
    travel_mode = profile.travel_mode
    travel_with_children = profile.children
    start_str, end_str = _schedule_for_mode(TravelMode(travel_mode))

    settings.routes_api_enabled = True
    settings.toptw_num_candidates = num_candidates

    raw_candidates = await fetch_candidate_pois(db, city.id, travel_with_children=travel_with_children)
    if len(raw_candidates) < num_days * 3:
        logger.warning("skip %s/%s/%dd/%s — only %d candidates",
                       profile.key, city.name, num_days, solver, len(raw_candidates))
        return None

    prefs = _build_prefs(profile)
    uvec = _apply_mode_bias(_user_vec(prefs), travel_mode)
    raw_popularity = compute_popularity_scores(raw_candidates)

    food_pois = [p for p in raw_candidates if p.travel_category == "food" or is_actual_food_poi(p)]
    activity_pois = [p for p in raw_candidates if p.travel_category != "food" and not is_actual_food_poi(p)]
    activity_pois = [p for p in activity_pois if is_touristic(p)]
    max_m = resolve_activity_radius_m(activity_pois, city.lat, city.lng, num_days)
    activity_pois = [p for p in activity_pois if haversine_m(p.lat, p.lng, city.lat, city.lng) <= max_m]
    if travel_mode == "family":
        activity_pois = [p for p in activity_pois if p.travel_category != "nightlife"]
    selected_activity = [
        p for p, _prize, _sim in select_candidates(
            activity_pois,
            uvec,
            raw_popularity,
            confirmed_visited_ids=set(),
            previously_suggested_ids=set(),
            n=num_candidates,
            w_sim=settings.toptw_w_sim,
            w_pop=settings.toptw_w_pop,
        )
    ]
    candidates = [*selected_activity, *food_pois]
    if len(selected_activity) < num_days * 3:
        logger.warning(
            "skip %s/%s/%dd/%s/nc=%d — only %d selected activity candidates",
            profile.key, city.name, num_days, solver, num_candidates, len(selected_activity),
        )
        return None
    activity_pois = selected_activity
    popularity = compute_popularity_scores(candidates)

    prize_by_id = {
        p.id: compute_prize(p, uvec, popularity, settings.toptw_w_sim, settings.toptw_w_pop)[0]
        for p in activity_pois
    }

    t0 = time.monotonic()
    try:
        all_days, _ = await itinerary_planner.generate(
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
    except Exception as exc:
        logger.warning("generate failed %s/%dd/%s/nc=%d: %s",
                       city.name, num_days, solver, num_candidates, exc)
        return None
    solve_time_ms = int((time.monotonic() - t0) * 1000)

    included_ids: set = set()
    for day in all_days:
        for stop in day:
            if not (stop.poi.travel_category == "food" or is_actual_food_poi(stop.poi)):
                included_ids.add(stop.poi.id)

    m = await compute_metrics(
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

    row = {
        "profile_key": profile.key,
        "city": city.name,
        "num_days": num_days,
        "solver": solver,
        "num_candidates": num_candidates,
        **{k: m.get(k) for k in FIELDS[5:]},
    }
    logger.info("  ok %s/%dd/%s/nc=%d → relevance=%.3f  stops=%s  time=%dms",
                city.name, num_days, solver, num_candidates,
                m.get("avg_relevance", 0), m.get("num_activities_included", "?"), solve_time_ms)
    return row


def _resolve_profiles(raw: str) -> list:
    if raw.strip().lower() == "all":
        keys = [p.key for p in PROFILES_BY_KEY.values()]
    else:
        keys = [k.strip() for k in raw.split(",") if k.strip()]
    profiles = []
    for k in keys:
        if k not in PROFILES_BY_KEY:
            raise SystemExit(f"Unknown profile {k!r}. Available: {sorted(PROFILES_BY_KEY)}")
        profiles.append(PROFILES_BY_KEY[k])
    return profiles


async def run(args) -> None:
    city_names = [c.strip() for c in args.cities.split(",") if c.strip()]
    profiles = _resolve_profiles(args.profiles)

    orig_candidates = settings.toptw_num_candidates
    orig_routes = settings.routes_api_enabled

    rows: list[dict] = []
    try:
        async with AsyncSessionLocal() as db:
            cities = []
            for name in city_names:
                res = await db.execute(select(City).where(City.name.ilike(name)))
                city = res.scalar_one_or_none()
                if city is None:
                    logger.error("City %r not found — run the pipeline first; skipping.", name)
                    continue
                cities.append(city)
            if not cities:
                logger.error("No valid cities — nothing to do.")
                return

            n_instances = len(cities) * len(profiles) * len(DURATIONS)
            logger.info(
                "Scalability grid: %d cities × %d profiles × %d durations = %d instances, "
                "%d candidate levels × 2 solvers",
                len(cities), len(profiles), len(DURATIONS), n_instances, len(CANDIDATE_COUNTS),
            )

            for city in cities:
                for profile in profiles:
                    for num_days in DURATIONS:
                        logger.info("════ %s / %s / %dd ════", city.name, profile.key, num_days)
                        for nc in CANDIDATE_COUNTS:
                            logger.info("── %d activity candidates ──", nc)
                            for solver in ("greedy", "toptw"):
                                row = await _run_cell(db, profile, city, num_days, solver, nc)
                                if row:
                                    rows.append(row)

    finally:
        settings.toptw_num_candidates = orig_candidates
        settings.routes_api_enabled = orig_routes

    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Saved %d rows → %s", len(rows), args.out)


def main() -> None:
    ap = argparse.ArgumentParser(description="RQ1c scalability sweep")
    ap.add_argument("--cities",   default=",".join(DEFAULT_CITIES),
                    help="Comma-separated city names (must be pipeline-ingested)")
    ap.add_argument("--profiles", default=",".join(DEFAULT_PROFILES),
                    help="Comma-separated profile keys, or 'all'")
    ap.add_argument("--out",      default="scalability_results.csv", help="Output CSV path")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
