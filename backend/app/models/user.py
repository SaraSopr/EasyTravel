from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.preference import UserPreference
    from app.models.experience import UserExperienceChoice


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    age_range: Mapped[str | None] = mapped_column(String(20), nullable=True)
    home_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    travel_with_children: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    preferences: Mapped["UserPreference"] = relationship(
        back_populates="user", uselist=False
    )
    experience_choices: Mapped[list["UserExperienceChoice"]] = relationship(
        back_populates="user"
    )
