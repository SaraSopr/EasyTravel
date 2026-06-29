"""Figure: the full evaluation configuration space (factorial design).

Renders every test-matrix axis (profiles × cities × durations × solvers × routings)
and the 2×2 solver×routing ablation that is the core of the comparison. Values are
read live from ``config`` / ``profiles`` so the figure can never drift from what the
harness actually runs.

Run:
    python -m evaluation.plot_config_space          # saves figures/fig0_config_space.png
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

from evaluation import config as cfg
from evaluation.profiles import PROFILES

# Same palette as analysis.py so the 2×2 cells match the other thesis figures.
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
        ("Profili", [p.key for p in PROFILES]),
        ("Città", list(cfg.CITIES)),
        ("Durate", [f"{d} giorni" for d in cfg.DURATIONS]),
        ("Solver", list(cfg.SOLVERS)),
        ("Routing", list(cfg.ROUTINGS)),
    ]


def _wrap(values: list[str], per_line: int) -> str:
    lines = [", ".join(values[i:i + per_line]) for i in range(0, len(values), per_line)]
    return "\n".join(lines)


def plot(out_dir: Path) -> Path:
    factors = _factor_values()
    counts = [len(v) for _, v in factors]
    total = 1
    for c in counts:
        total *= c

    fig, (axL, axR) = plt.subplots(
        1, 2, figsize=(14, 6.2), gridspec_kw={"width_ratios": [1.75, 1]}
    )
    fig.suptitle(
        f"Spazio di configurazione della valutazione — design fattoriale completo "
        f"({' × '.join(map(str, counts))} = {total} itinerari)",
        fontsize=12, fontweight="bold",
    )

    # ── Left: the factorial chain (one row per axis) ───────────────────────────
    axL.set_xlim(0, 10)
    axL.set_ylim(0, 10)
    axL.axis("off")
    axL.set_title("Assi della matrice di test", fontsize=10, fontweight="bold", pad=6)

    n = len(factors)
    top, bottom = 9.2, 1.6
    row_h = (top - bottom) / n
    per_line = {"Profili": 3}  # profiles are many → wrap 3 per line; others fit on one
    for i, (label, values) in enumerate(factors):
        yc = top - (i + 0.5) * row_h
        # count badge box on the left
        box = FancyBboxPatch(
            (0.2, yc - row_h * 0.36), 2.1, row_h * 0.72,
            boxstyle="round,pad=0.02,rounding_size=0.12",
            linewidth=1.4, edgecolor=FACTOR_C, facecolor="#eaf2fb",
        )
        axL.add_patch(box)
        axL.text(1.25, yc, f"{label}\n(×{len(values)})", ha="center", va="center",
                 fontsize=10, fontweight="bold", color=FACTOR_C)
        # "×" between rows
        if i < n - 1:
            axL.text(1.25, yc - row_h * 0.5, "×", ha="center", va="center",
                     fontsize=13, color="#777")
        # values on the right
        axL.text(2.7, yc, _wrap(values, per_line.get(label, len(values))),
                 ha="left", va="center", fontsize=8.5, family="monospace", color="#222")

    # total bar at the bottom
    axL.add_patch(FancyBboxPatch(
        (0.2, 0.45), 9.3, 0.85, boxstyle="round,pad=0.02,rounding_size=0.12",
        linewidth=1.6, edgecolor="#d94801", facecolor="#fff1e6",
    ))
    axL.text(4.85, 0.87,
             f"Totale = {' × '.join(map(str, counts))} = {total} itinerari generati",
             ha="center", va="center", fontsize=11, fontweight="bold", color="#d94801")

    # ── Right: the 2×2 ablation grid (solver × routing) ────────────────────────
    axR.set_xlim(0, 2)
    axR.set_ylim(0, 2)
    axR.set_aspect("equal")
    axR.set_title("Ablazione 2×2 — core del confronto\n(isola algoritmo da routing)",
                  fontsize=10, fontweight="bold", pad=6)

    routings = ["estimated", "real"]   # columns
    solvers = ["toptw", "greedy"]       # rows (top→bottom): toptw on top
    for r, solver in enumerate(solvers):
        for c, routing in enumerate(routings):
            color = COLORS.get((solver, routing), "#cccccc")
            axR.add_patch(plt.Rectangle((c, 1 - r), 1, 1, facecolor=color,
                                        edgecolor="white", linewidth=3))
            axR.text(c + 0.5, 1 - r + 0.5,
                     f"{solver}\n({'haversine' if routing == 'estimated' else 'real routing'})",
                     ha="center", va="center", fontsize=9.5, fontweight="bold",
                     color="white")
    # axis labels
    axR.set_xticks([0.5, 1.5]); axR.set_xticklabels(["estimated\n(haversine)", "real\n(road)"], fontsize=9)
    axR.set_yticks([0.5, 1.5]); axR.set_yticklabels(["greedy", "toptw"], fontsize=9, fontweight="bold")
    axR.set_xlabel("Routing", fontsize=10, fontweight="bold")
    axR.set_ylabel("Solver", fontsize=10, fontweight="bold")
    axR.tick_params(length=0)
    for s in axR.spines.values():
        s.set_visible(False)
    axR.text(1.0, -0.42,
             "Solo la colonna 'real' alimenta la human-eval;\n'estimated' è il braccio offline dell'ablazione.",
             ha="center", va="top", fontsize=8, style="italic", color="#555")

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "fig0_config_space.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


if __name__ == "__main__":
    path = plot(Path(__file__).parent / "figures")
    print(f"saved {path}")
