from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PoiTourismValidationLog(Base):
    __tablename__ = "poi_tourism_validation_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    poi_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pois.id"), nullable=False)
    poi_name: Mapped[str] = mapped_column(String(255), nullable=False)
    poi_types: Mapped[str | None] = mapped_column(String(500))
    # comma-separated Google types for easy querying
    poi_rating: Mapped[float | None] = mapped_column(Float)
    poi_ratings_total: Mapped[int | None] = mapped_column(Integer)
    city_name: Mapped[str | None] = mapped_column(String(100))
    pipeline_run_id: Mapped[str | None] = mapped_column(String(100))

    # LLM1 decision (always runs)
    llm1_is_touristic: Mapped[bool | None] = mapped_column(Boolean)
    llm1_visit_type: Mapped[str | None] = mapped_column(String(10))
    llm1_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    llm1_confidence: Mapped[str | None] = mapped_column(String(10))
    # "high" | "low"
    llm1_reasoning: Mapped[str | None] = mapped_column(Text)

    # LLM2 decision (only runs when LLM1 confidence = "low")
    llm2_is_touristic: Mapped[bool | None] = mapped_column(Boolean)
    llm2_visit_type: Mapped[str | None] = mapped_column(String(10))
    llm2_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    llm2_reasoning: Mapped[str | None] = mapped_column(Text)
    llm2_was_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    # True if LLM2 was actually called

    # LLM1 suitable_for_children
    llm1_suitable_for_children: Mapped[bool | None] = mapped_column(Boolean)
    # LLM2 suitable_for_children (only when LLM2 was called)
    llm2_suitable_for_children: Mapped[bool | None] = mapped_column(Boolean)

    # Final decision
    final_is_touristic: Mapped[bool | None] = mapped_column(Boolean)
    final_visit_type: Mapped[str | None] = mapped_column(String(10))
    final_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    final_suitable_for_children: Mapped[bool | None] = mapped_column(Boolean)
    decision_source: Mapped[str | None] = mapped_column(String(20))
    # "llm1" | "llm2" | "disagreement" | "llm1_fallback"

    validated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
