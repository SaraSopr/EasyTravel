"""Export per-cell automatic metrics to CSV for the offline 2×2 analysis.

One row per generated cell (profile × city × num_days × solver × routing) with the
metrics from ``metrics.compute_metrics`` flattened into columns. This is the source
table for the thesis ablation:

- RQ1 (utility):     ``total_relevance`` — compare solver arms within a routing arm.
- RQ3 (feasibility): ``real_overrun_day_rate`` / ``real_overrun_min_avg`` — always
                     measured against the real travel cache, so the "estimated"
                     cells reveal how infeasible a haversine plan is in reality.
- RQ4 (cost / div.): ``solve_time_ms``, ``intra_list_diversity``, ``landmark_coverage``.

Usage:
    python -m evaluation.export_metrics                       # all rows → stdout
    python -m evaluation.export_metrics --run-id <uuid>       # one run only
    python -m evaluation.export_metrics --out metrics.csv     # write to file
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import sys
import uuid

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.evaluation import EvaluationItinerary

# Cell identity first, then every metric key. Kept explicit (not derived from the
# first row) so the column set is stable even if some cells are missing a metric.
CELL_COLUMNS = ["run_id", "profile_key", "city", "num_days", "solver", "routing"]
METRIC_COLUMNS = [
    "total_relevance",
    "avg_relevance",
    "num_activities_included",
    "landmark_coverage",
    "intra_list_diversity",
    "idle_minutes_per_day",
    "budget_fill_rate",
    "real_overrun_day_rate",
    "real_overrun_min_avg",
    "stops_per_day",
    "meals_complete_rate",
    "num_days_filled",
    "solve_time_ms",
]


async def export(run_id: uuid.UUID | None) -> list[dict]:
    stmt = select(EvaluationItinerary)
    if run_id is not None:
        stmt = stmt.where(EvaluationItinerary.run_id == run_id)
    stmt = stmt.order_by(
        EvaluationItinerary.city,
        EvaluationItinerary.profile_key,
        EvaluationItinerary.num_days,
        EvaluationItinerary.solver,
        EvaluationItinerary.routing,
    )
    async with AsyncSessionLocal() as db:
        rows = list((await db.execute(stmt)).scalars().all())

    out: list[dict] = []
    for it in rows:
        metrics = it.metrics_json or {}
        record = {
            "run_id": str(it.run_id),
            "profile_key": it.profile_key,
            "city": it.city,
            "num_days": it.num_days,
            "solver": it.solver,
            "routing": it.routing,
        }
        for key in METRIC_COLUMNS:
            record[key] = metrics.get(key)
        out.append(record)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Export evaluation cell metrics to CSV")
    ap.add_argument("--run-id", default=None, help="Filter to a single run UUID")
    ap.add_argument("--out", default=None, help="Output CSV path (default: stdout)")
    args = ap.parse_args()

    run_id = uuid.UUID(args.run_id) if args.run_id else None
    records = asyncio.run(export(run_id))

    fh = open(args.out, "w", newline="") if args.out else sys.stdout
    try:
        writer = csv.DictWriter(fh, fieldnames=CELL_COLUMNS + METRIC_COLUMNS)
        writer.writeheader()
        writer.writerows(records)
    finally:
        if args.out:
            fh.close()

    if args.out:
        print(f"Wrote {len(records)} cells to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
