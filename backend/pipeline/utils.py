from __future__ import annotations

import logging
import os
import sys
from datetime import datetime


FEATURES = ["nature", "culture", "food", "adventure", "nightlife", "relax", "family_friendly"]


def normalize_vector(v: list[float]) -> list[float]:
    """Normalize vector so values sum to 1.0."""
    total = sum(v)
    if total == 0:
        return v
    return [x / total for x in v]


def validate_vector(v: list[float]) -> bool:
    """Return True if vector has 7 elements, all in [0,1], sum within ±0.15 of 1.0."""
    if len(v) != 7:
        return False
    if not all(0.0 <= x <= 1.0 for x in v):
        return False
    total = sum(v)
    return abs(total - 1.0) <= 0.15


def setup_logging(city: str, date: str, verbose: bool = False) -> logging.Logger:
    """Configure console + file logging for pipeline run.

    Console handler lives on the "pipeline" parent so that sub-modules
    (tourism_validator, classifier, …) that use getLogger("pipeline") share
    the same output stream. File handler is per-city run.
    When verbose=True the console shows DEBUG lines (per-POI results).
    """
    os.makedirs("logs", exist_ok=True)
    log_file = f"logs/pipeline_{city}_{date}.log"
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    # Parent logger shared by all pipeline sub-modules
    parent = logging.getLogger("pipeline")
    parent.setLevel(logging.DEBUG)
    if not parent.handlers:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG if verbose else logging.INFO)
        ch.setFormatter(fmt)
        parent.addHandler(ch)
    else:
        # Update level on existing console handler (re-entrant runs)
        for h in parent.handlers:
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                h.setLevel(logging.DEBUG if verbose else logging.INFO)

    # Per-city file logger always captures DEBUG
    city_logger = logging.getLogger(f"pipeline.{city}")
    city_logger.setLevel(logging.DEBUG)
    if not city_logger.handlers:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        city_logger.addHandler(fh)

    return city_logger
