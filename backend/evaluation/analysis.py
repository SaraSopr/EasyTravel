"""Thesis analysis script — generates summary tables and plots from metrics_2x2.csv.

Terminology used throughout:
- Haversine (routing "estimated"): travel time estimated from straight-line distance
  between two points on Earth. Fast to compute but optimistic — ignores roads,
  traffic, one-way streets. Used as the baseline routing arm.
- Real routing (routing "real"): actual road travel times fetched from OpenRouteService
  and cached. Reflects what a tourist would actually experience.
- Overrun: a day plan that, when re-evaluated with REAL travel times, no longer fits
  within the day budget (e.g. planned 9:00-22:00 but real travel pushes finish to
  22:14 → overrun of 14 min). Overrun = the plan is infeasible in the real world.
  A plan built on haversine estimates is more likely to overrun because it
  underestimates how long getting between places actually takes.

Run:
    python -m evaluation.analysis                        # saves figures to evaluation/figures/
    python -m evaluation.analysis --csv path/to/file.csv
"""
from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from pathlib import Path

# ── optional matplotlib import ───────────────────────────────────────────────
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("matplotlib not installed — skipping plots, printing tables only.")


# ── helpers ──────────────────────────────────────────────────────────────────

def avg(vals: list) -> float | None:
    v = [float(x) for x in vals if x not in ("", "None", None)]
    return round(sum(v) / len(v), 4) if v else None


CELL_ORDER = [
    ("greedy", "estimated"),
    ("greedy", "real"),
    ("toptw",  "estimated"),
    ("toptw",  "real"),
]

CELL_LABELS = {
    ("greedy", "estimated"): "Greedy\n(haversine)",
    ("greedy", "real"):      "Greedy\n(real routing)",
    ("toptw",  "estimated"): "TOPTW\n(haversine)",
    ("toptw",  "real"):      "TOPTW\n(real routing)",
}

COLORS = {
    ("greedy", "estimated"): "#9ecae1",
    ("greedy", "real"):      "#2171b5",
    ("toptw",  "estimated"): "#fdae6b",
    ("toptw",  "real"):      "#d94801",
}


def load(csv_path: str) -> dict[tuple, list[dict]]:
    cells: dict[tuple, list[dict]] = defaultdict(list)
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            cells[(row["solver"], row["routing"])].append(row)
    return cells


# ── tables ───────────────────────────────────────────────────────────────────

def print_2x2_table(cells: dict) -> None:
    metrics = [
        ("avg_relevance",          "Selection quality (avg prize/POI) ↑"),
        ("num_activities_included", "N. activities included ↑"),
        ("real_overrun_day_rate",   "Overrun rate* ↓"),
        ("real_overrun_min_avg",    "Overrun avg (min)* ↓"),
        ("intra_list_diversity",    "Intra-list diversity ↑"),
        ("landmark_coverage",       "Landmark coverage ↑"),
        ("idle_minutes_per_day",    "Idle min/day"),
        ("stops_per_day",           "Stops/day"),
        ("solve_time_ms",           "Solve time (ms) ↓"),
    ]
    col_w = 14
    label_w = 40
    header = f"{'Metric':<{label_w}}" + "".join(
        f"{CELL_LABELS[k].replace(chr(10),' '):>{col_w}}" for k in CELL_ORDER
    )
    print("\n" + "=" * len(header))
    print("2×2 ABLATION — aggregated across all profiles and durations")
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    for col, label in metrics:
        vals = [avg([r[col] for r in cells[k]]) for k in CELL_ORDER]
        row = f"{label:<{label_w}}" + "".join(f"{str(v):>{col_w}}" for v in vals)
        print(row)

    print()
    print("* Overrun = the day plan, when re-walked with REAL road travel times,")
    print("  no longer fits within the day budget. Measures real-world feasibility.")
    print("  'haversine' cells are PLANNED on straight-line estimates but EVALUATED")
    print("  against reality — so their overrun rate reveals how much the estimates")
    print("  underestimate actual travel time.")


def print_ablation_decomposition(cells: dict) -> None:
    print("\n── Ablation decomposition (avg_relevance) ──────────────────────────────")
    print("Isolates the contribution of each change independently.\n")

    ge = avg([r["avg_relevance"] for r in cells[("greedy", "estimated")]])
    gr = avg([r["avg_relevance"] for r in cells[("greedy", "real")]])
    te = avg([r["avg_relevance"] for r in cells[("toptw",  "estimated")]])
    tr = avg([r["avg_relevance"] for r in cells[("toptw",  "real")]])

    algo   = round(te - ge, 4)
    route  = round(gr - ge, 4)
    combo  = round(tr - ge, 4)
    synergy = round(combo - algo - route, 4)

    print(f"  Baseline            A = greedy + haversine :  {ge}")
    print(f"  Algorithm effect  A→C = toptw  + haversine :  {te}  (Δ = {algo:+.4f})")
    print(f"  Routing effect    A→B = greedy + real      :  {gr}  (Δ = {route:+.4f})")
    print(f"  Combined          A→D = toptw  + real      :  {tr}  (Δ = {combo:+.4f})")
    print(f"  Synergy (D − A − algo − routing)           :  {synergy:+.4f}")
    print()
    print("  Interpretation: if synergy ≈ 0, the two changes are independent.")
    print("  A positive synergy means TOPTW benefits more from real routing than")
    print("  the greedy does (the solver exploits accurate travel times better).")

    print("\n── Overrun breakdown ───────────────────────────────────────────────────")
    print("Shows which arm produces infeasible plans when validated against reality.\n")
    for k in CELL_ORDER:
        rate = avg([r["real_overrun_day_rate"] for r in cells[k]])
        mins = avg([r["real_overrun_min_avg"]  for r in cells[k]])
        label = CELL_LABELS[k].replace("\n", " / ")
        print(f"  {label:<25} → {rate*100:4.0f}% days overrun,  {mins:.1f} min avg overrun")


# ── plots ────────────────────────────────────────────────────────────────────

def _bar_group(ax, data: list[float | None], title: str, ylabel: str, note: str = "") -> None:
    x = range(len(CELL_ORDER))
    colors = [COLORS[k] for k in CELL_ORDER]
    labels = [CELL_LABELS[k] for k in CELL_ORDER]
    vals = [v if v is not None else 0 for v in data]
    bars = ax.bar(x, vals, color=colors, width=0.55, edgecolor="white", linewidth=1.2)
    ax.bar_label(bars, [f"{v:.3f}" for v in vals], padding=3, fontsize=8)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.set_title(title, fontsize=10, fontweight="bold", pad=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_ylim(0, max(vals) * 1.25 if max(vals) > 0 else 1)
    if note:
        ax.text(0.01, 0.97, note, transform=ax.transAxes,
                fontsize=7, va="top", color="#666666",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#cccccc", alpha=0.8))


def _legend(fig, bbox=(0.5, -0.06), ncol=4):
    patches = [mpatches.Patch(color=COLORS[k], label=CELL_LABELS[k].replace("\n", " / "))
               for k in CELL_ORDER]
    fig.legend(handles=patches, loc="lower center", ncol=ncol, fontsize=8,
               frameon=False, bbox_to_anchor=bbox)


def plot_main_figures(cells: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    all_rows = sum(cells.values(), [])
    profiles = sorted({r["profile_key"] for r in all_rows})
    durations = sorted({int(r["num_days"]) for r in all_rows})

    # ── Figure 1 — RQ1a: utility (2×2 ablation + decomposition) ─────────────
    # Shows avg_relevance (primary quality metric) for the 4 cells and decomposes
    # the total gain into algorithm effect (A→C) vs routing effect (A→B).
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    fig.suptitle(
        "RQ1a — Selection quality: 2×2 ablation\n"
        "avg_relevance = mean prize per included POI (isolates quality from quantity)",
        fontsize=11, fontweight="bold",
    )

    vals0 = [avg([r["avg_relevance"] for r in cells[k]]) for k in CELL_ORDER]
    _bar_group(
        axes[0],
        vals0,
        "avg_relevance by cell\n(primary utility metric)",
        "avg_relevance (↑ better)",
        None,
    )
    # zoom in so small differences are visible
    ymin = min(v for v in vals0 if v) * 0.985
    ymax = max(v for v in vals0 if v) * 1.015
    axes[0].set_ylim(ymin, ymax)
    axes[0].text(0.01, 0.01,
                 "Greedy vs TOPTW × haversine vs real routing.\nDifference = algorithm effect + routing effect.",
                 transform=axes[0].transAxes, fontsize=7, va="bottom", color="#666",
                 bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#ccc", alpha=0.8))

    # Ablation decomposition bar chart
    ge = avg([r["avg_relevance"] for r in cells[("greedy", "estimated")]]) or 0
    gr = avg([r["avg_relevance"] for r in cells[("greedy", "real")]]) or 0
    te = avg([r["avg_relevance"] for r in cells[("toptw",  "estimated")]]) or 0
    tr = avg([r["avg_relevance"] for r in cells[("toptw",  "real")]]) or 0
    effects = [te - ge, gr - ge, tr - ge - (te - ge) - (gr - ge)]
    effect_labels = ["Algorithm\n(A→C)", "Routing\n(A→B)", "Synergy\n(D−A−alg−rout)"]
    effect_colors = ["#fdae6b", "#2171b5", "#9ecae1"]
    bars = axes[1].bar(range(3), effects, color=effect_colors, width=0.5,
                       edgecolor="white", linewidth=1.2)
    axes[1].bar_label(bars, [f"{v:+.4f}" for v in effects], padding=3, fontsize=8)
    axes[1].axhline(0, color="#999", linewidth=0.8, linestyle="--")
    axes[1].set_xticks([0, 1, 2])
    axes[1].set_xticklabels(effect_labels, fontsize=9)
    axes[1].set_ylabel("Δ avg_relevance vs baseline (greedy/haversine)", fontsize=9)
    axes[1].set_title("Ablation decomposition\n(isolates each factor's contribution)",
                      fontsize=10, fontweight="bold", pad=8)
    axes[1].spines[["top", "right"]].set_visible(False)
    axes[1].text(0.01, 0.97,
                 "Synergy ≈ 0 → effects independent\n"
                 "Synergy > 0 → TOPTW benefits more from real routing",
                 transform=axes[1].transAxes, fontsize=7, va="top", color="#666",
                 bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#ccc", alpha=0.8))

    _legend(fig)
    fig.tight_layout()
    fig.savefig(out_dir / "fig1_rq1a_utility.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {out_dir / 'fig1_rq1a_utility.png'}")

    # ── Figure 2 — RQ1b: real-world feasibility (overrun oracle) ─────────────
    # All 4 cells are re-evaluated with REAL travel times regardless of how they
    # were planned. Overrun = the plan no longer fits the day budget in reality.
    # The haversine cells reveal how much straight-line estimates underestimate
    # actual travel time.
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    fig.suptitle(
        "RQ1b — Real-world feasibility oracle\n"
        "All plans re-evaluated with real road travel times (cache, no API call).\n"
        "Overrun: the day plan, built on possibly optimistic estimates, no longer fits "
        "its budget when real travel times are applied.",
        fontsize=10, fontweight="bold",
    )

    _bar_group(
        axes[0],
        [avg([r["real_overrun_day_rate"] for r in cells[k]]) for k in CELL_ORDER],
        "Overrun rate\n(fraction of days that exceed budget in reality)",
        "overrun rate (↓ better = 0%)",
        "Haversine (straight-line) estimates are optimistic.\n"
        "Plans built on them may underestimate real travel time\n"
        "→ day runs past its end time in the real world.",
    )
    _bar_group(
        axes[1],
        [avg([r["real_overrun_min_avg"] for r in cells[k]]) for k in CELL_ORDER],
        "Overrun magnitude\n(avg minutes past budget, overrun days only)",
        "avg overrun (min) (↓ better)",
    )

    _legend(fig, bbox=(0.5, -0.08))
    fig.tight_layout()
    fig.savefig(out_dir / "fig2_rq1b_feasibility.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {out_dir / 'fig2_rq1b_feasibility.png'}")

    # ── Figure 3 — RQ1c: scalability (trip duration 2d vs 4d) ────────────────
    # Three panels: selection quality, feasibility, and solve time, all split by
    # num_days. This covers the "travel days" axis of RQ1c; the candidate-pool
    # axis (toptw_num_candidates) is varied in a separate experiment.
    if len(durations) >= 2:
        fig, axes = plt.subplots(1, 3, figsize=(16, 4.8))
        fig.suptitle(
            "RQ1c — Scalability: how do quality, feasibility and runtime change with trip duration?\n"
            "(means across all 9 profiles × 3 cities; trip duration is the scalability axis)",
            fontsize=11, fontweight="bold",
        )

        panel_specs = [
            (axes[0], "avg_relevance",        "avg_relevance (↑ better)",    "Selection quality",  True),
            (axes[1], "real_overrun_day_rate", "overrun rate (↓ better)",     "Feasibility",        False),
            (axes[2], "solve_time_ms",         "solve time (ms)",             "Runtime",            False),
        ]
        for ax, metric, ylabel, title, do_zoom in panel_specs:
            x = list(range(len(durations)))
            width = 0.18
            all_vals = []
            for ci, k in enumerate(CELL_ORDER):
                vals = []
                for d in durations:
                    raw = [float(r[metric]) for r in cells[k]
                           if int(r["num_days"]) == d and r[metric] not in ("", "None", None)]
                    vals.append(sum(raw) / len(raw) if raw else 0.0)
                    all_vals.append(vals[-1])
                offset = (ci - 1.5) * width
                xs = [xi + offset for xi in x]
                bars = ax.bar(xs, vals, width=width, color=COLORS[k],
                              edgecolor="white", linewidth=0.8,
                              label=CELL_LABELS[k].replace("\n", " / "))
                ax.bar_label(bars,
                             [f"{v:.0f}" if metric == "solve_time_ms" else f"{v:.3f}" for v in vals],
                             padding=2, fontsize=6.5, rotation=90)
            ax.set_xticks(x)
            ax.set_xticklabels([f"{d} days" for d in durations], fontsize=10)
            ax.set_ylabel(ylabel, fontsize=9)
            ax.set_title(title, fontsize=10, fontweight="bold", pad=8)
            ax.spines[["top", "right"]].set_visible(False)
            if do_zoom and all_vals:
                ymin = min(v for v in all_vals if v > 0) * 0.985
                ymax = max(all_vals) * 1.03
                ax.set_ylim(ymin, ymax)

        _legend(fig, bbox=(0.5, -0.07), ncol=4)
        fig.tight_layout()
        fig.savefig(out_dir / "fig3_rq1c_scalability.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved: {out_dir / 'fig3_rq1c_scalability.png'}")
    else:
        print("  Skipped fig3 (need ≥ 2 durations in data)")

    # ── Figure 4 — RQ2c: personalisation (diversity + coverage per profile) ──
    # Do different user profiles receive meaningfully different itineraries,
    # or does the system converge on the same top-popular POIs regardless?
    # Uses the real-routing arm (production quality) for both solvers.
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    fig.suptitle(
        "RQ2c — Personalisation: do different profiles get different itineraries?\n"
        "(real-routing arm only — production quality)",
        fontsize=11, fontweight="bold",
    )

    real_cells = {k: cells[k] for k in [("greedy", "real"), ("toptw", "real")]}
    real_colors = {("greedy", "real"): "#2171b5", ("toptw", "real"): "#d94801"}
    real_labels = {("greedy", "real"): "Greedy / real", ("toptw", "real"): "TOPTW / real"}

    for ax, metric, xlabel, title, note in [
        (axes[0], "intra_list_diversity",
         "diversity (↑ = more varied categories)",
         "Intra-list diversity per profile",
         "1 − mean pairwise cosine over included POIs.\n"
         "Low = repetitive / filter-bubble effect.\nHigh = varied categories across the day."),
        (axes[1], "landmark_coverage",
         "landmark coverage (↑ = more must-sees)",
         "Landmark coverage per profile",
         "Share of city top-15 POIs (by review count)\n"
         "included in the itinerary."),
    ]:
        width = 0.35
        y = range(len(profiles))
        for ci, (k, color) in enumerate(real_colors.items()):
            vals = [avg([r[metric] for r in real_cells[k] if r["profile_key"] == p]) or 0
                    for p in profiles]
            offset = (ci - 0.5) * width
            bars = ax.barh([yi + offset for yi in y], vals,
                           height=width, color=color, label=real_labels[k],
                           edgecolor="white", linewidth=0.8)
            ax.bar_label(bars, [f"{v:.2f}" for v in vals], padding=3, fontsize=7)
        ax.set_yticks(list(y))
        ax.set_yticklabels(profiles, fontsize=8)
        ax.set_xlabel(xlabel, fontsize=9)
        ax.set_title(title, fontsize=10, fontweight="bold", pad=8)
        ax.spines[["top", "right"]].set_visible(False)
        ax.text(0.99, 0.02, note, transform=ax.transAxes,
                fontsize=7, va="bottom", ha="right", color="#666",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#ccc", alpha=0.8))

    handles = [mpatches.Patch(color=c, label=l) for c, l in
               zip(real_colors.values(), real_labels.values())]
    fig.legend(handles=handles, loc="lower center", ncol=2, fontsize=9,
               frameon=False, bbox_to_anchor=(0.5, -0.04))
    fig.tight_layout()
    fig.savefig(out_dir / "fig4_rq2c_personalisation.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {out_dir / 'fig4_rq2c_personalisation.png'}")


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Thesis analysis from metrics_2x2.csv")
    ap.add_argument("--csv", default="metrics_2x2.csv", help="Path to the metrics CSV")
    ap.add_argument("--out", default="evaluation/figures", help="Output directory for figures")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        print(f"CSV not found: {args.csv}")
        print("Run: python -m evaluation.export_metrics --out metrics_2x2.csv")
        return

    cells = load(args.csv)
    n_rows = sum(len(v) for v in cells.values())
    cities = sorted({r["city"] for rows in cells.values() for r in rows})
    print(f"\nLoaded {n_rows} cells | cities: {', '.join(cities)}\n")

    print_2x2_table(cells)
    print_ablation_decomposition(cells)

    if HAS_MPL:
        print(f"\nGenerating figures → {args.out}/")
        plot_main_figures(cells, Path(args.out))
    else:
        print("\nInstall matplotlib to generate figures: pip install matplotlib")


if __name__ == "__main__":
    main()
