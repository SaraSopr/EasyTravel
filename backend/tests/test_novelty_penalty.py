"""Unit tests for the novelty penalty and its landmark exemption.

Regression guard for the "city loses all its icons after a few regenerations" bug:
globally-famous landmarks must survive the *implicit* previously-suggested penalty,
because re-proposing the same draft must not be treated as "already seen". The
confirmed-visited penalty still applies to landmarks (an explicit visit is real).
"""
from app.services.itinerary_planner import (
    CONFIRMED_VISITED_SCORE,
    IMPLICIT_SUGGESTED_PENALTY,
    apply_novelty_penalty,
)

POI = "poi-1"


def test_never_seen_poi_unchanged():
    assert apply_novelty_penalty(1.0, POI, set(), set()) == 1.0


def test_previously_suggested_non_landmark_is_penalized():
    out = apply_novelty_penalty(1.0, POI, set(), {POI}, is_landmark=False)
    assert out == IMPLICIT_SUGGESTED_PENALTY


def test_previously_suggested_landmark_is_exempt():
    # The core fix: a landmark previously shown in a draft keeps its full prize.
    out = apply_novelty_penalty(1.0, POI, set(), {POI}, is_landmark=True)
    assert out == 1.0


def test_confirmed_visited_landmark_still_penalized():
    # Exemption is only for the implicit signal; an explicit visit still ranks last.
    out = apply_novelty_penalty(1.0, POI, {POI}, set(), is_landmark=True)
    assert out == CONFIRMED_VISITED_SCORE


def test_confirmed_takes_precedence_over_suggested():
    out = apply_novelty_penalty(1.0, POI, {POI}, {POI}, is_landmark=False)
    assert out == CONFIRMED_VISITED_SCORE
