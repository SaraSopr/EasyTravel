from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.poi import Poi


class Itinerary(Base):
    __tablename__ = "itineraries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    items: Mapped[list["ItineraryItem"]] = relationship(
        back_populates="itinerary",
        order_by="ItineraryItem.day_number, ItineraryItem.position",
    )


class ItineraryItem(Base):
    __tablename__ = "itinerary_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    itinerary_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("itineraries.id"), nullable=False
    )
    place_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pois.id"), nullable=False
    )
    day_number: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    arrival_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    departure_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    visited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)

    itinerary: Mapped["Itinerary"] = relationship(back_populates="items")
    place: Mapped["Poi"] = relationship()
