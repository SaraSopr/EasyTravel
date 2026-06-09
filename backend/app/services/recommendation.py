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
