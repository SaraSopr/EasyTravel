"""Evaluation test matrix + tunable parameters (see docs/evaluation-harness-spec.md §2, §8)."""
from __future__ import annotations

# 2 dense capitals (Roma, Madrid) + 1 medium city (Porto) to stress POI scarcity,
# where the greedy↔toptw gap is largest. Each must already be pipeline-ingested.
CITIES: list[str] = ["Roma", "Madrid", "Porto"]

DURATIONS: list[int] = [2, 4]          # short (must-see prioritisation) vs long (completeness)
SOLVERS: list[str] = ["greedy", "toptw"]

# Routing arm of the 2×2 ablation. Crossing SOLVERS × ROUTINGS isolates the
# algorithm change (greedy→toptw) from the routing change (estimated→real), so a
# better result can be attributed correctly instead of confounding the two.
#   "real"      — cached real road travel times (settings.routes_api_enabled=True)
#   "estimated" — haversine straight-line estimate (settings.routes_api_enabled=False)
# Note: the feasibility metric (real_overrun_*) ALWAYS re-walks with the real cache,
# so an "estimated" plan is scored against reality — the RQ3 oracle.
ROUTINGS: list[str] = ["real", "estimated"]

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

# Calibration subset: a small, fixed set of pairs (same ones for every evaluator who
# shares a city, picked deterministically) shown before the per-evaluator random
# batch. Without this, each evaluator's pairs are drawn independently at random, so
# with few real evaluators the overlap needed to compute inter-rater agreement
# (Krippendorff's alpha) is close to empty. Stratified per (pair_type × city): an
# evaluator who says "I know Roma" only needs to overlap with other Roma raters, not
# with someone who picked Madrid and has never seen those POIs.
CALIBRATION_PAIRS_PER_CELL: int = 2    # x3 pair types x3 cities = 18 calibration pairs total
CALIBRATION_ITINERARIES_PER_CITY: int = 4  # x3 cities = 12 calibration itineraries total
CALIBRATION_SEED: str = "calibration-set-v1"  # bump to reshuffle the calibration set

# Reproducibility
RANDOM_SEED: int = 42
