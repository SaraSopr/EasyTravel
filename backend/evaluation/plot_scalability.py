"""Plot RQ1c scalability from scalability_results.csv.

Reads the output of run_scalability.py (a grid of cities × profiles × durations)
and writes evaluation/figures/fig3_rq1c_scalability.png.

Each (city, profile, duration) is one instance. For TOPTW the figure shows, per
duration, the mean over instances at each candidate level with a shaded min–max
band, so the N-trend is visible *and* its spread across instances is exposed —
the scalability claim no longer rests on a single (city, profile) pair. Greedy
is drawn as a horizontal reference (its mean, candidate count does not apply).

Usage (from backend/):
    python -m evaluation.plot_scalability
    python -m evaluation.plot_scalability --csv scalability_results.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
from collections import defaultdict
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("matplotlib not installed — cannot generate figure.")

DURATION_COLORS = {2: "#2171b5", 4: "#d94801"}
DURATION_MARKERS = {2: "o", 4: "s"}


def _float(val) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def load(csv_path: str) -> list[dict]:
    rows = []
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            nc = row.get("num_candidates")
            row["num_candidates"] = int(nc) if nc not in ("N/A", "", None) else None
            row["num_days"] = int(row["num_days"])
            rows.append(row)
    return rows


def _quantile(vals: list[float], q: float) -> float:
    """Linear-interpolated quantile (no numpy dependency)."""
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(pos)
    frac = pos - lo
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * frac


def _aggregate(rows: list[dict], solver: str, num_days: int, metric: str):
    """Returns (xs, means, los, his) over candidate levels for TOPTW, aggregating
    across city × profile instances. Band is the inter-quartile range (25–75th
    percentile) — robust to single-instance outliers (e.g. cold-cache solve time).
    xs are sorted candidate counts."""
    by_n: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        if r["solver"] != solver or r["num_days"] != num_days or r["num_candidates"] is None:
            continue
        v = _float(r[metric])
        if v is not None:
            by_n[r["num_candidates"]].append(v)
    xs = sorted(by_n)
    means = [statistics.mean(by_n[x]) for x in xs]
    los = [_quantile(by_n[x], 0.25) for x in xs]
    his = [_quantile(by_n[x], 0.75) for x in xs]
    return xs, means, los, his


def _greedy_mean(rows: list[dict], num_days: int, metric: str) -> float | None:
    vals = [
        _float(r[metric]) for r in rows
        if r["solver"] == "greedy" and r["num_days"] == num_days and _float(r[metric]) is not None
    ]
    return statistics.mean(vals) if vals else None


def plot(csv_path: str, out_dir: Path) -> None:
    if not HAS_MPL:
        return
    rows = load(csv_path)
    durations = sorted({r["num_days"] for r in rows})
    instances = {(r["city"], r["profile_key"], r["num_days"]) for r in rows}
    candidate_levels = sorted({r["num_candidates"] for r in rows if r["num_candidates"] is not None})
    out_dir.mkdir(parents=True, exist_ok=True)

    panels = [
        ("avg_relevance",        "avg_relevance (↑ better)",       "Selection quality", True),
        ("real_overrun_min_avg", "budget overrun min/day (↓ better)", "Feasibility",    False),
        ("solve_time_ms",        "solve time (ms)",                 "Runtime",         False),
    ]
    fig, axes = plt.subplots(1, len(panels), figsize=(18, 5))
    fig.suptitle(
        "RQ1c — Scalability vs candidate pool size (N): TOPTW mean over instances, "
        "IQR band (25–75th pct)\n"
        f"({len(instances)} instances = "
        f"{len({i[0] for i in instances})} cities × "
        f"{len({i[1] for i in instances})} profiles × {len(durations)} durations; routing: real)",
        fontsize=11, fontweight="bold",
    )

    for ax, (metric, ylabel, title, do_zoom) in zip(axes, panels):
        handles = []
        band_vals = []   # collect band edges to size the y-axis
        for num_days in durations:
            color = DURATION_COLORS.get(num_days, "#999")
            marker = DURATION_MARKERS.get(num_days, "^")

            xs, means, los, his = _aggregate(rows, "toptw", num_days, metric)
            if xs:
                ax.fill_between(xs, los, his, color=color, alpha=0.13, linewidth=0)
                line, = ax.plot(xs, means, color=color, marker=marker, linewidth=2,
                                markersize=6, label=f"TOPTW / {num_days}d (mean, IQR band)")
                handles.append(line)
                band_vals += los + his

            gval = _greedy_mean(rows, num_days, metric)
            if gval is not None:
                ax.axhline(gval, color=color, linewidth=1.4, linestyle="--", alpha=0.6)
                xmax = max(candidate_levels) if candidate_levels else 120
                ax.text(xmax + 1, gval, f"Greedy/{num_days}d", va="center",
                        fontsize=7.5, color=color, alpha=0.8)

        # Tighten the y-axis to the IQR band (means + quartiles), so the trend is
        # legible; do this BEFORE drawing the N=80 marker so its label is anchored
        # to the final axes.
        if do_zoom and band_vals:
            pad = (max(band_vals) - min(band_vals)) * 0.08 or 0.01
            ax.set_ylim(min(band_vals) - pad, max(band_vals) + pad)

        # default reference line at N=80 (label anchored in axes fraction)
        ax.axvline(80, color="#aaa", linewidth=1, linestyle=":", alpha=0.7)
        ax.text(80, 0.02, " default (N=80)", fontsize=7, color="#888",
                va="bottom", ha="left", transform=ax.get_xaxis_transform())

        ax.set_xlabel("toptw_num_candidates (N)", fontsize=10)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.set_title(title, fontsize=10, fontweight="bold", pad=8)
        ax.spines[["top", "right"]].set_visible(False)
        if handles:
            ax.legend(handles=handles, fontsize=8, frameon=False)

    fig.tight_layout()
    out = out_dir / "fig3_rq1c_scalability.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}  ({len(instances)} instances)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Plot RQ1c scalability figure")
    ap.add_argument("--csv", default="scalability_results.csv")
    ap.add_argument("--out", default="evaluation/figures")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        print(f"CSV not found: {args.csv}")
        print("Run first: python -m evaluation.run_scalability")
        return

    plot(args.csv, Path(args.out))


if __name__ == "__main__":
    main()
