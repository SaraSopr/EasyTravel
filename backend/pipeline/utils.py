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


def setup_logging(city: str, date: str) -> logging.Logger:
    """Configure console + file logging for pipeline run."""
    os.makedirs("logs", exist_ok=True)
    log_file = f"logs/pipeline_{city}_{date}.log"

    logger = logging.getLogger(f"pipeline.{city}")
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    logger.addHandler(ch)
    logger.addHandler(fh)

    return logger
