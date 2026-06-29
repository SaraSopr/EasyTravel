"""Unit + light integration tests for the TOPTW itinerary solver.

No DB and no network: depots default to the city center and routing is disabled
(``routes_api_enabled`` defaults to False), so ``plan`` runs purely on the
haversine fallback. See docs/toptw-itinerary-solver-spec.md.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from app.services import itinerary_planner, toptw_solver
from app.services.itinerary_planner import _is_open, food_price_level_limit

# Rome-ish coordinates, a few hundred metres apart so travel legs are short.
_BASE_LAT, _BASE_LNG = 41.9000, 12.4900


def _poi(
    name: str,
    *,
    dlat: float = 0.0,
    dlng: float = 0.0,
    opening_hours=None,
    types=None,
    travel_category="culture",
    user_ratings_total=1000,
    rating=4.5,
    culture=0.9,
    nature=0.1,
    tourism_duration_minutes=60,
    tourism_visit_type="indoor",
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        lat=_BASE_LAT + dlat,
        lng=_BASE_LNG + dlng,
        opening_hours=opening_hours,
        types=types or ["tourist_attraction"],
        travel_category=travel_category,
        user_ratings_total=user_ratings_total,
        rating=rating,
        is_indoor_visitable=True,
        tourism_duration_minutes=tourism_duration_minutes,
        tourism_visit_type=tourism_visit_type,
        # feature vector dimensions
        nature=nature, culture=culture, food=0.0, adventure=0.0,
        nightlife=0.0, relax=0.0, family_friendly=0.0,
    )


def _restaurant(name: str, *, dlat: float = 0.0, dlng: float = 0.0, price_level: int | None = None):
    poi = _poi(
        name, dlat=dlat, dlng=dlng,
        opening_hours=None,  # always open
        types=["restaurant"], travel_category="food",
        tourism_duration_minutes=75, tourism_visit_type="indoor",
    )
    poi.price_level = price_level
    return poi


def _uvec():
    # Strong culture preference, matching the default POIs.
    return np.array([0.1, 0.9, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=float)


def test_food_preference_caps_price_level():
    assert food_price_level_limit(0.25) == 2
    assert food_price_level_limit(0.50) == 3
    assert food_price_level_limit(0.80) is None


def test_nearest_open_food_respects_price_cap():
    cheap = _restaurant("Cheap", dlat=0.002, dlng=0.0, price_level=2)
    expensive = _restaurant("Expensive", dlat=0.0001, dlng=0.0, price_level=4)

    picked = toptw_solver._nearest_open_food(
        [expensive, cheap],
        used_ids=set(),
        t=datetime.today(),
        lat=_BASE_LAT,
        lng=_BASE_LNG,
        popularity_scores={},
        meal_only=True,
        max_price_level=food_price_level_limit(0.25),
    )

    assert picked is cheap


# ── adaptive activity radius ────────────────────────────────────────

def test_activity_radius_fixed_mode_uses_configured_radius(monkeypatch):
    monkeypatch.setattr(itinerary_planner.settings, "activity_radius_mode", "fixed", raising=False)
    monkeypatch.setattr(itinerary_planner.settings, "activity_radius_km", 8.0, raising=False)

    pois = [_poi("Near"), _poi("Far", dlat=0.14)]

    radius_m = itinerary_planner.resolve_activity_radius_m(pois, _BASE_LAT, _BASE_LNG, num_days=1)

    assert radius_m == 8000


def test_activity_radius_adaptive_expands_for_extended_poi_distribution(monkeypatch):
    monkeypatch.setattr(itinerary_planner.settings, "activity_radius_mode", "adaptive", raising=False)
    monkeypatch.setattr(itinerary_planner.settings, "activity_radius_km", 8.0, raising=False)
    monkeypatch.setattr(itinerary_planner.settings, "activity_radius_target_share", 0.85, raising=False)
    monkeypatch.setattr(itinerary_planner.settings, "activity_radius_min_pois_per_day", 8, raising=False)

    compact = [_poi(f"C{i}", dlat=0.001 * i) for i in range(5)]
    extended = [_poi(f"E{i}", dlat=0.10 + 0.005 * i) for i in range(5)]

    radius_m = itinerary_planner.resolve_activity_radius_m(
        [*compact, *extended],
        _BASE_LAT,
        _BASE_LNG,
        num_days=1,
    )

    assert 8000 < radius_m < 20000


# ── time_window_seconds ──────────────────────────────────────────────

def test_time_window_outdoor_is_full_day():
    poi = _poi("Park", opening_hours=None)
    # day window 09:00–18:00 → 9h = 32400 s
    assert toptw_solver.time_window_seconds(poi, google_day=1, day_start_min=540, day_total_s=32400) == (0, 32400)


def test_time_window_uses_correct_weekday():
    # Open Mondays (google day 1) 10:00–17:00; closed otherwise.
    oh = {"periods": [{"open": {"day": 1, "time": "1000"}, "close": {"day": 1, "time": "1700"}}]}
    poi = _poi("Museum", opening_hours=oh)
    # Monday: window relative to 09:00 start → open at +1h (3600), close at +8h (28800)
    assert toptw_solver.time_window_seconds(poi, google_day=1, day_start_min=540, day_total_s=32400) == (3600, 28800)
    # Tuesday (google day 2): closed → None
    assert toptw_solver.time_window_seconds(poi, google_day=2, day_start_min=540, day_total_s=32400) is None


def test_time_window_clamped_to_day_budget():
    # Open 08:00–23:00; day window 09:00–18:00 (budget 32400). Clamp to [0, 32400].
    oh = {"periods": [{"open": {"day": 1, "time": "0800"}, "close": {"day": 1, "time": "2300"}}]}
    poi = _poi("Basilica", opening_hours=oh)
    assert toptw_solver.time_window_seconds(poi, google_day=1, day_start_min=540, day_total_s=32400) == (0, 32400)


def test_time_window_none_when_opening_after_day_end():
    oh = {"periods": [{"open": {"day": 1, "time": "1900"}, "close": {"day": 1, "time": "2300"}}]}
    poi = _poi("Night spot", opening_hours=oh)
    # Day ends 18:00 → POI opens after the window → None
    assert toptw_solver.time_window_seconds(poi, google_day=1, day_start_min=540, day_total_s=32400) is None


# ── select_candidates: prize ordering + cap ──────────────────────────

def test_select_candidates_orders_by_prize_and_caps_n():
    # Landmark POI should outrank a low-popularity one.
    landmark = _poi("Colosseum", user_ratings_total=200_000, culture=0.9)
    minor = _poi("Minor church", user_ratings_total=300, culture=0.2)
    pois = [minor, landmark]
    out = toptw_solver.select_candidates(
        pois, _uvec(), {landmark.id: 1.0, minor.id: 0.1},
        set(), set(), n=1, w_sim=0.7, w_pop=0.3,
    )
    assert len(out) == 1
    assert out[0][0] is landmark


def test_select_candidates_applies_novelty_penalty():
    a = _poi("A", culture=0.9)
    b = _poi("B", culture=0.9)
    pops = {a.id: 0.5, b.id: 0.5}
    # b is confirmed-visited → prize ×0 → ranked last.
    out = toptw_solver.select_candidates(
        [a, b], _uvec(), pops, confirmed_visited_ids={b.id}, previously_suggested_ids=set(),
        n=2, w_sim=0.7, w_pop=0.3,
    )
    assert out[0][0] is a
    assert out[-1][0] is b


# ── plan(): end-to-end on haversine, single day ──────────────────────

@pytest.mark.asyncio
async def test_plan_single_day_returns_valid_route(monkeypatch):
    monkeypatch.setattr(toptw_solver.settings, "routes_api_enabled", False, raising=False)
    monkeypatch.setattr(toptw_solver.settings, "toptw_time_limit_s", 3, raising=False)

    activities = [
        _poi("A1", dlat=0.000, dlng=0.000),
        _poi("A2", dlat=0.002, dlng=0.001),
        _poi("A3", dlat=0.001, dlng=0.003),
        _poi("A4", dlat=0.003, dlng=0.002),
    ]
    food = [_restaurant("R1", dlat=0.001, dlng=0.001), _restaurant("R2", dlat=0.002, dlng=0.002)]

    all_days, warnings = await toptw_solver.plan(
        activity_pois=activities, food_pois=food, uvec=_uvec(), popularity_scores={},
        num_days=1, start_time_str="09:00", end_time_str="18:00",
        city_lat=_BASE_LAT, city_lng=_BASE_LNG,
        confirmed_visited_ids=set(), previously_suggested_ids=set(),
        session=None,
    )

    assert len(all_days) == 1
    day = all_days[0]
    assert day, "the day must contain stops"

    start_dt = datetime.today().replace(hour=9, minute=0, second=0, microsecond=0)
    end_dt = start_dt.replace(hour=18)
    activity_stops = [s for s in day if s.poi.travel_category != "food"]
    assert activity_stops, "at least one activity must be scheduled"
    for s in day:
        # Every stop fits within the day window and respects its opening hours.
        assert start_dt <= s.arrival <= s.departure <= end_dt
        assert _is_open(s.poi, s.arrival)


@pytest.mark.asyncio
async def test_plan_respects_restricted_opening_hours(monkeypatch):
    monkeypatch.setattr(toptw_solver.settings, "routes_api_enabled", False, raising=False)
    monkeypatch.setattr(toptw_solver.settings, "toptw_time_limit_s", 3, raising=False)

    today = datetime.today()
    gday = (today.weekday() + 1) % 7
    # One POI open only 14:00–16:00 today; if the solver includes it, arrival must
    # fall inside that window.
    restricted = _poi(
        "Afternoon-only",
        opening_hours={"periods": [{"open": {"day": gday, "time": "1400"},
                                    "close": {"day": gday, "time": "1600"}}]},
        user_ratings_total=500_000,  # high prize → solver wants it
    )
    others = [_poi(f"O{i}", dlat=0.001 * i, dlng=0.001 * i) for i in range(3)]

    all_days, _ = await toptw_solver.plan(
        activity_pois=[restricted, *others], food_pois=[_restaurant("R", dlat=0.0015, dlng=0.0015)],
        uvec=_uvec(), popularity_scores={}, num_days=1,
        start_time_str="09:00", end_time_str="20:00",
        city_lat=_BASE_LAT, city_lng=_BASE_LNG,
        confirmed_visited_ids=set(), previously_suggested_ids=set(), session=None,
    )

    for day in all_days:
        for s in day:
            if s.poi is restricted:
                assert 14 <= s.arrival.hour < 16


@pytest.mark.asyncio
async def test_fill_underfull_day_borrows_nearby_candidates(monkeypatch):
    """A sparse/short-visit zone leaves its day under-full under pinning. With the
    fill flag on, that day borrows nearby unused POIs and ends up with more stops,
    while the far zone is never polluted (borrow radius caps the reach)."""
    monkeypatch.setattr(toptw_solver.settings, "routes_api_enabled", False, raising=False)
    monkeypatch.setattr(toptw_solver.settings, "toptw_time_limit_s", 3, raising=False)
    monkeypatch.setattr(toptw_solver.settings, "toptw_num_candidates", 6, raising=False)
    monkeypatch.setattr(toptw_solver.settings, "toptw_pre_cluster_mode", "on", raising=False)
    monkeypatch.setattr(toptw_solver.settings, "toptw_prune_outliers", False, raising=False)

    # West zone: many short-visit POIs. With n=6 / 2 days only the top-3 become
    # candidates; the remaining 5 are the unused pool an under-full day can borrow.
    west = [
        _poi(f"W{i}", dlat=0.0005 * i, dlng=-0.03,
             tourism_duration_minutes=20, user_ratings_total=1000 + i)
        for i in range(8)
    ]
    # East zone: a few long-visit POIs that already fill their own day.
    east = [
        _poi(f"E{i}", dlat=0.0005 * i, dlng=0.03,
             tourism_duration_minutes=120, user_ratings_total=5000)
        for i in range(3)
    ]
    food = [_restaurant("Rw", dlng=-0.03), _restaurant("Re", dlng=0.03)]

    async def _run():
        return await toptw_solver.plan(
            activity_pois=[*west, *east], food_pois=food, uvec=_uvec(),
            popularity_scores={}, num_days=2,
            start_time_str="09:00", end_time_str="20:00",
            city_lat=_BASE_LAT, city_lng=_BASE_LNG,
            confirmed_visited_ids=set(), previously_suggested_ids=set(), session=None,
        )

    def _west_activity_count(all_days):
        best = 0
        for day in all_days:
            acts = [s for s in day if s.poi.travel_category != "food"]
            if acts and sum(s.poi.lng for s in acts) / len(acts) < _BASE_LNG:
                best = max(best, len(acts))
        return best

    monkeypatch.setattr(toptw_solver.settings, "toptw_fill_underfull_days", False, raising=False)
    days_off, _ = await _run()

    monkeypatch.setattr(toptw_solver.settings, "toptw_fill_underfull_days", True, raising=False)
    days_on, _ = await _run()

    # The under-full west day gains stops; the east day stays purely eastern.
    assert _west_activity_count(days_on) > _west_activity_count(days_off)
    for day in days_on:
        acts = [s for s in day if s.poi.travel_category != "food"]
        if acts and sum(s.poi.lng for s in acts) / len(acts) > _BASE_LNG:
            assert all(s.poi.lng > _BASE_LNG for s in acts), "east day must stay eastern"


def test_prune_cluster_outliers_drops_isolated_non_icon():
    """An isolated non-icon POI is pruned; a far-but-iconic one is protected."""
    from app.services.itinerary_planner import _prune_cluster_outliers

    core = [_poi(f"core{i}", dlat=0.0002 * i, dlng=0.0002 * i, user_ratings_total=5_000) for i in range(5)]
    outlier = _poi("Far park", dlat=0.02, dlng=0.02, user_ratings_total=20_000)        # ~3 km away
    icon = _poi("Far must-see", dlat=-0.02, dlng=-0.02, user_ratings_total=300_000)     # ~3 km away

    clusters = {0: [*core, outlier, icon]}
    pruned, dropped = _prune_cluster_outliers(clusters, max_nn_m=1500, protect_min_ratings=100_000)

    assert outlier.id in dropped          # isolated + not iconic → dropped
    assert icon.id not in dropped         # isolated but iconic → kept
    assert {p.id for p in pruned[0]} == {*(p.id for p in core), icon.id}


def test_prune_cluster_outliers_respects_min_cluster_size():
    """A cluster at/below min size is never shrunk, even with isolated members."""
    from app.services.itinerary_planner import _prune_cluster_outliers

    pois = [_poi("a"), _poi("Far b", dlat=0.03, dlng=0.03, user_ratings_total=500)]
    pruned, dropped = _prune_cluster_outliers({0: pois}, max_nn_m=1500, protect_min_ratings=100_000)

    assert dropped == set()
    assert len(pruned[0]) == 2


def test_prune_cluster_outliers_centroid_catches_subcluster_pair():
    """A pair of POIs mutually close (beating NN threshold) but both far from
    the zone centroid should be pruned by the centroid criterion."""
    from app.services.itinerary_planner import _prune_cluster_outliers

    # Large dense core tightly clustered at the centre (12 POIs keep the centroid
    # close to the core, not dragged south by the far pair).
    core = [_poi(f"core{i}", dlat=0.001 * i, dlng=0.001 * i, user_ratings_total=5_000)
            for i in range(12)]
    # Southern sub-pair: ~580 m apart (passes NN@1200m) but ~2.8 km from centroid
    far_a = _poi("Far south A", dlat=-0.025, dlng=0.000, user_ratings_total=18_000)
    far_b = _poi("Far south B", dlat=-0.025, dlng=0.007, user_ratings_total=15_000)

    clusters = {0: [*core, far_a, far_b]}
    pruned, dropped = _prune_cluster_outliers(
        clusters, max_nn_m=1200, protect_min_ratings=100_000, max_centroid_m=2500
    )

    assert far_a.id in dropped or far_b.id in dropped  # at least one of the pair pruned
    assert all(p.id not in dropped for p in core)       # core kept intact


def test_transit_legs_use_driving_matrix_scaled():
    """Transit legs reuse the driving matrix (ORS has no transit) and scale the
    time by settings.transit_driving_factor."""
    from app.config import settings
    from app.services.itinerary_planner import _travel, select_transport, haversine_m

    o = (41.9009, 12.4833)
    d = (41.9169, 12.4820)  # ~1.78 km → select_transport picks "transit"
    mode, _ = select_transport(haversine_m(*o, *d), 1250)
    assert mode == "transit"

    # only a "driving" cache entry exists (no "transit" key is ever written now)
    lookup = {("A", "B", "driving"): (6.0, 1600)}
    out_mode, minutes = _travel("A", o[0], o[1], "B", d[0], d[1], lookup, 1250)
    assert out_mode == "transit"
    assert minutes == 6.0 * settings.transit_driving_factor


def test_dedupe_nearby_pois_collapses_coincident_keeps_distinct():
    """Near-coincident POIs collapse to the most-reviewed; distinct neighbours stay."""
    from app.services.itinerary_planner import _dedupe_nearby_pois

    sistine = _poi("Sistine Chapel", dlat=0.0, dlng=0.0, user_ratings_total=50_000)
    last_judgment = _poi("The Last Judgment", dlat=0.00002, dlng=0.00002, user_ratings_total=800)  # ~3 m
    neighbour = _poi("Nearby museum", dlat=0.002, dlng=0.0, user_ratings_total=90_000)  # ~220 m

    kept = _dedupe_nearby_pois([last_judgment, sistine, neighbour], radius_m=30.0)
    names = {p.name for p in kept}

    assert "The Last Judgment" not in names      # collapsed
    assert "Sistine Chapel" in names             # canonical (more reviews) survives
    assert "Nearby museum" in names              # distinct neighbour preserved
