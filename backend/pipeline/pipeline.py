"""POI pipeline — fetch from Google Places + classify with Claude/Perplexity.

Usage:
    # lat/lng opzionali: se omessi vengono risolti via Nominatim (OpenStreetMap)
    python pipeline/pipeline.py --city "Roma" --country "Italy"
    python pipeline/pipeline.py --city "Roma" --country "Italy" --lat 41.9028 --lng 12.4964
    python pipeline/pipeline.py --city "Roma" --country "Italy" --force-refetch
    python pipeline/pipeline.py --city "Roma" --country "Italy" --classify-only
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid as uuid_module
from datetime import datetime, timezone

import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.city import City
from app.models.poi import Poi
from pipeline.classifier import classify_batch, setup_llm_log
from pipeline.tourism_validator import validate_tourism_batch
from pipeline.fetcher import fetch_city_pois, fetch_city_pois_text_search
from pipeline.hours_fetcher import fetch_opening_hours_for_city
from pipeline.llm_client import get_backend
from app.constants import FEATURE_NAMES as _FEATURE_LABELS
from pipeline.utils import setup_logging, validate_vector, normalize_vector

CLASSIFY_BATCH = 10
CHECKPOINT_EVERY = 10


async def geocode(city: str, country: str) -> tuple[float, float]:
    """Resolve city coordinates via Nominatim (OpenStreetMap). No API key required."""
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": f"{city}, {country}", "format": "json", "limit": 1}
    headers = {"User-Agent": "EasyTravel-Pipeline/1.0"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        results = resp.json()
    if not results:
        raise ValueError(f"Nominatim: nessun risultato per '{city}, {country}'")
    lat = float(results[0]["lat"])
    lng = float(results[0]["lon"])
    return lat, lng


async def get_or_create_city(
    session,
    name: str,
    country: str,
    lat: float,
    lng: float,
) -> City:
    result = await session.execute(select(City).where(City.name == name))
    city = result.scalar_one_or_none()
    if city is None:
        city = City(name=name, country=country, lat=lat, lng=lng)
        session.add(city)
        await session.commit()
        await session.refresh(city)
    return city


async def run_pipeline(
    city_name: str,
    country: str,
    lat: float | None,
    lng: float | None,
    force_refetch: bool = False,
    classify_only: bool = False,
    limit: int | None = None,
    skip_hours: bool = False,
    hours_only: bool = False,
    reclassify: bool = False,
    tourism_only: bool = False,
    skip_tourism: bool = False,
    reclassify_tourism: bool = False,
    min_ratings: int | None = None,
    food_tourism: bool = False,
    text_search: bool = False,
) -> None:
    date_str = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d")
    logger = setup_logging(city_name, date_str)
    setup_llm_log(city_name, date_str)
    pipeline_run_id = str(uuid_module.uuid4())
    logger.info(f"=== Pipeline start: {city_name} (run_id={pipeline_run_id}) ===")

    # Geocoding automatico se lat/lng non forniti
    if lat is None or lng is None:
        logger.info(f"lat/lng non specificati — geocoding via Nominatim per '{city_name}, {country}'...")
        try:
            lat, lng = await geocode(city_name, country)
            logger.info(f"  → lat={lat}, lng={lng}")
        except Exception as e:
            logger.error(f"Geocoding fallito: {e}")
            return

    async with AsyncSessionLocal() as session:
        city = await get_or_create_city(session, city_name, country, lat, lng)
        logger.info(f"City: {city.name} (id={city.id}, lat={city.lat}, lng={city.lng})")

        # food_tourism: re-validate only food-type POIs with the updated prompt
        if food_tourism:
            logger.info("--food-tourism: re-validating food POIs with updated tourism prompt")
            from sqlalchemy import update as sa_update
            from app.services.itinerary_planner import FOOD_SERVICE_TYPES
            food_types_list = list(FOOD_SERVICE_TYPES)
            # Reset tourism_validated_at only for food-type POIs so they are re-processed
            await session.execute(
                sa_update(Poi)
                .where(Poi.city_id == city.id)
                .where(Poi.types.overlap(food_types_list))
                .values(tourism_validated_at=None)
            )
            await session.commit()
            reset_result = await session.execute(
                select(Poi)
                .where(Poi.city_id == city.id)
                .where(Poi.types.overlap(food_types_list))
            )
            reset_count = len(reset_result.scalars().all())
            logger.info("  → Reset %d food POIs for re-validation", reset_count)
            backend = get_backend(settings.pipeline_llm_backend, settings.pipeline_llm_model)
            validated, _, tv_failed = await validate_tourism_batch(
                session=session,
                city_id=city.id,
                city_name=city_name,
                backend=backend,
                pipeline_run_id=pipeline_run_id,
            )
            logger.info(f"=== Food tourism validation complete: {validated} validated, {tv_failed} failed ===")
            return

        # hours_only: skip fetch and classify, only run Step 4
        if hours_only:
            logger.info("--hours-only: skipping fetch and classify")
            if not settings.google_places_api_key:
                logger.error("GOOGLE_PLACES_API_KEY not set")
                return
            fetched, skipped, failed = await fetch_opening_hours_for_city(
                session=session,
                city_id=city.id,
                api_key=settings.google_places_api_key,
            )
            logger.info(
                f"=== Hours complete: {fetched} fetched, "
                f"{skipped} skipped, {failed} failed ==="
            )
            return

        # Step 1: Fetch POIs
        if not classify_only:
            logger.info("Step 1: Fetching POIs from Google Places...")
            if not settings.google_places_api_key:
                logger.error("GOOGLE_PLACES_API_KEY not set")
                return
            count = await fetch_city_pois(
                city=city,
                api_key=settings.google_places_api_key,
                session=session,
                force=force_refetch,
                limit=limit,
            )
            logger.info(f"  → {count} POIs upserted")

            if text_search:
                logger.info("Step 1b: Text search supplemental fetch...")
                ts_count = await fetch_city_pois_text_search(
                    city=city,
                    city_name=city_name,
                    country=country,
                    api_key=settings.google_places_api_key,
                    session=session,
                )
                logger.info(f"  → {ts_count} new POIs from text search")
        else:
            logger.info("Step 1: Skipped (--classify-only)")
            if text_search:
                logger.info("Step 1b: Text search supplemental fetch...")
                if not settings.google_places_api_key:
                    logger.error("GOOGLE_PLACES_API_KEY not set")
                else:
                    ts_count = await fetch_city_pois_text_search(
                        city=city,
                        city_name=city_name,
                        country=country,
                        api_key=settings.google_places_api_key,
                        session=session,
                    )
                    logger.info(f"  → {ts_count} new POIs from text search")

        # Step 1.5: Tourism validation
        if tourism_only:
            logger.info("--tourism-only: running tourism validation then stopping")
            backend = get_backend(settings.pipeline_llm_backend, settings.pipeline_llm_model)
            await validate_tourism_batch(
                session=session,
                city_id=city.id,
                city_name=city_name,
                backend=backend,
                pipeline_run_id=pipeline_run_id,
            )
            return

        if not skip_tourism:
            logger.info("Step 1.5: Tourism validation...")

            if reclassify_tourism:
                logger.info("  --reclassify-tourism: resetting validation status")
                from sqlalchemy import update as sa_update
                await session.execute(
                    sa_update(Poi)
                    .where(Poi.city_id == city.id)
                    .values(tourism_validated_at=None)
                )
                await session.commit()

            backend = get_backend(settings.pipeline_llm_backend, settings.pipeline_llm_model)
            validated, _, tv_failed = await validate_tourism_batch(
                session=session,
                city_id=city.id,
                city_name=city_name,
                backend=backend,
                pipeline_run_id=pipeline_run_id,
            )
            logger.info(f"  → {validated} validated, {tv_failed} failed")
        else:
            logger.info("Step 1.5: Skipped (--skip-tourism)")

        # Step 2: Load POIs to classify (only touristic, validated POIs)
        if reclassify:
            logger.info("Step 2: Loading POIs with is_indoor_visitable IS NULL (--reclassify)...")
            poi_query = (
                select(Poi)
                .where(Poi.city_id == city.id)
                .where(Poi.is_indoor_visitable.is_(None))
                .where(Poi.tourism_validated_at.is_not(None))
                .where(Poi.is_touristic == True)  # noqa: E712
            )
        else:
            logger.info("Step 2: Loading unclassified touristic POIs...")
            poi_query = (
                select(Poi)
                .where(Poi.city_id == city.id)
                .where(Poi.classified_at.is_(None))
                .where(Poi.tourism_validated_at.is_not(None))
                .where(Poi.is_touristic == True)  # noqa: E712
            )
        if min_ratings is not None:
            poi_query = poi_query.where(Poi.user_ratings_total >= min_ratings)
            logger.info(f"  → filter: user_ratings_total >= {min_ratings}")
        poi_query = poi_query.execution_options(yield_per=100)
        result = await session.stream(poi_query)
        pois = [row async for row in result.scalars()]
        logger.info(f"  → {len(pois)} POIs to classify")

        if not pois:
            logger.info("Nothing to classify. Done.")
            return

        # Step 3: Classify
        logger.info(f"Step 3: Classifying POIs (backend={settings.pipeline_llm_backend}, model={settings.pipeline_llm_model})...")
        try:
            backend = get_backend(settings.pipeline_llm_backend, settings.pipeline_llm_model)
        except ValueError as e:
            logger.error(str(e))
            return

        failed = 0
        for i in range(0, len(pois), CLASSIFY_BATCH):
            batch = pois[i : i + CLASSIFY_BATCH]
            results = await classify_batch(
                batch,
                backend,
                session=session,
                city_name=city_name,
                pipeline_run_id=pipeline_run_id,
            )

            for poi, res in zip(batch, results):
                travel_category = res.get("travel_category")
                feature_vector = res.get("feature_vector")
                confidence = res.get("confidence", "failed")

                if confidence == "failed" or feature_vector is None:
                    poi.confidence = "failed"
                    failed += 1
                else:
                    if not validate_vector(feature_vector):
                        original_len = len(feature_vector) if isinstance(feature_vector, list) else "?"
                        feature_vector = normalize_vector(feature_vector)
                        if not validate_vector(feature_vector):
                            logger.warning(
                                f"  Invalid feature_vector for '{poi.name}': "
                                f"got {original_len} elements (expected 7), skipping"
                            )
                            poi.confidence = "failed"
                            failed += 1
                            continue

                    poi.travel_category = travel_category
                    poi.confidence = confidence
                    indoor = res.get("is_indoor_visitable", None)
                    if isinstance(indoor, str):
                        indoor = None if indoor.lower() == "null" else indoor.lower() == "true"
                    poi.is_indoor_visitable = indoor
                    for label, val in zip(_FEATURE_LABELS, feature_vector):
                        setattr(poi, label, val)

                poi.classified_at = datetime.now(timezone.utc).replace(tzinfo=None)
                logger.debug(f"  [{confidence}] {poi.name} → {travel_category}")

            if (i + CLASSIFY_BATCH) % CHECKPOINT_EVERY == 0 or (i + CLASSIFY_BATCH) >= len(pois):
                await session.commit()
                logger.info(f"  Checkpoint: {min(i + CLASSIFY_BATCH, len(pois))}/{len(pois)} classified")

        await session.commit()
        classified = len(pois) - failed
        logger.info(f"=== Pipeline complete: {classified} classified, {failed} failed ===")

        # Step 4: Fetch opening hours
        if not skip_hours:
            logger.info("Step 4: Fetching opening hours from Google Places Details...")
            if not settings.google_places_api_key:
                logger.error("GOOGLE_PLACES_API_KEY not set, skipping hours fetch")
            else:
                fetched, skipped, failed = await fetch_opening_hours_for_city(
                    session=session,
                    city_id=city.id,
                    api_key=settings.google_places_api_key,
                )
                logger.info(
                    f"  → Hours complete: {fetched} fetched, "
                    f"{skipped} skipped (outdoor), {failed} failed"
                )
        else:
            logger.info("Step 4: Skipped (--skip-hours)")


def main() -> None:
    parser = argparse.ArgumentParser(description="EasyTravel POI pipeline")
    parser.add_argument("--city", required=True, help="Nome della città")
    parser.add_argument("--country", required=True, help="Nome del paese")
    parser.add_argument("--lat", type=float, default=None, help="Latitudine (opzionale, risolta via Nominatim se omessa)")
    parser.add_argument("--lng", type=float, default=None, help="Longitudine (opzionale, risolta via Nominatim se omessa)")
    parser.add_argument("--force-refetch", action="store_true", help="Re-fetch anche se la città è stata fetchata di recente")
    parser.add_argument("--classify-only", action="store_true", help="Salta il fetch, classifica solo i POI esistenti")
    parser.add_argument("--limit", type=int, default=None, help="Numero massimo di POI da fetchare (utile per test)")
    parser.add_argument(
        "--skip-hours",
        action="store_true",
        help="Skip opening hours fetch (Step 4)",
    )
    parser.add_argument(
        "--hours-only",
        action="store_true",
        help="Only fetch opening hours, skip fetch and classify",
    )
    parser.add_argument(
        "--reclassify",
        action="store_true",
        help="Re-classify POIs that are already classified but have is_indoor_visitable IS NULL",
    )
    parser.add_argument(
        "--tourism-only",
        action="store_true",
        help="Only run tourism validation, skip fetch and classify",
    )
    parser.add_argument(
        "--skip-tourism",
        action="store_true",
        help="Skip tourism validation step (Step 1.5)",
    )
    parser.add_argument(
        "--reclassify-tourism",
        action="store_true",
        help="Re-run tourism validation even for already-validated POIs (resets tourism_validated_at)",
    )
    parser.add_argument(
        "--min-ratings",
        type=int,
        default=None,
        help="Classifica solo POI con user_ratings_total >= N (es. --min-ratings 500)",
    )
    parser.add_argument(
        "--food-tourism",
        action="store_true",
        help="Re-run tourism validation only for food-type POIs (resets their tourism_validated_at)",
    )
    parser.add_argument(
        "--text-search",
        action="store_true",
        help="Run supplemental Text Search queries to catch POIs missed by Nearby Search (e.g. public squares)",
    )
    args = parser.parse_args()

    asyncio.run(
        run_pipeline(
            city_name=args.city,
            country=args.country,
            lat=args.lat,
            lng=args.lng,
            force_refetch=args.force_refetch,
            classify_only=args.classify_only,
            limit=args.limit,
            skip_hours=args.skip_hours,
            hours_only=args.hours_only,
            reclassify=args.reclassify,
            tourism_only=args.tourism_only,
            skip_tourism=args.skip_tourism,
            reclassify_tourism=args.reclassify_tourism,
            min_ratings=args.min_ratings,
            food_tourism=args.food_tourism,
            text_search=args.text_search,
        )
    )


if __name__ == "__main__":
    main()
