from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from jinja2 import Environment, FileSystemLoader
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import AsyncSessionLocal, get_db
from app.models.city import City
from app.models.experience import CityExperience, UserExperienceChoice
from app.models.log import LlmLog
from app.models.poi import Poi
from app.models.preference import UserPreference
from app.models.user import User
from app.schemas.user import UserOut
from app.services import recommendation as recommendation_service
from app.utils.auth import get_current_user

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

logger = logging.getLogger(__name__)

PLACES_SEMAPHORE = asyncio.Semaphore(5)

# Per-city lock to prevent thundering-herd duplicate Perplexity calls
_city_locks: dict[str, asyncio.Lock] = {}
_city_locks_mutex = asyncio.Lock()


async def _get_city_lock(city: str) -> asyncio.Lock:
    async with _city_locks_mutex:
        if city not in _city_locks:
            _city_locks[city] = asyncio.Lock()
        return _city_locks[city]


# ─────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────

class ExperienceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    city: str
    name: str
    description: str | None
    icon: str | None
    category: str | None
    slot: str | None
    why_locals_love_it: str | None
    effort_level: str | None
    time_of_day: str | None
    price_range: str | None
    verifiable: bool
    feature_vector: dict
    google_place_id: str | None
    latitude: float | None
    longitude: float | None
    address: str | None
    phone: str | None
    website: str | None
    google_rating: float | None
    photo_url: str | None
    verified: bool


class ChoicesRequest(BaseModel):
    experience_ids: list[uuid.UUID]


# ─────────────────────────────────────────────
# Perplexity helper
# ─────────────────────────────────────────────

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_jinja_env = Environment(
    loader=FileSystemLoader(_PROMPTS_DIR),
    autoescape=False,
    keep_trailing_newline=True,
)


_EXPERIENCE_MODEL = "gpt-5.4-mini"


async def fetch_experiences_with_web_search(city: str, max_results: int = 10) -> list[dict]:
    """Fetch experiences from gpt-5.4-mini with web search tool use."""
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured")

    from pipeline.llm_client import get_backend

    template = _jinja_env.get_template("experience_discovery_prompt.jinja2")
    user_msg = template.render(city=city, max_results=max_results)

    backend = get_backend("openai", _EXPERIENCE_MODEL, tool_use=True)

    logger.info("experience discovery request city=%s max_results=%d (with web search)", city, max_results)
    t0 = time.monotonic()
    try:
        raw_text, in_tokens, out_tokens = await backend.complete("", user_msg)
    except Exception:
        logger.exception("experience web search API error city=%s", city)
        raise

    latency_ms = int((time.monotonic() - t0) * 1000)

    # Defensive JSON parsing
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not match:
            logger.error("experience unparseable response city=%s text=%s", city, raw_text[:200])
            raise HTTPException(status_code=502, detail="LLM returned unparseable response")
        data = json.loads(match.group())

    experiences = data.get("experiences", [])
    if not isinstance(experiences, list):
        raise HTTPException(status_code=502, detail="Response missing 'experiences' array")

    logger.info(
        "experience response city=%s experiences=%d latency_ms=%d tokens_in=%d tokens_out=%d",
        city, len(experiences), latency_ms, in_tokens, out_tokens,
    )

    # Fire-and-forget DB log
    names = [e.get("name", "") for e in experiences if e.get("name")]

    async def _log() -> None:
        try:
            async with AsyncSessionLocal() as session:
                session.add(LlmLog(
                    model_name=f"{_EXPERIENCE_MODEL}+web_search",
                    prompt=f"city={city}, max_results={max_results}",
                    response=", ".join(names),
                    latency_ms=latency_ms,
                    tokens_used=in_tokens + out_tokens,
                ))
                await session.commit()
        except Exception:
            pass

    asyncio.create_task(_log())
    return experiences


# ─────────────────────────────────────────────
# Google Places helper
# ─────────────────────────────────────────────

async def search_google_places(query: str, city: str) -> dict | None:
    if not settings.google_places_api_key:
        return None

    key = settings.google_places_api_key

    # Places API (New) Text Search returns full place objects in one call; the
    # field mask selects exactly the fields we need (and drives billing).
    field_mask = ",".join([
        "places.id",
        "places.displayName",
        "places.location",
        "places.formattedAddress",
        "places.internationalPhoneNumber",
        "places.websiteUri",
        "places.rating",
        "places.photos",
    ])
    async with PLACES_SEMAPHORE, httpx.AsyncClient(timeout=15.0) as client:
        ts_resp = await client.post(
            "https://places.googleapis.com/v1/places:searchText",
            json={"textQuery": query, "pageSize": 1},
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": field_mask,
            },
        )
        ts_resp.raise_for_status()
        places = ts_resp.json().get("places", [])

    if not places:
        return None

    result = places[0]
    location = result.get("location", {})
    photos = result.get("photos", [])
    first_photo = next((p.get("name") for p in photos if p.get("name")), None)
    final_place_id = result.get("id")

    # Upload photo to R2 (idempotent — skips if already stored)
    photo_url = None
    if first_photo and final_place_id:
        from app.services.storage import upload_photo_from_url
        # Place Photos (New): resource name + /media; key passes as a query param.
        google_photo_url = (
            f"https://places.googleapis.com/v1/{first_photo}/media"
            f"?maxWidthPx=800"
            f"&key={key}"
        )
        photo_url = await upload_photo_from_url(google_photo_url, final_place_id, city)

    return {
        "google_place_id": final_place_id,
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "address": result.get("formattedAddress"),
        "phone": result.get("internationalPhoneNumber"),
        "website": result.get("websiteUri"),
        "google_rating": result.get("rating"),
        "photo_url": photo_url,
    }


def _normalize_place_name(name: str | None) -> str:
    if not name:
        return ""
    normalized = re.sub(r"\s+", " ", name.strip().casefold())
    return normalized


async def _build_local_place_cache(db: AsyncSession, city: str) -> dict[str, dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}

    city_exp_result = await db.execute(
        select(CityExperience)
        .where(CityExperience.city == city)
        .where(CityExperience.google_place_id.is_not(None))
        .order_by(CityExperience.created_at.desc())
    )
    for ce in city_exp_result.scalars().all():
        key = _normalize_place_name(ce.name)
        if key and key not in by_name:
            by_name[key] = {
                "google_place_id": ce.google_place_id,
                "latitude": ce.latitude,
                "longitude": ce.longitude,
                "address": ce.address,
                "phone": ce.phone,
                "website": ce.website,
                "google_rating": ce.google_rating,
                "photo_url": ce.photo_url,
            }

    city_row_result = await db.execute(select(City).where(City.name.ilike(city)))
    city_row = city_row_result.scalar_one_or_none()
    if city_row is None:
        return by_name

    poi_result = await db.execute(select(Poi).where(Poi.city_id == city_row.id))
    for poi in poi_result.scalars().all():
        key = _normalize_place_name(poi.name)
        if key and key not in by_name:
            by_name[key] = {
                "google_place_id": poi.google_place_id,
                "latitude": poi.lat,
                "longitude": poi.lng,
                "address": poi.address,
                "phone": poi.phone,
                "website": poi.website,
                "google_rating": poi.rating,
                "photo_url": None,
            }

    return by_name


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────

@router.get("/experiences", response_model=list[ExperienceOut])
async def get_experiences(
    city: str,
    max_results: int = 10,
    db: AsyncSession = Depends(get_db),
):
    # 1. Cache check
    cutoff = datetime.utcnow() - timedelta(days=settings.cache_ttl_days)
    result = await db.execute(
        select(CityExperience)
        .where(CityExperience.city == city)
        .where(CityExperience.is_deleted == False)  # noqa: E712
        .where(CityExperience.created_at >= cutoff)
    )
    cached = result.scalars().all()
    if cached:
        logger.info("cache hit city=%s count=%d", city, len(cached))
        return cached

    # 2. Per-city lock — prevents two simultaneous requests from both calling Perplexity
    city_lock = await _get_city_lock(city)
    async with city_lock:
        # Re-check cache after acquiring lock (another request may have populated it)
        result = await db.execute(
            select(CityExperience)
            .where(CityExperience.city == city)
            .where(CityExperience.is_deleted == False)  # noqa: E712
            .where(CityExperience.created_at >= cutoff)
        )
        cached = result.scalars().all()
        if cached:
            logger.info("cache hit city=%s count=%d (after lock)", city, len(cached))
            return cached

        logger.info("cache miss city=%s — calling Claude Sonnet with web search", city)

        # 3. Fetch from Claude Sonnet with web search tool use
        raw_experiences = await fetch_experiences_with_web_search(city, max_results)

        # Build an in-request cache from historical data to avoid re-calling Google for known places.
        local_place_cache = await _build_local_place_cache(db, city)

        # 4. Optionally enrich with Google Places (feature flag: GOOGLE_PLACES_ENABLED)
        logger.info("enriching %d experiences for city=%s", len(raw_experiences), city)

        async def enrich(exp: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
            if settings.google_places_enabled and exp.get("verifiable") and exp.get("search_query"):
                name_key = _normalize_place_name(exp.get("name"))
                cached_place = local_place_cache.get(name_key)
                if cached_place is not None:
                    logger.info("reusing cached place for experience '%s' in city=%s", exp.get("name"), city)
                    return {**exp, **cached_place, "verified": True}, exp

                places_data = await search_google_places(exp["search_query"], city)
                if places_data is None:
                    logger.warning("discarding experience '%s' — not found on Google Places", exp.get("name"))
                    return None, exp

                if name_key:
                    local_place_cache[name_key] = places_data
                return {**exp, **places_data, "verified": True}, exp
            return exp, exp

        pairs = await asyncio.gather(*[enrich(e) for e in raw_experiences])
        enriched = [r for r, _ in pairs if r is not None]
        discarded = [orig for r, orig in pairs if r is None]

        # Group discards by slot and fetch replacements from Perplexity
        if discarded:
            discards_by_slot: dict[str, list[str]] = defaultdict(list)
            for exp in discarded:
                slot = exp.get("slot")
                if slot:
                    discards_by_slot[slot].append(exp.get("name", ""))

            async def fetch_and_enrich_replacements(slot: str, exclude_names: list[str]) -> list[dict[str, Any]]:
                count = min(len(exclude_names) + 1, 3)
                candidates = await fetch_replacements_from_perplexity(city, slot, exclude_names, count)
                replacement_pairs = await asyncio.gather(*[enrich(c) for c in candidates])
                accepted = [r for r, _ in replacement_pairs if r is not None]
                logger.info("replacements for slot=%s: %d/%d accepted", slot, len(accepted), len(candidates))
                return accepted

            replacement_results = await asyncio.gather(*[
                fetch_and_enrich_replacements(slot, names)
                for slot, names in discards_by_slot.items()
            ])
            for replacements in replacement_results:
                enriched.extend(replacements)

        # 5. Soft-delete old experiences and insert new ones
        logger.info("saving %d experiences for city=%s", len(enriched), city)
        await db.execute(
            update(CityExperience)
            .where(CityExperience.city == city)
            .where(CityExperience.is_deleted == False)  # noqa: E712
            .values(is_deleted=True)
        )
        valid_fields = {c.key for c in CityExperience.__table__.columns}
        for exp_data in enriched:
            filtered = {k: v for k, v in exp_data.items() if k in valid_fields}
            db_exp = CityExperience(city=city, **filtered)
            db.add(db_exp)
        await db.commit()
        logger.info("saved experiences for city=%s", city)

        # 6. Return fresh rows
        result = await db.execute(
            select(CityExperience)
            .where(CityExperience.city == city)
            .where(CityExperience.is_deleted == False)  # noqa: E712
            .where(CityExperience.created_at >= cutoff)
        )
        return result.scalars().all()


@router.post("/experiences/choices", response_model=UserOut)
async def submit_choices(
    payload: ChoicesRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Delete old choices
    old_result = await db.execute(
        select(UserExperienceChoice).where(
            UserExperienceChoice.user_id == current_user.id
        )
    )
    for old_choice in old_result.scalars().all():
        await db.delete(old_choice)

    # Insert new choices
    for exp_id in payload.experience_ids:
        choice = UserExperienceChoice(
            user_id=current_user.id,
            experience_id=exp_id,
        )
        db.add(choice)

    await db.flush()

    # Load the experiences for the selected IDs
    exp_result = await db.execute(
        select(CityExperience).where(CityExperience.id.in_(payload.experience_ids))
    )
    experiences = exp_result.scalars().all()

    # Rebuild preference vector from stored feature_vectors
    vector = recommendation_service.build_user_vector(
        [e.feature_vector for e in experiences if e.feature_vector]
    )

    # Upsert UserPreference
    pref_result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == current_user.id)
    )
    pref = pref_result.scalar_one_or_none()
    if pref is None:
        pref = UserPreference(user_id=current_user.id)
        db.add(pref)

    pref.nature = vector["nature"]
    pref.culture = vector["culture"]
    pref.food = vector["food"]
    pref.adventure = vector["adventure"]
    pref.nightlife = vector["nightlife"]
    pref.relax = vector["relax"]
    pref.family_friendly = vector["family_friendly"]

    await db.commit()

    result = await db.execute(
        select(User)
        .options(selectinload(User.preferences))
        .where(User.id == current_user.id)
    )
    user = result.scalar_one()
    return UserOut.model_validate(user)
