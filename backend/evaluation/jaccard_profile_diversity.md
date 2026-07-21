# Inter-profile Jaccard similarity (POI set diversification)

Computed on the 216 cells in `evaluation_itineraries` (9 profiles × 3 cities × 2
durations × 2 solvers × 2 routings). POI set per cell = included **activity** POIs
(`candidates_json` where `included=true`; food stops excluded). Jaccard(A, B) =
|A∩B| / |A∪B|. Per-control breakdown in
[jaccard_profile_diversity_per_control.csv](jaccard_profile_diversity_per_control.csv).

## Summary table

| Comparison | n pairs | mean Jaccard | min | max |
|---|---:|---:|---:|---:|
| (a) **Different profiles**, same city/duration/solver/routing (control) | 864 | **0.453** | 0.00 | 0.90 |
| (b1) **Same profile**, same city, different duration (solver/routing fixed) | 108 | **0.383** | 0.14 | 0.63 |
| (b2) **Same profile**, different city (any duration/solver/routing) | 216 | 0.000 | 0.00 | 0.00 |

(b2) is a degenerate control, not a real baseline: POI ids are city-specific, so
cross-city Jaccard is 0 by construction, independent of the profile. Kept only for
completeness since the request explicitly asked to vary city/duration.

## Breakdown of (a) — different profiles

| By solver | mean Jaccard | n |
|---|---:|---:|
| greedy | 0.485 | 432 |
| toptw | 0.420 | 432 |

| By city | mean Jaccard | n |
|---|---:|---:|
| Roma | 0.567 | 288 |
| Madrid | 0.395 | 288 |
| Porto | 0.395 | 288 |

| By routing | mean Jaccard | n |
|---|---:|---:|
| estimated | 0.453 | 432 |
| real | 0.452 | 432 |

**Most differentiated profile pairs** (lowest mean Jaccard, aggregated over all
controls): `couple_museums`↔`family_toddlers` (0.277), `family_toddlers`↔`senior_solo_culture`
(0.288), `couple_museums`↔`family_teen` (0.295).

**Least differentiated profile pairs** (highest mean Jaccard): `young_solo_outdoor`↔`young_solo_relax`
(0.643), `couple_foodie`↔`couple_generalist` (0.628), `couple_museums`↔`senior_solo_culture` (0.606).

## Interpretation

Different profiles do get measurably different POI sets — the diff-profile Jaccard
(0.453) is comparable to, and even slightly *higher* than, the same-profile
same-city Jaccard across durations (0.383), so profile identity is not obviously a
weaker driver of selection than trip length is. The picture is uneven, though:
profile pairs that differ on a concrete constraint (family with children vs.
culture-focused solo/senior) separate cleanly (~0.28–0.30), while pairs with
similar underlying interests (young solo outdoor vs. relax, or the two "couple"
profiles) overlap much more (~0.60–0.64) — plausibly a real preference-vector
effect, not noise. Roma stands out with much higher overlap (0.567) than Madrid or
Porto (0.395 each). **Correction**: this is *not* explained by a smaller classified-POI
pool — checked directly against the `pois` table (2026-07-21), Roma actually has more
production-classified POIs (1102) than Madrid (397) or Porto (410); an earlier note in
memory about Roma having "only 5 classified POIs" refers to a different, unrelated
dataset (`poi_classification_logs`, the LLM1/LLM2 inter-rater-agreement sample used only
in the classifier test, not the planner's candidate pool — see
[[roma-partial-classification]], now corrected). The real driver of Roma's higher overlap
is still open — plausibly geographic density or city size — and needs separate
verification before it goes in the thesis. **This measures algorithmic diversification
only** — it says
whether different profiles receive different POIs, not whether those POIs are the
*right* ones for each profile or whether users would be satisfied; it is a
descriptive statistic, not evidence of profile correctness or causal validity.
