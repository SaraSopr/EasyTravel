from __future__ import annotations

import asyncio
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np

from app.config import settings

if TYPE_CHECKING:
    from app.models.poi import Poi
    from app.models.preference import UserPreference

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FOOD_TYPES: frozenset[str] = frozenset(
    {"restaurant", "cafe", "bakery", "bar", "food", "meal_takeaway", "meal_delivery"}
)

# Suitable for a full meal (lunch or dinner)
MEAL_SERVICE_TYPES: frozenset[str] = frozenset({
    "restaurant",
    "meal_takeaway",
    "meal_delivery",
})

# Suitable only for snacks, coffee, breakfast
SNACK_SERVICE_TYPES: frozenset[str] = frozenset({
    "cafe",
    "bakery",
    "bar",
    "food",
})

# Union of both — used for food/activity separation (is_actual_food_poi)
FOOD_SERVICE_TYPES: frozenset[str] = MEAL_SERVICE_TYPES | SNACK_SERVICE_TYPES

EXCLUDED_TYPES: frozenset[str] = frozenset({
    # Medical / health services
    "doctor", "dentist", "hospital", "pharmacy", "physiotherapist",
    "health", "veterinary_care",
    # Fitness (not tourist attractions)
    "gym",
    # Accommodation (visited to sleep, not to tour)
    "lodging",
    # Beauty / personal care (not tourist attractions)
    "beauty_salon", "hair_care", "nail_salon",
    # Nightlife / entertainment venues (not tourist attractions)
    "night_club", "movie_theater", "casino",
    # Leisure venues that are not tourist attractions
    "bowling_alley", "spa",
    # Shopping venues (not attractions)
    "shopping_mall",
    # Cemetery (individual graves are not tourist attractions)
    "cemetery",
    # Daily errands
    "laundry", "car_wash", "car_repair", "car_dealer",
    "gas_station", "parking", "bank", "atm",
    "post_office", "insurance_agency", "real_estate_agency",
    "lawyer", "accounting",
    # Generic retail (not attractions)
    "store", "clothing_store", "furniture_store", "hardware_store",
    "home_goods_store", "electronics_store",
    "grocery_or_supermarket", "supermarket",
    "convenience_store", "liquor_store", "department_store",
    # Other non-touristic
    "moving_company", "storage", "funeral_home",
    "embassy", "local_government_office", "courthouse",
    "fire_station", "police",
    "electrician", "plumber", "painter", "locksmith", "roofing_contractor",
    "general_contractor",
    # Commercial services that are not tourist attractions
    "travel_agency", "bicycle_store",
})

# Types that require a much higher popularity threshold (≥5000 ratings)
# to filter out local/minor venues while keeping only famous landmarks.
HIGH_POPULARITY_TYPES: frozenset[str] = frozenset({"stadium", "race_track"})

# Types that typically require indoor access (for visit_mode resolution)
_NEEDS_HOURS_TYPES: frozenset[str] = frozenset({
    "museum", "art_gallery", "church", "library",
    "restaurant", "cafe", "bakery", "bar", "food",
    "amusement_park", "stadium", "zoo", "aquarium",
    "meal_takeaway",
})

VISIT_DURATION_INDOOR: dict[str, int] = {
    "museum": 120, "art_gallery": 90, "church": 45, "library": 45,
    "aquarium": 90, "zoo": 150, "amusement_park": 180, "stadium": 120,
    "tourist_attraction": 90,
    "default": 60,
}

VISIT_DURATION_OUTDOOR: dict[str, int] = {
    "park": 45, "campground": 60, "natural_feature": 20,
    "tourist_attraction": 45, "point_of_interest": 30,
    "default": 30,
}

VISIT_DURATION_FOOD: dict[str, int] = {
    "restaurant": 75, "cafe": 30, "bakery": 20, "bar": 45,
    "meal_takeaway": 15,
    "default": 45,
}

SPEED_MS: dict[str, float] = {"walking": 1.39, "transit": 5.56, "taxi": 8.33}

LUNCH_TARGET_H = 13    # 13:00
DINNER_TARGET_H = 20   # 20:00
MEAL_WINDOW_MIN = 30   # start looking 30 min before target hour
DINNER_MIN_H = 18      # post-loop dinner insertion won't fire before this hour

OUTDOOR_VISIT_THRESHOLD = 0.3   # below this cosine similarity → exterior visit only
MMR_LAMBDA = 0.6                # weight of relevance vs diversity in MMR

# Max times the same primary Google type may appear as an activity stop in one day.
# Prevents church/basilica fatigue in cities like Rome.
_PRIMARY_TYPE_DAY_CAP: dict[str, int] = {
    "church": 2,
    "place_of_worship": 2,
    "tourist_attraction": 5,
}
SAME_CATEGORY_PENALTY = 0.3     # extra redundancy penalty for same travel_category
CONFIRMED_VISITED_SCORE = 0.0   # multiplier for confirmed-visited POIs (rank last)
IMPLICIT_SUGGESTED_PENALTY = 0.6  # multiplier for recently-suggested POIs
IMPLICIT_WINDOW_DAYS = 365      # window for implicit "previously suggested" signal

LANDMARK_THRESHOLD: int = 10_000  # user_ratings_total >= this → globally famous landmark
LANDMARK_BOOST: float = 0.15      # score bonus applied to landmark POIs

# POIs within this distance of an already-selected POI are considered duplicates
# and receive a maximum redundancy penalty in MMR (prevents Bernabéu + Tour Bernabéu).
MMR_MIN_DISTANCE_M: float = 150.0

# Activity POIs beyond this radius from the city center are excluded before clustering
# (prevents out-of-city day-trip destinations like Aranjuez appearing in urban itineraries).
# This is the hard ceiling; the effective radius is usually tighter (see
# resolve_activity_radius_m, which adapts it to each city's POI distribution).
MAX_CITY_RADIUS_KM: float = 20.0

# Senior age buckets (see app.constants.AGE_RANGES). "55-70" and "70+" are the
# current senior cohorts; "55+" is the legacy bucket kept for rows stored before
# the split (reads stay tolerant — new input is validated to the canonical set).
SENIOR_AGE_RANGES: frozenset[str] = frozenset({"55-70", "70+", "55+"})

# Per-age multiplier on the base walking cut-off: how far each cohort is willing
# to walk before switching to transit/taxi. Missing/unknown age → 1.0 (neutral).
# "55+" is the legacy value (≈ the 55-70 bucket) for already-stored profiles.
_AGE_WALK_FACTOR: dict[str, float] = {
    "18-25": 1.6,
    "26-35": 1.4,
    "36-45": 1.2,
    "46-55": 1.0,
    "55-70": 0.75,
    "70+": 0.55,
    "55+": 0.75,  # legacy
}

from app.constants import FEATURE_NAMES as _FEATURE_KEYS


# ---------------------------------------------------------------------------
# Touristic filter helpers
# ---------------------------------------------------------------------------

def is_touristic(poi: Poi) -> bool:
    """
    Returns True if no type in the POI's types array is in EXCLUDED_TYPES.
    All types are checked (not just primary) so venues like cinemas or hotels
    that appear as secondary types are always excluded.
    """
    poi_types = poi.types or []
    if not poi_types:
        return True
    return not any(t in EXCLUDED_TYPES for t in poi_types)


def is_actual_food_poi(poi: Poi) -> bool:
    """
    Returns True for POIs that serve food as primary purpose.
    Uses FOOD_SERVICE_TYPES (union of meal + snack types).
    Excludes nightlife venues (night_club, casino).
    """
    poi_types = set(poi.types or [])
    primary_type = (poi.types or [""])[0]
    has_food_type = bool(poi_types & FOOD_SERVICE_TYPES)
    not_nightlife_primary = primary_type not in {"night_club", "casino"}
    correct_category = poi.travel_category in ("food", None)
    return has_food_type and not_nightlife_primary and correct_category


def is_meal_poi(poi: Poi) -> bool:
    """
    Returns True if the POI is suitable for a full lunch or dinner.

    Criteria:
    - Has at least one type in MEAL_SERVICE_TYPES
    - AND travel_category is "food" or None
    - AND primary type is NOT in SNACK_SERVICE_TYPES

    Examples:
    - Trattoria Da Danilo (restaurant, food) → True
    - Gelateria Giolitti (cafe, food) → False (primary type: cafe)
    - Bar San Calisto (bar, food) → False (primary type: bar)
    - McDonald's (meal_takeaway, food) → True
    - Pasticceria (bakery, food) → False (primary type: bakery)
    """
    poi_types = set(poi.types or [])
    primary_type = (poi.types or [""])[0]
    has_meal_type = bool(poi_types & MEAL_SERVICE_TYPES)
    primary_not_snack = primary_type not in SNACK_SERVICE_TYPES
    correct_category = poi.travel_category in ("food", None)
    return has_meal_type and primary_not_snack and correct_category


# Primary Google types that mark a venue as takeaway/delivery rather than a sit-down
# meal — penalised (not excluded) so a proper restaurant wins when one is nearby.
TAKEAWAY_PRIMARY_TYPES: frozenset[str] = frozenset({"meal_takeaway", "meal_delivery"})


def is_takeaway_food(poi: Poi) -> bool:
    """True if the POI's primary type is takeaway/delivery (not a proper meal venue)."""
    return (poi.types or [""])[0] in TAKEAWAY_PRIMARY_TYPES


def score_food_candidate(poi: Poi, dist_m: float, popularity: float, radius_m: float) -> float:
    """Quality-aware meal score: proximity + rating, minus a takeaway penalty.

    Proximity decays linearly to 0 at ``radius_m``; rating is the Google rating
    normalised to 0..1 (unrated → 3.5/5). Popularity is a tiny tie-break only, so
    a hugely-reviewed tourist trap can't outrank a closer, better-rated trattoria.
    """
    proximity = max(0.0, 1.0 - dist_m / radius_m) if radius_m > 0 else 0.0
    rating = (poi.rating if poi.rating is not None else 3.5) / 5.0
    score = settings.food_w_distance * proximity + settings.food_w_rating * rating
    if is_takeaway_food(poi):
        score -= settings.food_takeaway_penalty
    return score + 0.01 * popularity


def pick_best_food(
    eligible: list[tuple[Poi, float]], popularity_scores: dict | None
) -> Poi | None:
    """Best meal among eligible ``(poi, distance_m)`` by quality-aware score.

    Candidates within ``settings.food_pick_radius_m`` are ranked by
    ``score_food_candidate`` (proximity + rating − takeaway penalty). If none sit
    within the radius (sparse area), falls back to the strictly nearest so a meal is
    always placed. Returns ``None`` only when ``eligible`` is empty.
    """
    if not eligible:
        return None
    radius_m = settings.food_pick_radius_m
    within = [pd for pd in eligible if pd[1] <= radius_m]
    if not within:
        return min(eligible, key=lambda pd: pd[1])[0]
    return max(
        within,
        key=lambda pd: score_food_candidate(
            pd[0], pd[1], (popularity_scores or {}).get(pd[0].id, 0.5), radius_m
        ),
    )[0]


# ---------------------------------------------------------------------------
# Internal dataclass
# ---------------------------------------------------------------------------

@dataclass
class _Stop:
    poi: Poi
    arrival: datetime
    departure: datetime
    transport: str | None = None        # None for the first stop of the day
    travel_minutes: float = 0.0
    similarity_score: float = 1.0      # cosine similarity between user prefs and POI
    visit_mode: str = "indoor"          # "indoor" | "outdoor"
    visit_duration_minutes: int = 0    # actual visit duration used for scheduling
    visit_note: str | None = None      # e.g. "Suggested as an exterior visit"


# ---------------------------------------------------------------------------
# Duration helpers
# ---------------------------------------------------------------------------

def get_indoor_duration(poi: Poi) -> int:
    """Duration for a full indoor visit.

    Uses the MAXIMUM duration across all matching types so that type ordering
    in the Google Places array does not affect the result.
    """
    durations = [VISIT_DURATION_INDOOR[t] for t in (poi.types or []) if t in VISIT_DURATION_INDOOR]
    return max(durations) if durations else VISIT_DURATION_INDOOR["default"]


def get_outdoor_duration(poi: Poi) -> int:
    """Duration for an exterior/outdoor visit.

    Uses the MAXIMUM duration across all matching types so that type ordering
    in the Google Places array does not affect the result.
    """
    durations = [VISIT_DURATION_OUTDOOR[t] for t in (poi.types or []) if t in VISIT_DURATION_OUTDOOR]
    return max(durations) if durations else VISIT_DURATION_OUTDOOR["default"]


def get_food_duration(poi: Poi) -> int:
    """Duration for a food POI visit.

    Uses the MAXIMUM duration across all matching types so that a place tagged
    as both "bar" and "restaurant" (or "meal_takeaway" and "restaurant") gets
    the longer sit-down duration rather than the shorter snack duration.
    """
    durations = [
        VISIT_DURATION_FOOD[t]
        for t in (poi.types or [])
        if t in VISIT_DURATION_FOOD
    ]
    return max(durations) if durations else VISIT_DURATION_FOOD["default"]


def resolve_visit_mode(
    poi: Poi,
    similarity_score: float,
) -> tuple[str, int, str | None]:
    """
    Returns (visit_mode, duration_minutes, visit_note).

    Logic:
    - If tourism_duration_minutes is set, it takes priority over lookup tables.
    - Food POIs: always "indoor", food duration, no note (restaurants are always entered)
    - Genuinely outdoor (is_indoor_visitable=False): "outdoor", outdoor duration, no note
    - Indoor (is_indoor_visitable=True or inferred via types) + similarity >= threshold:
        "indoor", indoor duration, no note
    - Indoor + similarity < threshold:
        "outdoor", outdoor duration, "Suggested as an exterior visit"
    - Unknown (is_indoor_visitable=None, not inferred as indoor):
        "outdoor", outdoor duration, no note
    """
    poi_types = set(poi.types or [])

    # Tourism validation duration takes priority over lookup tables
    if poi.tourism_duration_minutes is not None:
        vtype = poi.tourism_visit_type
        if vtype == "outdoor":
            return "outdoor", poi.tourism_duration_minutes, None
        elif vtype == "indoor":
            return "indoor", poi.tourism_duration_minutes, None
        elif vtype == "both":
            if similarity_score < OUTDOOR_VISIT_THRESHOLD:
                return "outdoor", min(poi.tourism_duration_minutes, 30), "Suggested as an exterior visit"
            return "indoor", poi.tourism_duration_minutes, None
        # visit_type unknown → fall through to standard logic but keep duration

    # Food POIs: always full indoor visit regardless of similarity
    if poi_types & FOOD_TYPES:
        return "indoor", get_food_duration(poi), None

    # Genuinely outdoor POI: no ticket, always exterior
    if poi.is_indoor_visitable is False:
        return "outdoor", get_outdoor_duration(poi), None

    # Determine if this POI is indoor (explicit or inferred from types)
    is_indoor = poi.is_indoor_visitable is True or (
        poi.is_indoor_visitable is None and bool(poi_types & _NEEDS_HOURS_TYPES)
    )

    if not is_indoor:
        # Unknown type, not inferred as indoor → treat as outdoor
        return "outdoor", get_outdoor_duration(poi), None

    # Indoor POI: apply similarity threshold
    if similarity_score >= OUTDOOR_VISIT_THRESHOLD:
        return "indoor", get_indoor_duration(poi), None
    else:
        return "outdoor", get_outdoor_duration(poi), "Suggested as an exterior visit"


def get_duration(poi: Poi, similarity_score: float = 1.0) -> int:
    """Public function: returns the visit duration for a POI given a similarity score."""
    _, duration, _ = resolve_visit_mode(poi, similarity_score)
    return duration


def _get_duration(poi: Poi) -> int:
    """Legacy internal helper kept for backward compatibility."""
    return get_duration(poi, similarity_score=1.0)


def is_landmark_poi(poi: Poi) -> bool:
    """True if the POI is a globally-famous landmark (>= LANDMARK_THRESHOLD ratings)."""
    return (poi.user_ratings_total or 0) >= LANDMARK_THRESHOLD


def apply_novelty_penalty(
    score: float,
    poi_id: object,
    confirmed_visited_ids: set,
    previously_suggested_ids: set,
    is_landmark: bool = False,
) -> float:
    """
    Applies novelty penalty to a combined/MMR score.
    - Confirmed visited → score × 0.0  (rank last; not hard-excluded so sparse cities still fill)
    - Previously suggested in last 12 months → score × 0.6
    - Never seen → no change

    Landmarks (``is_landmark=True``) are exempt from the *implicit* previously-suggested
    penalty: a globally-famous POI (Colosseum, Trevi…) should not be hidden just because
    an earlier — possibly regenerated — itinerary already proposed it. The implicit signal
    conflates "shown in a draft" with "already seen", which otherwise wipes every icon out
    of a city after a few regenerations. The confirmed-visited penalty still applies (an
    explicit "I went there" is a real signal, landmark or not).
    """
    if poi_id in confirmed_visited_ids:
        return score * CONFIRMED_VISITED_SCORE
    if poi_id in previously_suggested_ids and not is_landmark:
        return score * IMPLICIT_SUGGESTED_PENALTY
    return score


# ---------------------------------------------------------------------------
# Other helpers (unchanged)
# ---------------------------------------------------------------------------

def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def resolve_activity_radius_m(
    activity_pois: list[Poi],
    city_lat: float,
    city_lng: float,
    num_days: int,
) -> float:
    """Resolve the city-centre activity radius used before solving.

    ``fixed`` mode keeps the thesis A/B switch simple. ``adaptive`` mode treats
    ``activity_radius_km`` as the compact-city floor, then expands to cover a
    configurable share/count of the candidate POI distribution, capped by the
    hard city radius to avoid day-trip outliers.

    Note: tightening the radius below the floor was tried and reverted — it helps
    spread cities but degrades compact ones (Madrid). The robust lever for the
    multi-day spread problem is conditional pre-clustering in the TOPTW solver, not
    the radius (see toptw_solver._should_pre_cluster).
    """
    min_radius_m = max(0.0, min(settings.activity_radius_km, MAX_CITY_RADIUS_KM)) * 1000
    max_radius_m = MAX_CITY_RADIUS_KM * 1000
    mode = (settings.activity_radius_mode or "adaptive").strip().lower()

    if mode == "fixed":
        return min_radius_m
    if mode != "adaptive":
        logger.warning("Unknown activity_radius_mode=%r; falling back to adaptive", mode)

    distances = sorted(
        haversine_m(p.lat, p.lng, city_lat, city_lng)
        for p in activity_pois
        if p.lat is not None and p.lng is not None
    )
    distances = [d for d in distances if d <= max_radius_m]
    if not distances:
        return min_radius_m

    target_share = max(0.0, min(1.0, settings.activity_radius_target_share))
    min_count = max(num_days * 2, num_days * max(1, settings.activity_radius_min_pois_per_day))
    share_count = math.ceil(len(distances) * target_share)
    target_count = min(len(distances), max(min_count, share_count))
    adaptive_radius_m = distances[target_count - 1]
    return max(min_radius_m, min(adaptive_radius_m, max_radius_m))


DEFAULT_WALK_THRESHOLD_M: float = 800.0  # base walking cut-off (personalization off)
TAXI_THRESHOLD_M: float = 5000.0         # above this a leg always takes a taxi


def compute_walk_threshold_m(age_range: str | None, relax: float | None) -> float:
    """Personalized walking cut-off (metres) for select_transport().

    Scales the base cut-off by the traveller's age cohort and relax preference:
    a young/intense profile walks further, a senior/relax profile switches to a
    vehicle sooner. Clamped to [min, max] so extreme profiles never degenerate.
    When personalization is disabled the fixed base is returned for everyone
    (the thesis A/B baseline). See settings.walk_* in app/config.py.
    """
    if not settings.walk_personalization:
        return settings.walk_threshold_base_m
    age_factor = _AGE_WALK_FACTOR.get((age_range or "").strip(), 1.0)
    r = 0.0 if relax is None else max(0.0, min(1.0, float(relax)))
    relax_factor = settings.walk_relax_base - settings.walk_relax_slope * r
    raw = settings.walk_threshold_base_m * age_factor * relax_factor
    return max(settings.walk_threshold_min_m, min(settings.walk_threshold_max_m, raw))


def select_transport(
    distance_m: float, walk_threshold_m: float = DEFAULT_WALK_THRESHOLD_M
) -> tuple[str, float]:
    if distance_m < walk_threshold_m:
        mode = "walking"
    elif distance_m < TAXI_THRESHOLD_M:
        mode = "transit"
    else:
        mode = "taxi"
    travel_minutes = (distance_m / SPEED_MS[mode]) / 60
    return mode, travel_minutes


# scheduler mode → DB / Routes mode (taxi maps to road "driving")
_SCHED_TO_DB_MODE: dict[str, str] = {"walking": "walking", "transit": "transit", "taxi": "driving"}

# Type alias for the in-memory travel lookup resolved from the cache before scheduling.
# Key: (origin_poi_id, dest_poi_id, db_mode) → (minutes, meters)
TravelLookup = dict


def _travel(
    origin_id,
    origin_lat: float,
    origin_lng: float,
    dest_id,
    dest_lat: float,
    dest_lng: float,
    travel_lookup: TravelLookup | None,
    walk_threshold_m: float = DEFAULT_WALK_THRESHOLD_M,
) -> tuple[str, float]:
    """Return (transport_mode, minutes) for one leg.

    The transport MODE is chosen from the haversine distance and the (possibly
    personalized) walking cut-off. The MINUTES come from the real travel-time
    cache when a hit exists, otherwise from the haversine estimate. The fallback
    is never blocking.
    """
    dist = haversine_m(origin_lat, origin_lng, dest_lat, dest_lng)
    mode, hav_min = select_transport(dist, walk_threshold_m)
    if travel_lookup and origin_id is not None and dest_id is not None:
        hit = travel_lookup.get((origin_id, dest_id, _SCHED_TO_DB_MODE[mode]))
        if hit is not None:
            return mode, hit[0]
    return mode, hav_min


async def prefetch_travel_matrix(
    session, pois: list[Poi], walk_threshold_m: float = DEFAULT_WALK_THRESHOLD_M
) -> TravelLookup:
    """Pre-populate the travel-time cache for all directed pairs among ``pois``.

    Returns a lookup keyed by (origin_id, dest_id, db_mode) → (minutes, meters).
    The mode per pair is decided by select_transport() on the haversine distance
    and the same ``walk_threshold_m`` the scheduler uses — so the mode prefetched
    matches the mode looked up later (otherwise the lookup misses and falls back
    to haversine). Only the mode each pair needs is requested (halving the matrix
    elements). Failures fall back to haversine inside routes_client — this call
    never raises on routing.
    """
    from collections import defaultdict

    from app.services import routes_client

    by_mode: dict[str, list[tuple[Poi, Poi]]] = defaultdict(list)
    for a in pois:
        for b in pois:
            if a.id == b.id:
                continue
            mode, _ = select_transport(haversine_m(a.lat, a.lng, b.lat, b.lng), walk_threshold_m)
            by_mode[_SCHED_TO_DB_MODE[mode]].append((a, b))

    lookup: TravelLookup = {}
    for db_mode, pairs in by_mode.items():
        lookup.update(await routes_client.get_travel_times_batch(session, pairs, db_mode))
    return lookup


def _is_open(poi: Poi, dt: datetime) -> bool:
    """Return True if the POI is open at the given datetime."""
    if not poi.opening_hours:
        return True  # outdoor / no data → assume always open
    try:
        periods = poi.opening_hours.get("periods", [])
        if not periods:
            return True
        # Google: day 0=Sunday … 6=Saturday; Python weekday() 0=Monday … 6=Sunday
        py_day = dt.weekday()
        google_day = (py_day + 1) % 7
        current_hhmm = dt.hour * 100 + dt.minute
        for period in periods:
            open_info = period.get("open", {})
            close_info = period.get("close", {})
            if open_info.get("day") != google_day:
                continue
            open_hhmm = int(open_info.get("time", "0000"))
            close_hhmm = int(close_info.get("time", "2359")) if close_info else 2359
            if open_hhmm <= current_hhmm <= close_hhmm:
                return True
        return False
    except Exception as exc:
        logger.warning("Could not parse opening_hours for POI %s: %s", getattr(poi, "id", "?"), exc)
        return True


def _poi_vec(poi: Poi) -> np.ndarray:
    return np.array([getattr(poi, k) or 0.0 for k in _FEATURE_KEYS], dtype=float)


def _user_vec(prefs: UserPreference) -> np.ndarray:
    return np.array([getattr(prefs, k) or 0.0 for k in _FEATURE_KEYS], dtype=float)


def food_price_level_limit(food_preference: float | None) -> int | None:
    """Map the user's food interest to the highest Google price level allowed.

    Low food interest means meals should be practical stops, not premium dining
    experiences. ``None`` means no price cap.
    """
    food = 0.0 if food_preference is None else max(0.0, min(1.0, food_preference))
    if food < 0.35:
        return 2
    if food < 0.70:
        return 3
    return None


def is_food_price_acceptable(poi: Poi, max_price_level: int | None) -> bool:
    if max_price_level is None:
        return True
    price_level = getattr(poi, "price_level", None)
    return price_level is None or price_level <= max_price_level


# Feature key order: nature, culture, food, adventure, nightlife, relax, family_friendly
_MODE_BIAS: dict[str, np.ndarray] = {
    "solo":    np.array([ 0.0,  0.0,  0.0,  0.0,  0.0,  0.0,  0.0]),
    "couple":  np.array([ 0.0,  0.05, 0.1,  0.0,  0.0,  0.15,-0.1]),
    "friends": np.array([ 0.0,  0.0,  0.05, 0.15, 0.2,  0.0, -0.1]),
    "family":  np.array([ 0.05, 0.0,  0.05, 0.05,-0.5,  0.0,  0.3]),
}


def _apply_mode_bias(uvec: np.ndarray, travel_mode: str) -> np.ndarray:
    """Add travel-mode bias to user preference vector and re-normalize."""
    bias = _MODE_BIAS.get(travel_mode, _MODE_BIAS["solo"])
    biased = uvec + bias
    biased = np.clip(biased, 0.0, None)  # no negative dimensions
    norm = np.linalg.norm(biased)
    return biased / norm if norm > 0 else uvec


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / norm) if norm > 0 else 0.0


def _solve_tsp(pois: list[Poi], depot_lat: float, depot_lng: float) -> list[Poi]:
    """Return pois reordered to minimise total travel distance from depot."""
    if len(pois) <= 1:
        return list(pois)

    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    all_points = [(depot_lat, depot_lng)] + [(p.lat, p.lng) for p in pois]
    n = len(all_points)

    dist_matrix = [
        [int(haversine_m(*all_points[i], *all_points[j])) for j in range(n)]
        for i in range(n)
    ]

    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def dist_cb(from_idx: int, to_idx: int) -> int:
        return dist_matrix[manager.IndexToNode(from_idx)][manager.IndexToNode(to_idx)]

    cb_idx = routing.RegisterTransitCallback(dist_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(cb_idx)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.time_limit.seconds = 5

    solution = routing.SolveWithParameters(params)
    if not solution:
        return list(pois)

    ordered: list[Poi] = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        if node != 0:  # skip depot
            ordered.append(pois[node - 1])
        index = solution.Value(routing.NextVar(index))
    return ordered


# ---------------------------------------------------------------------------
# Clustering helpers (unchanged)
# ---------------------------------------------------------------------------

def _cluster_pois_leiden(
    activity_pois: list[Poi],
    num_days: int,
    k_neighbors: int = 10,
) -> dict[int, list[Poi]]:
    """
    Leiden-based geographic clustering on a k-NN graph.
    See docs/leiden-clustering-spec.md for the full algorithm description.

    Steps:
      1. Build a weighted k-NN graph (edges = Haversine distance, weight = exp(-d/sigma))
      2. Run Leiden (ModularityVertexPartition) to find natural geographic communities
      3. Merge the closest community pairs until exactly num_days groups remain
    """
    import math
    import igraph as ig
    import leidenalg

    n = len(activity_pois)
    k = min(k_neighbors, n - 1)

    # --- Step 1: weighted k-NN graph ---
    dists: list[list[float]] = [
        [
            haversine_m(
                activity_pois[i].lat, activity_pois[i].lng,
                activity_pois[j].lat, activity_pois[j].lng,
            )
            for j in range(n)
        ]
        for i in range(n)
    ]

    # k nearest neighbors for each node (excluding self)
    knn_lists: list[list[int]] = []
    nn_dists: list[float] = []
    for i in range(n):
        order = sorted(range(n), key=lambda j, _i=i: dists[_i][j])
        neighbors = order[1: k + 1]
        knn_lists.append(neighbors)
        nn_dists.extend(dists[i][j] for j in neighbors)

    # Adaptive scale sigma = median of all k-NN distances
    sigma = max(float(np.median(nn_dists)) if nn_dists else 1000.0, 1.0)

    edge_set: set[tuple[int, int]] = set()
    edge_list: list[tuple[int, int]] = []
    weight_list: list[float] = []
    for i, neighbors in enumerate(knn_lists):
        for j in neighbors:
            pair = (min(i, j), max(i, j))
            if pair not in edge_set:
                edge_set.add(pair)
                edge_list.append(pair)
                weight_list.append(math.exp(-dists[i][j] / sigma))

    # --- Step 2: Leiden community detection ---
    g = ig.Graph(n=n, edges=edge_list)
    g.es["weight"] = weight_list

    partition = leidenalg.find_partition(
        g,
        leidenalg.ModularityVertexPartition,
        weights="weight",
        seed=42,
    )

    communities: dict[int, list[Poi]] = {
        cid: [activity_pois[i] for i in members]
        for cid, members in enumerate(partition)
        if members
    }

    logger.info(
        "Leiden: %d POIs → %d natural communities (target %d days)",
        n, len(communities), num_days,
    )

    if len(communities) < num_days:
        raise ValueError(
            f"Leiden found only {len(communities)} communities for {num_days} days"
        )

    # --- Step 3: size-aware hierarchical merge down to num_days ---
    # Score = geographic_distance * size_imbalance_penalty
    # where penalty = merged_size / mean_target_size, capped at 3.
    # This prevents one cluster from absorbing too many communities.
    target_size = len(activity_pois) / num_days

    while len(communities) > num_days:
        comm_ids = list(communities.keys())
        centroids: dict[int, tuple[float, float]] = {
            cid: _cluster_center(communities[cid]) for cid in comm_ids
        }

        best_pair: tuple[int, int] = (comm_ids[0], comm_ids[1])
        best_score = float("inf")
        for ii in range(len(comm_ids)):
            for jj in range(ii + 1, len(comm_ids)):
                ci, cj = comm_ids[ii], comm_ids[jj]
                geo_dist = haversine_m(*centroids[ci], *centroids[cj])
                merged_size = len(communities[ci]) + len(communities[cj])
                imbalance = 1.0 + 2.0 * ((merged_size - target_size) ** 2) / (target_size ** 2)
                score = geo_dist * imbalance
                if score < best_score:
                    best_score = score
                    best_pair = (ci, cj)

        ci, cj = best_pair
        communities[ci] = communities[ci] + communities[cj]
        del communities[cj]

    return {new_id: pois for new_id, (_, pois) in enumerate(communities.items())}


def _cluster_pois(
    activity_pois: list[Poi],
    num_days: int,
    city_lat: float,
    city_lng: float,
) -> dict[int, list[Poi]]:
    """
    Assign activity POIs to day-clusters based on geographic proximity.
    Tries Leiden clustering first; falls back to KMeans if unavailable or failed.

    Special cases:
    - num_days == 1: skip clustering, return all POIs in a single cluster
    - len(activity_pois) < num_days * 2: too few for meaningful clusters,
      return a single cluster with all POIs
    """
    if num_days == 1 or len(activity_pois) < num_days * 2:
        return {0: list(activity_pois)}

    # Try Leiden clustering (see docs/leiden-clustering-spec.md)
    try:
        return _cluster_pois_leiden(activity_pois, num_days)
    except ImportError:
        logger.info("leidenalg/igraph not installed — falling back to KMeans")
    except Exception as exc:
        logger.warning("Leiden clustering failed (%s) — falling back to KMeans", exc)

    # KMeans fallback
    from sklearn.cluster import KMeans

    coords = np.array([[p.lat, p.lng] for p in activity_pois])
    kmeans = KMeans(n_clusters=num_days, random_state=42, n_init=10)
    labels = kmeans.fit_predict(coords)

    clusters: dict[int, list[Poi]] = {i: [] for i in range(num_days)}
    for poi, label in zip(activity_pois, labels):
        clusters[int(label)].append(poi)

    # Merge clusters with fewer than 2 POIs into the nearest large cluster
    small_ids = [k for k, v in clusters.items() if 0 < len(v) < 2]
    for small_id in small_ids:
        if not clusters[small_id]:
            continue
        small_center = np.mean([[p.lat, p.lng] for p in clusters[small_id]], axis=0)
        best_id, best_dist = None, float("inf")
        for other_id, other_pois in clusters.items():
            if other_id == small_id or len(other_pois) < 2:
                continue
            other_center = np.mean([[p.lat, p.lng] for p in other_pois], axis=0)
            dist = float(np.linalg.norm(small_center - other_center))
            if dist < best_dist:
                best_dist = dist
                best_id = other_id
        if best_id is not None:
            clusters[best_id].extend(clusters[small_id])
            clusters[small_id] = []

    result = {k: v for k, v in clusters.items() if v}

    # If KMeans produced fewer clusters than num_days, split the largest
    next_id = max(result.keys()) + 1
    while len(result) < num_days:
        largest_id = max(result, key=lambda k: len(result[k]))
        largest_pois = result[largest_id]
        if len(largest_pois) < 4:
            break
        coords = np.array([[p.lat, p.lng] for p in largest_pois])
        sub = KMeans(n_clusters=2, random_state=42, n_init=10).fit_predict(coords)
        half_a = [p for p, lbl in zip(largest_pois, sub) if lbl == 0]
        half_b = [p for p, lbl in zip(largest_pois, sub) if lbl == 1]
        if not half_a or not half_b:
            break
        result[largest_id] = half_a
        result[next_id] = half_b
        next_id += 1

    return result


# Minimum POIs a cluster should have before borrowing from neighbours.
# Below this threshold the scheduler won't have enough candidates to fill a day.
_MIN_CLUSTER_SIZE: int = 10


def _rebalance_clusters(clusters: dict[int, list[Poi]]) -> dict[int, list[Poi]]:
    """
    Supplement clusters that have fewer than _MIN_CLUSTER_SIZE POIs by borrowing
    the geographically closest POIs from donor clusters.

    POIs are *moved* (not copied) so each POI still appears in exactly one cluster.
    A donor only gives away POIs it can spare: its size must exceed _MIN_CLUSTER_SIZE
    after the transfer.  If no donor can spare enough, we borrow as many as possible.
    """
    if len(clusters) <= 1:
        return clusters

    result: dict[int, list[Poi]] = {k: list(v) for k, v in clusters.items()}

    for small_id in sorted(result.keys()):
        if len(result[small_id]) >= _MIN_CLUSTER_SIZE:
            continue

        if not result[small_id]:
            continue

        small_center = np.mean([[p.lat, p.lng] for p in result[small_id]], axis=0)
        needed = _MIN_CLUSTER_SIZE - len(result[small_id])

        # Build a sorted list of (distance, cluster_id, poi) from all other clusters
        candidates: list[tuple[float, int, "Poi"]] = []
        for other_id, other_pois in result.items():
            if other_id == small_id:
                continue
            for poi in other_pois:
                dist = float(np.linalg.norm(np.array([poi.lat, poi.lng]) - small_center))
                candidates.append((dist, other_id, poi))
        candidates.sort(key=lambda x: x[0])

        borrowed = 0
        for dist, donor_id, poi in candidates:
            if borrowed >= needed:
                break
            # Only take from donor if it can afford to lose one POI
            if len(result[donor_id]) > _MIN_CLUSTER_SIZE:
                result[donor_id].remove(poi)
                result[small_id].append(poi)
                borrowed += 1

        if borrowed:
            logger.info(
                "  Cluster %d had %d POIs — borrowed %d from neighbours (now %d)",
                small_id,
                _MIN_CLUSTER_SIZE - needed,
                borrowed,
                len(result[small_id]),
            )

    return result


def _prune_cluster_outliers(
    clusters: dict[int, list[Poi]],
    max_nn_m: float,
    protect_min_ratings: int,
    min_cluster_size: int = 4,
) -> tuple[dict[int, list[Poi]], set]:
    """Drop POIs geographically isolated within their own day-cluster.

    Pre-clustering pins every POI to a day, but a stray POI far from its cluster
    mates (e.g. Villa Doria Pamphili, ~2 km from the rest of its day) inflates that
    day's travel without a nearby companion stop. Such a POI — whose nearest
    same-cluster neighbour is farther than ``max_nn_m`` — is removed so the day stays
    compact. Truly iconic POIs (``user_ratings_total >= protect_min_ratings``) are
    always kept: skipping the Colosseum to save a few minutes is never worth it. Note
    this protection threshold is deliberately far higher than ``LANDMARK_THRESHOLD``
    (10k) — at 10k a far-flung 20k-review park would be spared, which is exactly the
    case we want to prune; only the 100k+ must-sees should be untouchable. A cluster
    is never shrunk below ``min_cluster_size``; the most isolated POIs are dropped
    first.

    Returns ``(pruned_clusters, dropped_ids)``. Distances use the original cluster
    membership (one pass) — removing one far outlier does not normally strand another.
    """
    dropped: set = set()
    result: dict[int, list[Poi]] = {}
    for cid, pois in clusters.items():
        if len(pois) <= min_cluster_size:
            result[cid] = list(pois)
            continue
        scored = []
        for p in pois:
            nn = min(
                (haversine_m(p.lat, p.lng, q.lat, q.lng) for q in pois if q is not p),
                default=0.0,
            )
            scored.append((nn, p))
        scored.sort(key=lambda x: x[0], reverse=True)  # most isolated first
        kept = list(pois)
        for nn, p in scored:
            if nn <= max_nn_m:
                break  # remaining POIs are within threshold
            if (p.user_ratings_total or 0) >= protect_min_ratings:
                continue
            if len(kept) <= min_cluster_size:
                break
            kept.remove(p)
            dropped.add(p.id)
        result[cid] = kept
    return result, dropped


def _cluster_center(pois: list[Poi]) -> tuple[float, float]:
    """Geographic centroid of a list of POIs."""
    lats = [p.lat for p in pois]
    lngs = [p.lng for p in pois]
    return sum(lats) / len(lats), sum(lngs) / len(lngs)


def compute_popularity_scores(pois: list[Poi]) -> dict:
    """
    Bayesian average popularity score (IMDb-style), normalized to [0, 1].

    score(v, R) = (v * R + m * C) / (v + m)
    where:
      v = user_ratings_total for this POI
      R = average rating for this POI
      m = global median of user_ratings_total (minimum vote threshold)
      C = global mean rating across all POIs with ratings

    POIs with NULL user_ratings_total or rating get a neutral score of 0.5.
    """
    import statistics

    rated = [p for p in pois if p.rating is not None and p.user_ratings_total is not None]
    if not rated:
        return {p.id: 0.5 for p in pois}

    m = statistics.median(p.user_ratings_total for p in rated)
    C = sum(p.rating for p in rated) / len(rated)

    raw: dict = {}
    for p in pois:
        if p.rating is None or p.user_ratings_total is None:
            raw[p.id] = None
        else:
            v = p.user_ratings_total
            R = p.rating
            raw[p.id] = (v * R + m * C) / (v + m)

    valid = [s for s in raw.values() if s is not None]
    if not valid:
        return {p.id: 0.5 for p in pois}

    min_s, max_s = min(valid), max(valid)
    result: dict = {}
    for p in pois:
        s = raw[p.id]
        if s is None:
            result[p.id] = 0.5
        elif max_s > min_s:
            result[p.id] = (s - min_s) / (max_s - min_s)
        else:
            result[p.id] = 0.5
    return result


def _proximity_km_for_profile(travel_with_children: bool, age_range: str | None) -> float:
    """
    Returns the proximity reference distance (km) based on user mobility profile.
    Smaller value = tighter geographic clusters = less walking per day.
    """
    if age_range and age_range in SENIOR_AGE_RANGES:
        return 2.5
    if travel_with_children:
        return 3.0
    return 5.0


def _combined_score(
    poi: Poi,
    uvec: np.ndarray,
    center_lat: float,
    center_lng: float,
    popularity_scores: dict | None = None,
    proximity_km: float = 5.0,
) -> float:
    """
    Combined score = 0.5 * cosine_similarity + 0.3 * proximity_score + 0.2 * popularity_score.
    proximity_score: 1.0 = at cluster center, 0.0 = proximity_km+ away.
    popularity_score: Bayesian average normalized to [0, 1], default 0.5 if unknown.
    Landmark bonus: +0.15 for POIs with user_ratings_total >= LANDMARK_THRESHOLD.
    """
    sim = _cosine_sim(_poi_vec(poi), uvec)
    dist = haversine_m(poi.lat, poi.lng, center_lat, center_lng)
    proximity = 1.0 - min(dist / (proximity_km * 1000), 1.0)
    popularity = (popularity_scores or {}).get(poi.id, 0.5)
    score = 0.5 * sim + 0.3 * proximity + 0.2 * popularity
    if is_landmark_poi(poi):
        score += LANDMARK_BOOST
    return min(score, 1.0)


# ---------------------------------------------------------------------------
# MMR selection
# ---------------------------------------------------------------------------

def _poi_redundancy(candidate: Poi, selected: list[Poi]) -> float:
    """
    Returns max redundancy between candidate and any already-selected POI.
    Composite kernel: cosine similarity on feature vectors
    + extra penalty if same travel_category.
    Returns 0.0 if selected is empty.
    """
    if not selected:
        return 0.0
    candidate_vec = _poi_vec(candidate)
    max_red = 0.0
    for sel in selected:
        vec_sim = _cosine_sim(candidate_vec, _poi_vec(sel))
        category_penalty = (
            SAME_CATEGORY_PENALTY
            if candidate.travel_category == sel.travel_category
            and candidate.travel_category is not None
            else 0.0
        )
        redundancy = min(vec_sim + category_penalty, 1.0)
        max_red = max(max_red, redundancy)
    return max_red


def _mmr_select(
    candidates: list[Poi],
    uvec: np.ndarray,
    center_lat: float,
    center_lng: float,
    k: int,
    lambda_: float = MMR_LAMBDA,
    confirmed_visited_ids: set | None = None,
    previously_suggested_ids: set | None = None,
    popularity_scores: dict | None = None,
    proximity_km: float = 5.0,
) -> list[tuple[Poi, float]]:
    """
    Selects up to k POIs from candidates using Maximal Marginal Relevance,
    with optional novelty penalties for confirmed-visited and recently-suggested POIs.
    Returns list of (poi, cosine_similarity_score) — the raw cosine sim
    (not MMR score) for use in resolve_visit_mode() and deferred logic.

    Step 1: first POI = highest penalized combined_score (no diversity penalty yet).
    Step 2+: argmax of λ·relevance − (1−λ)·max_redundancy over remaining.
    """
    if not candidates:
        return []

    confirmed_visited_ids = confirmed_visited_ids or set()
    previously_suggested_ids = previously_suggested_ids or set()

    # Precompute penalized combined score and raw cosine similarity for every candidate
    precomputed: dict = {
        poi.id: (
            apply_novelty_penalty(
                _combined_score(poi, uvec, center_lat, center_lng, popularity_scores, proximity_km),
                poi.id,
                confirmed_visited_ids,
                previously_suggested_ids,
                is_landmark=is_landmark_poi(poi),
            ),
            _cosine_sim(_poi_vec(poi), uvec),
        )
        for poi in candidates
    }

    remaining = list(candidates)
    selected: list[Poi] = []
    result: list[tuple[Poi, float]] = []

    while remaining and len(selected) < k:
        if not selected:
            best = max(remaining, key=lambda p: precomputed[p.id][0])
        else:
            def _mmr_score(poi: Poi) -> float:
                relevance = precomputed[poi.id][0]
                redundancy = _poi_redundancy(poi, selected)
                # Hard proximity penalty: POIs within MMR_MIN_DISTANCE_M of any
                # already-selected POI are treated as duplicates (same location).
                for sel in selected:
                    if haversine_m(poi.lat, poi.lng, sel.lat, sel.lng) < MMR_MIN_DISTANCE_M:
                        return -1.0
                return lambda_ * relevance - (1.0 - lambda_) * redundancy

            best = max(remaining, key=_mmr_score)

        _, sim = precomputed[best.id]
        selected.append(best)
        result.append((best, sim))
        remaining.remove(best)

    return result


# ---------------------------------------------------------------------------
# Day scheduler
# ---------------------------------------------------------------------------

def _schedule_day(
    activity_candidates: list[tuple[Poi, float]],  # (poi, cosine_similarity_score)
    food_pois: list[Poi],
    day_date: datetime,
    start_dt: datetime,
    end_dt: datetime,
    depot_lat: float,
    depot_lng: float,
    popularity_scores: dict | None = None,
    travel_lookup: TravelLookup | None = None,
    max_food_price_level: int | None = None,
    walk_threshold_m: float = DEFAULT_WALK_THRESHOLD_M,
) -> tuple[list[_Stop], list[tuple[Poi, float]]]:
    """
    Build the schedule for one day.
    1. Greedily selects activities and inserts lunch/dinner at target hours.
    2. Runs TSP on the selected activity stops (food anchors stay fixed).
    3. Re-propagates times after TSP reordering.

    Returns (stops, deferred_candidates) where deferred_candidates are (Poi, score)
    pairs skipped because the POI was closed at the planned arrival time.
    """
    used_food: set = set()
    used_activity: set = set()

    lunch_done = False
    dinner_done = False

    current = start_dt
    current_lat, current_lng = depot_lat, depot_lng
    current_id = None  # POI id of current position (None at the depot)

    selected_activities: list[tuple[Poi, float]] = []
    deferred_activities: list[tuple[Poi, float]] = []
    lunch_poi: Poi | None = None
    lunch_approx: datetime | None = None
    dinner_poi: Poi | None = None
    dinner_approx: datetime | None = None

    remaining_food = list(food_pois)

    _pop = popularity_scores or {}

    def _pick_nearest_open_food(
        t: datetime,
        meal_only: bool = False,
        pos_lat: float | None = None,
        pos_lng: float | None = None,
    ) -> Poi | None:
        """Find the nearest open food POI at time t.
        pos_lat/pos_lng override the Pass-1 current position (used in Pass 3 post-loop).
        """
        _lat = pos_lat if pos_lat is not None else current_lat
        _lng = pos_lng if pos_lng is not None else current_lng
        eligible: list[tuple[Poi, float]] = []
        for fp in remaining_food:
            if fp.id in used_food:
                continue
            if not _is_open(fp, t):
                continue
            if meal_only and not is_meal_poi(fp):
                continue
            if not is_food_price_acceptable(fp, max_food_price_level):
                continue
            eligible.append((fp, haversine_m(_lat, _lng, fp.lat, fp.lng)))
        return pick_best_food(eligible, _pop)

    for ap, sim_score in activity_candidates:
        if ap.id in used_activity:
            continue

        # Check lunch window
        if not lunch_done:
            target = day_date.replace(hour=LUNCH_TARGET_H, minute=0, second=0, microsecond=0)
            if current >= target - timedelta(minutes=MEAL_WINDOW_MIN):
                fp = _pick_nearest_open_food(current, meal_only=True)
                if fp is None:
                    logger.warning("No restaurant found for lunch, falling back to any food POI")
                    fp = _pick_nearest_open_food(current, meal_only=False)
                if fp:
                    used_food.add(fp.id)
                    lunch_poi = fp
                    lunch_approx = current
                    dur = get_food_duration(fp)
                    current = current + timedelta(minutes=dur)
                    current_lat, current_lng = fp.lat, fp.lng
                    current_id = fp.id
                    lunch_done = True
                    logger.info(
                        "Lunch selected: %s (type: %s, meal_poi: %s)",
                        fp.name, (fp.types or ["?"])[0], is_meal_poi(fp),
                    )
                else:
                    logger.warning("No food POI found for lunch around %s", current)
                    lunch_done = True  # prevent infinite retry

        # Check dinner window
        if not dinner_done:
            target = day_date.replace(hour=DINNER_TARGET_H, minute=0, second=0, microsecond=0)
            if current >= target - timedelta(minutes=MEAL_WINDOW_MIN):
                fp = _pick_nearest_open_food(current, meal_only=True)
                if fp is None:
                    logger.warning("No restaurant found for dinner, falling back to any food POI")
                    fp = _pick_nearest_open_food(current, meal_only=False)
                if fp:
                    used_food.add(fp.id)
                    dinner_poi = fp
                    dinner_approx = current
                    dur = get_food_duration(fp)
                    current = current + timedelta(minutes=dur)
                    current_lat, current_lng = fp.lat, fp.lng
                    current_id = fp.id
                    dinner_done = True
                    logger.info(
                        "Dinner selected: %s (type: %s, meal_poi: %s)",
                        fp.name, (fp.types or ["?"])[0], is_meal_poi(fp),
                    )
                else:
                    logger.warning("No food POI found for dinner around %s", current)
                    dinner_done = True  # prevent infinite retry

        # Travel to this activity
        try:
            _, travel_min = _travel(
                current_id, current_lat, current_lng, ap.id, ap.lat, ap.lng,
                travel_lookup, walk_threshold_m,
            )
            arrival = current + timedelta(minutes=travel_min)

            if not _is_open(ap, arrival):
                # Before deferring, check if the POI opens within the next 90 minutes.
                # This handles morning starts where museums/churches open at 09:00 or 10:00.
                wait_arrival = None
                for extra_min in range(5, 91, 5):
                    candidate_arrival = arrival + timedelta(minutes=extra_min)
                    if candidate_arrival > end_dt:
                        break
                    if _is_open(ap, candidate_arrival):
                        wait_arrival = candidate_arrival
                        break
                if wait_arrival is None:
                    deferred_activities.append((ap, sim_score))
                    continue
                arrival = wait_arrival  # wait until the POI opens

            _, visit_dur, _ = resolve_visit_mode(ap, sim_score)
            departure = arrival + timedelta(minutes=visit_dur)
            if departure > end_dt:
                break

            used_activity.add(ap.id)
            selected_activities.append((ap, sim_score))
            current = departure
            current_lat, current_lng = ap.lat, ap.lng
            current_id = ap.id
        except Exception as exc:
            logger.warning("Skipping POI %s during scheduling: %s", getattr(ap, "name", "?"), exc)

    # Pre-select any meal POI that the activity loop didn't reach (e.g. all activities
    # finished before 12:30 or 19:30).  Pass 3 post-loop will insert them if there is time.
    if not lunch_done:
        lunch_t = day_date.replace(hour=LUNCH_TARGET_H, minute=0, second=0, microsecond=0)
        fp = _pick_nearest_open_food(lunch_t, meal_only=True)
        if fp is None:
            fp = _pick_nearest_open_food(lunch_t, meal_only=False)
        if fp:
            used_food.add(fp.id)
            lunch_poi = fp

    if not dinner_done:
        dinner_t = day_date.replace(hour=DINNER_TARGET_H, minute=0, second=0, microsecond=0)
        fp = _pick_nearest_open_food(dinner_t, meal_only=True)
        if fp is None:
            logger.warning("No meal POI found for dinner pre-selection (meal_only=True) on %s", day_date.date())
            fp = _pick_nearest_open_food(dinner_t, meal_only=False)
        if fp:
            used_food.add(fp.id)
            dinner_poi = fp
            logger.info(
                "Dinner pre-selected (post-loop): %s (type: %s, meal_poi: %s)",
                fp.name, (fp.types or ["?"])[0], is_meal_poi(fp),
            )
        else:
            logger.warning("No food POI found for dinner pre-selection on %s", day_date.date())

    # --- Pass 2: TSP reorder activities ---
    selected_pois = [poi for poi, _ in selected_activities]
    score_by_id = {poi.id: score for poi, score in selected_activities}
    ordered_pois = _solve_tsp(selected_pois, depot_lat, depot_lng)
    ordered_activities = [(poi, score_by_id[poi.id]) for poi in ordered_pois]

    # --- Pass 3: re-propagate times ---
    final_stops: list[_Stop] = []
    type_counts: dict[str, int] = {}  # primary Google type → count of activity stops added

    cur = start_dt
    cur_lat, cur_lng = depot_lat, depot_lng
    cur_id = None  # POI id of current position (None at the depot)

    lunch_inserted = False
    dinner_inserted = False

    def _add_food_stop(food_poi: Poi, forced_arrival: datetime | None = None) -> None:
        nonlocal cur, cur_lat, cur_lng, cur_id
        if not final_stops:
            travel_min = 0.0
            transport = None
        else:
            transport, travel_min = _travel(
                cur_id, cur_lat, cur_lng, food_poi.id, food_poi.lat, food_poi.lng,
                travel_lookup, walk_threshold_m,
            )
        arrival = forced_arrival if forced_arrival is not None else cur + timedelta(minutes=travel_min)
        vm, vd, vn = resolve_visit_mode(food_poi, 1.0)
        departure = arrival + timedelta(minutes=vd)
        final_stops.append(_Stop(
            poi=food_poi,
            arrival=arrival,
            departure=departure,
            transport=transport,
            travel_minutes=travel_min,
            similarity_score=1.0,
            visit_mode=vm,
            visit_duration_minutes=vd,
            visit_note=vn,
        ))
        cur = departure
        cur_lat, cur_lng = food_poi.lat, food_poi.lng
        cur_id = food_poi.id

    def _add_activity_stop(poi: Poi, sim_score: float) -> bool:
        nonlocal cur, cur_lat, cur_lng, cur_id
        if not final_stops:
            travel_min = 0.0
            transport = None
        else:
            transport, travel_min = _travel(
                cur_id, cur_lat, cur_lng, poi.id, poi.lat, poi.lng,
                travel_lookup, walk_threshold_m,
            )
        arrival = cur + timedelta(minutes=travel_min)
        vm, vd, vn = resolve_visit_mode(poi, sim_score)
        departure = arrival + timedelta(minutes=vd)
        if departure > end_dt:
            return False
        # Protect the dinner slot: don't add an activity if dinner can no longer
        # fit before end_dt after it (15 min conservative travel estimate).
        if dinner_poi and not dinner_inserted:
            dinner_end_est = departure + timedelta(minutes=15 + get_food_duration(dinner_poi))
            if dinner_end_est > end_dt:
                return False
        # Per-day type cap: avoid church/type fatigue.
        primary = (poi.types or [""])[0]
        cap = _PRIMARY_TYPE_DAY_CAP.get(primary)
        if cap is not None and type_counts.get(primary, 0) >= cap:
            logger.debug("Skipping %s (type '%s' cap %d reached)", poi.name, primary, cap)
            return False
        final_stops.append(_Stop(
            poi=poi,
            arrival=arrival,
            departure=departure,
            transport=transport,
            travel_minutes=travel_min,
            similarity_score=sim_score,
            visit_mode=vm,
            visit_duration_minutes=vd,
            visit_note=vn,
        ))
        type_counts[primary] = type_counts.get(primary, 0) + 1
        cur = departure
        cur_lat, cur_lng = poi.lat, poi.lng
        cur_id = poi.id
        return True

    lunch_target = day_date.replace(hour=LUNCH_TARGET_H, minute=0, second=0, microsecond=0)
    dinner_target = day_date.replace(hour=DINNER_TARGET_H, minute=0, second=0, microsecond=0)

    for act, sim_score in ordered_activities:
        # Insert lunch before next activity if we've reached the lunch window
        if lunch_poi and not lunch_inserted:
            if cur >= lunch_target - timedelta(minutes=MEAL_WINDOW_MIN):
                _add_food_stop(lunch_poi)
                lunch_inserted = True

        # Insert dinner before next activity if we've reached the dinner window
        if dinner_poi and not dinner_inserted:
            if cur >= dinner_target - timedelta(minutes=MEAL_WINDOW_MIN):
                _add_food_stop(dinner_poi)
                dinner_inserted = True

        if not _add_activity_stop(act, sim_score):
            break  # day is full

    # After loop: insert any meal not yet added (e.g. all activities finished before meal time).
    # Only insert if at least one activity was scheduled — a day with only food stops makes
    # no sense and means all activities were deferred due to opening hours.
    has_activities = any(s.poi.travel_category != "food" and not is_actual_food_poi(s.poi) for s in final_stops)

    if has_activities and lunch_poi and not lunch_inserted:
        _, travel_min = _travel(
            cur_id, cur_lat, cur_lng, lunch_poi.id, lunch_poi.lat, lunch_poi.lng,
            travel_lookup, walk_threshold_m,
        )
        arrival = cur + timedelta(minutes=travel_min)
        if arrival + timedelta(minutes=get_food_duration(lunch_poi)) <= end_dt:
            _add_food_stop(lunch_poi)
            lunch_inserted = True
        else:
            logger.warning("Lunch not inserted for day %s — no time slot available", day_date.date())

    if has_activities and dinner_poi and not dinner_inserted:
        _, travel_min = _travel(
            cur_id, cur_lat, cur_lng, dinner_poi.id, dinner_poi.lat, dinner_poi.lng,
            travel_lookup, walk_threshold_m,
        )
        arrival = cur + timedelta(minutes=travel_min)
        dinner_min_dt = day_date.replace(hour=DINNER_MIN_H, minute=0, second=0, microsecond=0)
        if arrival < dinner_min_dt:
            # Safety net: force dinner at DINNER_MIN_H if it fits before end_dt
            forced = dinner_min_dt
            if forced + timedelta(minutes=get_food_duration(dinner_poi)) <= end_dt:
                _add_food_stop(dinner_poi, forced_arrival=forced)
                dinner_inserted = True
                logger.info(
                    "Dinner force-inserted at %s for day %s",
                    forced.strftime("%H:%M"), day_date.date(),
                )
            else:
                logger.warning("Dinner not inserted for day %s — no time slot available", day_date.date())
        elif arrival + timedelta(minutes=get_food_duration(dinner_poi)) <= end_dt:
            _add_food_stop(dinner_poi)
            dinner_inserted = True
        else:
            logger.warning("Dinner not inserted for day %s — no time slot available", day_date.date())

    # Collect food that was pre-selected but never inserted (reserved to avoid reuse next day)
    reserved_food_ids: set = set()
    if lunch_poi and not lunch_inserted:
        reserved_food_ids.add(lunch_poi.id)
    if dinner_poi and not dinner_inserted:
        reserved_food_ids.add(dinner_poi.id)

    return final_stops, deferred_activities, reserved_food_ids


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_user_poi_history(
    session: object,  # AsyncSession — imported lazily to avoid circular imports
    user_id: object,  # uuid.UUID
    city_id: object,  # uuid.UUID
) -> tuple[set, set]:
    """
    Returns (confirmed_visited_ids, previously_suggested_ids) for a user + city.

    confirmed_visited_ids:
      Items where visited_at IS NOT NULL (any time, no window)
    previously_suggested_ids:
      Items where visited_at IS NULL, itinerary created within last 12 months
      (implicit signal: suggested but user didn't confirm)
      Confirmed ids are removed from this set.
    """
    from datetime import timedelta

    from sqlalchemy import select as _select

    from app.models.city import City as _City
    from app.models.itinerary import Itinerary as _Itinerary
    from app.models.itinerary import ItineraryItem as _ItineraryItem

    cutoff = datetime.utcnow() - timedelta(days=IMPLICIT_WINDOW_DAYS)

    result = await session.execute(
        _select(
            _ItineraryItem.place_id,
            _ItineraryItem.visited_at,
            _Itinerary.created_at.label("itinerary_created_at"),
        )
        .join(_Itinerary, _ItineraryItem.itinerary_id == _Itinerary.id)
        .join(_City, _City.name == _Itinerary.city)
        .where(
            _Itinerary.user_id == user_id,
            _City.id == city_id,
        )
    )
    rows = result.all()

    confirmed = {row.place_id for row in rows if row.visited_at is not None}
    suggested = {
        row.place_id
        for row in rows
        if row.visited_at is None and row.itinerary_created_at >= cutoff
    }
    suggested -= confirmed

    return confirmed, suggested


async def generate(
    user_prefs: UserPreference,
    num_days: int,
    start_time_str: str,
    end_time_str: str,
    candidate_places: list[Poi],
    city_lat: float,
    city_lng: float,
    confirmed_visited_ids: set | None = None,
    previously_suggested_ids: set | None = None,
    travel_with_children: bool = False,
    age_range: str | None = None,
    travel_mode: str = "solo",
    session=None,  # AsyncSession — when provided + routes_api_enabled, real travel times are used
    solver: str | None = None,
    start_lat: float | None = None,
    start_lng: float | None = None,
    end_lat: float | None = None,
    end_lng: float | None = None,
) -> tuple[list[list[_Stop]], list[str]]:
    """
    Plan a multi-day itinerary.

    Two solvers are available (see docs/toptw-itinerary-solver-spec.md), selected by
    ``solver`` (falling back to ``settings.itinerary_solver``):
    - "greedy" (baseline): two-level geographic clustering + MMR + greedy scheduling.
    - "toptw": a single OR-Tools optimisation over all days (Team Orienteering Problem
      with Time Windows). Both receive the same filtered candidates and real travel
      times for a fair comparison.

    Returns (all_days, warnings):
    - all_days: list of days, each day is a list of _Stop objects
    - warnings: human-readable strings for days that are short or skipped
    """
    import time as _time_mod
    t0 = _time_mod.monotonic()

    warnings: list[str] = []
    confirmed_visited_ids = confirmed_visited_ids or set()
    previously_suggested_ids = previously_suggested_ids or set()
    max_food_price_level = food_price_level_limit(getattr(user_prefs, "food", None))
    uvec = _user_vec(user_prefs)
    uvec = _apply_mode_bias(uvec, travel_mode)
    proximity_km = _proximity_km_for_profile(travel_with_children, age_range)
    # Personalized walking cut-off (age + relax) shared by both solvers: it must
    # be identical in prefetch and scheduling so the prefetched travel mode is the
    # one looked up later (a mismatch silently falls back to haversine).
    walk_threshold_m = compute_walk_threshold_m(age_range, getattr(user_prefs, "relax", None))
    logger.info(
        "Walk threshold: %.0f m (age_range=%s relax=%.2f personalization=%s)",
        walk_threshold_m, age_range, float(getattr(user_prefs, "relax", 0.0) or 0.0),
        settings.walk_personalization,
    )

    # POIs classified as "food" always go to the food pool, even if Google types
    # don't include explicit food types (e.g. primary type "point_of_interest").
    food_pois = [p for p in candidate_places if p.travel_category == "food" or is_actual_food_poi(p)]
    activity_pois = [p for p in candidate_places if p.travel_category != "food" and not is_actual_food_poi(p)]

    # Python-level safety filter (catches edge cases SQL filter may miss)
    activity_pois = [p for p in activity_pois if is_touristic(p)]
    food_pois = [p for p in food_pois if is_touristic(p)]

    # Exclude activity POIs too far from the city centre. In fixed mode this is
    # the A/B radius; in adaptive mode the same 8 km default becomes the minimum
    # for compact cities, expanding for sparse/extended POI distributions. Food
    # POIs are not filtered — selection is proximity-weighted, so far venues do
    # not win against closer ones.
    max_radius_m = resolve_activity_radius_m(activity_pois, city_lat, city_lng, num_days)
    before_radius_count = len(activity_pois)
    activity_pois = [
        p for p in activity_pois
        if haversine_m(p.lat, p.lng, city_lat, city_lng) <= max_radius_m
    ]
    logger.info(
        "Activity radius filter: mode=%s radius=%.1f km kept=%d/%d",
        settings.activity_radius_mode,
        max_radius_m / 1000,
        len(activity_pois),
        before_radius_count,
    )

    # For family travel: exclude nightlife POIs (bars, clubs, casinos) from activities
    if travel_mode == "family":
        activity_pois = [p for p in activity_pois if p.travel_category != "nightlife"]

    logger.info(
        "POIs after touristic filter: %d activities, %d food",
        len(activity_pois), len(food_pois),
    )

    if len(activity_pois) < num_days * 2:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=422,
            detail=(
                f"Not enough touristic POIs available for {num_days} days "
                f"in this city. Try running the pipeline again."
            ),
        )

    from collections import Counter as _Counter
    type_dist = _Counter((poi.types or ["unknown"])[0] for poi in activity_pois)
    cat_dist = _Counter(poi.travel_category for poi in activity_pois)
    logger.info("Activity POI primary types: %s", dict(type_dist.most_common(10)))
    logger.info("Activity POI categories: %s", dict(cat_dist))
    logger.info("Food POIs available: %d", len(food_pois))

    # Compute Bayesian popularity scores once for all candidates
    popularity_scores = compute_popularity_scores(candidate_places)

    # Log top-5 POIs by popularity score
    top5_pop = sorted(candidate_places, key=lambda p: popularity_scores.get(p.id, 0.5), reverse=True)[:5]
    logger.info(
        "Top-5 by popularity: %s",
        [(p.name, round(popularity_scores.get(p.id, 0.5), 3)) for p in top5_pop],
    )

    # Sort food by cosine similarity (global pool, shared across days)
    food_pois.sort(key=lambda p: _cosine_sim(uvec, _poi_vec(p)), reverse=True)

    # --- Dispatch: TOPTW optimiser vs greedy baseline ---
    chosen_solver = (solver or settings.itinerary_solver or "greedy").lower()
    if chosen_solver == "toptw":
        from app.services import toptw_solver

        logger.info("Dispatching to TOPTW solver (num_days=%d)", num_days)
        toptw_days, toptw_warnings = await toptw_solver.plan(
            activity_pois=activity_pois,
            food_pois=food_pois,
            uvec=uvec,
            popularity_scores=popularity_scores,
            num_days=num_days,
            start_time_str=start_time_str,
            end_time_str=end_time_str,
            city_lat=city_lat,
            city_lng=city_lng,
            confirmed_visited_ids=confirmed_visited_ids,
            previously_suggested_ids=previously_suggested_ids,
            max_food_price_level=max_food_price_level,
            walk_threshold_m=walk_threshold_m,
            start_lat=start_lat,
            start_lng=start_lng,
            end_lat=end_lat,
            end_lng=end_lng,
            session=session,
        )
        warnings.extend(toptw_warnings)
        elapsed_ms = int((_time_mod.monotonic() - t0) * 1000)
        logger.info(
            "TOPTW itinerary generated: num_days=%d total_scheduled=%d elapsed_ms=%d",
            num_days, sum(len(d) for d in toptw_days), elapsed_ms,
        )
        return toptw_days, warnings

    sh, sm = map(int, start_time_str.split(":"))
    eh, em = map(int, end_time_str.split(":"))

    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=4)
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)

    # --- Level 1: geographic clustering ---
    clusters = _cluster_pois(activity_pois, num_days, city_lat, city_lng)
    clusters = _rebalance_clusters(clusters)
    actual_days = len(clusters)

    logger.info("Clustering: %d activity POIs → %d clusters", len(activity_pois), actual_days)

    if actual_days < num_days:
        warnings.append(
            f"Only {actual_days} day(s) of activities available for this city. "
            f"Some days may be shorter than expected."
        )

    # Novelty warning: if most activity POIs are already penalized, surface it
    penalized_count = sum(
        1 for p in activity_pois
        if p.id in previously_suggested_ids or p.id in confirmed_visited_ids
    )
    if activity_pois and penalized_count > len(activity_pois) * 0.6:
        warnings.append(
            "You've visited many POIs in this city. "
            "Your itinerary includes some new hidden gems!"
        )

    logger.info(
        "Novelty: %d confirmed visited, %d suggested in last 12mo",
        len(confirmed_visited_ids), len(previously_suggested_ids),
    )

    all_days: list[list[_Stop]] = []
    used_food_ids: set = set()
    global_deferred: list[tuple[Poi, float]] = []  # (poi, cosine_sim_score)
    had_closed_pois = False

    for day_idx, cluster_id in enumerate(sorted(clusters.keys())):
        day_date = today + timedelta(days=day_idx)
        start_dt = day_date.replace(hour=sh, minute=sm, second=0)
        end_dt = day_date.replace(hour=eh, minute=em, second=0)

        # Score cluster POIs by cosine similarity
        cluster_scored: list[tuple[Poi, float]] = [
            (p, _cosine_sim(_poi_vec(p), uvec)) for p in clusters[cluster_id]
        ]

        # Cluster center computed from this day's own POIs (before adding deferred)
        cluster_pois_only = [p for p, _ in cluster_scored]
        center_lat, center_lng = (
            _cluster_center(cluster_pois_only) if len(cluster_pois_only) > 1
            else (city_lat, city_lng)
        )

        # Prepend deferred from previous day, filtered by distance to this cluster
        _MAX_DEFERRED_M = 4000
        filtered_deferred = [
            (p, score) for p, score in global_deferred
            if haversine_m(p.lat, p.lng, center_lat, center_lng) <= _MAX_DEFERRED_M
        ]
        all_candidates: list[tuple[Poi, float]] = filtered_deferred + cluster_scored
        global_deferred = []

        if not all_candidates:
            warnings.append(f"Day {day_idx + 1} has no available POIs and was skipped.")
            continue

        logger.info(
            "  Cluster %d: %d POIs, center=(%.4f, %.4f)",
            cluster_id, len(all_candidates), center_lat, center_lng,
        )

        # --- Level 2: MMR selection (diversity + relevance) ---
        # Dynamic buffer: 3× the estimated stops needed to fill the day,
        # so opening-hour closures don't leave the day empty.
        day_minutes = (eh * 60 + em) - (sh * 60 + sm)
        estimated_stops = max(1, day_minutes // 75)
        mmr_k = min(len(all_candidates), max(25, estimated_stops * 3))

        candidate_pois_only = [p for p, _ in all_candidates]
        candidates = _mmr_select(
            candidates=candidate_pois_only,
            uvec=uvec,
            center_lat=center_lat,
            center_lng=center_lng,
            k=mmr_k,
            confirmed_visited_ids=confirmed_visited_ids,
            previously_suggested_ids=previously_suggested_ids,
            popularity_scores=popularity_scores,
            proximity_km=proximity_km,
        )

        from collections import Counter
        cats = Counter(poi.travel_category for poi, _ in candidates)
        logger.info(
            "  Cluster %d: MMR selected %d POIs from %d candidates — categories: %s",
            cluster_id, len(candidates), len(all_candidates), dict(cats),
        )

        available_food = [p for p in food_pois if p.id not in used_food_ids]

        # --- Pre-fetch real travel times for this day's activities ---
        # One batched matrix call (cache-first) before entering the sync scheduler,
        # so _schedule_day stays synchronous and does no I/O. Falls back to
        # haversine transparently when routing is disabled or a leg has no route.
        travel_lookup: TravelLookup = {}
        if session is not None and settings.routes_api_enabled:
            try:
                travel_lookup = await prefetch_travel_matrix(
                    session, [p for p, _ in candidates], walk_threshold_m
                )
            except Exception as exc:  # routing must never block generation
                logger.warning("Travel-matrix prefetch failed (%s) — using haversine", exc)

        # --- Schedule day ---
        stops, deferred, reserved = await loop.run_in_executor(
            executor,
            _schedule_day,
            candidates,
            available_food,
            day_date,
            start_dt,
            end_dt,
            center_lat,
            center_lng,
            popularity_scores,
            travel_lookup,
            max_food_price_level,
            walk_threshold_m,
        )

        if deferred:
            had_closed_pois = True
            global_deferred.extend(deferred)

        # Mark food as used: both inserted stops and pre-selected-but-uninserted
        used_food_ids.update(reserved)
        for s in stops:
            if any(t in FOOD_TYPES for t in (s.poi.types or [])):
                used_food_ids.add(s.poi.id)

        if not stops:
            warnings.append(f"Day {day_idx + 1} has no available POIs and was skipped.")
            continue

        # Warn if the day ends more than 2 hours before end_time
        last_departure = stops[-1].departure
        if (end_dt - last_departure).total_seconds() > 7200:
            warnings.append(
                f"Day {day_idx + 1}: few POIs available, "
                f"itinerary ends at {last_departure.strftime('%H:%M')}."
            )

        all_days.append(stops)

    if had_closed_pois:
        warnings.append("Some POIs could not be scheduled due to opening hours.")

    elapsed_ms = int((_time_mod.monotonic() - t0) * 1000)
    total_scheduled = sum(len(d) for d in all_days)
    logger.info(
        "Itinerary generated: city_lat=%.4f city_lng=%.4f num_days=%d "
        "total_pois_input=%d total_scheduled=%d elapsed_ms=%d",
        city_lat, city_lng, num_days,
        len(candidate_places), total_scheduled, elapsed_ms,
    )
    logger.info("Warnings generated: %s", warnings)

    return all_days, warnings
