"""Shared candidate-POI query for itinerary generation.

Single source of truth for *which* POIs are eligible for an itinerary, so the
production endpoint (`routers/itineraries.py`) and the evaluation harness
(`evaluation/run_eval.py`) select exactly the same candidate set. Keeping this in
one place is what makes the thesis evaluation faithful to production.
"""
from __future__ import annotations

import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.poi import Poi
from app.services.itinerary_planner import (
    EXCLUDED_TYPES,
    FOOD_SERVICE_TYPES,
    HIGH_POPULARITY_TYPES,
)

_EXCLUDED_TYPES_LIST = list(EXCLUDED_TYPES)
_HIGH_POPULARITY_TYPES_LIST = list(HIGH_POPULARITY_TYPES)
_FOOD_SERVICE_TYPES_LIST = list(FOOD_SERVICE_TYPES)


async def fetch_candidate_pois(
    db: AsyncSession,
    city_id: uuid.UUID,
    travel_with_children: bool = False,
) -> list[Poi]:
    """Return the classified, touristic POIs eligible for an itinerary in a city.

    Mirrors the filter used by the generate endpoint:
    - not permanently closed, rating >= 3.5, enough ratings (or unknown),
    - classified touristic activity POIs (excluding the non-touristic type blacklist),
    - OR notable food POIs validated as touristic,
    - when travelling with children, exclude POIs marked not child-friendly.
    """
    result = await db.execute(
        select(Poi).where(
            Poi.city_id == city_id,
            Poi.business_status != "CLOSED_PERMANENTLY",
            or_(Poi.user_ratings_total >= 200, Poi.user_ratings_total.is_(None)),
            Poi.rating >= 3.5,
            or_(
                and_(
                    Poi.confidence != "failed",
                    Poi.nature.is_not(None),
                    Poi.classified_at.is_not(None),
                    or_(Poi.is_touristic.is_(None), Poi.is_touristic == True),  # noqa: E712
                    or_(
                        Poi.types.is_(None),
                        Poi.types == [],
                        ~Poi.types.overlap(_EXCLUDED_TYPES_LIST),
                    ),
                    or_(
                        Poi.types.is_(None),
                        Poi.types == [],
                        ~Poi.types.overlap(_HIGH_POPULARITY_TYPES_LIST),
                        Poi.user_ratings_total >= 5000,
                    ),
                ),
                and_(
                    Poi.types.is_not(None),
                    Poi.types.overlap(_FOOD_SERVICE_TYPES_LIST),
                    or_(Poi.is_touristic.is_(None), Poi.is_touristic == True),  # noqa: E712
                ),
            ),
            *(
                [or_(
                    Poi.suitable_for_children.is_(None),
                    Poi.suitable_for_children == True,  # noqa: E712
                )]
                if travel_with_children else []
            ),
        )
    )
    return list(result.scalars().all())
