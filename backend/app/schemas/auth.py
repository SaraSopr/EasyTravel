from __future__ import annotations

import re
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.user import UserOut


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    home_city: str
    age_range: str
    travel_with_children: bool = False

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        """Normalize email: strip whitespace and convert to lowercase."""
        return v.strip().lower()

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v):
        """Validate password complexity:
        - At least 8 characters (already enforced by Field)
        - At least 1 uppercase letter
        - At least 1 lowercase letter
        - At least 1 digit
        - At least 1 special character
        """
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};:'\",.<>?/\\|`~]", v):
            raise ValueError("Password must contain at least one special character")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        """Normalize email: strip whitespace and convert to lowercase."""
        return v.strip().lower()


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        """Normalize email: strip whitespace and convert to lowercase."""
        return v.strip().lower()


class MessageResponse(BaseModel):
    message: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
