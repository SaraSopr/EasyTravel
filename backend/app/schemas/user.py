from __future__ import annotations

import re
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.constants import AgeRange


class PreferenceVector(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nature: float = Field(ge=0.0, le=1.0)
    culture: float = Field(ge=0.0, le=1.0)
    food: float = Field(ge=0.0, le=1.0)
    adventure: float = Field(ge=0.0, le=1.0)
    nightlife: float = Field(ge=0.0, le=1.0)
    relax: float = Field(ge=0.0, le=1.0)
    family_friendly: float = Field(ge=0.0, le=1.0)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    home_city: str | None
    age_range: str | None
    travel_with_children: bool
    preferences: PreferenceVector | None


class UpdateProfileRequest(BaseModel):
    home_city: str | None = None
    age_range: AgeRange | None = None
    travel_with_children: bool | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)

    @field_validator("new_password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        errors = []
        if not re.search(r"[A-Z]", v):
            errors.append("at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            errors.append("at least one lowercase letter")
        if not re.search(r"\d", v):
            errors.append("at least one digit")
        if not re.search(r"[!@#$%^&*()\-_=+\[\]{}|;:',.<>?/\\`~]", v):
            errors.append("at least one special character")
        if errors:
            raise ValueError(f"Password must contain: {', '.join(errors)}")
        return v
