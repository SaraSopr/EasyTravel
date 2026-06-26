from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.city import City


class Poi(Base):
    __tablename__ = "pois"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    city_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cities.id"), nullable=False)
    google_place_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    types: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    # Single canonical type from Places API (New); cleaner signal than the flat `types` array.
    primary_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Short editorial description from Places API (New) `editorialSummary`; fed to the LLM stages.
    editorial_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_ratings_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    business_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # OPERATIONAL | CLOSED_TEMPORARILY | CLOSED_PERMANENTLY (from Google Places)
    opening_hours: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    photo_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Tourism validation fields
    is_touristic: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    # None = not yet validated, True = worth visiting, False = not a tourist attraction
    tourism_visit_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # "indoor" | "outdoor" | "both" | None
    tourism_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Suggested visit duration; overrides planner lookup table when set
    suitable_for_children: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # None = not yet determined, True = child-friendly, False = not recommended for children
    tourism_validated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    travel_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_indoor_visitable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Explicit feature vector (same order as user_preferences)
    nature: Mapped[float | None] = mapped_column(Float, nullable=True)
    culture: Mapped[float | None] = mapped_column(Float, nullable=True)
    food: Mapped[float | None] = mapped_column(Float, nullable=True)
    adventure: Mapped[float | None] = mapped_column(Float, nullable=True)
    nightlife: Mapped[float | None] = mapped_column(Float, nullable=True)
    relax: Mapped[float | None] = mapped_column(Float, nullable=True)
    family_friendly: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)  # high|medium|failed
    classified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    city: Mapped["City"] = relationship(back_populates="pois")
