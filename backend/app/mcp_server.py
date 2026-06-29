"""EasyTravel MCP server (stdio).

Exposes the core domain capabilities — city/POI lookup, preference-based
recommendations and itinerary planning — as MCP tools, reusing the same service
layer and database session as the FastAPI app. There is no authenticated user in
an MCP session, so the user-specific pieces (preference vector, POI history) are
passed in as tool arguments instead of being read from a logged-in account.

Run it directly for an MCP client (Claude Desktop / Claude Code):

    python -m app.mcp_server

or register it (see `claude_desktop_config` snippet in the project docs).
"""
from __future__ import annotations

import uuid

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from app.constants import FEATURE_NAMES
from app.database import AsyncSessionLocal
from app.models.city import City
from app.models.poi import Poi
from app.schemas.itinerary import TravelMode
from app.schemas.place import PlaceOut
from app.schemas.user import PreferenceVector
from app.services import itinerary_planner
from app.services import recommendation as recommendation_service
from app.services.candidate_query import fetch_candidate_pois

mcp = FastMCP("EasyTravel")


def _prefs_from_dict(preferences: dict[str, float] | None) -> PreferenceVector:
    """Build a PreferenceVector from a partial {feature: 0..1} dict.

    Missing features default to 0.5 (neutral) so callers can pass only the
    features they care about. Unknown keys are ignored.
    """
    preferences = preferences or {}
    return PreferenceVector(
        **{f: float(preferences.get(f, 0.5)) for f in FEATURE_NAMES}
    )


def _place_dict(poi: Poi, score: float | None = None) -> dict:
    data = PlaceOut.model_validate(poi).model_dump(mode="json")
    if score is not None:
        data["score"] = round(score, 4)
    return data


@mcp.tool()
async def list_cities() -> list[dict]:
    """List the cities available for recommendations and itineraries."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(City).order_by(City.name))
        return [
            {"name": c.name, "country": c.country, "lat": c.lat, "lng": c.lng}
            for c in result.scalars().all()
        ]


@mcp.tool()
async def list_places(city: str, limit: int = 50, offset: int = 0) -> list[dict]:
    """List points of interest (POIs) in a city.

    Args:
        city: City name (must match a city from `list_cities`).
        limit: Max results (1-200).
        offset: Pagination offset.
    """
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Poi).join(City).where(City.name == city).offset(offset).limit(limit)
        )
        return [_place_dict(p) for p in result.scalars().all()]


@mcp.tool()
async def get_place(place_id: str) -> dict:
    """Get a single POI by its UUID. Raises if not found."""
    try:
        pid = uuid.UUID(place_id)
    except ValueError as exc:
        raise ValueError(f"Invalid place_id (not a UUID): {place_id!r}") from exc
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Poi).where(Poi.id == pid))
        poi = result.scalar_one_or_none()
        if poi is None:
            raise ValueError(f"Place not found: {place_id}")
        return _place_dict(poi)


@mcp.tool()
async def recommend_places(
    city: str,
    preferences: dict[str, float] | None = None,
    limit: int = 20,
) -> list[dict]:
    """Rank a city's POIs by cosine similarity to a preference vector.

    Args:
        city: City name (from `list_cities`).
        preferences: Map of feature -> value in [0, 1]. Features:
            nature, culture, food, adventure, nightlife, relax, family_friendly.
            Missing features default to 0.5 (neutral).
        limit: Max results (1-200).
    """
    limit = max(1, min(limit, 200))
    user_prefs = _prefs_from_dict(preferences)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Poi).join(City).where(City.name == city))
        pois = list(result.scalars().all())
    ranked = recommendation_service.rank_pois(user_prefs, pois)
    ranked.sort(key=lambda x: x[1], reverse=True)
    return [_place_dict(poi, score) for poi, score in ranked[:limit]]


@mcp.tool()
async def generate_itinerary(
    city: str,
    num_days: int,
    travel_mode: str = "solo",
    preferences: dict[str, float] | None = None,
    start_location: str | None = None,
    end_location: str | None = None,
    solver: str | None = None,
    age_range: str | None = None,
) -> dict:
    """Plan a multi-day itinerary for a city (preview — not persisted).

    Args:
        city: City name (from `list_cities`).
        num_days: Number of days (1-14).
        travel_mode: One of solo, couple, friends, family. Drives the daily
            schedule and child-friendly filtering.
        preferences: Feature -> value in [0, 1] (see `recommend_places`).
        start_location: Optional address/hotel name; geocoded to a depot.
            None -> city center.
        end_location: Optional end address; None -> same as start.
        solver: "greedy" or "toptw"; None -> server default.
        age_range: Optional traveller age bucket (e.g. "26-35").

    Returns a dict with `city`, `num_days`, `warnings` and `days` (each day has a
    `day_number` and ordered `stops`).
    """
    if not 1 <= num_days <= 14:
        raise ValueError("num_days must be between 1 and 14")
    try:
        mode = TravelMode(travel_mode)
    except ValueError as exc:
        raise ValueError(
            f"Invalid travel_mode {travel_mode!r}; expected one of "
            f"{[m.value for m in TravelMode]}"
        ) from exc

    # Imported lazily: pulls in the itineraries router (FastAPI deps) only when a
    # plan is actually requested.
    from app.routers.itineraries import (
        _geocode_location,
        _schedule_for_mode,
        _stop_to_schema,
    )

    start_time_str, end_time_str = _schedule_for_mode(mode)
    user_prefs = _prefs_from_dict(preferences)

    async with AsyncSessionLocal() as db:
        city_row = (
            await db.execute(select(City).where(City.name.ilike(city)))
        ).scalar_one_or_none()
        if city_row is None:
            raise ValueError(f"City not found: {city}")

        travel_with_children = mode == TravelMode.family
        candidates = await fetch_candidate_pois(
            db, city_row.id, travel_with_children=travel_with_children
        )
        if len(candidates) < num_days * 3:
            raise ValueError(
                f"Not enough POIs for {city}: {len(candidates)} candidates for "
                f"{num_days} day(s)."
            )

        start_lat = start_lng = end_lat = end_lng = None
        if start_location:
            coords = await _geocode_location(start_location, city_row.name)
            if coords is not None:
                start_lat, start_lng = coords
        if end_location:
            coords = await _geocode_location(end_location, city_row.name)
            if coords is not None:
                end_lat, end_lng = coords

        all_days, warnings = await itinerary_planner.generate(
            user_prefs=user_prefs,
            num_days=num_days,
            start_time_str=start_time_str,
            end_time_str=end_time_str,
            candidate_places=list(candidates),
            city_lat=city_row.lat,
            city_lng=city_row.lng,
            travel_with_children=travel_with_children,
            age_range=age_range,
            travel_mode=mode.value,
            session=db,
            solver=solver,
            start_lat=start_lat,
            start_lng=start_lng,
            end_lat=end_lat,
            end_lng=end_lng,
        )

    days_out = [
        {
            "day_number": day_idx + 1,
            "stops": [
                _stop_to_schema(s, pos).model_dump(mode="json")
                for pos, s in enumerate(day_stops, start=1)
            ],
        }
        for day_idx, day_stops in enumerate(all_days)
    ]
    return {
        "city": city_row.name,
        "num_days": num_days,
        "warnings": warnings,
        "days": days_out,
    }


if __name__ == "__main__":
    mcp.run()
