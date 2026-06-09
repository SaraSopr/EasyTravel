from __future__ import annotations

import uuid
from datetime import date, datetime
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


class ItineraryDayOut(BaseModel):
    day_number: int
    date: date
    stops: list[ItineraryStop]


class ItineraryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    itinerary_id: uuid.UUID
    city: str
    start_date: date
    end_date: date
    num_days: int
    warnings: list[str] = []
    days: list[ItineraryDayOut]


class CheckInRequest(BaseModel):
    visited_at: datetime | None = None  # None → use current UTC datetime


class CheckInResponse(BaseModel):
    item_id: uuid.UUID
    poi_id: uuid.UUID
    poi_name: str
    visited_at: datetime
