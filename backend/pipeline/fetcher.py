from __future__ import annotations

import asyncio
import logging
import math
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.city import City
from app.models.poi import Poi

logger = logging.getLogger(__name__)

# Google Places type groups mapped to travel categories
TYPE_GROUPS: dict[str, list[str]] = {
    "culture": ["museum", "art_gallery", "church", "hindu_temple", "mosque", "synagogue",
                "tourist_attraction", "cemetery", "library"],
    "nature": ["park", "national_park", "campground", "rv_park", "zoo"],
    "food": ["restaurant", "cafe", "bakery", "bar", "meal_takeaway", "meal_delivery"],
    "adventure": ["amusement_park", "bowling_alley", "stadium", "gym", "sports_complex"],
    "nightlife": ["night_club", "casino", "bar", "liquor_store"],
    "relax": ["spa", "beauty_salon", "shopping_mall", "park"],
    "family": ["amusement_park", "aquarium", "zoo", "playground", "movie_theater"],
}

# One representative type per travel category — used for the hexagonal grid sweep.
# Places API (New) Nearby Search returns at most 20 results per call (no pagination),
# so the grid is denser (GRID_STEP_M below) to keep coverage in dense areas.
GRID_SEARCH_TYPES = [
    "tourist_attraction",
    "museum",
    "restaurant",
    "park",
    "night_club",
    "spa",
    "amusement_park",
]

# ── Places API (New) endpoints ─────────────────────────────────────
SEARCH_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
SEARCH_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
# Geocoding is a separate Google API (not part of Places) — endpoint unchanged.
GOOGLE_GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# Field mask for search calls. Keep it lean: only the fields we persist.
# `editorialSummary`/`primaryType` enrich the LLM tourism/classification stages.
SEARCH_FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.location",
    "places.types",
    "places.primaryType",
    "places.rating",
    "places.userRatingCount",
    "places.priceLevel",
    "places.businessStatus",
    "places.formattedAddress",
    "places.photos",
    "places.editorialSummary",
])

# Nearby Search (New) hard limit: 20 results per call, no pagination.
NEARBY_MAX_RESULTS = 20
# Text Search (New): up to 60 results via pageSize(≤20) + pageToken.
TEXT_PAGE_SIZE = 20
TEXT_MAX_PAGES = 3
PAGE_SLEEP_S = 2
CACHE_TTL_DAYS = 30
# Denser than the legacy 3 000 m grid to offset the 20-result-per-call cap.
GRID_STEP_M = 2_000

# Map Places API (New) priceLevel enum → legacy integer 0–4 used by the DB column.
_PRICE_LEVEL_MAP = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}

TEXT_SEARCH_QUERIES = [
    "top tourist attractions in {city}, {country}",
    "famous landmarks {city}, {country}",
    "historic sites {city}, {country}",
    "best restaurants {city}, {country}",
    "parks and squares {city}, {country}",
]


async def fetch_city_pois(
    city: City,
    api_key: str,
    session: AsyncSession,
    force: bool = False,
    limit: int | None = None,
    country: str = "",
    grid_step_m: int = GRID_STEP_M,
) -> int:
    """Fetch POIs from Google Places (New) for the given city and upsert into DB.

    When a Geocoding viewport is available the search is distributed over a
    hexagonal grid of radius=grid_step_m cells covering the whole city bounding
    box, so outer neighbourhoods are covered in addition to the centre. Falls back
    to a single-centre search when the Geocoding call fails.

    Returns the number of POIs upserted.
    """
    if not force and city.last_fetched_at:
        threshold = datetime.now(timezone.utc) - timedelta(days=CACHE_TTL_DAYS)
        last = city.last_fetched_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last > threshold:
            logger.info(f"City {city.name} fetched recently, skipping (use --force-refetch to override)")
            return 0

    seen: set[str] = set()
    upserted = 0

    # --- Try to get city bounding box for grid search ---
    bbox = await _get_city_bbox(city.name, country, api_key)

    async with httpx.AsyncClient(timeout=30) as client:
        if bbox:
            sw_lat, sw_lng, ne_lat, ne_lng = bbox
            grid_points = _generate_hex_grid(sw_lat, sw_lng, ne_lat, ne_lng, grid_step_m)
            logger.info(
                f"Grid search: {len(grid_points)} hex cells "
                f"(step={grid_step_m}m, bbox=({sw_lat:.3f},{sw_lng:.3f})→({ne_lat:.3f},{ne_lng:.3f}))"
            )

            for place_type in GRID_SEARCH_TYPES:
                for pt_lat, pt_lng in grid_points:
                    places = await _search_nearby(
                        client, api_key, place_type, pt_lat, pt_lng, grid_step_m
                    )
                    for place in places:
                        if limit and upserted >= limit:
                            break
                        gid = place.get("id")
                        if not gid or gid in seen:
                            continue
                        seen.add(gid)
                        await _upsert_poi(session, city.id, place)
                        upserted += 1

                    await asyncio.sleep(PAGE_SLEEP_S)
                    if limit and upserted >= limit:
                        break

                if limit and upserted >= limit:
                    break

        else:
            # Fallback: single-centre search with the full TYPE_GROUPS list.
            logger.info("Geocoding bbox unavailable — falling back to centre-based search")
            for category, place_types in TYPE_GROUPS.items():
                for place_type in place_types:
                    places = await _search_nearby(
                        client, api_key, place_type, city.lat, city.lng, 5_000
                    )
                    for place in places:
                        if limit and upserted >= limit:
                            break
                        gid = place.get("id")
                        if not gid or gid in seen:
                            continue
                        seen.add(gid)
                        await _upsert_poi(session, city.id, place)
                        upserted += 1

                    await asyncio.sleep(PAGE_SLEEP_S)
                    if limit and upserted >= limit:
                        break

                if limit and upserted >= limit:
                    break

    city.last_fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await session.commit()
    logger.info(f"Fetched and upserted {upserted} POIs for {city.name}")
    return upserted


async def _search_nearby(
    client: httpx.AsyncClient,
    api_key: str,
    place_type: str,
    lat: float,
    lng: float,
    radius_m: float,
) -> list[dict]:
    """One Nearby Search (New) call. Returns the list of place objects (≤20)."""
    body = {
        "includedTypes": [place_type],
        "maxResultCount": NEARBY_MAX_RESULTS,
        "rankPreference": "POPULARITY",
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": float(min(radius_m, 50_000)),
            }
        },
    }
    data = await _request_with_retry(client, SEARCH_NEARBY_URL, body, api_key)
    return data.get("places", []) if data else []


async def _get_city_bbox(
    city_name: str, country: str, api_key: str
) -> tuple[float, float, float, float] | None:
    """Return (sw_lat, sw_lng, ne_lat, ne_lng) from the Google Geocoding viewport.

    Returns None if the API call fails or the city is not found.
    """
    address = f"{city_name}, {country}" if country else city_name
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                GOOGLE_GEOCODING_URL,
                params={"address": address, "key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            logger.warning(f"Geocoding API error for '{address}': {e}")
            return None

    results = data.get("results", [])
    if not results:
        logger.warning(f"Geocoding: no results for '{address}'")
        return None

    vp = results[0].get("geometry", {}).get("viewport", {})
    sw = vp.get("southwest", {})
    ne = vp.get("northeast", {})
    if not (sw.get("lat") is not None and ne.get("lat") is not None):
        logger.warning(f"Geocoding: viewport missing for '{address}'")
        return None

    return sw["lat"], sw["lng"], ne["lat"], ne["lng"]


def _generate_hex_grid(
    sw_lat: float, sw_lng: float, ne_lat: float, ne_lng: float, step_m: float
) -> list[tuple[float, float]]:
    """Generate hexagonal grid points covering the bounding box.

    Adjacent rows are offset by half a step (honeycomb packing) so the maximum
    distance from any point in the box to the nearest grid centre is ≤ step_m.
    Vertical spacing is step_m × (√3/2) to preserve the hexagonal geometry.
    """
    R = 6_371_000.0
    dy = math.degrees(step_m / R)
    dy_vert = dy * (math.sqrt(3) / 2)  # row-to-row spacing

    points: list[tuple[float, float]] = []
    row = 0
    lat = sw_lat
    while lat <= ne_lat + dy_vert:
        dx = math.degrees(step_m / (R * math.cos(math.radians(max(-89.9, min(89.9, lat))))))
        # odd rows shifted right by half a cell for hex packing
        offset = dx / 2.0 if row % 2 == 1 else 0.0
        lng = sw_lng + offset
        while lng <= ne_lng + dx:
            points.append((round(lat, 6), round(lng, 6)))
            lng += dx
        lat += dy_vert
        row += 1

    return points


async def _request_with_retry(
    client: httpx.AsyncClient,
    url: str,
    body: dict,
    api_key: str,
    field_mask: str = SEARCH_FIELD_MASK,
    max_retries: int = 3,
) -> dict | None:
    """POST to a Places API (New) endpoint with retry/backoff.

    Auth + field selection go in headers (not the body). Returns the parsed JSON
    response, or None on a non-retryable error / exhausted retries.
    """
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": field_mask,
    }
    backoff = 2
    for attempt in range(max_retries):
        try:
            resp = await client.post(url, json=body, headers=headers)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                logger.warning("Places API rate limited (429) — sleeping 60s before retry")
                await asyncio.sleep(60)
                continue
            if resp.status_code in (401, 403):
                # Bad key / API not enabled / restricted — retrying won't help.
                logger.error(
                    "Places API request denied (%s): %s", resp.status_code, resp.text[:300]
                )
                return None
            if 500 <= resp.status_code < 600:
                logger.warning(
                    "Places API server error (%s), retry %d/%d in %ds",
                    resp.status_code, attempt + 1, max_retries, backoff,
                )
                await asyncio.sleep(backoff)
                backoff *= 2
                continue
            # Other 4xx (e.g. 400 bad request) — non-retryable.
            logger.error("Places API error (%s): %s", resp.status_code, resp.text[:300])
            return None

        except httpx.RequestError as e:
            if attempt < max_retries - 1:
                logger.warning(f"Request error ({e}), retry {attempt + 1}/{max_retries} in {backoff}s")
                await asyncio.sleep(backoff)
                backoff *= 2
            else:
                logger.error(f"Request failed after {max_retries} retries: {e}")
                return None

    return None


async def fetch_city_pois_text_search(
    city: City,
    city_name: str,
    country: str,
    api_key: str,
    session: AsyncSession,
) -> int:
    """Supplement Nearby Search by running Text Search (New) queries for the city.

    For each result, checks the DB first — skips POIs that already exist
    (identified by google_place_id) and inserts only the new ones.
    Returns the number of new POIs inserted.
    """
    inserted = 0

    async with httpx.AsyncClient(timeout=30) as client:
        for query_template in TEXT_SEARCH_QUERIES:
            query = query_template.format(city=city_name, country=country)
            page_token: str | None = None

            for _page in range(TEXT_MAX_PAGES):
                body: dict = {"textQuery": query, "pageSize": TEXT_PAGE_SIZE}
                if page_token:
                    body["pageToken"] = page_token

                data = await _request_with_retry(client, SEARCH_TEXT_URL, body, api_key)
                if data is None:
                    break

                for place in data.get("places", []):
                    gid = place.get("id")
                    if not gid:
                        continue

                    # Check DB — skip if already exists
                    existing = await session.execute(
                        select(Poi).where(Poi.google_place_id == gid)
                    )
                    if existing.scalar_one_or_none() is not None:
                        continue

                    await _upsert_poi(session, city.id, place)
                    inserted += 1
                    logger.debug(f"  [text-search] New POI: {_display_name(place)!r}")

                page_token = data.get("nextPageToken")
                if not page_token:
                    break

                await asyncio.sleep(PAGE_SLEEP_S)

        await session.commit()

    logger.info(f"Text search: {inserted} new POIs inserted for {city_name}")
    return inserted


# ── Places API (New) response parsing ──────────────────────────────

def _display_name(place: dict) -> str:
    return (place.get("displayName") or {}).get("text", "") or ""


def _price_level(place: dict) -> int | None:
    return _PRICE_LEVEL_MAP.get(place.get("priceLevel"))


def _first_photo_name(place: dict) -> str | None:
    """Photo resource name, e.g. ``places/PLACE_ID/photos/REF`` (New API)."""
    photos = place.get("photos") or []
    return photos[0].get("name") if photos else None


def _editorial_summary(place: dict) -> str | None:
    return (place.get("editorialSummary") or {}).get("text")


async def _upsert_poi(session: AsyncSession, city_id, place: dict) -> None:
    gid = place["id"]
    location = place.get("location") or {}
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Opening hours require a separate Place Details (New) call (see hours_fetcher).
    values = {
        "id": uuid.uuid4(),
        "city_id": city_id,
        "google_place_id": gid,
        "name": _display_name(place),
        "address": place.get("formattedAddress"),
        "lat": location.get("latitude", 0.0),
        "lng": location.get("longitude", 0.0),
        "types": place.get("types"),
        "primary_type": place.get("primaryType"),
        "editorial_summary": _editorial_summary(place),
        "rating": place.get("rating"),
        "user_ratings_total": place.get("userRatingCount"),
        "price_level": _price_level(place),
        "business_status": place.get("businessStatus"),
        "opening_hours": sa.null(),
        "photo_reference": _first_photo_name(place),
        "created_at": now,
        "updated_at": now,
    }

    stmt = pg_insert(Poi).values(**values).on_conflict_do_update(
        index_elements=["google_place_id"],
        set_={
            "name": values["name"],
            "address": values["address"],
            "lat": values["lat"],
            "lng": values["lng"],
            "types": values["types"],
            "primary_type": values["primary_type"],
            "editorial_summary": values["editorial_summary"],
            "rating": values["rating"],
            "user_ratings_total": values["user_ratings_total"],
            "price_level": values["price_level"],
            "business_status": values["business_status"],
            "photo_reference": values["photo_reference"],
            "updated_at": now,
        },
    )
    await session.execute(stmt)
