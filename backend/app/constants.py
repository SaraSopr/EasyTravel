"""Shared application-level constants."""

from typing import Literal

# Canonical age buckets. Single source of truth for the input contract: the
# frontend dropdowns (Register/Profile) and the registration/profile schemas
# must offer exactly these. The legacy "55+" value may still exist in stored
# rows (older signups) — reads stay tolerant, but new input is restricted to
# this set. Keep AGE_RANGES (frontend) in sync.
AGE_RANGES: tuple[str, ...] = ("18-25", "26-35", "36-45", "46-55", "55-70", "70+")
AgeRange = Literal["18-25", "26-35", "36-45", "46-55", "55-70", "70+"]

FEATURE_NAMES: list[str] = [
    "nature",
    "culture",
    "food",
    "adventure",
    "nightlife",
    "relax",
    "family_friendly",
]
