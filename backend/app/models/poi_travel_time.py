from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PoiTravelTime(Base):
    """Persistent cache of real road travel times between two POIs for a given mode.

    POI coordinates are static, so the A→B time for a mode never changes: it is
    computed once (via Google Routes API or an haversine fallback) and stored here.
    See docs/routes-api-travel-times-spec.md.
    """

    __tablename__ = "poi_travel_times"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    origin_poi_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pois.id", ondelete="CASCADE"), nullable=False
    )
    dest_poi_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pois.id", ondelete="CASCADE"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    # "walking" | "transit" | "driving"
    seconds: Mapped[int] = mapped_column(Integer, nullable=False)  # real duration
    meters: Mapped[int] = mapped_column(Integer, nullable=False)   # real on-road distance
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="routes_api")
    # "routes_api" | "haversine_fallback"
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("origin_poi_id", "dest_poi_id", "mode", name="uq_travel_origin_dest_mode"),
        Index("ix_poi_travel_times_origin", "origin_poi_id"),
    )
