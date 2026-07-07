"""Read-only replay of the POI ingestion pipeline for the demo visualiser.

Every stage of ``pipeline/pipeline.py`` persists its outcome on the ``pois``
table (fetch → ``created_at``; tourism validation → ``is_touristic`` /
``tourism_visit_type`` / ``tourism_duration_minutes`` / ``suitable_for_children``;
LLM classification → ``travel_category``/feature columns/``confidence``;
hours fetch → ``opening_hours``), so the funnel shown by the demo is
reconstructed entirely from the database. No Google Places or LLM calls.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.constants import FEATURE_NAMES

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.poi import Poi

INGESTION_VERSION = 4

# The map only needs a representative sample of the discarded POIs; counts in
# the funnel always cover the full truth.
DISCARDED_SAMPLE_MAX = 150


# Uninformative Google types, skipped when falling back to the `types` array.
_GENERIC_TYPES = {"point_of_interest", "establishment"}


def _display_type(p: "Poi") -> str | None:
    # Cities fetched before the Places API (New) migration have no primary_type;
    # the first specific entry of the legacy `types` array is the next best signal.
    if p.primary_type:
        return p.primary_type
    return next((t for t in p.types or [] if t not in _GENERIC_TYPES), None)


def _poi_out(p: "Poi") -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "lat": p.lat,
        "lng": p.lng,
        "category": p.travel_category,
        "confidence": p.confidence,
        "hasHours": p.opening_hours is not None,
        "visitType": p.tourism_visit_type,
        "suitableForChildren": p.suitable_for_children,
        "primaryType": _display_type(p),
        "vector": {k: round(float(getattr(p, k) or 0.0), 3) for k in FEATURE_NAMES},
        "rating": p.rating,
        "ratingsTotal": p.user_ratings_total,
    }


def _has_overlap(types: list[str] | None, values: set[str] | frozenset[str]) -> bool:
    return bool(set(types or []) & set(values))


def _candidate_query_drop_reason(p: "Poi") -> str:
    from app.services.itinerary_planner import (
        EXCLUDED_TYPES,
        HIGH_POPULARITY_TYPES,
    )

    if p.business_status is None or p.business_status == "CLOSED_PERMANENTLY":
        return "business_status_missing_or_closed"
    if p.user_ratings_total is not None and p.user_ratings_total < 200:
        return "under_200_reviews"
    if p.rating is None or p.rating < 3.5:
        return "rating_missing_or_under_3_5"
    if p.confidence is None or p.confidence == "failed":
        return "confidence_missing_or_failed"
    if p.nature is None or p.classified_at is None:
        return "missing_vector_or_classified_at"
    if _has_overlap(p.types, EXCLUDED_TYPES) and p.travel_category != "nightlife":
        return "excluded_google_type"
    if _has_overlap(p.types, HIGH_POPULARITY_TYPES) and (p.user_ratings_total or 0) < 5000:
        return "high_popularity_type_under_5000_reviews"
    return "other"


async def build_ingestion_summary(db: "AsyncSession", city_name: str) -> dict:
    from collections import Counter

    from sqlalchemy import select

    from app.models.city import City
    from app.models.poi import Poi
    from app.services.candidate_query import fetch_candidate_pois
    from app.services.itinerary_planner import is_actual_food_poi, is_touristic

    result = await db.execute(select(City).where(City.name == city_name))
    city = result.scalar_one_or_none()
    if city is None:
        raise ValueError(f"City {city_name!r} not found in database")

    # Raw table scan on purpose: fetch_candidate_pois already filters on
    # is_touristic, but the ingestion screen must show the discarded POIs too.
    result = await db.execute(select(Poi).where(Poi.city_id == city.id))
    all_pois: list[Poi] = list(result.scalars())

    kept = [p for p in all_pois if p.is_touristic is True]
    discarded = [p for p in all_pois if p.is_touristic is False]
    unvalidated = [p for p in all_pois if p.is_touristic is None]

    classified = [p for p in kept if p.travel_category is not None]
    confidence_counts = {"high": 0, "medium": 0, "failed": 0}
    for p in classified:
        if p.confidence in confidence_counts:
            confidence_counts[p.confidence] += 1

    categories: dict[str, int] = {}
    for p in classified:
        categories[p.travel_category] = categories.get(p.travel_category, 0) + 1

    children = {"suitable": 0, "notSuitable": 0, "unknown": 0}
    for p in kept:
        if p.suitable_for_children is True:
            children["suitable"] += 1
        elif p.suitable_for_children is False:
            children["notSuitable"] += 1
        else:
            children["unknown"] += 1

    with_duration = sum(1 for p in kept if p.tourism_duration_minutes is not None)
    with_hours = sum(1 for p in kept if p.opening_hours is not None)

    planning_candidates = await fetch_candidate_pois(db, city.id, travel_with_children=False)
    planning_candidate_ids = {p.id for p in planning_candidates}
    raw_food_pois = [
        p for p in planning_candidates
        if (p.travel_category == "food" or is_actual_food_poi(p))
        and (p.is_touristic is None or p.is_touristic is True)
    ]
    raw_activity_pois = [
        p for p in planning_candidates
        if p.travel_category != "food" and not is_actual_food_poi(p) and is_touristic(p)
    ]
    candidate_query_rejections = [p for p in kept if p.id not in planning_candidate_ids]

    # Most-rated discarded POIs first: the interesting rejections (hotels,
    # pharmacies, supermarkets with thousands of reviews) make the best examples.
    discarded_sorted = sorted(
        discarded, key=lambda p: p.user_ratings_total or 0, reverse=True,
    )
    discarded_sample = [
        {
            "id": str(p.id),
            "name": p.name,
            "lat": p.lat,
            "lng": p.lng,
            "primaryType": _display_type(p),
            "ratingsTotal": p.user_ratings_total,
        }
        for p in discarded_sorted[:DISCARDED_SAMPLE_MAX]
    ]

    shown = kept + discarded_sorted[:DISCARDED_SAMPLE_MAX]
    lats = [p.lat for p in shown]
    lngs = [p.lng for p in shown]
    city_lat, city_lng = float(city.lat), float(city.lng)
    bounds = (
        [[min(lats) - 0.01, min(lngs) - 0.01], [max(lats) + 0.01, max(lngs) + 0.01]]
        if lats else
        [[city_lat - 0.1, city_lng - 0.1], [city_lat + 0.1, city_lng + 0.1]]
    )

    return {
        "ingestionVersion": INGESTION_VERSION,
        "city": {
            "name": city_name,
            "center": [city_lat, city_lng],
            "bounds": bounds,
        },
        "funnel": {
            "fetched": len(all_pois),
            "tourism": {
                "kept": len(kept),
                "discarded": len(discarded),
                "unvalidated": len(unvalidated),
                "children": children,
                "withDuration": with_duration,
            },
            "classified": {
                "total": len(classified),
                **confidence_counts,
            },
            "planning": {
                "source": "fetch_candidate_pois",
                "input": len(kept),
                "candidateQuery": len(planning_candidates),
                "displayPool": len(raw_activity_pois) + len(raw_food_pois),
                "activity": len(raw_activity_pois),
                "food": len(raw_food_pois),
                "removedByCandidateQuery": len(candidate_query_rejections),
                "candidateQueryRules": [
                    "business_status is present and not CLOSED_PERMANENTLY",
                    "rating >= 3.5",
                    "user_ratings_total >= 200 or unknown",
                    "classified activity with usable feature vector and allowed Google types",
                    "validated nightlife is allowed for non-family planning",
                    "or validated food-category POI with food-service type",
                ],
                "candidateQueryReasons": dict(
                    Counter(_candidate_query_drop_reason(p) for p in candidate_query_rejections).most_common()
                ),
            },
            "hours": {
                "withHours": with_hours,
                "withoutHours": len(kept) - with_hours,
            },
        },
        "categories": dict(sorted(categories.items(), key=lambda kv: -kv[1])),
        "pois": [_poi_out(p) for p in kept],
        "discardedSample": discarded_sample,
    }
