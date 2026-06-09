"""
Evaluation metrics for the POI recommendation system.
All functions are async and query the DB directly.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from math import log2

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models.classification_log import PoiClassificationLog
from app.models.itinerary import Itinerary, ItineraryItem
from app.models.poi import Poi
from app.models.preference import UserPreference
from app.models.tourism_validation_log import PoiTourismValidationLog


def _make_session() -> AsyncSession:
    """
    Create a one-shot async session with NullPool.
    NullPool disables connection reuse, so each asyncio.run() gets a fresh
    connection that is fully closed when the context manager exits.
    This avoids event-loop conflicts when called from Streamlit.
    """
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory()

PREFERENCE_KEYS = [
    "nature", "culture", "food", "adventure",
    "nightlife", "relax", "family_friendly",
]

FOOD_CATEGORIES = {"food"}


# ── vector helpers ─────────────────────────────────────────────────

def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Cosine similarity between two vectors. Returns 0.0 on error."""
    try:
        a, b = np.array(v1, dtype=float), np.array(v2, dtype=float)
        norm = np.linalg.norm(a) * np.linalg.norm(b)
        if norm == 0:
            return 0.0
        return float(np.dot(a, b) / norm)
    except Exception:
        return 0.0


def shannon_entropy(categories: list[str]) -> float:
    """
    Shannon entropy of category distribution.
    Higher = more diverse itinerary.
    """
    if not categories:
        return 0.0
    counts = Counter(categories)
    total = len(categories)
    return -sum(
        (c / total) * log2(c / total)
        for c in counts.values()
        if c > 0
    )


def haversine_km(lat1: float, lng1: float,
                 lat2: float, lng2: float) -> float:
    """Great-circle distance in km between two coordinates."""
    R = 6371
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lng2 - lng1)
    a = (np.sin(dphi / 2) ** 2
         + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2) ** 2)
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def _poi_vector(poi: Poi) -> list[float]:
    """Return Poi feature vector from explicit columns."""
    return [getattr(poi, k, None) or 0.0 for k in PREFERENCE_KEYS]


# ── per-itinerary metrics ──────────────────────────────────────────

async def get_itinerary_metrics(
    itinerary_id: str,
    session: AsyncSession,
) -> dict:
    """
    Compute all metrics for a single itinerary.

    Returns:
    - itinerary_id, city, num_days, total_stops, activity_stops
    - mean_preference_score: cosine similarity between user prefs and each
      activity POI vector, averaged across all activity stops
    - per_stop_scores: list[dict] with name, day, position, category,
      preference_score, feature_vector, rating
    - category_distribution: dict {category: count}
    - shannon_entropy: float
    - total_distance_km: float
    - mean_distance_per_day_km: float
    - user_preferences: dict
    """
    from uuid import UUID
    try:
        itin_uuid = UUID(itinerary_id)
    except ValueError:
        return {"error": f"Invalid UUID: {itinerary_id}"}

    itin = await session.get(Itinerary, itin_uuid)
    if not itin:
        return {"error": f"Itinerary {itinerary_id} not found"}

    items_result = await session.execute(
        select(ItineraryItem)
        .where(ItineraryItem.itinerary_id == itin_uuid)
        .order_by(ItineraryItem.day_number, ItineraryItem.position)
    )
    items = items_result.scalars().all()
    if not items:
        return {"error": "No items found"}

    poi_ids = [item.place_id for item in items]
    pois_result = await session.execute(
        select(Poi).where(Poi.id.in_(poi_ids))
    )
    poi_map = {poi.id: poi for poi in pois_result.scalars().all()}

    prefs_result = await session.execute(
        select(UserPreference).where(UserPreference.user_id == itin.user_id)
    )
    prefs = prefs_result.scalar_one_or_none()

    user_pref_vector: list[float] = []
    user_prefs_dict: dict = {}
    if prefs:
        user_pref_vector = [getattr(prefs, k) or 0.0 for k in PREFERENCE_KEYS]
        user_prefs_dict = {k: getattr(prefs, k) or 0.0 for k in PREFERENCE_KEYS}

    per_stop_scores: list[dict] = []
    activity_scores: list[float] = []
    categories: list[str] = []
    total_distance = 0.0
    prev_lat: float | None = None
    prev_lng: float | None = None

    for item in items:
        poi = poi_map.get(item.place_id)
        if not poi:
            continue

        cat = poi.travel_category or "unknown"
        categories.append(cat)

        if prev_lat is not None:
            total_distance += haversine_km(prev_lat, prev_lng, poi.lat, poi.lng)
        prev_lat, prev_lng = poi.lat, poi.lng

        score: float | None = None
        if cat not in FOOD_CATEGORIES and user_pref_vector:
            fv = _poi_vector(poi)
            if any(v > 0 for v in fv):
                score = cosine_similarity(user_pref_vector, fv)
                activity_scores.append(score)

        per_stop_scores.append({
            "name":             poi.name,
            "day":              item.day_number,
            "position":         item.position,
            "category":         cat,
            "preference_score": round(score, 4) if score is not None else None,
            "feature_vector":   _poi_vector(poi),
            "rating":           poi.rating,
        })

    num_days = (itin.end_date - itin.start_date).days + 1

    return {
        "itinerary_id":            itinerary_id,
        "city":                    itin.city,
        "num_days":                num_days,
        "total_stops":             len(items),
        "activity_stops":          len(activity_scores),
        "mean_preference_score":   (
            round(float(np.mean(activity_scores)), 4)
            if activity_scores else None
        ),
        "per_stop_scores":         per_stop_scores,
        "category_distribution":   dict(Counter(categories)),
        "shannon_entropy":         round(shannon_entropy(categories), 4),
        "total_distance_km":       round(total_distance, 2),
        "mean_distance_per_day_km": (
            round(total_distance / num_days, 2) if num_days else None
        ),
        "user_preferences":        user_prefs_dict,
    }


async def get_all_itineraries_metrics(
    city: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Compute metrics for all itineraries. Optionally filter by city."""
    async with _make_session() as session:
        query = select(Itinerary.id)
        if city:
            query = query.where(Itinerary.city == city)
        query = query.order_by(Itinerary.created_at.desc()).limit(limit)

        result = await session.execute(query)
        ids = [str(row[0]) for row in result.fetchall()]

        metrics = []
        for itin_id in ids:
            m = await get_itinerary_metrics(itin_id, session)
            if "error" not in m:
                metrics.append(m)
        return metrics


async def get_classification_metrics(city: str | None = None) -> dict:
    """
    Inter-rater agreement and vector consistency metrics from poi_classification_logs.

    Returns:
    - total_classified, category_agreement_rate, mean_cosine_distance, std_cosine_distance
    - confidence_distribution: dict {high/medium/failed: count}
    - top_disagreements: dict {category_pair: count} (top 5)
    - failed_rate, arbitration_rate
    - vector_consistency: dict {category: {count, mean_cosine_distance, most_variable_dimension}}
    """
    from collections import Counter as _Counter
    async with _make_session() as session:
        query = select(PoiClassificationLog)
        if city:
            query = query.where(PoiClassificationLog.city_name == city)
        result = await session.execute(query)
        logs = result.scalars().all()

    if not logs:
        return {"error": "No classification logs found"}

    total = len(logs)
    agreements = sum(1 for l in logs if l.category_agreement is True)
    failed = sum(1 for l in logs if l.final_confidence == "failed")
    medium = sum(1 for l in logs if l.final_confidence == "medium")

    distances = [l.vector_cosine_distance for l in logs if l.vector_cosine_distance is not None]

    disagreement_cats: dict[str, int] = {}
    for l in logs:
        if l.category_agreement is False:
            pair = " vs ".join(sorted([l.llm1_category or "unknown", l.llm2_category or "unknown"]))
            disagreement_cats[pair] = disagreement_cats.get(pair, 0) + 1
    top_disagreements = dict(sorted(disagreement_cats.items(), key=lambda x: -x[1])[:5])

    confidence_dist = dict(_Counter(l.final_confidence for l in logs if l.final_confidence))

    # Per-category vector consistency (only where categories agreed)
    DIMS = PREFERENCE_KEYS
    by_cat: dict[str, list] = {}
    for l in logs:
        if l.category_agreement and l.llm1_vector and l.llm2_vector:
            if len(l.llm1_vector) == 7 and len(l.llm2_vector) == 7:
                cat = l.llm1_category or "unknown"
                if cat not in by_cat:
                    by_cat[cat] = []
                by_cat[cat].append({
                    "dim_diffs": [abs(a - b) for a, b in zip(l.llm1_vector, l.llm2_vector)],
                    "cosine_dist": l.vector_cosine_distance,
                })

    vector_consistency: dict[str, dict] = {}
    for cat, entries in by_cat.items():
        dim_diffs = np.array([e["dim_diffs"] for e in entries])
        valid_dists = [e["cosine_dist"] for e in entries if e["cosine_dist"] is not None]
        vector_consistency[cat] = {
            "count": len(entries),
            "mean_cosine_distance": round(float(np.mean(valid_dists)), 4) if valid_dists else 0.0,
            "most_variable_dimension": DIMS[int(np.mean(dim_diffs, axis=0).argmax())],
        }

    return {
        "total_classified":        total,
        "category_agreement_rate": round(agreements / total, 4),
        "mean_cosine_distance":    round(float(np.mean(distances)), 4) if distances else None,
        "std_cosine_distance":     round(float(np.std(distances)), 4) if distances else None,
        "failed_rate":             round(failed / total, 4),
        "arbitration_rate":        round((medium + failed) / total, 4),
        "confidence_distribution": confidence_dist,
        "top_disagreements":       top_disagreements,
        "vector_consistency":      vector_consistency,
    }


async def get_tourism_metrics(city: str | None = None) -> dict:
    """
    Tourism validation statistics from poi_tourism_validation_logs.

    Returns:
    - total_validated, touristic_rate, llm2_needed_rate, disagreement_rate
    - visit_type_distribution: dict {indoor/outdoor/both: count}
    - duration_stats: dict {indoor_mean_minutes, outdoor_mean_minutes}
    """
    async with _make_session() as session:
        query = select(PoiTourismValidationLog)
        if city:
            query = query.where(PoiTourismValidationLog.city_name == city)
        result = await session.execute(query)
        logs = result.scalars().all()

    if not logs:
        return {"error": "No tourism validation logs found"}

    total = len(logs)
    touristic = [l for l in logs if l.final_is_touristic is True]
    llm2_needed = [l for l in logs if l.llm2_was_needed]
    disagreements = [l for l in logs if l.decision_source == "disagreement"]

    indoor_dur = [l.final_duration_minutes for l in touristic
                  if l.final_visit_type == "indoor" and l.final_duration_minutes]
    outdoor_dur = [l.final_duration_minutes for l in touristic
                   if l.final_visit_type == "outdoor" and l.final_duration_minutes]

    return {
        "total_validated":         total,
        "touristic_rate":          round(len(touristic) / total, 4),
        "non_touristic_count":     total - len(touristic),
        "llm2_needed_rate":        round(len(llm2_needed) / total, 4),
        "disagreement_rate":       round(len(disagreements) / len(llm2_needed), 4) if llm2_needed else 0.0,
        "visit_type_distribution": {
            vt: sum(1 for l in touristic if l.final_visit_type == vt)
            for vt in ["indoor", "outdoor", "both"]
        },
        "duration_stats": {
            "indoor_mean_minutes":  int(np.mean(indoor_dur)) if indoor_dur else None,
            "outdoor_mean_minutes": int(np.mean(outdoor_dur)) if outdoor_dur else None,
        },
    }


async def get_summary_stats(city: str | None = None) -> dict:
    """Aggregate statistics across all itineraries."""
    all_metrics = await get_all_itineraries_metrics(city=city)

    if not all_metrics:
        return {"error": "No itineraries found"}

    scores = [
        m["mean_preference_score"]
        for m in all_metrics
        if m["mean_preference_score"] is not None
    ]
    entropies = [m["shannon_entropy"] for m in all_metrics]
    distances = [
        m["mean_distance_per_day_km"]
        for m in all_metrics
        if m["mean_distance_per_day_km"] is not None
    ]
    all_categories: list[str] = []
    for m in all_metrics:
        all_categories.extend(m["category_distribution"].keys())

    return {
        "total_itineraries":       len(all_metrics),
        "city":                    city or "all",
        "mean_preference_score":   round(float(np.mean(scores)), 4) if scores else None,
        "std_preference_score":    round(float(np.std(scores)), 4) if scores else None,
        "mean_shannon_entropy":    round(float(np.mean(entropies)), 4),
        "mean_distance_per_day_km": round(float(np.mean(distances)), 2) if distances else None,
        "category_distribution":   dict(Counter(all_categories)),
        "per_itinerary":           all_metrics,
    }
