"""Frozen evaluation profiles (see docs/evaluation-harness-spec.md §1).

Each profile fixes everything the planner reads: the 7-dim preference vector
(order = app.constants.FEATURE_NAMES), travel_mode, age_range and whether
travelling with children. The vectors are intensities in [0, 1]; the planner
normalises them and adds the per-mode bias. Frozen here for reproducibility —
the harness writes them straight into an in-memory UserPreference, bypassing the
LLM-driven onboarding so the same profile always yields the same input.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Profile:
    key: str
    label: str
    travel_mode: str          # "solo" | "couple" | "friends" | "family"
    age_range: str
    children: bool
    vector: dict[str, float] = field(default_factory=dict)
    note: str = ""


PROFILES: list[Profile] = [
    Profile(
        key="senior_solo_culture",
        label="Anziano solo, culturale",
        travel_mode="solo", age_range="70-80", children=False,
        vector={"nature": 0.2, "culture": 0.9, "food": 0.5, "adventure": 0.05,
                "nightlife": 0.0, "relax": 0.7, "family_friendly": 0.1},
        note="Senior mobility (tight radius) + culture relevance",
    ),
    Profile(
        key="couple_foodie",
        label="Coppia foodie-romantica",
        travel_mode="couple", age_range="30-40", children=False,
        vector={"nature": 0.3, "culture": 0.6, "food": 0.9, "adventure": 0.2,
                "nightlife": 0.3, "relax": 0.7, "family_friendly": 0.0},
    ),
    Profile(
        key="young_solo_outdoor",
        label="Giovane solo, outdoor/avventura",
        travel_mode="solo", age_range="20-30", children=False,
        vector={"nature": 0.8, "culture": 0.4, "food": 0.5, "adventure": 0.9,
                "nightlife": 0.5, "relax": 0.2, "family_friendly": 0.0},
    ),
    Profile(
        key="friends_nightlife",
        label="Gruppo di amici, nightlife/social",
        travel_mode="friends", age_range="20-30", children=False,
        vector={"nature": 0.2, "culture": 0.3, "food": 0.7, "adventure": 0.7,
                "nightlife": 0.9, "relax": 0.2, "family_friendly": 0.0},
        note="Exercises the 'friends' bias branch (nightlife/adventure)",
    ),
    Profile(
        key="family_toddlers",
        label="Famiglia, bimbi piccoli",
        travel_mode="family", age_range="35-45", children=True,
        vector={"nature": 0.7, "culture": 0.4, "food": 0.5, "adventure": 0.4,
                "nightlife": 0.0, "relax": 0.6, "family_friendly": 1.0},
        note="suitable_for_children filter + no-nightlife + tight radius",
    ),
    Profile(
        key="family_teen",
        label="Famiglia, adolescente",
        travel_mode="family", age_range="40-50", children=True,
        vector={"nature": 0.5, "culture": 0.6, "food": 0.6, "adventure": 0.7,
                "nightlife": 0.1, "relax": 0.3, "family_friendly": 0.5},
        note="Edge case: system does not distinguish kid age → future work",
    ),
    Profile(
        key="couple_museums",
        label="Coppia 'solo musei' (monotematico)",
        travel_mode="couple", age_range="50-60", children=False,
        vector={"nature": 0.1, "culture": 1.0, "food": 0.4, "adventure": 0.1,
                "nightlife": 0.1, "relax": 0.4, "family_friendly": 0.0},
        note="Probes whether MMR diversity penalty hurts a mono-thematic user",
    ),
    Profile(
        key="young_solo_relax",
        label="Giovane solo, relax/benessere",
        travel_mode="solo", age_range="25-35", children=False,
        vector={"nature": 0.6, "culture": 0.3, "food": 0.6, "adventure": 0.2,
                "nightlife": 0.2, "relax": 0.9, "family_friendly": 0.0},
        note="Low sightseeing intensity → stresses completeness (empty days?)",
    ),
    Profile(
        key="couple_generalist",
        label="Coppia generalista (turista medio)",
        travel_mode="couple", age_range="30-40", children=False,
        vector={"nature": 0.5, "culture": 0.6, "food": 0.6, "adventure": 0.4,
                "nightlife": 0.3, "relax": 0.5, "family_friendly": 0.0},
        note="Neutral reference profile",
    ),
]

PROFILES_BY_KEY: dict[str, Profile] = {p.key: p for p in PROFILES}
