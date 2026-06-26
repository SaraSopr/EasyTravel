from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from app.models.poi import Poi
    from app.schemas.user import PreferenceVector

from app.constants import FEATURE_NAMES as FEATURES


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / norm) if norm > 0 else 0.0


def build_user_vector(feature_vectors: list[dict]) -> dict[str, float]:
    """Average the feature_vector dicts from selected CityExperience records."""
    if not feature_vectors:
        return {f: 0.0 for f in FEATURES}

    averaged = {f: sum(v.get(f, 0.0) for v in feature_vectors) / len(feature_vectors) for f in FEATURES}
    return averaged


# Implicit-feedback learning rate for in-itinerary edits. Small enough that a
# single swap nudges the profile without overwriting the onboarding signal.
PREFERENCE_LEARNING_RATE = 0.15


def nudge_user_preferences(
    pref,
    *,
    reward: "Poi | None" = None,
    penalty: "Poi | None" = None,
    lr: float = PREFERENCE_LEARNING_RATE,
) -> None:
    """Update a UserPreference in place from an itinerary edit (implicit feedback).

    When the user keeps/adds a POI (`reward`) we move the profile toward that POI's
    feature vector; when they remove/replace one (`penalty`) we move slightly away.
    Each feature is an EMA step, clamped to [0, 1] to stay comparable with the
    onboarding-built vector. Mutates `pref`; the caller commits.
    """
    for f in FEATURES:
        cur = getattr(pref, f) or 0.0
        if reward is not None:
            rv = getattr(reward, f)
            if rv is not None:
                cur += lr * (rv - cur)
        if penalty is not None:
            pv = getattr(penalty, f)
            if pv is not None:
                # Push away from the rejected POI's features, half-strength so a
                # removal is a weaker signal than an explicit pick.
                cur -= lr * 0.5 * pv
        setattr(pref, f, max(0.0, min(1.0, cur)))


def rank_pois(
    user_prefs: "PreferenceVector",
    pois: list["Poi"],
) -> list[tuple["Poi", float]]:
    """Rank POIs by cosine similarity between user preference vector and poi feature vector."""
    uvec = np.array([getattr(user_prefs, k) or 0.0 for k in FEATURES], dtype=float)
    ranked = []
    for poi in pois:
        if poi.confidence == "failed":
            continue
        poi_vec = [getattr(poi, k) for k in FEATURES]
        if None in poi_vec:
            continue
        ranked.append((poi, _cosine_sim(uvec, np.array(poi_vec, dtype=float))))
    return ranked
