"""Instrumented planner runner for the /api/demo/plan-trace endpoint.

The itineraries come from ``itinerary_planner.generate`` — the exact production
entry point the app's /itineraries/generate endpoint calls — with passive
``trace`` hooks recording the intermediate snapshots the frontend visualiser
animates. No planning logic is duplicated here.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np

from app.constants import FEATURE_NAMES
from app.services.itinerary_planner import (
    FOOD_TYPES,
    _SCHED_TO_DB_MODE,
    _Stop,
    _cosine_sim,
    _dedupe_nearby_pois,
    _is_open,
    _poi_vec,
    compute_popularity_scores,
    compute_walk_threshold_m,
    haversine_m,
    is_actual_food_poi,
    is_landmark_poi,
    is_touristic,
    resolve_activity_radius_m,
    resolve_visit_mode,
    select_transport,
)
from app.services.toptw_solver import compute_prize

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.poi import Poi
    from app.services.itinerary_planner import TravelLookup

logger = logging.getLogger(__name__)

# Schema version of the trace payload. Bump whenever the JSON shape consumed by
# the frontend changes, then regenerate the baked traces
# (scripts/generate_demo_traces.py) — the frontend refuses older baked files.
TRACE_VERSION = 4

# ---------------------------------------------------------------------------
# Persona definitions
# ---------------------------------------------------------------------------

DEMO_PERSONAS: dict[str, dict] = {
    "couple_museums": {
        "id": "couple_museums",
        "label": "Culture Couple",
        "blurb": "A couple deeply passionate about art, history, and architecture.",
        "travel_mode": "couple",
        "vector": {"nature": 0.2, "culture": 1.0, "food": 0.4, "adventure": 0.1,
                   "nightlife": 0.1, "relax": 0.3, "family_friendly": 0.5},
    },
    "young_solo_outdoor": {
        "id": "young_solo_outdoor",
        "label": "Solo Adventurer",
        "blurb": "A young solo traveler craving outdoor experiences and thrills.",
        "travel_mode": "solo",
        "vector": {"nature": 0.8, "culture": 0.3, "food": 0.4, "adventure": 0.9,
                   "nightlife": 0.6, "relax": 0.2, "family_friendly": 0.0},
    },
    "couple_generalist": {
        "id": "couple_generalist",
        "label": "Balanced Couple",
        "blurb": "A couple who enjoys a bit of everything — no strong preferences.",
        "travel_mode": "couple",
        "vector": {"nature": 0.6, "culture": 0.6, "food": 0.6, "adventure": 0.5,
                   "nightlife": 0.3, "relax": 0.5, "family_friendly": 0.6},
    },
    "family_with_kids": {
        "id": "family_with_kids",
        "label": "Family with Kids",
        "blurb": "Parents traveling with children, favoring relaxed and family-friendly places.",
        "travel_mode": "family",
        "vector": {"nature": 0.7, "culture": 0.5, "food": 0.6, "adventure": 0.3,
                   "nightlife": 0.0, "relax": 0.6, "family_friendly": 1.0},
    },
}


def _vec_from_dict(d: dict) -> np.ndarray:
    v = np.array([d.get(k, 0.0) for k in FEATURE_NAMES], dtype=float)
    norm = np.linalg.norm(v)
    return v / norm if norm > 0 else v


def _poi_prize(poi: "Poi", uvec: np.ndarray, pop_scores: dict) -> float:
    from app.config import settings
    w_sim = getattr(settings, "toptw_w_sim", 0.7)
    w_pop = getattr(settings, "toptw_w_pop", 0.3)
    prize, _ = compute_prize(poi, uvec, pop_scores, w_sim, w_pop)
    return round(prize, 4)


def _opening_windows(
    poi: "Poi",
    num_days: int,
    day_start_min: int,
    day_end_min: int,
) -> list[list[int] | None]:
    """Per-day [startMin, endMin] display windows (minutes from midnight).

    Mirrors the solver's view by construction: each window is
    ``toptw_solver.time_window_seconds`` for that weekday converted back to
    minutes-from-midnight (so no-data POIs show the full day span and split
    periods collapse to the bounding interval, exactly as the solver sees
    them). ``None`` = the solver gives the POI no node that day.
    """
    from app.services.toptw_solver import time_window_seconds

    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    day_total_s = (day_end_min - day_start_min) * 60
    windows: list[list[int] | None] = []
    for d in range(num_days):
        # Match toptw_solver.plan(): day 0 is today, not tomorrow.
        date = today + timedelta(days=d)
        gday = (date.weekday() + 1) % 7  # Google: 0=Sun … 6=Sat
        win = time_window_seconds(poi, gday, day_start_min, day_total_s)
        if win is None:
            windows.append(None)
            continue
        open_s, close_s = win
        windows.append([
            day_start_min + open_s // 60,
            day_start_min + close_s // 60,
        ])
    return windows


def _stop_to_dict(stop: "_Stop", kind: str = "visit") -> dict:
    start_min = stop.arrival.hour * 60 + stop.arrival.minute
    end_min = stop.departure.hour * 60 + stop.departure.minute
    return {
        "poiId": str(stop.poi.id),
        "arrivalMin": start_min,
        "departMin": end_min,
        "kind": kind,
        "transportFromPrevious": stop.transport,
        "travelMinutesFromPrevious": (
            round(stop.travel_minutes, 1) if stop.transport else None
        ),
    }


def _is_food_stop(stop: "_Stop") -> bool:
    return any(t in FOOD_TYPES for t in (stop.poi.types or []))


def _day_idle_min(stops: list["_Stop"], day_start_min: int, day_end_min: int) -> int:
    """Waiting not explained by travel (opening-hour waits, the gap before a
    floored dinner) plus the unused tail of the day. Uses the scheduler's own
    per-leg travel minutes, so it is exact for both solvers."""
    if not stops:
        return max(0, day_end_min - day_start_min)
    idle = 0.0
    if stops:
        first_arrival_min = stops[0].arrival.hour * 60 + stops[0].arrival.minute
        idle += max(0, first_arrival_min - day_start_min)
    prev = None
    for s in stops:
        if prev is not None:
            gap = (s.arrival - prev.departure).total_seconds() / 60 - (s.travel_minutes or 0)
            if gap > 0:
                idle += gap
        prev = s
    last_depart_min = (
        stops[-1].departure.hour * 60 + stops[-1].departure.minute if stops else 0
    )
    return int(round(idle + max(0, day_end_min - last_depart_min)))


async def _compute_replay(
    db: "AsyncSession",
    stops: list["_Stop"],
    day_date: datetime,
    end_min: int,
    walk_threshold_m: float,
) -> dict:
    """Replay one fixed route with the thesis feasibility metric's travel model.

    The order and visit durations stay unchanged. Every inter-stop leg is resolved
    cache-first with ``allow_api=False``, exactly like
    ``evaluation.metrics.compute_metrics``: API-derived rows are real travel times,
    while a cache miss (or a cached no-route row) falls back to Haversine.
    """
    from sqlalchemy import select

    from app.models.poi_travel_time import PoiTravelTime
    from app.services.routes_client import get_travel_time

    wanted_keys: set[tuple] = set()
    for previous, stop in zip(stops, stops[1:]):
        distance_m = haversine_m(
            previous.poi.lat, previous.poi.lng, stop.poi.lat, stop.poi.lng,
        )
        mode, _ = select_transport(distance_m, walk_threshold_m)
        wanted_keys.add((previous.poi.id, stop.poi.id, _SCHED_TO_DB_MODE[mode]))

    cache_sources: dict[tuple, str] = {}
    if wanted_keys:
        result = await db.execute(
            select(PoiTravelTime).where(
                PoiTravelTime.origin_poi_id.in_({key[0] for key in wanted_keys}),
                PoiTravelTime.dest_poi_id.in_({key[1] for key in wanted_keys}),
                PoiTravelTime.mode.in_({key[2] for key in wanted_keys}),
            )
        )
        cache_sources = {
            (row.origin_poi_id, row.dest_poi_id, row.mode): row.source
            for row in result.scalars()
            if (row.origin_poi_id, row.dest_poi_id, row.mode) in wanted_keys
        }

    replay_stops = []
    cur_min = (
        stops[0].arrival.hour * 60 + stops[0].arrival.minute
        if stops else 0
    )
    overrun_min = 0
    closed_on_arrival: list[str] = []
    real_legs = 0
    cached_fallback_legs = 0
    uncached_fallback_legs = 0

    for index, stop in enumerate(stops):
        if index == 0:
            travel_min = 0.0
            transport = None
        else:
            previous = stops[index - 1]
            distance_m = haversine_m(
                previous.poi.lat, previous.poi.lng, stop.poi.lat, stop.poi.lng,
            )
            transport, _ = select_transport(distance_m, walk_threshold_m)
            db_mode = _SCHED_TO_DB_MODE[transport]
            key = (previous.poi.id, stop.poi.id, db_mode)
            travel_min, _ = await get_travel_time(
                db, previous.poi, stop.poi, db_mode, allow_api=False,
            )
            source = cache_sources.get(key)
            if source == "routes_api":
                real_legs += 1
            elif source == "haversine_fallback":
                cached_fallback_legs += 1
            else:
                uncached_fallback_legs += 1

        arrival_exact = cur_min + travel_min
        depart_exact = arrival_exact + stop.visit_duration_minutes
        arrival_min = round(arrival_exact)
        depart_min = round(depart_exact)

        # Check if POI is closed on arrival
        probe_dt = day_date.replace(
            hour=0, minute=0, second=0, microsecond=0,
        ) + timedelta(minutes=arrival_exact)
        if not _is_open(stop.poi, probe_dt) and not _is_food_stop(stop):
            closed_on_arrival.append(str(stop.poi.id))

        replay_stops.append({
            "poiId": str(stop.poi.id),
            "arrivalMin": arrival_min,
            "departMin": depart_min,
            "transportFromPrevious": transport,
            "travelMinutesFromPrevious": (
                round(travel_min, 1) if transport else None
            ),
        })
        cur_min = depart_exact

    if cur_min > end_min:
        overrun_min = round(cur_min - end_min, 1)

    total_legs = max(0, len(stops) - 1)
    return {
        "stops": replay_stops,
        "overrunMin": overrun_min,
        "closedOnArrival": closed_on_arrival,
        "totalLegs": total_legs,
        "realLegs": real_legs,
        "fallbackLegs": cached_fallback_legs + uncached_fallback_legs,
        "cachedFallbackLegs": cached_fallback_legs,
        "uncachedFallbackLegs": uncached_fallback_legs,
    }


# ---------------------------------------------------------------------------
# Main trace builder
# ---------------------------------------------------------------------------

async def build_trace(
    db: "AsyncSession",
    city_name: str,
    persona_id: str,
    num_days: int,
    solver: str = "both",
    start_time_str: str | None = None,
    end_time_str: str | None = None,
) -> dict:
    """Run the production planners with passive instrumentation and return the trace.

    The itineraries come from ``itinerary_planner.generate`` — the exact function
    the app's /itineraries/generate endpoint calls — so the demo shows what the
    app actually produces. Greedy runs without a session (haversine estimates,
    the thesis baseline); TOPTW runs with the session (real cached travel times).
    """
    from app.models.city import City
    from app.models.preference import UserPreference
    from sqlalchemy import select
    from app.services.candidate_query import fetch_candidate_pois
    from app.services.itinerary_planner import _apply_mode_bias

    persona = DEMO_PERSONAS.get(persona_id)
    if not persona:
        raise ValueError(f"Unknown persona_id: {persona_id!r}")

    travel_mode = persona.get("travel_mode", "solo")
    # Same schedule the app derives from the travel mode.
    from app.routers.itineraries import _schedule_for_mode
    from app.schemas.itinerary import TravelMode

    mode_start, mode_end = _schedule_for_mode(TravelMode(travel_mode))
    start_time_str = start_time_str or mode_start
    end_time_str = end_time_str or mode_end

    user_prefs = UserPreference(**persona["vector"])
    # Display prizes must match the planner's view: same mode-biased vector.
    uvec = _apply_mode_bias(_vec_from_dict(persona["vector"]), travel_mode)

    # Load city
    result = await db.execute(select(City).where(City.name == city_name))
    city = result.scalar_one_or_none()
    if city is None:
        raise ValueError(f"City {city_name!r} not found in database")

    city_lat, city_lng = float(city.lat), float(city.lng)

    # Load the broad eligible pool for the visual filtering step. Family personas
    # also load the production child-safe pool so the trace can show exactly which
    # candidates the SQL suitability filter removed.
    raw_pois = await fetch_candidate_pois(db, city.id, travel_with_children=False)
    family_mode = persona.get("travel_mode") == "family"
    planner_pois = (
        await fetch_candidate_pois(db, city.id, travel_with_children=True)
        if family_mode else list(raw_pois)
    )

    raw_food_pois = [
        p for p in raw_pois
        if (p.travel_category == "food" or is_actual_food_poi(p))
        and (p.is_touristic is None or p.is_touristic is True)
    ]
    raw_activity_pois = [
        p for p in raw_pois
        if p.travel_category != "food" and not is_actual_food_poi(p) and is_touristic(p)
    ]
    food_pois = [
        p for p in planner_pois
        if (p.travel_category == "food" or is_actual_food_poi(p))
        and (p.is_touristic is None or p.is_touristic is True)
    ]
    activity_before_radius = [
        p for p in planner_pois
        if p.travel_category != "food" and not is_actual_food_poi(p) and is_touristic(p)
    ]

    max_radius_m = resolve_activity_radius_m(
        activity_before_radius, city_lat, city_lng, num_days,
    )
    radius_excluded = [
        p for p in activity_before_radius
        if haversine_m(p.lat, p.lng, city_lat, city_lng) > max_radius_m
    ]
    activity_pois = [
        p for p in activity_before_radius
        if haversine_m(p.lat, p.lng, city_lat, city_lng) <= max_radius_m
    ]

    # Production applies this Python-level family guard after the radius filter.
    family_nightlife_excluded: list["Poi"] = []
    if family_mode:
        family_nightlife_excluded = [
            p for p in activity_pois if p.travel_category == "nightlife"
        ]
        activity_pois = [
            p for p in activity_pois if p.travel_category != "nightlife"
        ]

    # Mirror production near-coincident deduplication and retain the removed→kept
    # relationship so the frontend can animate duplicate markers collapsing.
    from app.config import settings

    before_dedup = list(activity_pois)
    if settings.dedup_radius_m > 0:
        activity_pois = _dedupe_nearby_pois(activity_pois, settings.dedup_radius_m)
    kept_ids = {p.id for p in activity_pois}
    duplicate_pois = [p for p in before_dedup if p.id not in kept_ids]
    duplicate_pairs: list[dict[str, str]] = []
    for removed in duplicate_pois:
        nearby_kept = [
            kept for kept in activity_pois
            if haversine_m(removed.lat, removed.lng, kept.lat, kept.lng)
            <= settings.dedup_radius_m
        ]
        if nearby_kept:
            canonical = min(
                nearby_kept,
                key=lambda kept: haversine_m(
                    removed.lat, removed.lng, kept.lat, kept.lng,
                ),
            )
            duplicate_pairs.append({
                "removedId": str(removed.id),
                "keptId": str(canonical.id),
            })

    planner_ids = {p.id for p in planner_pois}
    family_sql_excluded = [p for p in raw_pois if p.id not in planner_ids]
    raw_display_ids = {p.id for p in raw_activity_pois + raw_food_pois}
    family_excluded_ids = {
        str(p.id)
        for p in family_sql_excluded + family_nightlife_excluded
        if p.id in raw_display_ids
    }

    pop_scores = compute_popularity_scores(planner_pois)
    food_pois.sort(key=lambda p: _cosine_sim(_poi_vec(p), uvec), reverse=True)

    sh, sm = map(int, start_time_str.split(":"))
    eh, em = map(int, end_time_str.split(":"))
    day_start_min = sh * 60 + sm
    day_end_min = eh * 60 + em

    # The map includes pre-filter candidates; the solvers receive only the final
    # activity/food pools above.
    all_demo_pois = raw_activity_pois + raw_food_pois
    raw_food_ids = {p.id for p in raw_food_pois}

    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)

    def _make_poi_dict(p: "Poi") -> dict:
        pvec = {k: round(float(getattr(p, k) or 0.0), 3) for k in FEATURE_NAMES}
        landmark = is_landmark_poi(p)
        prize = _poi_prize(p, uvec, pop_scores)
        open_win = _opening_windows(p, num_days, day_start_min, day_end_min)
        pop = round(float(pop_scores.get(p.id, 0.5)), 3)
        _, visit_min, _ = resolve_visit_mode(p, _cosine_sim(_poi_vec(p), uvec))
        return {
            "id": str(p.id),
            "name": p.name,
            "lat": p.lat,
            "lng": p.lng,
            "category": p.travel_category or "unknown",
            "isFood": p.id in raw_food_ids,
            "vector": pvec,
            "popularity": pop,
            "landmark": landmark,
            "visit_min": visit_min,
            "opening": open_win,
            "prize": prize,
        }

    pois_out = [_make_poi_dict(p) for p in all_demo_pois]
    final_demo_pois = activity_pois + food_pois
    final_lats = [p.lat for p in final_demo_pois]
    final_lngs = [p.lng for p in final_demo_pois]
    filtered_bounds = (
        [
            [min(final_lats) - 0.01, min(final_lngs) - 0.01],
            [max(final_lats) + 0.01, max(final_lngs) + 0.01],
        ]
        if final_lats else
        [[city_lat - 0.1, city_lng - 0.1], [city_lat + 0.1, city_lng + 0.1]]
    )
    preprocessing = {
        "initialCount": len(all_demo_pois),
        "finalCount": len(activity_pois) + len(food_pois),
        "radiusM": round(max_radius_m),
        "dedupRadiusM": round(settings.dedup_radius_m),
        "familyMode": family_mode,
        "radiusExcluded": [str(p.id) for p in radius_excluded],
        "familyExcluded": sorted(family_excluded_ids),
        "duplicates": duplicate_pairs,
        "finalActivityIds": [str(p.id) for p in activity_pois],
        "finalFoodIds": [str(p.id) for p in food_pois],
        "filteredBounds": filtered_bounds,
    }

    greedy_trace: dict | None = None
    toptw_trace: dict | None = None

    walk_threshold_m = compute_walk_threshold_m(None, float(persona["vector"].get("relax", 0.0)))

    if solver in ("greedy", "both"):
        greedy_trace = await _build_greedy_trace(
            planner_pois, user_prefs, travel_mode, num_days,
            start_time_str, end_time_str, day_start_min, day_end_min,
            city_lat, city_lng, walk_threshold_m, db,
        )

    if solver in ("toptw", "both"):
        toptw_trace = await _build_toptw_trace(
            planner_pois, user_prefs, travel_mode, num_days,
            start_time_str, end_time_str, day_start_min, day_end_min,
            city_lat, city_lng, db,
        )

    prize_by_id = {p["id"]: p["prize"] for p in pois_out}
    metrics = _compute_metrics(greedy_trace, toptw_trace, num_days, prize_by_id)

    # City bounds from POI bounding box
    lats = [p.lat for p in all_demo_pois]
    lngs = [p.lng for p in all_demo_pois]
    if lats:
        bounds = [[min(lats) - 0.01, min(lngs) - 0.01],
                  [max(lats) + 0.01, max(lngs) + 0.01]]
    else:
        bounds = [[city_lat - 0.1, city_lng - 0.1],
                  [city_lat + 0.1, city_lng + 0.1]]

    from app.services.itinerary_planner import LANDMARK_BOOST, MMR_LAMBDA

    return {
        "traceVersion": TRACE_VERSION,
        "city": {
            "name": city_name,
            "center": [city_lat, city_lng],
            "bounds": bounds,
        },
        "persona": persona,
        "daySpan": [day_start_min, day_end_min],
        "schedule": {"start": start_time_str, "end": end_time_str},
        # The actual runtime parameters, so captions never drift from config.
        "params": {
            "wSim": getattr(settings, "toptw_w_sim", 0.7),
            "wPop": getattr(settings, "toptw_w_pop", 0.3),
            "landmarkBoost": LANDMARK_BOOST,
            "mmrLambda": MMR_LAMBDA,
            "timeLimitS": settings.toptw_time_limit_s,
            "balanceMin": settings.toptw_cluster_balance_min,
        },
        "pois": pois_out,
        "preprocessing": preprocessing,
        "greedy": greedy_trace,
        "toptw": toptw_trace,
        "metrics": metrics,
    }


async def _build_greedy_trace(
    planner_pois: list["Poi"],
    user_prefs,
    travel_mode: str,
    num_days: int,
    start_time_str: str,
    end_time_str: str,
    day_start_min: int,
    day_end_min: int,
    city_lat: float,
    city_lng: float,
    walk_threshold_m: float,
    db: "AsyncSession",
) -> dict:
    """Run the production greedy pipeline (thesis baseline).

    Calls ``itinerary_planner.generate`` — the same function the app's endpoint
    uses — with ``session=None`` so the scheduler plans on haversine estimates,
    exactly like the old system. The real-time replay then stress-tests that
    plan with cached real travel times.
    """
    from app.services import itinerary_planner

    hooks: dict = {}
    days, _warnings = await itinerary_planner.generate(
        user_prefs=user_prefs,
        num_days=num_days,
        start_time_str=start_time_str,
        end_time_str=end_time_str,
        candidate_places=list(planner_pois),
        city_lat=city_lat,
        city_lng=city_lng,
        travel_with_children=travel_mode == "family",
        travel_mode=travel_mode,
        session=None,
        solver="greedy",
        trace=hooks,
    )

    days_out: list[dict] = []
    for stops in days:
        if not stops:  # defensive: an empty day would break replay/date derivation
            continue
        day_date = stops[0].arrival.replace(hour=0, minute=0, second=0, microsecond=0)
        stops_out: list[dict] = []
        route_ids: list[str] = []
        for s in stops:
            kind = "meal" if _is_food_stop(s) else "visit"
            stops_out.append(_stop_to_dict(s, kind))
            route_ids.append(str(s.poi.id))

        replay = await _compute_replay(db, stops, day_date, day_end_min, walk_threshold_m)

        days_out.append({
            "stops": stops_out,
            "route": route_ids,
            "idleMin": _day_idle_min(stops, day_start_min, day_end_min),
            "replayReal": replay,
        })

    return {
        "clusters": hooks.get("clusters", {}),
        "selected": hooks.get("mmr_selected", []),
        "days": days_out,
        "refill": [],
    }


async def _build_toptw_trace(
    planner_pois: list["Poi"],
    user_prefs,
    travel_mode: str,
    num_days: int,
    start_time_str: str,
    end_time_str: str,
    day_start_min: int,
    day_end_min: int,
    city_lat: float,
    city_lng: float,
    db: "AsyncSession",
) -> dict:
    """Run the production TOPTW pipeline exactly as the app does.

    ``session=db`` enables the real cached travel matrix, pre-clustering,
    under-full fill and TSPTW reorder — the itinerary shown is the one the app
    would return. Intermediate snapshots come from the passive ``trace`` hooks
    in ``generate``/``plan``.
    """
    from app.services import itinerary_planner

    hooks: dict = {}
    days, _warnings = await itinerary_planner.generate(
        user_prefs=user_prefs,
        num_days=num_days,
        start_time_str=start_time_str,
        end_time_str=end_time_str,
        candidate_places=list(planner_pois),
        city_lat=city_lat,
        city_lng=city_lng,
        travel_with_children=travel_mode == "family",
        travel_mode=travel_mode,
        session=db,
        solver="toptw",
        trace=hooks,
    )

    poi_by_id = {str(p.id): p for p in planner_pois}
    scheduled_ids = {str(s.poi.id) for stops in days for s in stops}
    candidate_ids: list[str] = hooks.get("candidates", [])
    # The solver drops unplaceable POIs silently, so the exact cause (opening
    # windows vs day budget) is not recorded — report the honest umbrella reason.
    excluded_notable = [
        {"poiId": pid, "reason": "not_scheduled"}
        for pid in candidate_ids
        if pid not in scheduled_ids
        and pid in poi_by_id and is_landmark_poi(poi_by_id[pid])
    ]

    pre_reorder: dict[int, list[str]] = hooks.get("pre_reorder", {})
    post_reorder: dict[int, list[str]] = hooks.get("post_reorder", {})
    post_reorder_stops: dict[int, list["_Stop"]] = hooks.get("post_reorder_stops", {})
    pre_meal_stops: dict[int, list["_Stop"]] = hooks.get("pre_meal_stops", {})

    def _total_travel(ids: list[str]) -> float:
        pts = [poi_by_id[i] for i in ids if i in poi_by_id]
        if not pts:
            return 0.0
        total = haversine_m(city_lat, city_lng, pts[0].lat, pts[0].lng)
        for a, b in zip(pts, pts[1:]):
            total += haversine_m(a.lat, a.lng, b.lat, b.lng)
        return total

    def _activity_stops_out(stops: list["_Stop"]) -> list[dict]:
        return [_stop_to_dict(stop, "visit") for stop in stops]

    days_out: list[dict] = []
    returned_day_indices: list[int] = hooks.get(
        "returned_day_indices", list(range(len(days)))
    )
    for returned_idx, stops in enumerate(days):
        stops_out: list[dict] = []
        activity_route: list[str] = []
        for s in stops:
            kind = "meal" if _is_food_stop(s) else "visit"
            stops_out.append(_stop_to_dict(s, kind))
            if kind == "visit":
                activity_route.append(str(s.poi.id))

        # plan() records the original solver-day index because empty days are omitted
        # from the returned list.
        route_set = set(activity_route)
        source_day_idx = returned_day_indices[returned_idx]
        pre_ids = activity_route
        if source_day_idx in pre_reorder:
            best_ids = pre_reorder[source_day_idx]
            if route_set & set(best_ids):
                # Same POIs in the solver's pre-reorder order (minus any the
                # scheduler later skipped) — the honest "before untangling" view.
                pre_ids = [pid for pid in best_ids if pid in route_set]

        reordered_ids = post_reorder.get(source_day_idx, activity_route)
        common_reorder_ids = set(reordered_ids)
        comparable_pre_ids = [pid for pid in pre_ids if pid in common_reorder_ids]

        pre_dist = _total_travel(comparable_pre_ids)
        post_dist = _total_travel(reordered_ids)
        travel_saved_pct = round(
            100.0 * (pre_dist - post_dist) / pre_dist, 1
        ) if pre_dist > 0 else 0.0

        days_out.append({
            "sourceDayIdx": source_day_idx,
            "preReorderRoute": pre_ids,
            "route": activity_route,
            "reorderStops": _activity_stops_out(
                post_reorder_stops.get(source_day_idx, [])
            ),
            "preMealStops": _activity_stops_out(
                pre_meal_stops.get(source_day_idx, [])
            ),
            "stops": stops_out,
            "idleMin": _day_idle_min(stops, day_start_min, day_end_min),
            "travelSavedPct": travel_saved_pct,
        })

    fill_trace: dict = hooks.get("fill", {})
    fill_days_out = {
        str(day_idx): {
            "status": state.get("status", "not_evaluated"),
            "usedMinBefore": round(state.get("used_s_before", 0) / 60, 1),
            "usedMinAfter": round(state.get("used_s_after", 0) / 60, 1),
            "injected": state.get("injected", []),
            "scheduled": state.get("scheduled", []),
        }
        for day_idx, state in fill_trace.get("days", {}).items()
    }
    injected = [
        pid for state in fill_days_out.values() for pid in state["injected"]
    ]
    scheduled_fill = [
        pid for state in fill_days_out.values() for pid in state["scheduled"]
    ]
    return {
        "candidates": candidate_ids,
        "zones": hooks.get("zones", {}),
        "balance": hooks.get("balance", 0.0),
        "preClusterActive": hooks.get("pre_cluster_active", False),
        "pruned": hooks.get("pruned", []),
        "excludedNotable": excluded_notable[:3],  # cap for display
        "days": days_out,
        "refill": {
            "enabled": fill_trace.get("enabled", False),
            "applicable": fill_trace.get("applicable", False),
            "ratio": fill_trace.get("ratio", 0.0),
            "budgetMin": round(fill_trace.get("budget_s", 0) / 60, 1),
            "thresholdMin": round(fill_trace.get("threshold_s", 0) / 60, 1),
            "injected": injected,
            "added": scheduled_fill,
            "byDay": {
                day_idx: state["scheduled"]
                for day_idx, state in fill_days_out.items()
                if state["scheduled"]
            },
            "days": fill_days_out,
        },
    }


def _compute_metrics(
    greedy: dict | None,
    toptw: dict | None,
    num_days: int,
    prize_by_id: dict | None = None,
) -> dict:
    """Compute comparison metrics from the two traces.
    Falls back to thesis evaluation numbers where the demo trace lacks data.
    """
    # Thesis evaluation figures (216-itinerary 2x2 factorial evaluation, real-routing
    # arm: cell B = greedy + API routing, cell D = TOPTW + API routing). avgRelevance
    # difference is NOT statistically significant (paired Wilcoxon, Holm p=0.708).
    THESIS = {
        "avgRelevance": {"greedy": 0.638, "toptw": 0.639},
        "overrunRate": {"greedy": 0.144, "toptw": 0.0},
        "stopsPerDay": {"greedy": 7.86, "toptw": 7.19},
        "diversity": {"greedy": 0.43, "toptw": 0.34},
        "idleMin": {"greedy": 29, "toptw": 76},
    }

    if greedy is None or toptw is None:
        return THESIS

    # Compute actual demo metrics where possible
    g_days = greedy.get("days", [])
    t_days = toptw.get("days", [])

    # Overrun rate over the days actually returned (skipped days can't overrun)
    g_overrun_days = sum(1 for d in g_days if d.get("replayReal", {}).get("overrunMin", 0) > 0)
    g_overrun_rate = (
        round(g_overrun_days / len(g_days), 3)
        if g_days else THESIS["overrunRate"]["greedy"]
    )
    t_overrun_rate = 0.0  # TOPTW guarantees no overrun by design

    # Mean prize (relevance) over included activity POIs. Uses the same prize
    # values shown on the map, so the "quantity/variety cost" cards above are
    # read against the (statistically non-significant) quality difference.
    def _avg_relevance(days):
        if not prize_by_id:
            return None
        prizes = [
            prize_by_id[s["poiId"]]
            for d in days
            for s in d.get("stops", [])
            if s.get("kind") == "visit" and s.get("poiId") in prize_by_id
        ]
        return round(sum(prizes) / len(prizes), 3) if prizes else None

    g_avg_relevance = _avg_relevance(g_days) or THESIS["avgRelevance"]["greedy"]
    t_avg_relevance = _avg_relevance(t_days) or THESIS["avgRelevance"]["toptw"]

    # Stops/day (activity only). A genuine 0 is a valid demo value — only fall
    # back to the thesis figure when there are no days at all.
    def _activity_stops(days):
        total = sum(
            sum(1 for s in d.get("stops", []) if s.get("kind") == "visit")
            for d in days
        )
        return round(total / len(days), 2) if days else 0.0

    # Idle min/day (both computed the same way from the scheduled stops)
    g_idle = round(
        sum(d.get("idleMin", 0) for d in g_days) / len(g_days), 1
    ) if g_days else THESIS["idleMin"]["greedy"]
    t_idle = round(
        sum(d.get("idleMin", 0) for d in t_days) / len(t_days), 1
    ) if t_days else THESIS["idleMin"]["toptw"]

    return {
        "avgRelevance": {"greedy": g_avg_relevance, "toptw": t_avg_relevance},
        "overrunRate": {"greedy": g_overrun_rate, "toptw": t_overrun_rate},
        "stopsPerDay": {
            "greedy": _activity_stops(g_days) if g_days else THESIS["stopsPerDay"]["greedy"],
            "toptw": _activity_stops(t_days) if t_days else THESIS["stopsPerDay"]["toptw"],
        },
        "diversity": THESIS["diversity"],  # requires embedding computation — use thesis value
        "idleMin": {
            "greedy": g_idle,
            "toptw": t_idle,
        },
    }

