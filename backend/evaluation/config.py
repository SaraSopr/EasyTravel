"""Evaluation test matrix + tunable parameters (see docs/evaluation-harness-spec.md §2, §8)."""
from __future__ import annotations

# 3 dense capitals + 1 medium city (Porto) to stress POI scarcity, where the
# greedy↔toptw gap is largest. Each must already be pipeline-ingested.
CITIES: list[str] = ["Roma", "Londra", "Madrid", "Porto"]

DURATIONS: list[int] = [2, 4]          # short (must-see prioritisation) vs long (completeness)
SOLVERS: list[str] = ["greedy", "toptw"]

# Depot kept at city center for every cell, so it is not an extra variable in the
# greedy-vs-toptw comparison. (Set to an address to test the depot feature later.)
DEPOT_START: str | None = None
DEPOT_END: str | None = None

# --- Automatic metrics ---
TOP_N_LANDMARK: int = 15               # city's top-N by popularity for landmark_coverage
BUDGET_FILL_THRESHOLD: float = 0.7     # a day "fills" the budget if occupied ≥ this fraction

# --- Human-eval pair sampling ---
PAIRS_PER_TYPE: int = 3                # max pairs per type per itinerary
SUBSTITUTABLE_RADIUS_M: float = 1000.0  # B must be within this radius of A (logistics controlled)
SUBSTITUTABLE_MAX_COST_RATIO: float = 1.5  # B travel-cost from depot ≤ this × A's (logistics controlled)
HUMAN_SAMPLE_SIZE: int = 40            # itineraries sampled into the human dashboard
HUMAN_PRIORITISE_SOLVER_DIFF: bool = True  # prefer cells where greedy/toptw inclusions differ

# Reproducibility
RANDOM_SEED: int = 42
