"""Plot RQ1c scalability from scalability_results.csv.

Reads the output of run_scalability.py and writes
evaluation/figures/fig3_rq1c_scalability.png.

Usage (from backend/):
    python -m evaluation.plot_scalability
    python -m evaluation.plot_scalability --csv scalability_results.csv
"""
from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("matplotlib not installed — cannot generate figure.")

DURATION_COLORS = {2: "#2171b5", 4: "#d94801"}
DURATION_MARKERS = {2: "o", 4: "s"}


def load(csv_path: str) -> dict:
    """Returns {(solver, num_days): [row, ...]}"""
    cells: dict = defaultdict(list)
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            key = (row["solver"], int(row["num_days"]))
            row["num_candidates"] = int(row["num_candidates"]) if row["num_candidates"] != "N/A" else None
            cells[key].append(row)
    return cells


def _float(val) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def plot(csv_path: str, out_dir: Path) -> None:
    if not HAS_MPL:
        return
    cells = load(csv_path)
    durations = sorted({k[1] for k in cells})
    out_dir.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle(
        "RQ1c — Scalability: selection quality and solve time vs candidate pool size\n"
        f"(profile: couple_generalist, city: Roma, routing: real)",
        fontsize=11, fontweight="bold",
    )

    for ax, metric, ylabel, title, do_zoom in [
        (axes[0], "avg_relevance",  "avg_relevance (↑ better)",   "Selection quality vs candidate pool",  True),
        (axes[1], "solve_time_ms",  "solve time (ms)",             "Solve time vs candidate pool",         False),
    ]:
        handles = []

        for num_days in durations:
            color = DURATION_COLORS.get(num_days, "#999")
            marker = DURATION_MARKERS.get(num_days, "^")

            # TOPTW curve
            toptw_rows = sorted(
                [r for r in cells.get(("toptw", num_days), []) if r["num_candidates"] is not None],
                key=lambda r: r["num_candidates"],
            )
            if toptw_rows:
                xs = [r["num_candidates"] for r in toptw_rows]
                ys = [_float(r[metric]) or 0 for r in toptw_rows]
                line, = ax.plot(xs, ys, color=color, marker=marker, linewidth=2,
                                markersize=6, label=f"TOPTW / {num_days}d")
                handles.append(line)

            # Greedy reference (horizontal dashed line — one value per duration)
            greedy_rows = [r for r in cells.get(("greedy", num_days), [])]
            if greedy_rows:
                gval = _float(greedy_rows[0][metric])
                if gval is not None:
                    xmin = min(CANDIDATE_COUNTS_HINT) if CANDIDATE_COUNTS_HINT else 20
                    xmax = max(CANDIDATE_COUNTS_HINT) if CANDIDATE_COUNTS_HINT else 120
                    ref = ax.axhline(gval, color=color, linewidth=1.4, linestyle="--", alpha=0.6)
                    ax.text(xmax + 1, gval, f"Greedy/{num_days}d",
                            va="center", fontsize=7.5, color=color, alpha=0.8)

        # default reference line at toptw_num_candidates=80
        ax.axvline(80, color="#aaa", linewidth=1, linestyle=":", alpha=0.7)
        ax.text(81, ax.get_ylim()[0] if ax.get_ylim()[0] != 0 else 0,
                "default\n(N=80)", fontsize=7, color="#888", va="bottom")

        ax.set_xlabel("toptw_num_candidates", fontsize=10)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.set_title(title, fontsize=10, fontweight="bold", pad=8)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(handles=handles, fontsize=8, frameon=False)
        if do_zoom and handles:
            # tighten y-axis so differences are visible
            all_vals = []
            for num_days in durations:
                for r in cells.get(("toptw", num_days), []):
                    v = _float(r[metric])
                    if v is not None:
                        all_vals.append(v)
            if all_vals:
                ax.set_ylim(min(all_vals) * 0.985, max(all_vals) * 1.015)

    fig.tight_layout()
    out = out_dir / "fig3_rq1c_scalability.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


# fallback hint for axis limits (updated at runtime from the CSV)
CANDIDATE_COUNTS_HINT: list[int] = []


def main() -> None:
    global CANDIDATE_COUNTS_HINT
    ap = argparse.ArgumentParser(description="Plot RQ1c scalability figure")
    ap.add_argument("--csv", default="scalability_results.csv")
    ap.add_argument("--out", default="evaluation/figures")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        print(f"CSV not found: {args.csv}")
        print("Run first: python -m evaluation.run_scalability")
        return

    # populate hint from actual data
    with open(args.csv) as f:
        for row in csv.DictReader(f):
            if row["num_candidates"] not in ("N/A", "", None):
                CANDIDATE_COUNTS_HINT.append(int(row["num_candidates"]))
    CANDIDATE_COUNTS_HINT = sorted(set(CANDIDATE_COUNTS_HINT))

    plot(args.csv, Path(args.out))


if __name__ == "__main__":
    main()
