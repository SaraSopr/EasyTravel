from __future__ import annotations

import asyncio
import logging
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
    "nature": ["park", "natural_feature", "campground", "rv_park", "zoo"],
    "food": ["restaurant", "cafe", "bakery", "bar", "food", "meal_takeaway", "meal_delivery"],
    "adventure": ["amusement_park", "bowling_alley", "stadium", "gym", "sports_complex"],
    "nightlife": ["night_club", "casino", "bar", "liquor_store"],
    "relax": ["spa", "beauty_salon", "shopping_mall", "park", "beach"],
    "family": ["amusement_park", "aquarium", "zoo", "playground", "movie_theater"],
}

GOOGLE_PLACES_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
GOOGLE_TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
MAX_PAGES = 3
PAGE_SLEEP_S = 2
CACHE_TTL_DAYS = 30

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
) -> int:
    """Fetch POIs from Google Places for the given city and upsert into DB.

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

    async with httpx.AsyncClient(timeout=30) as client:
        for category, place_types in TYPE_GROUPS.items():
            for place_type in place_types:
                page_token: str | None = None
                for page in range(MAX_PAGES):
                    params: dict = {
                        "location": f"{city.lat},{city.lng}",
                        "radius": 5000,
                        "type": place_type,
                        "key": api_key,
                    }
                    if page_token:
                        params["pagetoken"] = page_token

                    data = await _request_with_retry(client, params)
                    if data is None:
                        break

                    results = data.get("results", [])
                    for place in results:
                        if limit and upserted >= limit:
                            break
                        gid = place.get("place_id")
                        if not gid or gid in seen:
                            continue
                        seen.add(gid)

                        await _upsert_poi(session, city.id, place)
                        upserted += 1

                    if limit and upserted >= limit:
                        break

                    page_token = data.get("next_page_token")
                    if not page_token:
                        break

                if limit and upserted >= limit:
                    break

                await asyncio.sleep(PAGE_SLEEP_S)

            if limit and upserted >= limit:
                break

    city.last_fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await session.commit()
    logger.info(f"Fetched and upserted {upserted} POIs for {city.name}")
    return upserted


async def _request_with_retry(
    client: httpx.AsyncClient,
    params: dict,
    max_retries: int = 3,
) -> dict | None:
    backoff = 2
    for attempt in range(max_retries):
        try:
            resp = await client.get(GOOGLE_PLACES_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")

            if status == "OK" or status == "ZERO_RESULTS":
                return data
            if status == "OVER_QUERY_LIMIT":
                logger.warning("OVER_QUERY_LIMIT — sleeping 60s before retry")
                await asyncio.sleep(60)
                continue
            if status in ("UNKNOWN_ERROR", "REQUEST_DENIED"):
                logger.error(f"Google Places error: {status}")
                return None

            return data

        except (httpx.HTTPStatusError, httpx.RequestError) as e:
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
    """Supplement Nearby Search by running Text Search queries for the city.

    For each result, checks the DB first — skips POIs that already exist
    (identified by google_place_id) and inserts only the new ones.
    Returns the number of new POIs inserted.
    """
    inserted = 0

    async with httpx.AsyncClient(timeout=30) as client:
        for query_template in TEXT_SEARCH_QUERIES:
            query = query_template.format(city=city_name, country=country)
            page_token: str | None = None

            for _page in range(MAX_PAGES):
                params: dict = {"query": query, "key": api_key}
                if page_token:
                    params["pagetoken"] = page_token

                try:
                    resp = await client.get(GOOGLE_TEXT_SEARCH_URL, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                except (httpx.HTTPStatusError, httpx.RequestError) as e:
                    logger.warning(f"Text search error for '{query}': {e}")
                    break

                status = data.get("status")
                if status not in ("OK", "ZERO_RESULTS"):
                    logger.warning(f"Text search status '{status}' for query: {query}")
                    break

                for place in data.get("results", []):
                    gid = place.get("place_id")
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
                    logger.debug(f"  [text-search] New POI: {place.get('name')!r}")

                page_token = data.get("next_page_token")
                if not page_token:
                    break

                await asyncio.sleep(PAGE_SLEEP_S)

        await session.commit()

    logger.info(f"Text search: {inserted} new POIs inserted for {city_name}")
    return inserted


async def _upsert_poi(session: AsyncSession, city_id, place: dict) -> None:
    gid = place["place_id"]
    geometry = place.get("geometry", {}).get("location", {})
    photos = place.get("photos", [])
    photo_ref = photos[0].get("photo_reference") if photos else None
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Nearby Search restituisce solo {"open_now": bool} — dato real-time inutile.
    # Gli orari completi richiedono Place Details API (chiamata separata per POI).
    values = {
        "id": uuid.uuid4(),
        "city_id": city_id,
        "google_place_id": gid,
        "name": place.get("name", ""),
        "address": place.get("vicinity"),
        "lat": geometry.get("lat", 0.0),
        "lng": geometry.get("lng", 0.0),
        "types": place.get("types"),
        "rating": place.get("rating"),
        "user_ratings_total": place.get("user_ratings_total"),
        "price_level": place.get("price_level"),
        "business_status": place.get("business_status"),
        "opening_hours": sa.null(),
        "photo_reference": photo_ref,
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
            "rating": values["rating"],
            "user_ratings_total": values["user_ratings_total"],
            "price_level": values["price_level"],
            "business_status": values["business_status"],
            "photo_reference": values["photo_reference"],
            "updated_at": now,
        },
    )
    await session.execute(stmt)
