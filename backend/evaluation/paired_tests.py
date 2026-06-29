"""Paired non-parametric significance tests on the 2x2 ablation.

Promotes the RQ1 results from descriptive means to paired inference, using the
data already produced by run_eval.py — no new generation runs required.

Pairing unit = scenario = (profile_key, city, num_days) -> 9*3*2 = 54 matched
scenarios. Cells:
    A = greedy/estimated   B = greedy/real   C = toptw/estimated   D = toptw/real

For every metric and every contrast we report the median/mean paired difference
(hi - lo), win/loss/tie counts, a Wilcoxon signed-rank p-value (drops zero diffs)
and a sign-test p-value (binomial on non-tie pairs). p-values are Holm-corrected
within each contrast's 8-metric family.

Caveats to keep in the write-up:
  * the 54 scenarios are a fixed grid, not a random sample — read significance as
    "effect consistent across the tested grid", not population inference;
  * overrun/landmark/stops are tie-heavy, so a non-significant Wilcoxon there is
    often low power (floor effect), not evidence of equality.

Usage:
    python -m evaluation.paired_tests [path/to/metrics_2x2.csv]   # console tables
    python -m evaluation.paired_tests --latex                     # LaTeX for the thesis
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd
from scipy.stats import binomtest, wilcoxon

KEY = ["profile_key", "city", "num_days"]
CELLS = {
    "A": ("greedy", "estimated"),
    "B": ("greedy", "real"),
    "C": ("toptw", "estimated"),
    "D": ("toptw", "real"),
}
# metric -> (label, higher_is_better)
METRICS = {
    "avg_relevance": ("Avg.\\ relevance", True),
    "total_relevance": ("Total relevance", True),
    "real_overrun_day_rate": ("Overrun rate", False),
    "intra_list_diversity": ("Diversity", True),
    "landmark_coverage": ("Landmark cov.", True),
    "stops_per_day": ("Stops/day", True),
    "idle_minutes_per_day": ("Idle min/day", False),
    "solve_time_ms": ("Solve time (ms)", False),
}
CONTRASTS = [("A", "C"), ("B", "D"), ("A", "B"), ("C", "D")]
# the two algorithm contrasts the thesis RQ1 narrative needs
LATEX_CONTRASTS = [("A", "C"), ("B", "D")]


def _cell(df: pd.DataFrame, letter: str) -> pd.DataFrame:
    solver, routing = CELLS[letter]
    return df[(df.solver == solver) & (df.routing == routing)].set_index(KEY)


def holm(pvals: np.ndarray) -> np.ndarray:
    """Holm-Bonferroni step-down adjustment."""
    order = np.argsort(pvals)
    m = len(pvals)
    adj = np.empty(m)
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, (m - rank) * pvals[idx])
        adj[idx] = min(running, 1.0)
    return adj


def analyse(df: pd.DataFrame, lo: str, hi: str) -> pd.DataFrame:
    a, b = _cell(df, lo), _cell(df, hi)
    common = a.index.intersection(b.index)
    rows, raw_p = [], []
    for metric, (_, hib) in METRICS.items():
        x = a.loc[common, metric].astype(float).to_numpy()
        y = b.loc[common, metric].astype(float).to_numpy()
        d = y - x  # positive = 'hi' cell larger
        wins, losses = int((d > 0).sum()), int((d < 0).sum())
        ties = int((d == 0).sum())
        wp = (
            wilcoxon(x, y, zero_method="wilcox", alternative="two-sided").pvalue
            if wins + losses
            else np.nan
        )
        sp = binomtest(wins, wins + losses, 0.5).pvalue if wins + losses else np.nan
        raw_p.append(wp if wp == wp else 1.0)
        better, worse = (wins, losses) if hib else (losses, wins)
        rows.append(
            dict(
                metric=metric,
                median=float(np.median(d)),
                mean=float(d.mean()),
                better=better,
                worse=worse,
                ties=ties,
                wilcoxon_p=wp,
                sign_p=sp,
                higher_better=hib,
            )
        )
    out = pd.DataFrame(rows)
    out["holm_p"] = holm(np.array(raw_p))
    out.attrs["n"] = len(common)
    return out


def print_console(df: pd.DataFrame) -> None:
    for lo, hi in CONTRASTS:
        res = analyse(df, lo, hi)
        print(
            f"\n{'='*92}\nCONTRAST {lo}->{hi}  "
            f"({CELLS[lo][0]}/{CELLS[lo][1]} -> {CELLS[hi][0]}/{CELLS[hi][1]})  "
            f"n={res.attrs['n']}"
        )
        print(
            f"{'metric':<24}{'med Δ':>10}{'mean Δ':>10}"
            f"{'win/loss/tie':>16}{'Wilcoxon':>11}{'Holm':>9}{'sign':>9}"
        )
        print("-" * 92)
        for _, r in res.iterrows():
            star = "*" if (r.holm_p == r.holm_p and r.holm_p < 0.05) else " "
            arrow = "↑" if r.higher_better else "↓"
            print(
                f"{r.metric:<24}{r['median']:>10.4f}{r['mean']:>10.4f}"
                f"{f'{int(r.better)}/{int(r.worse)}/{int(r.ties)}':>16}"
                f"{r.wilcoxon_p:>11.4f}{r.holm_p:>8.3f}{star}{r.sign_p:>9.4f}"
            )
        print("  (win/loss/tie oriented to the better direction; * survives Holm@.05)")


def print_latex(df: pd.DataFrame) -> None:
    res = {f"{lo}{hi}": analyse(df, lo, hi) for lo, hi in LATEX_CONTRASTS}
    n = next(iter(res.values())).attrs["n"]

    def fmt(r):
        sig = "$^{*}$" if (r.holm_p == r.holm_p and r.holm_p < 0.05) else ""
        p = "$<$0.001" if r.holm_p < 0.001 else f"{r.holm_p:.3f}"
        return f"{r['median']:+.4f}{sig}", p

    print(r"\begin{table}[t]")
    print(r"\centering")
    print(
        r"\caption{Paired significance of the planner change (greedy$\to$TOPTW) at "
        r"each routing model, over the " + str(n) + r" matched scenarios "
        r"(9 profiles $\times$ 3 cities $\times$ 2 durations). $\Delta$ is the median "
        r"paired difference TOPTW$-$greedy; $p$ is the Holm-adjusted Wilcoxon "
        r"signed-rank value within each column. $^{*}$ significant at .05.}"
    )
    print(r"\label{tab:paired-rq1}")
    print(r"\begin{tabular}{lcccc}")
    print(r"\toprule")
    print(
        r" & \multicolumn{2}{c}{A$\to$C (Haversine)} "
        r"& \multicolumn{2}{c}{B$\to$D (real routing)} \\"
    )
    print(r"\cmidrule(lr){2-3}\cmidrule(lr){4-5}")
    print(r"Metric & median $\Delta$ & Holm $p$ & median $\Delta$ & Holm $p$ \\")
    print(r"\midrule")
    for metric, (label, _) in METRICS.items():
        ac = res["AC"].set_index("metric").loc[metric]
        bd = res["BD"].set_index("metric").loc[metric]
        ac_d, ac_p = fmt(ac)
        bd_d, bd_p = fmt(bd)
        print(f"{label} & {ac_d} & {ac_p} & {bd_d} & {bd_p} \\\\")
    print(r"\bottomrule")
    print(r"\end{tabular}")
    print(r"\end{table}")


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--latex"]
    path = args[0] if args else "metrics_2x2.csv"
    df = pd.read_csv(path)
    if "--latex" in sys.argv[1:]:
        print_latex(df)
    else:
        print_console(df)


if __name__ == "__main__":
    main()
