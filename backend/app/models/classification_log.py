from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PoiClassificationLog(Base):
    __tablename__ = "poi_classification_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    poi_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pois.id"), nullable=False)
    poi_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # LLM1 output
    llm1_category: Mapped[str | None] = mapped_column(String(50))
    llm1_vector: Mapped[list | None] = mapped_column(JSONB)
    llm1_is_indoor: Mapped[bool | None] = mapped_column(Boolean)
    llm1_reasoning: Mapped[str | None] = mapped_column(Text)

    # LLM2 output
    llm2_category: Mapped[str | None] = mapped_column(String(50))
    llm2_vector: Mapped[list | None] = mapped_column(JSONB)
    llm2_is_indoor: Mapped[bool | None] = mapped_column(Boolean)
    llm2_reasoning: Mapped[str | None] = mapped_column(Text)

    # LLM3 arbitration output
    llm3_final_category: Mapped[str | None] = mapped_column(String(50))
    llm3_final_vector: Mapped[list | None] = mapped_column(JSONB)
    llm3_final_is_indoor: Mapped[bool | None] = mapped_column(Boolean)
    llm3_confidence: Mapped[str | None] = mapped_column(String(10))
    llm3_reasoning: Mapped[str | None] = mapped_column(Text)

    # Agreement metrics
    category_agreement: Mapped[bool | None] = mapped_column(Boolean)
    vector_cosine_distance: Mapped[float | None] = mapped_column(Float)
    # distance between LLM1 and LLM2 vectors (0=identical, 1=opposite)

    # Final outcome
    final_category: Mapped[str | None] = mapped_column(String(50))
    final_confidence: Mapped[str | None] = mapped_column(String(10))
    # "high" | "medium" | "failed"

    # Metadata
    city_name: Mapped[str | None] = mapped_column(String(100))
    pipeline_run_id: Mapped[str | None] = mapped_column(String(100))
    # UUID string identifying a specific pipeline run (--city Roma at time T)

    classified_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
