"""Tests for the personalized walking threshold (transport-mode selection).

``compute_walk_threshold_m`` scales the base walking cut-off by the traveller's
age cohort and relax preference; ``select_transport`` then uses that cut-off to
pick walking vs transit vs taxi. No DB and no network.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.services import itinerary_planner as ip


@pytest.fixture(autouse=True)
def _personalization_on(monkeypatch):
    # Defaults the suite relies on; restored automatically by monkeypatch.
    monkeypatch.setattr(settings, "walk_personalization", True, raising=False)
    monkeypatch.setattr(settings, "walk_threshold_base_m", 800.0, raising=False)
    monkeypatch.setattr(settings, "walk_threshold_min_m", 350.0, raising=False)
    monkeypatch.setattr(settings, "walk_threshold_max_m", 2000.0, raising=False)
    monkeypatch.setattr(settings, "walk_relax_base", 1.15, raising=False)
    monkeypatch.setattr(settings, "walk_relax_slope", 0.45, raising=False)


def test_young_intense_walks_further_than_senior_relaxed():
    young = ip.compute_walk_threshold_m("18-25", 0.0)
    senior = ip.compute_walk_threshold_m("55-70", 0.9)
    assert young > 800.0 > senior
    # 800 · 1.6 · 1.15 = 1472 ; 800 · 0.75 · (1.15 − 0.45·0.9) = 447
    assert young == pytest.approx(1472.0, abs=1.0)
    assert senior == pytest.approx(447.0, abs=1.0)


def test_oldest_cohort_walks_less_than_younger_senior():
    # 70+ has a smaller factor than 55-70 → shorter walking cut-off.
    assert ip.compute_walk_threshold_m("70+", 0.5) < ip.compute_walk_threshold_m("55-70", 0.5)


def test_legacy_55plus_still_resolves_and_is_senior():
    # Rows stored before the 55+ → 55-70/70+ split must degrade gracefully.
    assert ip.compute_walk_threshold_m("55+", 0.0) == pytest.approx(690.0, abs=1.0)  # 800·0.75·1.15
    assert "55+" in ip.SENIOR_AGE_RANGES


def test_missing_age_and_relax_fall_back_to_neutral_factors():
    # Unknown/missing age → factor 1.0; relax None → 0.0 (intense → base·1.15).
    assert ip.compute_walk_threshold_m(None, None) == pytest.approx(920.0, abs=1.0)
    assert ip.compute_walk_threshold_m("99-100", 0.0) == pytest.approx(920.0, abs=1.0)


def test_clamped_within_bounds(monkeypatch):
    monkeypatch.setattr(settings, "walk_threshold_max_m", 1000.0, raising=False)
    monkeypatch.setattr(settings, "walk_threshold_min_m", 600.0, raising=False)
    assert ip.compute_walk_threshold_m("18-25", 0.0) == 1000.0   # would be 1472 → ceiling
    assert ip.compute_walk_threshold_m("55+", 1.0) == 600.0       # would be ~392 → floor


def test_relax_is_clamped_to_unit_interval():
    # Out-of-range relax must not blow past the relax-factor bounds.
    assert ip.compute_walk_threshold_m("46-55", 5.0) == ip.compute_walk_threshold_m("46-55", 1.0)
    assert ip.compute_walk_threshold_m("46-55", -3.0) == ip.compute_walk_threshold_m("46-55", 0.0)


def test_personalization_off_returns_fixed_base(monkeypatch):
    monkeypatch.setattr(settings, "walk_personalization", False, raising=False)
    for age in ("18-25", "55+", None):
        for relax in (0.0, 0.5, 1.0):
            assert ip.compute_walk_threshold_m(age, relax) == 800.0


def test_select_transport_honours_custom_threshold():
    # A 1200 m leg is transit at the default cut-off but walking at a higher one.
    assert ip.select_transport(1200.0)[0] == "transit"
    assert ip.select_transport(1200.0, 1500.0)[0] == "walking"
    # Taxi threshold is independent of the walking cut-off.
    assert ip.select_transport(6000.0, 1500.0)[0] == "taxi"


def test_select_transport_default_unchanged():
    assert ip.select_transport(700.0)[0] == "walking"
    assert ip.select_transport(900.0)[0] == "transit"
    assert ip.select_transport(6000.0)[0] == "taxi"


# --- Input contract: age_range validation on the schemas ---------------------


def test_age_factor_map_covers_every_canonical_range():
    from app.constants import AGE_RANGES

    for r in AGE_RANGES:
        assert r in ip._AGE_WALK_FACTOR, f"{r} missing from _AGE_WALK_FACTOR"


def test_register_schema_accepts_canonical_and_rejects_legacy_and_unknown():
    import pydantic

    from app.constants import AGE_RANGES
    from app.schemas.auth import RegisterRequest

    base = dict(email="a@b.com", password="Abcdef1!", home_city="Roma")
    for r in AGE_RANGES:
        RegisterRequest(**base, age_range=r)  # must not raise
    for bad in ("55+", "99-100", "", "thirty"):
        with pytest.raises(pydantic.ValidationError):
            RegisterRequest(**base, age_range=bad)


def test_update_profile_schema_allows_none_but_validates_value():
    import pydantic

    from app.schemas.user import UpdateProfileRequest

    UpdateProfileRequest(age_range=None)        # omitted/None is fine
    UpdateProfileRequest(age_range="70+")        # canonical ok
    with pytest.raises(pydantic.ValidationError):
        UpdateProfileRequest(age_range="55+")    # legacy rejected on input
