from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class PlaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    travel_category: str | None
    address: str | None
    lat: float
    lng: float
    rating: float | None
    website: str | None
    photo_reference: str | None
    confidence: str | None


class PlaceOutWithScore(PlaceOut):
    score: float
