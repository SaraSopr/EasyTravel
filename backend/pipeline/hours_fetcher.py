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


def _normalize_periods(new_periods: list[dict]) -> list[dict]:
    """Convert Places API (New) period shape to the legacy shape the planner reads.

    New:    {"open": {"day": 0, "hour": 9, "minute": 0}, "close": {...}}
    Legacy: {"open": {"day": 0, "time": "0900"}, "close": {"day": 0, "time": "1700"}}

    The day convention is identical (0=Sunday … 6=Saturday), so only the time
    representation changes. See itinerary_planner._is_open.
    """
    def _point(p: dict | None) -> dict | None:
        if not p:
            return None
        return {
            "day": p.get("day"),
            "time": f"{int(p.get('hour', 0)):02d}{int(p.get('minute', 0)):02d}",
        }

    out: list[dict] = []
    for period in new_periods:
        entry: dict = {}
        op = _point(period.get("open"))
        cl = _point(period.get("close"))
        if op:
            entry["open"] = op
        if cl:
            entry["close"] = cl
        if entry:
            out.append(entry)
    return out


async def fetch_place_details_hours(
    client: httpx.AsyncClient,
    google_place_id: str,
    api_key: str,
) -> dict | None:
    """
    Call Place Details (New) requesting only the regularOpeningHours field.
    Returns parsed hours dict (legacy shape) or None on error/missing data.
    Cost: 1 Place Details (New) call per POI, billed by the requested field mask.
    """
    url = f"https://places.googleapis.com/v1/places/{google_place_id}"
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "regularOpeningHours",
    }
    try:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            logger.warning(
                f"Place Details error for {google_place_id}: "
                f"{resp.status_code} {resp.text[:200]}"
            )
            return None
        hours = resp.json().get("regularOpeningHours", {})
        if not hours:
            return {}  # explicitly empty: no hours available
        return {
            "periods": _normalize_periods(hours.get("periods", [])),
            "weekday_text": hours.get("weekdayDescriptions", []),
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
