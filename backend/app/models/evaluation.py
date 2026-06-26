"""Evaluation tables (see docs/evaluation-harness-spec.md §5).

Frozen snapshots of generated itineraries + pre-built human-eval pairs + human
votes. Snapshots are stored as JSON so the dashboard renders exactly what was
generated, immune to later changes in the live POI data.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EvaluationItinerary(Base):
    __tablename__ = "evaluation_itineraries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    profile_key: Mapped[str] = mapped_column(String(50), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    num_days: Mapped[int] = mapped_column(Integer, nullable=False)
    solver: Mapped[str] = mapped_column(String(10), nullable=False)  # "greedy" | "toptw"
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)      # ItineraryOut-shaped snapshot
    candidates_json: Mapped[list] = mapped_column(JSONB, nullable=False)   # [{poi_id, name, prize, included, ...}]
    metrics_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class EvaluationPair(Base):
    __tablename__ = "evaluation_pairs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    itinerary_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_itineraries.id", ondelete="CASCADE"), nullable=False
    )
    pair_type: Mapped[str] = mapped_column(String(20), nullable=False)  # substitutable|famous_skipped|margin
    poi_a_id: Mapped[uuid.UUID] = mapped_column(nullable=False)  # included in the trip
    poi_b_id: Mapped[uuid.UUID] = mapped_column(nullable=False)  # discarded / not seen
    poi_a_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    poi_b_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    profile_key: Mapped[str] = mapped_column(String(50), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class EvaluationRating(Base):
    __tablename__ = "evaluation_ratings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    pair_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_pairs.id", ondelete="CASCADE"), nullable=False
    )
    evaluator_id: Mapped[str] = mapped_column(String(100), nullable=False)
    choice: Mapped[str] = mapped_column(String(10), nullable=False)  # "a" | "b" | "equal"
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class EvaluationLikert(Base):
    __tablename__ = "evaluation_likert"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    itinerary_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_itineraries.id", ondelete="CASCADE"), nullable=False
    )
    evaluator_id: Mapped[str] = mapped_column(String(100), nullable=False)
    realism: Mapped[int] = mapped_column(Integer, nullable=False)        # 1-5
    completeness: Mapped[int] = mapped_column(Integer, nullable=False)   # 1-5
    profile_fit: Mapped[int] = mapped_column(Integer, nullable=False)    # 1-5
    overall: Mapped[int] = mapped_column(Integer, nullable=False)        # 1-5
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
