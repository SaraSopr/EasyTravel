from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class CityExperience(Base):
    __tablename__ = "city_experiences"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    city: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    # Perplexity fields
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    slot: Mapped[str | None] = mapped_column(String(50), nullable=True)
    why_locals_love_it: Mapped[str | None] = mapped_column(Text, nullable=True)
    effort_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    time_of_day: Mapped[str | None] = mapped_column(String(20), nullable=True)
    price_range: Mapped[str | None] = mapped_column(String(20), nullable=True)
    verifiable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    search_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    feature_vector: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Google Places fields
    google_place_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class UserExperienceChoice(Base):
    __tablename__ = "user_experience_choices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    experience_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("city_experiences.id", ondelete="SET NULL"), nullable=True
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="experience_choices")
