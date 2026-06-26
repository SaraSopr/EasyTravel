from __future__ import annotations

import logging
import uuid
from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.city import City
from app.models.itinerary import Itinerary, ItineraryItem
from app.models.poi import Poi
from app.models.preference import UserPreference
from app.models.user import User
from app.schemas.itinerary import (
    CheckInRequest,
    CheckInResponse,
    GenerateItineraryRequest,
    ItineraryDayOut,
    ItineraryOut,
    ItineraryStop,
    ItinerarySummary,
    PoiSuggestion,
    ReplaceStopRequest,
    TravelMode,
)
from app.services import itinerary_planner
from app.services import recommendation as recommendation_service
from app.services.candidate_query import fetch_candidate_pois
from app.services.itinerary_planner import get_user_poi_history, haversine_m, select_transport
from app.utils.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/itineraries", tags=["itineraries"])


def _parse_time(s: str) -> time:
    try:
        h, m = map(int, s.split(":"))
        return time(h, m)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid time format '{s}'. Expected HH:MM.",
        )


_TRAVEL_MODE_SCHEDULE: dict[TravelMode, tuple[str, str]] = {
    TravelMode.solo:    ("09:00", "22:00"),  # flexible, own pace, long evenings
    TravelMode.couple:  ("09:30", "22:00"),  # slight morning delay, long evenings
    TravelMode.friends: ("10:00", "23:00"),  # later start, longer nights
    TravelMode.family:  ("08:30", "20:00"),  # early with kids, finish before dark
}


def _schedule_for_mode(travel_mode: TravelMode) -> tuple[str, str]:
    return _TRAVEL_MODE_SCHEDULE.get(travel_mode, ("09:00", "22:00"))


def _google_maps_url(poi) -> str | None:
    if poi.google_place_id:
        return f"https://www.google.com/maps/place/?q=place_id:{poi.google_place_id}"
    return None


async def _geocode_location(query: str, city: str) -> tuple[float, float] | None:
    """Resolve a free-text address / hotel name to (lat, lng) via Nominatim.

    Biased toward the requested city by appending it to the query. Returns None on
    any failure — the caller then falls back to the city center, so a bad address
    never blocks itinerary generation.
    """
    import httpx

    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": f"{query}, {city}", "format": "json", "limit": 1}
    headers = {"User-Agent": "EasyTravel/1.0"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            results = resp.json()
        if not results:
            return None
        return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as exc:
        logger.warning("Geocoding failed for %r: %s", query, exc)
        return None


async def _read_travel_time(db, origin, dest) -> tuple[str, float]:
    """Travel (transport, minutes) for a saved itinerary leg, cache-first.

    Mode is chosen by the haversine heuristic; the duration comes from the real
    travel-time cache when available, else haversine. Never calls the API on read.
    """
    from app.services.routes_client import get_travel_time

    mode, hav_min = select_transport(haversine_m(origin.lat, origin.lng, dest.lat, dest.lng))
    minutes, _meters = await get_travel_time(
        db, origin, dest, itinerary_planner._SCHED_TO_DB_MODE[mode], allow_api=False
    )
    return mode, minutes


def _stop_to_schema(
    stop: itinerary_planner._Stop,
    position: int,
    is_new: bool = True,
    item_id: uuid.UUID | None = None,
) -> ItineraryStop:
    poi = stop.poi
    return ItineraryStop(
        position=position,
        poi_id=poi.id,
        name=poi.name,
        address=poi.address,
        lat=poi.lat,
        lng=poi.lng,
        travel_category=poi.travel_category,
        rating=poi.rating,
        photo_reference=poi.photo_reference,
        google_maps_url=_google_maps_url(poi),
        arrival_time=stop.arrival.strftime("%H:%M"),
        departure_time=stop.departure.strftime("%H:%M"),
        transport_from_previous=stop.transport,
        travel_minutes_from_previous=round(stop.travel_minutes, 1) if stop.transport else None,
        visit_mode=stop.visit_mode,
        visit_duration_minutes=stop.visit_duration_minutes,
        visit_note=stop.visit_note,
        is_new_suggestion=is_new,
        item_id=item_id,
    )


@router.post("/generate", response_model=ItineraryOut, status_code=status.HTTP_201_CREATED)
async def generate_itinerary(
    payload: GenerateItineraryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # --- Derive schedule from travel mode ---
    start_time_str, end_time_str = _schedule_for_mode(payload.travel_mode)

    # --- Fetch city ---
    city_result = await db.execute(
        select(City).where(City.name.ilike(payload.city))
    )
    city = city_result.scalar_one_or_none()
    if city is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="City not found.")

    # --- Fetch classified POIs (shared with the evaluation harness) ---
    candidate_places = await fetch_candidate_pois(
        db, city.id, travel_with_children=payload.travel_mode == TravelMode.family
    )
    logger.info(
        "POIs after all filters: %d (popularity + type blacklist + tourism filter applied)",
        len(candidate_places),
    )

    if len(candidate_places) < payload.num_days * 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Not enough POIs for this city.",
        )

    # --- Fetch user preferences ---
    pref_result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == current_user.id)
    )
    user_prefs = pref_result.scalar_one_or_none()
    if user_prefs is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Complete onboarding before generating an itinerary.",
        )

    logger.info(
        "Generating itinerary: user_id=%s city=%s num_days=%d pois=%d",
        current_user.id, city.name, payload.num_days, len(candidate_places),
    )

    # --- Fetch user POI history for novelty-aware planning ---
    confirmed_visited_ids, previously_suggested_ids = await get_user_poi_history(
        session=db,
        user_id=current_user.id,
        city_id=city.id,
    )
    logger.info(
        "User %s history for %s: %d confirmed, %d suggested",
        current_user.id, city.name,
        len(confirmed_visited_ids), len(previously_suggested_ids),
    )

    # --- Resolve optional depot (start/end location) ---
    start_lat = start_lng = end_lat = end_lng = None
    if payload.start_location:
        coords = await _geocode_location(payload.start_location, city.name)
        if coords is not None:
            start_lat, start_lng = coords
        else:
            logger.warning("Could not geocode start_location %r — using city center", payload.start_location)
    if payload.end_location:
        coords = await _geocode_location(payload.end_location, city.name)
        if coords is not None:
            end_lat, end_lng = coords
        else:
            logger.warning("Could not geocode end_location %r — using start/center", payload.end_location)

    # --- Plan ---
    all_days, warnings = await itinerary_planner.generate(
        user_prefs=user_prefs,
        num_days=payload.num_days,
        start_time_str=start_time_str,
        end_time_str=end_time_str,
        candidate_places=list(candidate_places),
        city_lat=city.lat,
        city_lng=city.lng,
        confirmed_visited_ids=confirmed_visited_ids,
        previously_suggested_ids=previously_suggested_ids,
        travel_with_children=payload.travel_mode == TravelMode.family,
        age_range=current_user.age_range,
        travel_mode=payload.travel_mode.value,
        session=db,
        solver=payload.solver,
        start_lat=start_lat,
        start_lng=start_lng,
        end_lat=end_lat,
        end_lng=end_lng,
    )

    # --- Persist ---
    itinerary = Itinerary(
        user_id=current_user.id,
        city=city.name,
    )
    db.add(itinerary)
    # Maps (day_number, position) -> persisted item id, so the response can expose
    # item_id for in-itinerary edits (replace/remove) right after generation.
    item_ids: dict[tuple[int, int], uuid.UUID] = {}
    try:
        await db.flush()
        for day_num, day_stops in enumerate(all_days, start=1):
            for pos, stop in enumerate(day_stops, start=1):
                item = ItineraryItem(
                    itinerary_id=itinerary.id,
                    place_id=stop.poi.id,
                    day_number=day_num,
                    position=pos,
                    arrival_time=stop.arrival.time(),
                    departure_time=stop.departure.time(),
                )
                db.add(item)
                item_ids[(day_num, pos)] = item.id
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to save itinerary: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save itinerary.",
        )

    # --- Build response ---
    seen_ids = confirmed_visited_ids | previously_suggested_ids
    days_out: list[ItineraryDayOut] = []
    for day_idx, day_stops in enumerate(all_days):
        stops_out = [
            _stop_to_schema(
                s, pos,
                is_new=s.poi.id not in seen_ids,
                item_id=item_ids.get((day_idx + 1, pos)),
            )
            for pos, s in enumerate(day_stops, start=1)
        ]
        days_out.append(ItineraryDayOut(day_number=day_idx + 1, stops=stops_out))

    return ItineraryOut(
        itinerary_id=itinerary.id,
        city=city.name,
        num_days=payload.num_days,
        warnings=warnings,
        days=days_out,
    )


@router.get("", response_model=list[ItinerarySummary])
async def list_itineraries(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """All itineraries generated by the current user, newest first.

    Returns a lightweight summary per itinerary (no stops); the full itinerary
    is fetched on demand via GET /itineraries/{id}.
    """
    result = await db.execute(
        select(Itinerary)
        .options(selectinload(Itinerary.items))
        .where(Itinerary.user_id == current_user.id)
        .order_by(Itinerary.created_at.desc())
    )
    itineraries = result.scalars().all()

    summaries: list[ItinerarySummary] = []
    for it in itineraries:
        num_days = max((item.day_number for item in it.items), default=0)
        summaries.append(ItinerarySummary(
            itinerary_id=it.id,
            city=it.city,
            num_days=num_days,
            created_at=it.created_at,
            num_stops=len(it.items),
            num_visited=sum(1 for item in it.items if item.visited_at is not None),
        ))
    return summaries


@router.get("/{itinerary_id}", response_model=ItineraryOut)
async def get_itinerary(
    itinerary_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Itinerary)
        .options(selectinload(Itinerary.items).selectinload(ItineraryItem.place))
        .where(
            Itinerary.id == itinerary_id,
            Itinerary.user_id == current_user.id,
        )
    )
    itinerary = result.scalar_one_or_none()
    if itinerary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary not found.")

    # Group items by day
    days_map: dict[int, list[ItineraryItem]] = {}
    for item in itinerary.items:
        days_map.setdefault(item.day_number, []).append(item)

    days_out: list[ItineraryDayOut] = []
    for day_num in sorted(days_map.keys()):
        items = days_map[day_num]
        stops_out: list[ItineraryStop] = []
        prev_poi: object | None = None

        for pos, item in enumerate(items, start=1):
            poi = item.place
            if prev_poi is not None:
                transport, travel_min = await _read_travel_time(db, prev_poi, poi)
            else:
                transport, travel_min = None, 0.0

            if item.arrival_time and item.departure_time:
                _base = datetime.combine(day_date, item.arrival_time)
                _end = datetime.combine(day_date, item.departure_time)
                visit_dur = max(0, int((_end - _base).total_seconds() / 60))
            else:
                visit_dur = 0

            vm, _vd, vn = itinerary_planner.resolve_visit_mode(poi, 1.0)
            stops_out.append(ItineraryStop(
                position=pos,
                poi_id=poi.id,
                name=poi.name,
                address=poi.address,
                lat=poi.lat,
                lng=poi.lng,
                travel_category=poi.travel_category,
                rating=poi.rating,
                photo_reference=poi.photo_reference,
                google_maps_url=_google_maps_url(poi),
                arrival_time=item.arrival_time.strftime("%H:%M") if item.arrival_time else None,
                departure_time=item.departure_time.strftime("%H:%M") if item.departure_time else None,
                transport_from_previous=transport,
                travel_minutes_from_previous=round(travel_min, 1) if transport else None,
                visit_duration_minutes=visit_dur,
                visit_mode=vm,
                visit_note=vn,
                item_id=item.id,
            ))
            prev_poi = poi

        days_out.append(ItineraryDayOut(day_number=day_num, stops=stops_out))

    num_days = max(days_map.keys(), default=0)
    return ItineraryOut(
        itinerary_id=itinerary.id,
        city=itinerary.city,
        num_days=num_days,
        days=days_out,
    )


@router.post(
    "/{itinerary_id}/items/{item_id}/visited",
    response_model=CheckInResponse,
    status_code=status.HTTP_200_OK,
)
async def check_in(
    itinerary_id: uuid.UUID,
    item_id: uuid.UUID,
    body: CheckInRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ItineraryItem)
        .options(selectinload(ItineraryItem.place))
        .join(Itinerary, ItineraryItem.itinerary_id == Itinerary.id)
        .where(
            ItineraryItem.id == item_id,
            ItineraryItem.itinerary_id == itinerary_id,
            Itinerary.user_id == current_user.id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary item not found.")

    item.visited_at = body.visited_at or datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(item)
    await db.commit()
    await db.refresh(item)

    return CheckInResponse(
        item_id=item.id,
        poi_id=item.place_id,
        poi_name=item.place.name,
        visited_at=item.visited_at,
    )


@router.delete(
    "/{itinerary_id}/items/{item_id}/visited",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def undo_check_in(
    itinerary_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ItineraryItem)
        .join(Itinerary, ItineraryItem.itinerary_id == Itinerary.id)
        .where(
            ItineraryItem.id == item_id,
            ItineraryItem.itinerary_id == itinerary_id,
            Itinerary.user_id == current_user.id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary item not found.")

    item.visited_at = None
    db.add(item)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────────
# In-itinerary editing: swap / remove a suggested place
# ─────────────────────────────────────────────

async def _load_owned_item(db, itinerary_id, item_id, user_id) -> ItineraryItem:
    """Fetch an itinerary item (with its place) verifying it belongs to the user."""
    result = await db.execute(
        select(ItineraryItem)
        .options(selectinload(ItineraryItem.place))
        .join(Itinerary, ItineraryItem.itinerary_id == Itinerary.id)
        .where(
            ItineraryItem.id == item_id,
            ItineraryItem.itinerary_id == itinerary_id,
            Itinerary.user_id == user_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary item not found.")
    return item


async def _load_user_prefs(db, user_id) -> UserPreference:
    pref_result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == user_id)
    )
    pref = pref_result.scalar_one_or_none()
    if pref is None:
        pref = UserPreference(user_id=user_id)
        db.add(pref)
    return pref


@router.get(
    "/{itinerary_id}/items/{item_id}/alternatives",
    response_model=list[PoiSuggestion],
)
async def get_stop_alternatives(
    itinerary_id: uuid.UUID,
    item_id: uuid.UUID,
    limit: int = 12,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ranked alternative POIs for a stop, to let the user swap a suggestion.

    Candidates are the same eligible POIs used for generation, minus everything
    already in this itinerary, ranked by cosine similarity to the user's
    preference vector with a boost for matching the slot's travel category.
    """
    item = await _load_owned_item(db, itinerary_id, item_id, current_user.id)

    itinerary = await db.get(Itinerary, itinerary_id)
    city_result = await db.execute(select(City).where(City.name.ilike(itinerary.city)))
    city = city_result.scalar_one_or_none()
    if city is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="City not found.")

    user_prefs = await _load_user_prefs(db, current_user.id)

    candidates = await fetch_candidate_pois(
        db, city.id, travel_with_children=current_user.travel_with_children
    )

    # Exclude POIs already present anywhere in this itinerary.
    used_result = await db.execute(
        select(ItineraryItem.place_id).where(ItineraryItem.itinerary_id == itinerary_id)
    )
    used_ids = set(used_result.scalars().all())

    ranked = recommendation_service.rank_pois(user_prefs, candidates)
    current_category = item.place.travel_category
    # Same-category alternatives first, then by similarity.
    ranked.sort(
        key=lambda ps: (ps[0].travel_category == current_category, ps[1]),
        reverse=True,
    )

    out: list[PoiSuggestion] = []
    for poi, sim in ranked:
        if poi.id in used_ids:
            continue
        out.append(PoiSuggestion(
            poi_id=poi.id,
            name=poi.name,
            address=poi.address,
            lat=poi.lat,
            lng=poi.lng,
            travel_category=poi.travel_category,
            rating=poi.rating,
            photo_reference=poi.photo_reference,
            google_maps_url=_google_maps_url(poi),
            similarity=round(sim, 4),
        ))
        if len(out) >= limit:
            break
    return out


@router.put(
    "/{itinerary_id}/items/{item_id}",
    response_model=CheckInResponse,
)
async def replace_stop(
    itinerary_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ReplaceStopRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Swap the POI in a stop for a user-chosen alternative.

    Keeps the slot's time window; travel times are recomputed live on read. The
    edit is implicit feedback: the profile moves toward the chosen POI and away
    from the replaced one.
    """
    item = await _load_owned_item(db, itinerary_id, item_id, current_user.id)
    old_poi = item.place

    new_poi = await db.get(Poi, body.poi_id)
    if new_poi is None or new_poi.city_id != old_poi.city_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid replacement POI.")

    # Reject duplicates already in the itinerary.
    dup_result = await db.execute(
        select(ItineraryItem).where(
            ItineraryItem.itinerary_id == itinerary_id,
            ItineraryItem.place_id == body.poi_id,
            ItineraryItem.id != item_id,
        )
    )
    if dup_result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That place is already in your itinerary.")

    item.place_id = new_poi.id
    item.visited_at = None  # a swapped-in place hasn't been visited

    user_prefs = await _load_user_prefs(db, current_user.id)
    recommendation_service.nudge_user_preferences(user_prefs, reward=new_poi, penalty=old_poi)

    db.add_all([item, user_prefs])
    await db.commit()

    return CheckInResponse(
        item_id=item.id,
        poi_id=new_poi.id,
        poi_name=new_poi.name,
        visited_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )


@router.delete(
    "/{itinerary_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_stop(
    itinerary_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a suggested stop and shift the rest of the day up by one position.

    Removing a place is implicit negative feedback: the profile moves away from
    that POI's features.
    """
    item = await _load_owned_item(db, itinerary_id, item_id, current_user.id)
    removed_poi = item.place
    day_number = item.day_number
    position = item.position

    user_prefs = await _load_user_prefs(db, current_user.id)
    recommendation_service.nudge_user_preferences(user_prefs, penalty=removed_poi)

    await db.delete(item)

    # Close the gap so positions stay contiguous within the day.
    later_result = await db.execute(
        select(ItineraryItem).where(
            ItineraryItem.itinerary_id == itinerary_id,
            ItineraryItem.day_number == day_number,
            ItineraryItem.position > position,
        )
    )
    for later in later_result.scalars().all():
        later.position -= 1
        db.add(later)

    db.add(user_prefs)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
