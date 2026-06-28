"""TOPTW itinerary solver — Team Orienteering Problem with Time Windows.

Replaces the greedy ``clustering → MMR → scheduling`` pipeline with a single
optimisation that, over *all* days at once, maximises the total relevance (prize)
of the included POIs subject to opening hours, visit durations, a per-day time
budget and **real** travel times. See docs/toptw-itinerary-solver-spec.md.

Implemented with the OR-Tools routing solver (``pywrapcp``) — the same engine the
baseline already uses for the TSP reordering in ``itinerary_planner._solve_tsp``.

Model summary:
- Vehicles = days. Each vehicle has its own day budget.
- Activity candidates are **optional** nodes; skipping one costs its prize
  (an OR-Tools disjunction with ``penalty = prize``), so the solver prefers to
  include high-prize POIs that fit in the available time.
- A candidate is replicated once per day so its time window can reflect that
  day's weekday opening hours; a single disjunction across a POI's replicas
  enforces "visit at most once, on at most one day".
- Meals are NOT solver nodes: the day budget reserves a block of time for them
  and a post-pass inserts the best open restaurant along the optimised route.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.config import settings
from app.services.itinerary_planner import (
    DINNER_MIN_H,
    DINNER_TARGET_H,
    LANDMARK_BOOST,
    LUNCH_TARGET_H,
    DEFAULT_WALK_THRESHOLD_M,
    MEAL_WINDOW_MIN,
    _PRIMARY_TYPE_DAY_CAP,
    _SCHED_TO_DB_MODE,
    _Stop,
    _cosine_sim,
    _is_open,
    _poi_vec,
    _travel,
    apply_novelty_penalty,
    is_landmark_poi,
    get_food_duration,
    haversine_m,
    is_food_price_acceptable,
    is_meal_poi,
    pick_best_food,
    prefetch_travel_matrix,
    resolve_visit_mode,
    select_transport,
)

if TYPE_CHECKING:
    import numpy as np

    from app.models.poi import Poi
    from app.services.itinerary_planner import TravelLookup

logger = logging.getLogger(__name__)

# Waiting (slack) the solver may insert at a node to reach an opening time.
_SLACK_MAX_S = 4 * 3600


# ---------------------------------------------------------------------------
# Prize + time-window helpers (unit-tested)
# ---------------------------------------------------------------------------

def compute_prize(
    poi: "Poi",
    uvec: "np.ndarray",
    popularity_scores: dict,
    w_sim: float,
    w_pop: float,
) -> tuple[float, float]:
    """Return ``(prize, cosine_similarity)`` for an activity POI.

    Prize ≈ ``w_sim·cosine + w_pop·popularity (+ landmark boost)``. Unlike the
    baseline ``_combined_score`` there is **no** cluster-proximity term: geography
    is handled by the solver through travel costs, not by pre-clustering.
    """
    sim = _cosine_sim(_poi_vec(poi), uvec)
    pop = (popularity_scores or {}).get(poi.id, 0.5)
    prize = w_sim * sim + w_pop * pop
    if is_landmark_poi(poi):
        prize += LANDMARK_BOOST
    return prize, sim


def _hhmm_to_minutes(value: str) -> int:
    """Google opening-hours ``"0930"`` → minutes from midnight (570)."""
    v = int(value)
    return (v // 100) * 60 + (v % 100)


def time_window_seconds(
    poi: "Poi",
    google_day: int,
    day_start_min: int,
    day_total_s: int,
) -> tuple[int, int] | None:
    """Opening window for ``poi`` on weekday ``google_day``, in seconds-from-day-start.

    Returns ``(open_s, close_s)`` clamped to ``[0, day_total_s]`` (the day budget),
    or ``None`` if the POI is closed for the whole day window — such a POI must not
    get a node for that day.

    POIs with no ``opening_hours`` (outdoor / no data) are treated as open the whole
    day → ``(0, day_total_s)``. Split opening periods are collapsed to the bounding
    ``[min open, max close]`` interval (a single OR-Tools CumulVar range).
    """
    if not poi.opening_hours:
        return (0, day_total_s)
    try:
        periods = poi.opening_hours.get("periods", [])
    except Exception:  # malformed opening_hours → assume open
        return (0, day_total_s)
    if not periods:
        return (0, day_total_s)

    opens: list[int] = []
    closes: list[int] = []
    for period in periods:
        open_info = period.get("open", {})
        close_info = period.get("close", {})
        if open_info.get("day") != google_day:
            continue
        opens.append(_hhmm_to_minutes(open_info.get("time", "0000")))
        closes.append(_hhmm_to_minutes(close_info.get("time", "2359")) if close_info else 23 * 60 + 59)

    if not opens:
        return None  # closed that weekday

    open_s = max(0, (min(opens) - day_start_min) * 60)
    close_s = min(day_total_s, (max(closes) - day_start_min) * 60)
    if close_s <= open_s:
        return None  # opening hours don't overlap the day window
    return (open_s, close_s)


# ---------------------------------------------------------------------------
# Candidate pre-filter
# ---------------------------------------------------------------------------

def select_candidates(
    activity_pois: list["Poi"],
    uvec: "np.ndarray",
    popularity_scores: dict,
    confirmed_visited_ids: set,
    previously_suggested_ids: set,
    n: int,
    w_sim: float,
    w_pop: float,
) -> list[tuple["Poi", float, float]]:
    """Top-N activity candidates by (novelty-penalised) prize.

    Returns ``[(poi, prize, cosine_sim), ...]`` sorted by prize desc, length ≤ n.
    """
    scored: list[tuple["Poi", float, float]] = []
    for poi in activity_pois:
        prize, sim = compute_prize(poi, uvec, popularity_scores, w_sim, w_pop)
        prize = apply_novelty_penalty(
            prize, poi.id, confirmed_visited_ids, previously_suggested_ids,
            is_landmark=is_landmark_poi(poi),
        )
        scored.append((poi, prize, sim))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:n]


# ---------------------------------------------------------------------------
# OR-Tools model
# ---------------------------------------------------------------------------

class _Node:
    """A node in the routing graph: a depot or a (candidate, day) replica."""

    __slots__ = ("lat", "lng", "poi", "poi_id", "day", "sim", "prize", "service_s", "window")

    def __init__(self, lat, lng, poi=None, day=None, sim=1.0, prize=0.0, service_s=0):
        self.lat = lat
        self.lng = lng
        self.poi = poi
        self.poi_id = poi.id if poi is not None else None
        self.day = day
        self.sim = sim
        self.prize = prize
        self.service_s = service_s
        self.window = None  # (open_s, close_s) for replica nodes


def _build_travel_seconds(
    nodes: list[_Node],
    travel_lookup: "TravelLookup",
    walk_threshold_m: float = DEFAULT_WALK_THRESHOLD_M,
) -> list[list[int]]:
    """Full node×node travel-time matrix (seconds).

    Real cached times are used for POI→POI legs (mode chosen from the haversine
    distance, matching the scheduler); depot legs and cache misses fall back to
    the haversine estimate. Travel time is day-independent, so replicas of the
    same POI share the same leg times.
    """
    n = len(nodes)
    matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        a = nodes[i]
        for j in range(n):
            if i == j:
                continue
            b = nodes[j]
            dist = haversine_m(a.lat, a.lng, b.lat, b.lng)
            mode, hav_min = select_transport(dist, walk_threshold_m)
            seconds = int(hav_min * 60)
            if travel_lookup and a.poi_id is not None and b.poi_id is not None:
                hit = travel_lookup.get((a.poi_id, b.poi_id, _SCHED_TO_DB_MODE[mode]))
                if hit is not None:
                    seconds = int(hit[0] * 60)
            matrix[i][j] = seconds
    return matrix


def _solve(
    candidates: list[tuple["Poi", float, float]],
    num_days: int,
    day_start_min: int,
    day_total_s: int,
    budget_s: int,
    day_dates: list[datetime],
    start_lat: float,
    start_lng: float,
    end_lat: float,
    end_lng: float,
    travel_lookup: "TravelLookup",
    prize_scale: int,
    time_limit_s: int,
    day_assignment: dict | None = None,
    walk_threshold_m: float = DEFAULT_WALK_THRESHOLD_M,
) -> list[list[tuple["Poi", float]]] | None:
    """Build and solve the TOPTW model. Returns per-day ordered ``[(poi, sim)]``.

    ``None`` if OR-Tools found no solution at all (caller falls back / warns).

    ``day_assignment`` (optional): ``{poi_id: day_index}``. When given, a POI gets a
    replica only on its assigned day, pinning it to one geographic cluster (keeps
    days spatially compact). When ``None``, a replica is created for every day and
    the solver is free to place the POI on any day (global TOPTW).
    """
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    # --- Nodes: depot(s) first, then (candidate, day) replicas ---
    same_depot = abs(start_lat - end_lat) < 1e-9 and abs(start_lng - end_lng) < 1e-9
    nodes: list[_Node] = [_Node(start_lat, start_lng)]  # 0 = start depot
    if same_depot:
        end_node_idx = 0
    else:
        nodes.append(_Node(end_lat, end_lng))  # 1 = end depot
        end_node_idx = 1

    # Replicas, grouped by POI for the disjunction.
    replicas_by_poi: dict[object, list[int]] = {}
    for poi, prize, sim in candidates:
        _, visit_dur, _ = resolve_visit_mode(poi, sim)
        service_s = int(visit_dur * 60)
        google_days = [(d.weekday() + 1) % 7 for d in day_dates]
        pinned_day = day_assignment.get(poi.id) if day_assignment is not None else None
        for day, gday in enumerate(google_days):
            if pinned_day is not None and day != pinned_day:
                continue  # pre-clustered: this POI belongs to another day
            window = time_window_seconds(poi, gday, day_start_min, day_total_s)
            if window is None:
                continue  # closed that day → no replica
            node = _Node(poi.lat, poi.lng, poi=poi, day=day, sim=sim, prize=prize, service_s=service_s)
            node.window = window
            idx = len(nodes)
            nodes.append(node)
            replicas_by_poi.setdefault(poi.id, []).append(idx)

    if not replicas_by_poi:
        return None

    starts = [0] * num_days
    ends = [end_node_idx] * num_days
    manager = pywrapcp.RoutingIndexManager(len(nodes), num_days, starts, ends)
    routing = pywrapcp.RoutingModel(manager)

    travel_seconds = _build_travel_seconds(nodes, travel_lookup, walk_threshold_m)

    def time_cb(from_index: int, to_index: int) -> int:
        f = manager.IndexToNode(from_index)
        t = manager.IndexToNode(to_index)
        return travel_seconds[f][t] + nodes[f].service_s

    transit_idx = routing.RegisterTransitCallback(time_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    routing.AddDimension(
        transit_idx,
        _SLACK_MAX_S,      # waiting allowed to reach an opening time
        day_total_s,       # max cumul (seconds from day start)
        True,              # start cumul fixed to 0 = day start
        "Time",
    )
    time_dim = routing.GetDimensionOrDie("Time")

    # Per-day activity budget: the day's route must finish within the budget that
    # leaves room for post-inserted meals.
    for v in range(num_days):
        time_dim.CumulVar(routing.End(v)).SetMax(budget_s)

    # Time windows + per-day allowed vehicle for each replica.
    for idx in range(len(nodes)):
        node = nodes[idx]
        if node.poi is None:
            continue
        ri = manager.NodeToIndex(idx)
        open_s, close_s = node.window
        time_dim.CumulVar(ri).SetRange(open_s, close_s)
        # Restrict this replica to its own day's vehicle: it may be either
        # unperformed (-1) or served by vehicle ``node.day``. (The
        # SetAllowedVehiclesForIndex binding is unusable in this OR-Tools build.)
        routing.VehicleVar(ri).SetValues([-1, node.day])

    # Optional nodes: one disjunction per POI across its day-replicas; skipping the
    # POI (no replica performed) costs its prize. max_cardinality=1 → at most one
    # replica, i.e. the POI is visited on at most one day.
    for poi_id, indices in replicas_by_poi.items():
        ris = [manager.NodeToIndex(i) for i in indices]
        prize = nodes[indices[0]].prize
        routing.AddDisjunction(ris, int(max(prize, 0.0) * prize_scale), 1)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.time_limit.seconds = max(1, time_limit_s)

    solution = routing.SolveWithParameters(params)
    if solution is None:
        return None

    days: list[list[tuple["Poi", float]]] = []
    for v in range(num_days):
        ordered: list[tuple["Poi", float]] = []
        index = routing.Start(v)
        while not routing.IsEnd(index):
            node = nodes[manager.IndexToNode(index)]
            if node.poi is not None:
                ordered.append((node.poi, node.sim))
            index = solution.Value(routing.NextVar(index))
        days.append(ordered)
    return days


# ---------------------------------------------------------------------------
# Meal post-insertion (decision #1) + time propagation on the optimised route
# ---------------------------------------------------------------------------

def _nearest_open_food(
    food_pois: list["Poi"],
    used_ids: set,
    t: datetime,
    lat: float,
    lng: float,
    popularity_scores: dict,
    meal_only: bool,
    max_price_level: int | None = None,
) -> "Poi | None":
    """Best open (optionally meal-grade) food POI near (lat, lng) at time ``t``.

    Mirrors the baseline ``_pick_nearest_open_food``: quality-aware scoring within a
    walkable radius (proximity + rating − takeaway penalty), nearest as fallback.
    """
    eligible: list[tuple["Poi", float]] = []
    for fp in food_pois:
        if fp.id in used_ids:
            continue
        if not _is_open(fp, t):
            continue
        if meal_only and not is_meal_poi(fp):
            continue
        if not is_food_price_acceptable(fp, max_price_level):
            continue
        eligible.append((fp, haversine_m(lat, lng, fp.lat, fp.lng)))
    return pick_best_food(eligible, popularity_scores)


def schedule_day_route(
    ordered_activities: list[tuple["Poi", float]],
    food_pois: list["Poi"],
    used_food_ids: set,
    day_date: datetime,
    start_dt: datetime,
    end_dt: datetime,
    depot_lat: float,
    depot_lng: float,
    popularity_scores: dict,
    travel_lookup: "TravelLookup",
    max_food_price_level: int | None = None,
    walk_threshold_m: float = DEFAULT_WALK_THRESHOLD_M,
) -> list[_Stop]:
    """Turn the solver's ordered activities into timed ``_Stop``s + insert meals.

    Times are propagated from ``start_dt`` with the real travel cache (haversine
    fallback). Lunch/dinner are inserted along the already-optimised route at the
    nearest open restaurant to the route position at the meal hour (fix for the
    meal-detour problem). ``used_food_ids`` is mutated to share the food pool
    across days.
    """
    final_stops: list[_Stop] = []
    type_counts: dict[str, int] = {}
    activity_count = 0
    cur = start_dt
    cur_lat, cur_lng = depot_lat, depot_lng
    cur_id = None

    lunch_inserted = False
    dinner_inserted = False
    lunch_target = day_date.replace(hour=LUNCH_TARGET_H, minute=0, second=0, microsecond=0)
    dinner_target = day_date.replace(hour=DINNER_TARGET_H, minute=0, second=0, microsecond=0)

    def _add_food_stop(food_poi: "Poi", forced_arrival: datetime | None = None) -> bool:
        nonlocal cur, cur_lat, cur_lng, cur_id
        if not final_stops:
            transport, travel_min = None, 0.0
        else:
            transport, travel_min = _travel(
                cur_id, cur_lat, cur_lng, food_poi.id, food_poi.lat, food_poi.lng,
                travel_lookup, walk_threshold_m,
            )
        arrival = forced_arrival if forced_arrival is not None else cur + timedelta(minutes=travel_min)
        vm, vd, vn = resolve_visit_mode(food_poi, 1.0)
        departure = arrival + timedelta(minutes=vd)
        if departure > end_dt:
            return False
        final_stops.append(_Stop(
            poi=food_poi, arrival=arrival, departure=departure, transport=transport,
            travel_minutes=travel_min, similarity_score=1.0,
            visit_mode=vm, visit_duration_minutes=vd, visit_note=vn,
        ))
        used_food_ids.add(food_poi.id)
        cur = departure
        cur_lat, cur_lng = food_poi.lat, food_poi.lng
        cur_id = food_poi.id
        return True

    def _try_insert_meal(target: datetime) -> bool:
        fp = _nearest_open_food(
            food_pois, used_food_ids, cur, cur_lat, cur_lng, popularity_scores,
            meal_only=True, max_price_level=max_food_price_level,
        )
        if fp is None:
            fp = _nearest_open_food(
                food_pois, used_food_ids, cur, cur_lat, cur_lng, popularity_scores,
                meal_only=False, max_price_level=max_food_price_level,
            )
        if fp is None:
            return False
        return _add_food_stop(fp)

    def _add_activity_stop(poi: "Poi", sim_score: float) -> str:
        """Returns "added" | "skip" (type cap) | "full" (no time left)."""
        nonlocal cur, cur_lat, cur_lng, cur_id, activity_count
        if not final_stops:
            transport, travel_min = None, 0.0
        else:
            transport, travel_min = _travel(
                cur_id, cur_lat, cur_lng, poi.id, poi.lat, poi.lng,
                travel_lookup, walk_threshold_m,
            )
        arrival = cur + timedelta(minutes=travel_min)
        # The solver may have used waiting (slack) to reach this POI's opening time;
        # re-propagation here does no waiting, so reproduce it: if we'd arrive before
        # it opens, wait (up to the solver's slack budget) until it does.
        if not _is_open(poi, arrival):
            waited = None
            probe = arrival
            for _ in range(_SLACK_MAX_S // 300):  # 5-min steps up to slack budget
                probe = probe + timedelta(minutes=5)
                if probe > end_dt:
                    break
                if _is_open(poi, probe):
                    waited = probe
                    break
            if waited is None:
                return "skip"
            arrival = waited
        vm, vd, vn = resolve_visit_mode(poi, sim_score)
        departure = arrival + timedelta(minutes=vd)
        if departure > end_dt:
            return "full"
        primary = (poi.types or [""])[0]
        cap = _PRIMARY_TYPE_DAY_CAP.get(primary)
        if cap is not None and type_counts.get(primary, 0) >= cap:
            return "skip"
        final_stops.append(_Stop(
            poi=poi, arrival=arrival, departure=departure, transport=transport,
            travel_minutes=travel_min, similarity_score=sim_score,
            visit_mode=vm, visit_duration_minutes=vd, visit_note=vn,
        ))
        type_counts[primary] = type_counts.get(primary, 0) + 1
        activity_count += 1
        cur = departure
        cur_lat, cur_lng = poi.lat, poi.lng
        cur_id = poi.id
        return "added"

    for poi, sim in ordered_activities:
        if not lunch_inserted and cur >= lunch_target - timedelta(minutes=MEAL_WINDOW_MIN):
            lunch_inserted = _try_insert_meal(lunch_target) or lunch_inserted
        if not dinner_inserted and cur >= dinner_target - timedelta(minutes=MEAL_WINDOW_MIN):
            dinner_inserted = _try_insert_meal(dinner_target) or dinner_inserted
        result = _add_activity_stop(poi, sim)
        if result == "full":
            break
        # "skip" (type cap) → just move on to the next activity.

    # Post-loop: insert any meal not yet placed (e.g. all activities ended early).
    # Only if the day actually has activities — a food-only day makes no sense.
    if activity_count and not lunch_inserted:
        if _try_insert_meal(lunch_target):
            lunch_inserted = True
    if activity_count and not dinner_inserted:
        fp = _nearest_open_food(
            food_pois, used_food_ids, cur, cur_lat, cur_lng, popularity_scores,
            meal_only=True, max_price_level=max_food_price_level,
        ) or _nearest_open_food(
            food_pois, used_food_ids, cur, cur_lat, cur_lng, popularity_scores,
            meal_only=False, max_price_level=max_food_price_level,
        )
        if fp is not None:
            _, travel_min = _travel(
                cur_id, cur_lat, cur_lng, fp.id, fp.lat, fp.lng, travel_lookup, walk_threshold_m
            )
            arrival = cur + timedelta(minutes=travel_min)
            dinner_min_dt = day_date.replace(hour=DINNER_MIN_H, minute=0, second=0, microsecond=0)
            if arrival < dinner_min_dt and dinner_min_dt + timedelta(minutes=get_food_duration(fp)) <= end_dt:
                _add_food_stop(fp, forced_arrival=dinner_min_dt)
            else:
                _add_food_stop(fp)

    return final_stops


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def plan(
    activity_pois: list["Poi"],
    food_pois: list["Poi"],
    uvec: "np.ndarray",
    popularity_scores: dict,
    num_days: int,
    start_time_str: str,
    end_time_str: str,
    city_lat: float,
    city_lng: float,
    confirmed_visited_ids: set,
    previously_suggested_ids: set,
    start_lat: float | None = None,
    start_lng: float | None = None,
    end_lat: float | None = None,
    end_lng: float | None = None,
    session=None,
    max_food_price_level: int | None = None,
    walk_threshold_m: float = DEFAULT_WALK_THRESHOLD_M,
) -> tuple[list[list[_Stop]], list[str]]:
    """Plan a multi-day itinerary with the TOPTW solver.

    Inputs mirror the post-filter state of ``itinerary_planner.generate`` (already
    touristic/radius/family-filtered activity & food pools, user vector, popularity).
    Returns ``(all_days, warnings)`` exactly like the greedy path.
    """
    import asyncio

    warnings: list[str] = []

    n = settings.toptw_num_candidates
    candidates = select_candidates(
        activity_pois, uvec, popularity_scores,
        confirmed_visited_ids, previously_suggested_ids,
        n, settings.toptw_w_sim, settings.toptw_w_pop,
    )
    if not candidates:
        return [], ["No activity candidates available for this city."]

    # --- Geographic pre-clustering: pin each POI to one day's cluster ---
    # Keeps every day spatially compact, at the cost of the solver's freedom to
    # rebalance prize across days. With far outliers already removed by the activity-
    # radius filter, candidates cluster into balanced day-regions and pinning helps
    # (it fixes Roma's badly-balanced global solution and slightly improves Madrid).
    # The only failure mode is a degenerate split (one dominant cluster + a sparse
    # tail); "auto" detects that via the cluster balance and falls back to global
    # TOPTW. "on"/"off" force the choice (thesis A/B).
    day_assignment: dict | None = None
    mode = (settings.toptw_pre_cluster_mode or "auto").strip().lower()
    if mode != "off" and num_days > 1:
        from app.services.itinerary_planner import (
            _cluster_pois, _rebalance_clusters, _prune_cluster_outliers, haversine_m,
        )

        # Cluster the FULL activity pool (not just the prize-filtered top-N) so the
        # day-zones reflect the city's real geographic density — the same input the
        # greedy baseline uses, which yields cleaner, more recognisable zones and
        # sidesteps the degenerate [38, 38, 4] split the sparse top-N produced (which
        # otherwise drove "auto" to fall back to a sprawling global TOPTW). Candidates
        # are then pinned to the zone that geographically contains them.
        cluster_pool = (
            activity_pois if settings.toptw_cluster_full_pool else [c[0] for c in candidates]
        )
        clusters = _rebalance_clusters(_cluster_pois(cluster_pool, num_days, city_lat, city_lng))
        # Order zones → day indices deterministically (west→east by centroid lng),
        # capping at num_days so an over-split never produces an out-of-range day.
        ordered_clusters = sorted(
            (pois for pois in clusters.values() if pois),
            key=lambda ps: sum(p.lng for p in ps) / len(ps),
        )[:num_days]
        zone_centroids = [
            (sum(p.lat for p in z) / len(z), sum(p.lng for p in z) / len(z))
            for z in ordered_clusters
        ]
        zone_of = {p.id: zi for zi, z in enumerate(ordered_clusters) for p in z}

        # Group the prize candidates by their zone (nearest centroid if a candidate
        # wasn't in the clustered pool — only possible on the full-pool path for a POI
        # the radius filter dropped from activity_pois, so practically never).
        cand_by_day: dict = {zi: [] for zi in range(len(ordered_clusters))}
        for c in candidates:
            zi = zone_of.get(c[0].id)
            if zi is None:
                zi = min(
                    range(len(zone_centroids)),
                    key=lambda k: haversine_m(c[0].lat, c[0].lng, *zone_centroids[k]),
                )
            cand_by_day[zi].append(c[0])

        # Balance is measured on the CANDIDATES per day (what the solver can actually
        # schedule) — a zone dense in the pool but thin in candidates still starves
        # its day.
        sizes = [len(cand_by_day[zi]) for zi in range(len(ordered_clusters))]
        total = sum(sizes)
        even_share = total / num_days if num_days else 0
        balance = (min(sizes) / even_share) if (sizes and even_share) else 0.0

        if mode == "on" or (mode == "auto" and balance >= settings.toptw_cluster_balance_min):
            # Drop intra-day outliers (a stray candidate far from its day's other stops)
            # so one isolated park/site doesn't inflate the day's travel. Pruned POIs
            # leave the candidate pool entirely — otherwise they'd be un-pinned
            # (day_assignment.get → None) and free to slot on any day, the opposite of
            # pruning. Must-sees are protected inside _prune_cluster_outliers.
            if settings.toptw_prune_outliers and settings.toptw_cluster_outlier_max_nn_m > 0:
                cand_by_day, dropped_ids = _prune_cluster_outliers(
                    cand_by_day,
                    settings.toptw_cluster_outlier_max_nn_m,
                    settings.toptw_outlier_protect_min_ratings,
                    max_centroid_m=settings.toptw_cluster_outlier_max_centroid_m,
                )
                if dropped_ids:
                    candidates = [c for c in candidates if c[0].id not in dropped_ids]
                    sizes = [len(cand_by_day[zi]) for zi in range(len(ordered_clusters))]
                    logger.info(
                        "TOPTW pruned %d intra-cluster outlier(s) (max_nn=%.0fm) sizes=%s",
                        len(dropped_ids), settings.toptw_cluster_outlier_max_nn_m, sizes,
                    )
            day_assignment = {p.id: day for day, pois in cand_by_day.items() for p in pois}
            logger.info(
                "TOPTW pre-cluster ON (mode=%s balance=%.2f sizes=%s pool=%s)",
                mode, balance, sizes,
                "full" if settings.toptw_cluster_full_pool else "candidates",
            )
        else:
            logger.info(
                "TOPTW pre-cluster OFF (mode=%s balance=%.2f < %.2f sizes=%s) → global TOPTW",
                mode, balance, settings.toptw_cluster_balance_min, sizes,
            )

    # Depots default to the city center.
    s_lat = start_lat if start_lat is not None else city_lat
    s_lng = start_lng if start_lng is not None else city_lng
    e_lat = end_lat if end_lat is not None else s_lat
    e_lng = end_lng if end_lng is not None else s_lng

    sh, sm = map(int, start_time_str.split(":"))
    eh, em = map(int, end_time_str.split(":"))
    day_start_min = sh * 60 + sm
    day_total_s = ((eh * 60 + em) - day_start_min) * 60
    budget_s = max(0, day_total_s - settings.toptw_meal_reserve_min * 60)

    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    day_dates = [today + timedelta(days=i) for i in range(num_days)]

    # --- Pre-fetch the real travel matrix for the candidate POIs (one batch) ---
    travel_lookup: TravelLookup = {}
    if session is not None and settings.routes_api_enabled:
        try:
            travel_lookup = await prefetch_travel_matrix(
                session, [c[0] for c in candidates], walk_threshold_m
            )
        except Exception as exc:  # routing must never block generation
            logger.warning("TOPTW travel-matrix prefetch failed (%s) — using haversine", exc)

    logger.info(
        "TOPTW: %d candidates, %d days, budget=%dmin (day=%dmin, meal_reserve=%dmin)",
        len(candidates), num_days, budget_s // 60, day_total_s // 60, settings.toptw_meal_reserve_min,
    )

    loop = asyncio.get_event_loop()
    solver_days = await loop.run_in_executor(
        None,
        _solve,
        candidates, num_days, day_start_min, day_total_s, budget_s, day_dates,
        s_lat, s_lng, e_lat, e_lng, travel_lookup,
        settings.toptw_prize_scale, settings.toptw_time_limit_s,
        day_assignment, walk_threshold_m,
    )

    if solver_days is None:
        warnings.append("The optimiser could not build an itinerary; try fewer days or another city.")
        return [], warnings

    included = sum(len(d) for d in solver_days)
    logger.info("TOPTW solved: %d activity stops assigned across %d days", included, num_days)

    # --- Per-day: meal post-insertion + time propagation (shared food pool) ---
    all_days: list[list[_Stop]] = []
    used_food_ids: set = set()
    for day_idx, ordered in enumerate(solver_days):
        day_date = day_dates[day_idx]
        start_dt = day_date.replace(hour=sh, minute=sm, second=0)
        end_dt = day_date.replace(hour=eh, minute=em, second=0)

        if not ordered:
            warnings.append(f"Day {day_idx + 1} has no scheduled activities.")
            continue

        available_food = [p for p in food_pois if p.id not in used_food_ids]
        stops = schedule_day_route(
            ordered, available_food, used_food_ids,
            day_date, start_dt, end_dt, s_lat, s_lng,
            popularity_scores, travel_lookup, max_food_price_level,
            walk_threshold_m,
        )
        if not stops:
            warnings.append(f"Day {day_idx + 1} has no schedulable activities.")
            continue
        all_days.append(stops)

    # POIs the solver could not place anywhere are dropped silently — opening hours
    # and budget are hard constraints, so there is no "deferred for hours" notion.
    placed = sum(len(d) for d in all_days)
    if placed < len(candidates):
        logger.info(
            "TOPTW: %d/%d candidates not placeable within opening hours and budget",
            len(candidates) - placed, len(candidates),
        )

    return all_days, warnings
