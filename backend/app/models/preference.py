from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), primary_key=True
    )
    nature: Mapped[float] = mapped_column(Float, default=0.0)
    culture: Mapped[float] = mapped_column(Float, default=0.0)
    food: Mapped[float] = mapped_column(Float, default=0.0)
    adventure: Mapped[float] = mapped_column(Float, default=0.0)
    nightlife: Mapped[float] = mapped_column(Float, default=0.0)
    relax: Mapped[float] = mapped_column(Float, default=0.0)
    family_friendly: Mapped[float] = mapped_column(Float, default=0.0)

    user: Mapped["User"] = relationship(back_populates="preferences")
