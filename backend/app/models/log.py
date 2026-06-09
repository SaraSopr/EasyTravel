import uuid
from datetime import datetime, timezone

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LlmLog(Base):
    __tablename__ = "llm_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    model_name: Mapped[str] = mapped_column(String(100))
    prompt: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text)
    latency_ms: Mapped[int] = mapped_column(Integer)
    tokens_used: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class ApiLog(Base):
    __tablename__ = "api_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    endpoint: Mapped[str] = mapped_column(String(255))
    method: Mapped[str] = mapped_column(String(10))
    status_code: Mapped[int] = mapped_column(Integer)
    request_body: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
