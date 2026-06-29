"""Small-scale exploratory human evaluation statistics.

Queries evaluation_ratings (pairwise preference) and evaluation_likert
(whole-itinerary quality) and produces a structured report covering:

  1. Pairwise win-rate (system included POI = A chosen by human) with
     bootstrap 95% CI, broken down by pair_type. Includes win/tie/loss
     counts, effective N, and missing data warnings.
  2. Must-see gap (famous_skipped pairs): % where humans prefer B, the
     landmark that the system left out.
  3. Krippendorff α nominal on pairwise choices (overall + per pair_type).
  4. Greedy vs TOPTW: per-evaluator aggregated differences on each Likert
     dimension, tested with sign test and (if scipy available) Wilcoxon
     signed-rank test.
  5. Likert means + bootstrap 95% CI per dimension × solver. Dimensions
     are kept separate — realism, completeness, profile_fit, overall are
     never fused into a single score.
  6. Krippendorff α ordinal per Likert dimension.

This is a "small-scale exploratory human evaluation", not a conclusive
user study. With ≤5 evaluators, statistical tests have very low power.
Report findings with qualified language ("suggests", "tendency") and
always state evaluator count and effective N alongside every statistic.

Usage:
    python -m evaluation.human_eval_stats
    python -m evaluation.human_eval_stats --bootstrap-n 5000 --min-raters 3
    python -m evaluation.human_eval_stats --csv-out human_eval_summary.csv
    python -m evaluation.human_eval_stats --run-id <uuid>
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import math
import sys
from collections import defaultdict
from typing import Callable

import numpy as np
from sqlalchemy import text

from app.database import AsyncSessionLocal

try:
    from scipy.stats import wilcoxon as _scipy_wilcoxon
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

LIKERT_DIMS = ["realism", "completeness", "profile_fit", "overall"]
PAIR_TYPES = ["substitutable", "famous_skipped", "margin"]


# ── data loading ──────────────────────────────────────────────────────────────

async def _load(run_id: str | None):
    run_filter = "AND ei.run_id = :run_id" if run_id else ""

    async with AsyncSessionLocal() as db:
        r = await db.execute(
            text(f"""
                SELECT r.id, r.pair_id, r.evaluator_id, r.choice,
                       p.pair_type, p.profile_key, p.city,
                       ei.solver, ei.num_days, ei.run_id
                FROM evaluation_ratings r
                JOIN evaluation_pairs p    ON r.pair_id       = p.id
                JOIN evaluation_itineraries ei ON p.itinerary_id = ei.id
                WHERE 1=1 {run_filter}
            """),
            {"run_id": run_id} if run_id else {},
        )
        ratings = [dict(row._mapping) for row in r.fetchall()]

        l = await db.execute(
            text(f"""
                SELECT el.id, el.itinerary_id, el.evaluator_id,
                       el.realism, el.completeness, el.profile_fit, el.overall,
                       ei.solver, ei.profile_key, ei.city, ei.num_days, ei.run_id
                FROM evaluation_likert el
                JOIN evaluation_itineraries ei ON el.itinerary_id = ei.id
                WHERE 1=1 {run_filter}
            """),
            {"run_id": run_id} if run_id else {},
        )
        likert = [dict(row._mapping) for row in l.fetchall()]

    return ratings, likert


# ── Krippendorff α ────────────────────────────────────────────────────────────

def krippendorff_alpha(
    units_data: list[list],
    level: str = "nominal",
) -> float | None:
    """
    units_data: list of units; each unit is a list of rater values (None = missing).
    level: "nominal" — distance 0/1; "ordinal" — squared cumulative-frequency distance.
    Returns α ∈ (-∞, 1] or None if not enough data.
    """
    all_vals = [v for unit in units_data for v in unit if v is not None]
    if len(all_vals) < 4:
        return None

    unique_vals = sorted(set(all_vals))
    K = len(unique_vals)
    idx = {v: i for i, v in enumerate(unique_vals)}

    # Coincidence matrix (Krippendorff 2004, eq. 3)
    c = np.zeros((K, K), dtype=float)
    for unit in units_data:
        obs = [v for v in unit if v is not None]
        m = len(obs)
        if m < 2:
            continue
        cnt: dict = defaultdict(int)
        for v in obs:
            cnt[v] += 1
        for v1, n1 in cnt.items():
            for v2, n2 in cnt.items():
                i, j = idx[v1], idx[v2]
                if v1 == v2:
                    c[i, j] += n1 * (n1 - 1) / (m - 1)
                else:
                    c[i, j] += n1 * n2 / (m - 1)

    n_k = c.sum(axis=1)
    n = n_k.sum()
    if n < 2:
        return None

    if level == "nominal":
        d = 1.0 - np.eye(K)
    elif level == "ordinal":
        # d²(v,w) = (Σ_{g=min..max} n_g − (n_v + n_w)/2)²
        d = np.zeros((K, K), dtype=float)
        for i in range(K):
            for j in range(K):
                if i == j:
                    continue
                lo, hi = min(i, j), max(i, j)
                s = n_k[lo : hi + 1].sum() - (n_k[lo] + n_k[hi]) / 2
                d[i, j] = s ** 2
    else:
        raise ValueError(f"Unknown level: {level!r}")

    D_o = float((c * d).sum() / n)
    D_e = float((np.outer(n_k, n_k) * d).sum() / (n * (n - 1)))

    if D_e == 0:
        return 1.0 if D_o == 0 else None
    return 1.0 - D_o / D_e


# ── bootstrap CI ──────────────────────────────────────────────────────────────

def bootstrap_ci(
    values: list[float],
    stat_fn: Callable = np.mean,
    n_boot: int = 2000,
    ci: float = 0.95,
) -> tuple[float, float] | None:
    if len(values) < 2:
        return None
    arr = np.array(values, dtype=float)
    rng = np.random.default_rng(42)
    samples = rng.choice(arr, size=(n_boot, len(arr)), replace=True)
    stats = stat_fn(samples, axis=1)
    lo_q = (1 - ci) / 2
    return float(np.quantile(stats, lo_q)), float(np.quantile(stats, 1 - lo_q))


# ── sign test (no scipy dependency) ──────────────────────────────────────────

def sign_test(diffs: list[float]) -> tuple[int, int, float]:
    """Two-tailed sign test. Returns (n_pos, n_neg, p_value). Zeros excluded."""
    pos = sum(1 for d in diffs if d > 0)
    neg = sum(1 for d in diffs if d < 0)
    n = pos + neg
    if n == 0:
        return 0, 0, float("nan")
    k = min(pos, neg)
    p = min(2.0 * sum(math.comb(n, i) * 0.5**n for i in range(k + 1)), 1.0)
    return pos, neg, p


# ── pairwise analysis ─────────────────────────────────────────────────────────

def pairwise_stats(ratings: list[dict], min_raters: int, n_boot: int) -> dict:
    # Group by pair_id and filter by minimum rater count
    by_pair: dict[str, list[dict]] = defaultdict(list)
    for r in ratings:
        by_pair[str(r["pair_id"])].append(r)
    valid = {pid: rs for pid, rs in by_pair.items() if len(rs) >= min_raters}

    out: dict = {
        "total_pairs": len(by_pair),
        "excluded_pairs": len(by_pair) - len(valid),
        "by_type": {},
    }

    for pt in ["all"] + PAIR_TYPES:
        if pt == "all":
            pair_ids = set(valid)
        else:
            pair_ids = {pid for pid, rs in valid.items()
                        if rs and rs[0]["pair_type"] == pt}

        pair_ratings = [r for pid in pair_ids for r in valid[pid]]
        choices = [r["choice"] for r in pair_ratings]
        wins   = choices.count("a")
        losses = choices.count("b")
        ties   = choices.count("equal")
        n_dec  = wins + losses
        total  = wins + losses + ties

        win_rate = wins / n_dec if n_dec > 0 else None
        win_ci = bootstrap_ci(
            [1 if c == "a" else 0 for c in choices if c != "equal"],
            n_boot=n_boot,
        ) if n_dec >= 2 else None

        # Krippendorff α nominal: each unit = one pair_id
        units = [[r["choice"] for r in valid[pid]] for pid in pair_ids if len(valid[pid]) >= 2]
        alpha = krippendorff_alpha(units, level="nominal") if units else None

        out["by_type"][pt] = {
            "n_pairs": len(pair_ids),
            "n_ratings": len(pair_ratings),
            "wins": wins, "losses": losses, "ties": ties,
            "n_decisive": n_dec, "total": total,
            "win_rate": win_rate, "win_ci": win_ci,
            "alpha_nominal": alpha,
        }

    # Must-see gap
    fs_ids = {pid for pid, rs in valid.items()
              if rs and rs[0]["pair_type"] == "famous_skipped"}
    fs_choices = [r["choice"] for pid in fs_ids for r in valid[pid]]
    fs_b  = fs_choices.count("b")
    fs_nd = len([c for c in fs_choices if c != "equal"])
    out["must_see_gap"] = {
        "rate": fs_b / fs_nd if fs_nd > 0 else None,
        "ci": bootstrap_ci(
            [1 if c == "b" else 0 for c in fs_choices if c != "equal"],
            n_boot=n_boot,
        ) if fs_nd >= 2 else None,
        "n": fs_nd,
    }

    return out


# ── Likert analysis ───────────────────────────────────────────────────────────

def likert_stats(likert: list[dict], n_boot: int) -> dict:
    out: dict = {"by_dim": {}}
    for dim in LIKERT_DIMS:
        dim_res: dict = {"by_solver": {}, "alpha_ordinal": None}

        for solver in ["greedy", "toptw"]:
            vals = [float(r[dim]) for r in likert if r["solver"] == solver]
            dim_res["by_solver"][solver] = {
                "n": len(vals),
                "mean": float(np.mean(vals)) if vals else None,
                "ci": bootstrap_ci(vals, n_boot=n_boot) if len(vals) >= 2 else None,
            }

        # Krippendorff α ordinal: units = itinerary_ids, values = rater scores
        by_itin: dict = defaultdict(list)
        for r in likert:
            by_itin[str(r["itinerary_id"])].append(float(r[dim]))
        units = [vs for vs in by_itin.values() if len(vs) >= 2]
        dim_res["alpha_ordinal"] = (
            krippendorff_alpha(units, level="ordinal") if units else None
        )
        out["by_dim"][dim] = dim_res

    return out


# ── greedy vs TOPTW (sign test + Wilcoxon) ───────────────────────────────────

def solver_comparison(likert: list[dict]) -> dict:
    """
    Match Likert rows by (evaluator_id, profile_key, city, num_days) across solvers.
    Aggregate differences per evaluator, then apply sign test and Wilcoxon.
    """
    key_fn = lambda r: (r["evaluator_id"], r["profile_key"], r["city"], r["num_days"])
    greedy_map: dict = {}
    toptw_map:  dict = {}
    for r in likert:
        k = key_fn(r)
        if r["solver"] == "greedy":
            greedy_map[k] = r
        elif r["solver"] == "toptw":
            toptw_map[k] = r

    common = set(greedy_map) & set(toptw_map)
    out: dict = {"n_matched": len(common), "by_dim": {}}

    for dim in LIKERT_DIMS:
        diffs = [float(toptw_map[k][dim]) - float(greedy_map[k][dim]) for k in common]

        # Aggregate per evaluator → one mean difference per person
        by_eval: dict[str, list[float]] = defaultdict(list)
        for k in common:
            by_eval[k[0]].append(float(toptw_map[k][dim]) - float(greedy_map[k][dim]))
        eval_means = [float(np.mean(vs)) for vs in by_eval.values()]

        n_pos, n_neg, sign_p = sign_test(eval_means)

        w_stat, w_p = None, None
        if HAS_SCIPY and len(eval_means) >= 5:
            try:
                res = _scipy_wilcoxon(eval_means, alternative="two-sided")
                w_stat, w_p = float(res.statistic), float(res.pvalue)
            except Exception:
                pass

        out["by_dim"][dim] = {
            "n_pairs": len(diffs),
            "n_evaluators": len(eval_means),
            "greedy_mean": float(np.mean([float(greedy_map[k][dim]) for k in common])) if common else None,
            "toptw_mean":  float(np.mean([float(toptw_map[k][dim])  for k in common])) if common else None,
            "mean_diff":   float(np.mean(diffs)) if diffs else None,
            "sign_n_pos": n_pos, "sign_n_neg": n_neg, "sign_p": sign_p,
            "wilcoxon_stat": w_stat, "wilcoxon_p": w_p,
        }

    return out


# ── report ────────────────────────────────────────────────────────────────────

def _f(v, digits: int = 3) -> str:
    return "n/a" if v is None else f"{v:.{digits}f}"

def _pct(v) -> str:
    return "n/a" if v is None else f"{v*100:.1f}%"

def _ci(ci) -> str:
    return "" if ci is None else f"[{ci[0]:.3f}, {ci[1]:.3f}]"


def print_report(
    pairwise: dict,
    likert: dict,
    cmp: dict,
    ratings: list[dict],
    likert_rows: list[dict],
    min_raters: int,
) -> None:
    n_eval_pw = len({r["evaluator_id"] for r in ratings})
    n_eval_lk = len({r["evaluator_id"] for r in likert_rows})

    W = 72
    print("\n" + "=" * W)
    print("HUMAN EVALUATION — small-scale exploratory (not a conclusive study)")
    print("=" * W)
    print(f"  Pairwise : {n_eval_pw} evaluator(s)  |  "
          f"{pairwise['total_pairs']} pairs total  |  "
          f"{pairwise['total_pairs'] - pairwise['excluded_pairs']} with ≥{min_raters} raters")
    print(f"  Likert   : {n_eval_lk} evaluator(s)  |  "
          f"{len({r['itinerary_id'] for r in likert_rows})} itineraries rated")

    # ── 1. Pairwise win-rate ─────────────────────────────────────────────────
    print(f"\n── 1. PAIRWISE WIN-RATE  (A = system's included POI) {'─'*12}")
    print(f"  {'type':<20} {'win':>7} {'tie':>7} {'loss':>7}  {'95% CI':<20}  {'N_dec':>6}  α_nom")
    for pt in ["all"] + PAIR_TYPES:
        s = pairwise["by_type"].get(pt)
        if not s:
            continue
        tot = s["total"] or 1
        print(
            f"  {pt:<20} {s['wins']/tot*100:>6.1f}% "
            f"{s['ties']/tot*100:>6.1f}% "
            f"{s['losses']/tot*100:>6.1f}%  "
            f"{_ci(s['win_ci']):<20}  "
            f"{s['n_decisive']:>6}  "
            f"{_f(s['alpha_nominal'])}"
        )
    if pairwise["excluded_pairs"]:
        print(f"\n  [!] {pairwise['excluded_pairs']} pair(s) excluded (< {min_raters} raters)")

    # ── 2. Must-see gap ──────────────────────────────────────────────────────
    mg = pairwise["must_see_gap"]
    print(f"\n── 2. MUST-SEE GAP  (famous_skipped: humans prefer B = skipped landmark) ──")
    print(f"  {_pct(mg['rate'])}  95% CI {_ci(mg['ci'])}  (N decisive = {mg['n']})")
    print("  High % → system misses must-see coverage.")

    # ── 3. Greedy vs TOPTW ───────────────────────────────────────────────────
    print(f"\n── 3. GREEDY vs TOPTW  (N matched pairs = {cmp['n_matched']}) {'─'*20}")
    print("  Aggregated per evaluator × scenario; sign test on evaluator-level means.")
    print(f"  {'dim':<15} {'greedy':>7} {'toptw':>7} {'Δ':>7}  "
          f"{'sign (+/−  p)':^22}  wilcoxon (W  p)")
    for dim in LIKERT_DIMS:
        s = cmp["by_dim"].get(dim, {})
        sign_str = f"+{s['sign_n_pos']}/−{s['sign_n_neg']}  p={_f(s.get('sign_p'))}"
        if s.get("wilcoxon_stat") is not None:
            w_str = f"W={_f(s['wilcoxon_stat'], 1)}  p={_f(s['wilcoxon_p'])}"
        elif not HAS_SCIPY:
            w_str = "(scipy not installed)"
        else:
            w_str = f"(need ≥5 evaluators, have {s.get('n_evaluators',0)})"
        print(
            f"  {dim:<15} {_f(s.get('greedy_mean')):>7} {_f(s.get('toptw_mean')):>7} "
            f"{_f(s.get('mean_diff')):>7}  {sign_str:<22}  {w_str}"
        )
    if not HAS_SCIPY:
        print("  → Install scipy for Wilcoxon test: pip install scipy")

    # ── 4. Likert per dimension × solver ─────────────────────────────────────
    print(f"\n── 4. LIKERT MEANS ± 95% CI  (dimensions kept separate, never fused) ──")
    print(f"  {'dim':<15}  {'greedy mean  95% CI  N':<30}  {'toptw mean  95% CI  N':<30}  α_ord")
    for dim in LIKERT_DIMS:
        s = likert["by_dim"][dim]
        g, t = s["by_solver"]["greedy"], s["by_solver"]["toptw"]
        g_str = f"{_f(g['mean'])}  {_ci(g['ci'])}  N={g['n']}"
        t_str = f"{_f(t['mean'])}  {_ci(t['ci'])}  N={t['n']}"
        print(f"  {dim:<15}  {g_str:<30}  {t_str:<30}  {_f(s['alpha_ordinal'])}")

    print()
    print("  All results are descriptive. With ≤5 evaluators, tests have very")
    print("  low power — qualify findings with 'tendency' or 'suggests'.")
    print("  Always report N, ties, and bootstrap CIs alongside every statistic.")
    print("=" * W)


# ── CSV export ────────────────────────────────────────────────────────────────

def export_csv(
    path: str,
    pairwise: dict,
    likert: dict,
    cmp: dict,
) -> None:
    rows: list[dict] = []

    # Pairwise win-rates
    for pt, s in pairwise["by_type"].items():
        ci = s["win_ci"] or (None, None)
        rows.append({
            "section": "pairwise_win_rate",
            "group": pt,
            "metric": "win_rate",
            "value": s["win_rate"],
            "ci_lo": ci[0], "ci_hi": ci[1],
            "n": s["n_decisive"],
            "extra": f"wins={s['wins']} ties={s['ties']} losses={s['losses']} alpha_nom={_f(s['alpha_nominal'])}",
        })

    mg = pairwise["must_see_gap"]
    ci = mg["ci"] or (None, None)
    rows.append({
        "section": "must_see_gap", "group": "famous_skipped",
        "metric": "pref_B_rate", "value": mg["rate"],
        "ci_lo": ci[0], "ci_hi": ci[1], "n": mg["n"], "extra": "",
    })

    # Likert per dim × solver
    for dim, s in likert["by_dim"].items():
        for solver, sv in s["by_solver"].items():
            ci = sv["ci"] or (None, None)
            rows.append({
                "section": "likert",
                "group": f"{solver}_{dim}",
                "metric": "mean",
                "value": sv["mean"],
                "ci_lo": ci[0], "ci_hi": ci[1],
                "n": sv["n"],
                "extra": f"alpha_ord={_f(s['alpha_ordinal'])}",
            })

    # Solver comparison
    for dim, s in cmp["by_dim"].items():
        rows.append({
            "section": "solver_comparison",
            "group": dim,
            "metric": "mean_diff_toptw_minus_greedy",
            "value": s["mean_diff"],
            "ci_lo": None, "ci_hi": None,
            "n": s["n_pairs"],
            "extra": (
                f"greedy={_f(s['greedy_mean'])} toptw={_f(s['toptw_mean'])} "
                f"sign+={s['sign_n_pos']} sign-={s['sign_n_neg']} sign_p={_f(s['sign_p'])} "
                f"wilcoxon_p={_f(s.get('wilcoxon_p'))}"
            ),
        })

    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["section", "group", "metric",
                                                 "value", "ci_lo", "ci_hi", "n", "extra"])
        writer.writeheader()
        writer.writerows(rows)


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Human evaluation statistics for EasyTravel thesis")
    ap.add_argument("--run-id",      default=None, help="Filter to a single evaluation run UUID")
    ap.add_argument("--min-raters",  type=int, default=3,    help="Min raters per pair for α (default 3)")
    ap.add_argument("--bootstrap-n", type=int, default=2000, help="Bootstrap iterations (default 2000)")
    ap.add_argument("--csv-out",     default=None, help="Write summary CSV to this path")
    args = ap.parse_args()

    ratings, likert_rows = asyncio.run(_load(args.run_id))

    if not ratings and not likert_rows:
        print("No human evaluation data found. Run the evaluation dashboard first.", file=sys.stderr)
        sys.exit(1)

    pw  = pairwise_stats(ratings, min_raters=args.min_raters, n_boot=args.bootstrap_n)
    lk  = likert_stats(likert_rows, n_boot=args.bootstrap_n)
    cmp = solver_comparison(likert_rows)

    print_report(pw, lk, cmp, ratings, likert_rows, min_raters=args.min_raters)

    if args.csv_out:
        export_csv(args.csv_out, pw, lk, cmp)
        print(f"\nWrote summary CSV → {args.csv_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
