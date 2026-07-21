"""Per-phase wall-clock profiling for the greedy / TOPTW planners.

Disabled by default. Enable via .env: PHASE_PROFILING_ENABLED=true
(see app.config.settings.phase_profiling_enabled). When disabled, start()/stop()
are near-zero-cost no-ops (one attribute check, no lock, no dict write), so this
instrumentation is safe to leave in place permanently.
"""
from __future__ import annotations

import threading
import time

from app.config import settings

_lock = threading.Lock()
_totals: dict[str, float] = {}
_counts: dict[str, int] = {}


def start() -> float | None:
    if not settings.phase_profiling_enabled:
        return None
    return time.perf_counter()


def stop(name: str, t0: float | None) -> None:
    if t0 is None:
        return
    elapsed = time.perf_counter() - t0
    with _lock:
        _totals[name] = _totals.get(name, 0.0) + elapsed
        _counts[name] = _counts.get(name, 0) + 1


def reset() -> None:
    with _lock:
        _totals.clear()
        _counts.clear()


def snapshot() -> dict:
    with _lock:
        return {
            "ms": {k: round(v * 1000, 2) for k, v in _totals.items()},
            "counts": dict(_counts),
        }
