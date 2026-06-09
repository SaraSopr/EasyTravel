from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import and_, or_, select
from app.services.itinerary_planner import EXCLUDED_TYPES, FOOD_SERVICE_TYPES, HIGH_POPULARITY_TYPES

_EXCLUDED_TYPES_LIST = list(EXCLUDED_TYPES)
_HIGH_POPULARITY_TYPES_LIST = list(HIGH_POPULARITY_TYPES)
_FOOD_SERVICE_TYPES_LIST = list(FOOD_SERVICE_TYPES)
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
    TravelMode,
)
from app.services import itinerary_planner
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


def _stop_to_schema(
    stop: itinerary_planner._Stop,
    position: int,
    is_new: bool = True,
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

    # --- Fetch classified POIs ---
    pois_result = await db.execute(
        select(Poi).where(
            Poi.city_id == city.id,
            Poi.business_status != "CLOSED_PERMANENTLY",
            or_(Poi.user_ratings_total >= 200, Poi.user_ratings_total.is_(None)),
            Poi.rating >= 3.5,
            # Either: a classified touristic activity POI, OR a food-type POI.
            # Food POIs (restaurants, cafes, etc.) are correctly marked is_touristic=False
            # by tourism validation (they're not sightseeing attractions), so the pipeline
            # skips classifying them. We include them separately as meal stops.
            or_(
                # Activity POIs: must be classified and confirmed touristic
                and_(
                    Poi.confidence != "failed",
                    Poi.nature.is_not(None),
                    Poi.classified_at.is_not(None),
                    or_(Poi.is_touristic.is_(None), Poi.is_touristic == True),  # noqa: E712
                    # Exclude POIs where ANY type is in the non-touristic blacklist.
                    or_(
                        Poi.types.is_(None),
                        Poi.types == [],
                        ~Poi.types.overlap(_EXCLUDED_TYPES_LIST),
                    ),
                    # High-popularity types (stadium, race_track) require ≥5000 ratings.
                    or_(
                        Poi.types.is_(None),
                        Poi.types == [],
                        ~Poi.types.overlap(_HIGH_POPULARITY_TYPES_LIST),
                        Poi.user_ratings_total >= 5000,
                    ),
                ),
                # Food POIs: notable restaurants validated as touristic by the tourism
                # validator. is_touristic=False POIs (chains, fast food) are excluded.
                # Legacy unvalidated POIs (is_touristic IS NULL) are kept as fallback.
                and_(
                    Poi.types.is_not(None),
                    Poi.types.overlap(_FOOD_SERVICE_TYPES_LIST),
                    or_(Poi.is_touristic.is_(None), Poi.is_touristic == True),  # noqa: E712
                ),
            ),
            # Family filter: when traveling with children, exclude POIs explicitly
            # marked as not suitable for children. Legacy/unvalidated POIs (NULL) are kept.
            *(
                [or_(
                    Poi.suitable_for_children.is_(None),
                    Poi.suitable_for_children == True,  # noqa: E712
                )]
                if payload.travel_mode == TravelMode.family else []
            ),
        )
    )
    candidate_places = pois_result.scalars().all()
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
    )

    # --- Persist ---
    today = date.today()
    end_date = today + timedelta(days=payload.num_days - 1)
    itinerary = Itinerary(
        user_id=current_user.id,
        city=city.name,
        start_date=today,
        end_date=end_date,
    )
    db.add(itinerary)
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
        day_date = today + timedelta(days=day_idx)
        stops_out = [
            _stop_to_schema(s, pos, is_new=s.poi.id not in seen_ids)
            for pos, s in enumerate(day_stops, start=1)
        ]
        days_out.append(ItineraryDayOut(day_number=day_idx + 1, date=day_date, stops=stops_out))

    return ItineraryOut(
        itinerary_id=itinerary.id,
        city=city.name,
        start_date=today,
        end_date=end_date,
        num_days=payload.num_days,
        warnings=warnings,
        days=days_out,
    )


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
        day_date = itinerary.start_date + timedelta(days=day_num - 1)
        items = days_map[day_num]
        stops_out: list[ItineraryStop] = []
        prev_lat: float | None = None
        prev_lng: float | None = None

        for pos, item in enumerate(items, start=1):
            poi = item.place
            if prev_lat is not None and prev_lng is not None:
                dist = haversine_m(prev_lat, prev_lng, poi.lat, poi.lng)
                transport, travel_min = select_transport(dist)
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
            ))
            prev_lat, prev_lng = poi.lat, poi.lng

        days_out.append(ItineraryDayOut(day_number=day_num, date=day_date, stops=stops_out))

    num_days = (itinerary.end_date - itinerary.start_date).days + 1
    return ItineraryOut(
        itinerary_id=itinerary.id,
        city=itinerary.city,
        start_date=itinerary.start_date,
        end_date=itinerary.end_date,
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
