"""Figures (English): the evaluation configuration space, as two standalone plots.

- ``fig0a_config_space.png`` — the full factorial design (every test-matrix axis).
- ``fig0b_ablation_2x2.png`` — the solver×routing 2×2 ablation, the core comparison.

Values are read live from ``config`` / ``profiles`` so the figures can never drift
from what the harness actually runs.

Run:
    python -m evaluation.plot_config_space_en      # saves both figures to figures/
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

from evaluation import config as cfg
from evaluation.profiles import PROFILES

# Same palette as analysis.py so cells match the other thesis figures.
COLORS = {
    ("greedy", "estimated"): "#9ecae1",
    ("greedy", "real"):      "#2171b5",
    ("toptw",  "estimated"): "#fdae6b",
    ("toptw",  "real"):      "#d94801",
}
FACTOR_C = "#2171b5"


def _factor_values() -> list[tuple[str, list[str]]]:
    """The five axes, in multiplication order, each as (label, list-of-values)."""
    return [
        ("Profiles", [p.key for p in PROFILES]),
        ("Cities", list(cfg.CITIES)),
        ("Durations", [f"{d} days" for d in cfg.DURATIONS]),
        ("Solver", list(cfg.SOLVERS)),
        ("Routing", list(cfg.ROUTINGS)),
    ]


def _wrap(values: list[str], per_line: int) -> str:
    lines = [", ".join(values[i:i + per_line]) for i in range(0, len(values), per_line)]
    return "\n".join(lines)


def plot_config_space(out_dir: Path) -> Path:
    """Figure A — the factorial design space."""
    factors = _factor_values()
    counts = [len(v) for _, v in factors]
    total = 1
    for c in counts:
        total *= c

    fig, ax = plt.subplots(figsize=(9, 6.2))
    fig.suptitle(
        f"Evaluation configuration space — full factorial design\n"
        f"({' × '.join(map(str, counts))} = {total} itineraries)",
        fontsize=12, fontweight="bold",
    )

    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis("off")

    n = len(factors)
    top, bottom = 9.2, 1.6
    row_h = (top - bottom) / n
    per_line = {"Profiles": 3}  # profiles are many → wrap 3 per line; others fit on one
    for i, (label, values) in enumerate(factors):
        yc = top - (i + 0.5) * row_h
        ax.add_patch(FancyBboxPatch(
            (0.2, yc - row_h * 0.36), 2.1, row_h * 0.72,
            boxstyle="round,pad=0.02,rounding_size=0.12",
            linewidth=1.4, edgecolor=FACTOR_C, facecolor="#eaf2fb",
        ))
        ax.text(1.25, yc, f"{label}\n(×{len(values)})", ha="center", va="center",
                fontsize=10, fontweight="bold", color=FACTOR_C)
        if i < n - 1:
            ax.text(1.25, yc - row_h * 0.5, "×", ha="center", va="center",
                    fontsize=13, color="#777")
        ax.text(2.7, yc, _wrap(values, per_line.get(label, len(values))),
                ha="left", va="center", fontsize=8.5, family="monospace", color="#222")

    ax.add_patch(FancyBboxPatch(
        (0.2, 0.45), 9.3, 0.85, boxstyle="round,pad=0.02,rounding_size=0.12",
        linewidth=1.6, edgecolor="#d94801", facecolor="#fff1e6",
    ))
    ax.text(4.85, 0.87,
            f"Total = {' × '.join(map(str, counts))} = {total} itineraries generated",
            ha="center", va="center", fontsize=11, fontweight="bold", color="#d94801")

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "fig0a_config_space.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_ablation(out_dir: Path) -> Path:
    """Figure B — the 2×2 solver×routing ablation."""
    fig, ax = plt.subplots(figsize=(6, 6))
    fig.suptitle("2×2 ablation — core comparison\n(isolates algorithm from routing)",
                 fontsize=12, fontweight="bold")

    ax.set_xlim(0, 2)
    ax.set_ylim(0, 2)
    ax.set_aspect("equal")

    routings = ["estimated", "real"]   # columns
    solvers = ["toptw", "greedy"]       # rows (top→bottom): toptw on top
    for r, solver in enumerate(solvers):
        for c, routing in enumerate(routings):
            color = COLORS.get((solver, routing), "#cccccc")
            ax.add_patch(plt.Rectangle((c, 1 - r), 1, 1, facecolor=color,
                                       edgecolor="white", linewidth=3))
            ax.text(c + 0.5, 1 - r + 0.5,
                    f"{solver}\n({'haversine' if routing == 'estimated' else 'real routing'})",
                    ha="center", va="center", fontsize=10, fontweight="bold", color="white")

    ax.set_xticks([0.5, 1.5]); ax.set_xticklabels(["estimated\n(haversine)", "real\n(road)"], fontsize=9)
    ax.set_yticks([0.5, 1.5]); ax.set_yticklabels(["greedy", "toptw"], fontsize=9, fontweight="bold")
    ax.set_xlabel("Routing", fontsize=10, fontweight="bold")
    ax.set_ylabel("Solver", fontsize=10, fontweight="bold")
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.text(1.0, -0.42,
            "Only the 'real' column feeds the human study;\n'estimated' is the offline ablation arm.",
            ha="center", va="top", fontsize=8.5, style="italic", color="#555")

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "fig0b_ablation_2x2.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


if __name__ == "__main__":
    figs_dir = Path(__file__).parent / "figures"
    for p in (plot_config_space(figs_dir), plot_ablation(figs_dir)):
        print(f"saved {p}")
