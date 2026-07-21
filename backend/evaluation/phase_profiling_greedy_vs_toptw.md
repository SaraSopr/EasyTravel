# Phase profiling — greedy vs TOPTW (where does the time go)

Measured with `app.services._phase_timer` (permanent instrumentation, disabled by
default — set `PHASE_PROFILING_ENABLED=true` in `.env` to re-enable). No behaviour
change, just timers wrapped around the existing phases.

**Scenarios** (same profile/city/duration, solver and routing varied): Rome/couple_foodie/2d,
Madrid/family_toddlers/4d, Porto/young_solo_outdoor/2d. Raw per-scenario data in
[phase_profiling_greedy_vs_toptw.csv](phase_profiling_greedy_vs_toptw.csv).

## Aggregated table (avg ms across the 3 scenarios)

| Phase | greedy/estimated | greedy/real | TOPTW/estimated | TOPTW/real |
|---|---:|---:|---:|---:|
| **total (wall-clock)** | 196.2 | 823.9 | 89.8 | 358.2 |
| routing_prefetch (external calls) | 0 | **437.6** | 0 | **236.6** |
| mmr_select | 155.9 | 177.2 | — | — |
| select_candidates | — | — | 0.5 | 0.7 |
| clustering / pre_cluster | ~22.7* | ~22.7* | ~21–27 | ~21–27 |
| solve (OR-Tools MILP) | — | — | 40.6 | 60.1 |
| tsp_reorder / tsptw_reorder | 2.5 | 64.8 | 17.6 | 19.0 |
| schedule_day_total (Pass1+TSP+meal+refill, greedy) | 6.4 | 73.1 | — | — |
| underfull_fill | — | — | 0.1 | 0.1 |
| meal_insertion | 1.2 | 2.6 | 1.6 | 1.6 |

\* the "clustering" value on the very first real-routing run (116ms) was a warm-up
artifact (first import of the clustering module in the process); discarded and
replaced with the steady-state value (~22ms), comparable to TOPTW's `pre_cluster`.

## Takeaway

TOPTW's MILP is not "magically fast": the OR-Tools `solve` step costs 40–60ms, a
real and non-negligible cost. The gap is structural, not algorithmic: greedy calls
`prefetch_travel_matrix` once per day of the trip (N round-trips to the routing
cache/external API), while TOPTW does it once for the whole trip in a single batch
— this alone explains ~200ms of the ~465ms gap under real routing. Even stripping
out network I/O entirely (the "estimated" arm), greedy's pure computation is still
~2× slower (196ms vs 90ms), because greedy re-runs MMR selection (diversity +
relevance) once per day, whereas TOPTW selects candidates once, globally, with a
simple prize sort (sub-millisecond). Bottom line: TOPTW wins because it makes fewer
external calls and less repeated per-day work, not because its internal solver is
cheaper than greedy's heuristic pipeline.
