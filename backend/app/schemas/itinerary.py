from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TravelMode(str, Enum):
    solo = "solo"
    couple = "couple"
    friends = "friends"
    family = "family"


class GenerateItineraryRequest(BaseModel):
    city: str
    num_days: int = Field(ge=1, le=14)
    travel_mode: TravelMode = TravelMode.solo
    # Solver selection (see docs/toptw-itinerary-solver-spec.md). None → use the
    # server default (settings.itinerary_solver). Lets the same user/city generate
    # both arms ("greedy" baseline vs "toptw") for the thesis evaluation.
    solver: Literal["greedy", "toptw"] | None = None
    # Optional depot. Address or hotel name; geocoded server-side.
    #   start_location None → city center
    #   end_location   None → same as start_location
    start_location: str | None = None
    end_location: str | None = None


class ItineraryStop(BaseModel):
    position: int
    poi_id: uuid.UUID
    name: str
    address: str | None
    lat: float
    lng: float
    travel_category: str | None
    rating: float | None
    photo_reference: str | None
    google_maps_url: str | None            # https://www.google.com/maps/place/?q=place_id:...
    arrival_time: str | None               # "HH:MM"
    departure_time: str | None             # "HH:MM"
    transport_from_previous: str | None    # "walking"|"transit"|"taxi"|None for first stop
    travel_minutes_from_previous: float | None
    visit_mode: Literal["indoor", "outdoor"] = "indoor"  # "indoor"=full visit, "outdoor"=exterior only
    visit_duration_minutes: int = 0                       # actual visit time used for scheduling
    visit_note: str | None = None                         # e.g. "Suggested as an exterior visit"
    is_new_suggestion: bool = True                        # False if POI was already suggested/visited
    item_id: uuid.UUID | None = None                      # persisted ItineraryItem id (None for unsaved previews)


class PoiSuggestion(BaseModel):
    """A candidate POI offered as an alternative for an itinerary stop."""
    poi_id: uuid.UUID
    name: str
    address: str | None
    lat: float
    lng: float
    travel_category: str | None
    rating: float | None
    photo_reference: str | None
    google_maps_url: str | None
    similarity: float                      # cosine similarity to the user's preference vector


class ReplaceStopRequest(BaseModel):
    poi_id: uuid.UUID                      # the chosen alternative POI to put in this slot


class ItineraryDayOut(BaseModel):
    day_number: int
    stops: list[ItineraryStop]


class ItineraryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    itinerary_id: uuid.UUID
    city: str
    num_days: int
    warnings: list[str] = []
    days: list[ItineraryDayOut]


class ItinerarySummary(BaseModel):
    """Lightweight itinerary entry for the user's saved-itineraries list."""
    itinerary_id: uuid.UUID
    city: str
    num_days: int
    created_at: datetime
    num_stops: int       # total saved stops across all days
    num_visited: int     # stops the user has checked in


class CheckInRequest(BaseModel):
    visited_at: datetime | None = None  # None → use current UTC datetime


class CheckInResponse(BaseModel):
    item_id: uuid.UUID
    poi_id: uuid.UUID
    poi_name: str
    visited_at: datetime
