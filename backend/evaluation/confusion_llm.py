"""LLM1 vs LLM2 category confusion matrix for the classifier agreement analysis (§4.5.4).

Makes the reported Cohen's κ concrete: κ is a single number, the matrix shows
*where* the two parallel calls diverge and which pairs the arbitration pass had
to resolve. Reads ``poi_classification_logs`` — the same rows the κ in §4.5.4 is
computed from — and reuses ``pipeline.evaluation.cohens_kappa`` so the printed
κ cannot drift from the one already in the thesis.

Run:
    python -m evaluation.confusion_llm                  # all cities
    python -m evaluation.confusion_llm --city Madrid
    python -m evaluation.confusion_llm --latex          # LaTeX table to stdout
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from pathlib import Path

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.classification_log import PoiClassificationLog
from pipeline.evaluation import _kappa_label, cohens_kappa

# Fixed order so the diagonal is stable across runs and cities; the seven
# travel categories of §4.5, most frequent first for readability.
CATEGORIES = ["culture", "food", "nature", "relax", "family", "nightlife", "adventure"]


async def load_pairs(city: str | None) -> list[tuple[str, str]]:
    """Paired (LLM1, LLM2) labels for POIs where both calls returned a category."""
    async with AsyncSessionLocal() as db:
        q = select(PoiClassificationLog)
        if city:
            q = q.where(PoiClassificationLog.city_name == city)
        logs = (await db.execute(q)).scalars().all()
    return [
        (l.llm1_category, l.llm2_category)
        for l in logs
        if l.llm1_category and l.llm2_category
    ]


def build_matrix(pairs: list[tuple[str, str]]) -> tuple[list[str], dict]:
    """Confusion counts keyed (llm1, llm2); category list covers whatever occurred."""
    seen = {c for p in pairs for c in p}
    cats = [c for c in CATEGORIES if c in seen] + sorted(seen - set(CATEGORIES))
    return cats, Counter(pairs)


def print_matrix(cats: list[str], m: Counter, pairs: list[tuple[str, str]]) -> None:
    n = len(pairs)
    agree = sum(m[(c, c)] for c in cats)
    k = cohens_kappa([p[0] for p in pairs], [p[1] for p in pairs])

    w = max(len(c) for c in cats) + 1
    print(f"\nLLM1 (rows) × LLM2 (cols) — n = {n}")
    print(" " * w + "".join(f"{c[:6]:>8}" for c in cats) + f"{'row Σ':>8}")
    for r in cats:
        row = [m[(r, c)] for c in cats]
        print(f"{r:<{w}}" + "".join(f"{v:>8}" for v in row) + f"{sum(row):>8}")
    print(" " * w + "".join(f"{sum(m[(r, c)] for r in cats):>8}" for c in cats))

    print(f"\nobserved agreement : {agree}/{n} = {agree / n:.3f}")
    print(f"Cohen's kappa      : {k:.3f}  ({_kappa_label(k)}, Landis & Koch)")
    print(f"disagreements      : {n - agree}")

    off = Counter()
    for (a, b), v in m.items():
        if a != b:
            off[tuple(sorted((a, b)))] += v
    if off:
        print("\nmost frequent disagreeing pairs (unordered):")
        for (a, b), v in off.most_common(5):
            print(f"  {a} ↔ {b}: {v}")


def to_latex(cats: list[str], m: Counter, pairs: list[tuple[str, str]]) -> str:
    n = len(pairs)
    agree = sum(m[(c, c)] for c in cats)
    k = cohens_kappa([p[0] for p in pairs], [p[1] for p in pairs])
    head = " & ".join(f"\\textbf{{{c}}}" for c in cats)
    lines = [
        "\\begin{table}[htbp]",
        "\\centering",
        f"\\caption{{LLM1 (rows) against LLM2 (columns) travel-category assignments over "
        f"{n} POIs. Diagonal entries are agreements ({agree}, {agree / n * 100:.1f}\\%); "
        f"Cohen's $\\kappa = {k:.3f}$.}}",
        "\\label{tab:llm-confusion}",
        "\\begin{tabular}{l" + "r" * len(cats) + "}",
        "\\hline",
        f"& {head} \\\\",
        "\\hline",
    ]
    for r in cats:
        cells = " & ".join(
            (f"\\textbf{{{m[(r, c)]}}}" if r == c and m[(r, c)] else str(m[(r, c)]))
            for c in cats
        )
        lines += [f"\\textbf{{{r}}} & {cells} \\\\"]
    lines += ["\\hline", "\\end{tabular}", "\\end{table}"]
    return "\n".join(lines)


def plot(cats: list[str], m: Counter, pairs: list[tuple[str, str]], out: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print("matplotlib not installed — skipping figure")
        return

    n = len(pairs)
    k = cohens_kappa([p[0] for p in pairs], [p[1] for p in pairs])
    M = np.array([[m[(r, c)] for c in cats] for r in cats], dtype=float)
    # Row-normalise: raw counts are dominated by culture (~52% of POIs), which
    # would leave every other cell invisible on a shared colour scale.
    rows = M.sum(axis=1, keepdims=True)
    P = np.divide(M, rows, out=np.zeros_like(M), where=rows > 0)

    fig, ax = plt.subplots(figsize=(7.2, 6.0))
    im = ax.imshow(P, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(cats)), cats, rotation=45, ha="right")
    ax.set_yticks(range(len(cats)), cats)
    ax.set_xlabel("LLM2 category")
    ax.set_ylabel("LLM1 category")
    ax.set_title(
        f"LLM1 vs LLM2 category agreement (n = {n})\n"
        f"cell = count, shading = row share; $\\kappa$ = {k:.3f}",
        fontsize=11,
    )
    for i in range(len(cats)):
        for j in range(len(cats)):
            if M[i, j]:
                ax.text(j, i, int(M[i, j]), ha="center", va="center",
                        fontsize=9, color="white" if P[i, j] > 0.55 else "#222")
    fig.colorbar(im, ax=ax, label="share of LLM1 row", fraction=0.046)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"\nfigure → {out}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default=None, help="Restrict to one city (default: all)")
    ap.add_argument("--latex", action="store_true", help="Also print a LaTeX table")
    ap.add_argument("--out", default="evaluation/figures/fig6_llm_confusion.png")
    args = ap.parse_args()

    pairs = await load_pairs(args.city)
    if not pairs:
        print("No paired LLM1/LLM2 labels found.")
        return
    cats, m = build_matrix(pairs)
    print_matrix(cats, m, pairs)
    if args.latex:
        print("\n" + to_latex(cats, m, pairs))
    plot(cats, m, pairs, Path(args.out))


if __name__ == "__main__":
    asyncio.run(main())
