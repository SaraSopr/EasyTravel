"""
Fetch opening hours from Google Places Details API
for POIs that require them.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.poi import Poi

logger = logging.getLogger("pipeline")

# Types that require opening hours (visited indoors, can be closed)
NEEDS_HOURS_TYPES = {
    "museum", "art_gallery", "church", "library",
    "restaurant", "cafe", "bakery", "bar", "food",
    "night_club", "casino", "spa", "beauty_salon",
    "amusement_park", "stadium", "zoo", "aquarium",
    "bowling_alley", "meal_takeaway",
}

# Types that are clearly outdoor and never need hours
OUTDOOR_TYPES = {"park", "natural_feature", "campground", "cemetery", "route"}


def needs_hours_fetch(poi: Poi) -> bool:
    """
    Returns True if the POI likely has opening hours worth fetching.

    Priority order:
    1. Explicitly outdoor (is_indoor_visitable=False) → no hours needed
    2. Explicitly indoor (is_indoor_visitable=True) → always fetch
    3. Unknown (None) → fall back to types + travel_category heuristics
       (err on the side of fetching: better to have unused hours than miss a closed museum)
    """
    # Explicit signal from classifier
    if poi.is_indoor_visitable is False:
        return False
    if poi.is_indoor_visitable is True:
        return True

    # Unknown (None): use types + travel_category heuristic
    poi_types = set(poi.types or [])

    # Clearly outdoor by type → skip
    if poi_types and poi_types.issubset(OUTDOOR_TYPES | {"point_of_interest"}):
        return False

    # Has any indoor-leaning type → fetch
    if poi_types & NEEDS_HOURS_TYPES:
        return True

    # travel_category suggests indoor activity → fetch
    if poi.travel_category in ("culture", "nightlife", "relax", "family"):
        return True

    # tourist_attraction is ambiguous → fetch to be safe
    if "tourist_attraction" in poi_types:
        return True

    return False


async def fetch_place_details_hours(
    client: httpx.AsyncClient,
    google_place_id: str,
    api_key: str,
) -> dict | None:
    """
    Call Google Places Details API requesting only opening_hours field.
    Returns parsed hours dict or None on error/missing data.
    Cost: 1 Basic Data call per POI.
    """
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": google_place_id,
        "fields": "opening_hours",
        "key": api_key,
    }
    try:
        resp = await client.get(url, params=params)
        data = resp.json()
        if data.get("status") not in ("OK", "ZERO_RESULTS"):
            logger.warning(f"Place Details error for {google_place_id}: {data.get('status')}")
            return None
        hours = data.get("result", {}).get("opening_hours", {})
        if not hours:
            return {}  # explicitly empty: no hours available
        return {
            "periods": hours.get("periods", []),
            "weekday_text": hours.get("weekday_text", []),
        }
    except Exception as e:
        logger.warning(f"Place Details request failed for {google_place_id}: {e}")
        return None


async def fetch_opening_hours_for_city(
    session: AsyncSession,
    city_id,
    api_key: str,
) -> tuple[int, int, int]:
    """
    Fetch opening hours for all POIs in a city that:
    1. Need hours based on their types (needs_hours_fetch)
    2. Have opening_hours IS NULL (not yet fetched)

    opening_hours = None  → not yet processed
    opening_hours = {}    → processed, no hours available
    opening_hours = {...} → processed, hours available

    Returns (fetched, skipped, failed) counts.
    """
    result = await session.execute(
        select(Poi)
        .where(Poi.city_id == city_id)
        .where(Poi.opening_hours.is_(None))
        .where(
            (Poi.is_touristic == True) | Poi.is_touristic.is_(None)  # noqa: E712
        )
    )
    all_pois = result.scalars().all()
    pois_to_fetch = [p for p in all_pois if needs_hours_fetch(p)]
    skipped = len(all_pois) - len(pois_to_fetch)

    logger.info(f"  → {len(pois_to_fetch)} POIs need hours fetch, {skipped} skipped (outdoor/generic)")

    if not pois_to_fetch:
        return 0, skipped, 0

    fetched = 0
    failed = 0

    async with httpx.AsyncClient(timeout=15.0) as client:
        for i, poi in enumerate(pois_to_fetch):
            logger.info(f"  [{i+1}/{len(pois_to_fetch)}] {poi.name}")
            hours = await fetch_place_details_hours(client, poi.google_place_id, api_key)

            if hours is None:
                # API error: leave as None, will retry on next run
                failed += 1
                logger.warning(f"    Failed, will retry on next run")
            else:
                poi.opening_hours = hours
                poi.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                session.add(poi)
                fetched += 1

            # Checkpoint every 20 POIs
            if (i + 1) % 20 == 0:
                await session.commit()
                logger.info(f"  Checkpoint: {i+1}/{len(pois_to_fetch)} processed")

            await asyncio.sleep(0.5)  # rate limiting: 2 req/s

    await session.commit()
    return fetched, skipped, failed
