"""Automatic itinerary metrics (see docs/evaluation-harness-spec.md §4).

Computed on every generated itinerary, for both solver arms. Two axes:
- selection/relevance: total_relevance, landmark_coverage, intra_list_diversity
- completeness/realism: idle_minutes_per_day, budget_fill_rate, real_overrun,
  stops_per_day, meals_complete_rate

``real_overrun`` re-walks the planned sequence with the **real** travel-time cache
(cache-first, no API call) and reports how often a day no longer fits its budget.
With routing enabled it reads ~0 for a realistic plan and >0 for one built on
haversine — that's the realism signal the routing change is meant to fix.
"""
from __future__ import annotations

from datetime import datetime

from app.services.itinerary_planner import (
    _SCHED_TO_DB_MODE,
    _cosine_sim,
    _poi_vec,
    haversine_m,
    is_actual_food_poi,
    select_transport,
)
from app.services.routes_client import get_travel_time


def _is_food_stop(stop) -> bool:
    poi = stop.poi
    return poi.travel_category == "food" or is_actual_food_poi(poi)


def _minutes(td_start: datetime, td_end: datetime) -> float:
    return (td_end - td_start).total_seconds() / 60.0


async def compute_metrics(
    db,
    *,
    all_days,                       # list[list[_Stop]]
    all_activity_candidates,        # list[Poi] — the activity universe for this cell
    included_activity_ids,          # set[uuid] — activity POIs in the itinerary
    prize_by_id,                    # dict[uuid, float]
    start_str: str,
    end_str: str,
    solve_time_ms: int,
    top_n_landmark: int,
    budget_fill_threshold: float,
) -> dict:
    sh, sm = map(int, start_str.split(":"))
    eh, em = map(int, end_str.split(":"))
    budget_min = (eh * 60 + em) - (sh * 60 + sm)

    included = [p for p in all_activity_candidates if p.id in included_activity_ids]

    # --- selection / relevance ---
    total_relevance = float(sum(prize_by_id.get(p.id, 0.0) for p in included))

    top_landmarks = sorted(
        all_activity_candidates, key=lambda p: (p.user_ratings_total or 0), reverse=True
    )[:top_n_landmark]
    landmark_coverage = (
        sum(1 for p in top_landmarks if p.id in included_activity_ids) / len(top_landmarks)
        if top_landmarks else None
    )

    # intra-list diversity = 1 − mean pairwise cosine over included POI vectors
    if len(included) >= 2:
        vecs = [_poi_vec(p) for p in included]
        sims, n = 0.0, 0
        for i in range(len(vecs)):
            for j in range(i + 1, len(vecs)):
                sims += _cosine_sim(vecs[i], vecs[j])
                n += 1
        intra_list_diversity = 1.0 - (sims / n) if n else None
    else:
        intra_list_diversity = None

    # --- completeness / realism (per-day) ---
    idle_per_day: list[float] = []
    filled_days = 0
    overrun_days = 0
    overrun_minutes: list[float] = []
    meals_complete_days = 0
    activity_stops_counts: list[int] = []

    for day in all_days:
        if not day:
            continue
        first_arr = day[0].arrival
        last_dep = day[-1].departure
        occupied = _minutes(first_arr, last_dep)
        idle = max(0.0, budget_min - occupied)
        idle_per_day.append(idle)
        if budget_min > 0 and occupied / budget_min >= budget_fill_threshold:
            filled_days += 1

        food_stops = sum(1 for s in day if _is_food_stop(s))
        if food_stops >= 2:
            meals_complete_days += 1
        activity_stops_counts.append(sum(1 for s in day if not _is_food_stop(s)))

        # real_overrun: re-walk with real cached travel times (no API call)
        budget_end = first_arr.replace(hour=eh, minute=em, second=0, microsecond=0)
        cur = first_arr
        for i, stop in enumerate(day):
            if i > 0:
                prev = day[i - 1].poi
                mode, _ = select_transport(haversine_m(prev.lat, prev.lng, stop.poi.lat, stop.poi.lng))
                real_min, _m = await get_travel_time(
                    db, prev, stop.poi, _SCHED_TO_DB_MODE[mode], allow_api=False
                )
                cur = cur + _td(real_min)
            cur = cur + _td(stop.visit_duration_minutes)
        ov = max(0.0, _minutes(budget_end, cur))
        overrun_minutes.append(ov)
        if ov > 0:
            overrun_days += 1

    n_days = len([d for d in all_days if d])
    return {
        "total_relevance": round(total_relevance, 4),
        "landmark_coverage": round(landmark_coverage, 4) if landmark_coverage is not None else None,
        "intra_list_diversity": round(intra_list_diversity, 4) if intra_list_diversity is not None else None,
        "idle_minutes_per_day": round(sum(idle_per_day) / n_days, 1) if n_days else None,
        "budget_fill_rate": round(filled_days / n_days, 3) if n_days else None,
        "real_overrun_day_rate": round(overrun_days / n_days, 3) if n_days else None,
        "real_overrun_min_avg": round(sum(overrun_minutes) / n_days, 1) if n_days else None,
        "stops_per_day": round(sum(activity_stops_counts) / n_days, 2) if n_days else None,
        "meals_complete_rate": round(meals_complete_days / n_days, 3) if n_days else None,
        "num_days_filled": n_days,
        "solve_time_ms": solve_time_ms,
    }


def _td(minutes: float):
    from datetime import timedelta
    return timedelta(minutes=minutes)
