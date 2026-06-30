# Thesis Structure and Research Questions

This document is the working reference for restructuring the EasyTravel master's
thesis before translating and revising the full text in English.

## Working title

**Preference-Aware Multi-Day Itinerary Planning: An End-to-End System Based on
LLM-Enriched Points of Interest and TOPTW**

## Proposed thesis structure

### 1. Introduction

1. Context and motivation
2. Problem statement
3. Research questions
4. Objectives and scope
5. Main contributions
6. Thesis structure

### 2. Background and Related Work

1. Travel recommender systems
2. User preference and POI representation
3. Content-based recommendation, diversity, and popularity bias
4. Orienteering Problem, TOP, and TOPTW
5. Geographical clustering and itinerary construction
6. LLM-assisted POI enrichment
7. Research gap

### 3. EasyTravel System Design

1. Functional requirements and use case
2. End-to-end architecture
3. Frontend, backend, and external services
4. User onboarding and preference modeling
5. Database architecture and data flow
6. Main design decisions

### 4. POI Acquisition and Enrichment

1. POI data requirements
2. Acquisition from Google Places
3. Tourism validation
4. Semantic classification and feature representation
5. Opening hours and travel-time acquisition
6. LLM reliability, cost, and traceability
7. Limitations

Operational details such as complete CLI flag lists, prompts, database fields,
and full parameter tables should be moved to the appendices unless they are
required to explain a methodological contribution.

### 5. Itinerary Planning Methods

1. Formal problem definition
2. Shared preprocessing, utility, and constraints
3. Greedy baseline
4. Proposed hybrid TOPTW approach
5. Geographical pre-clustering
6. Intra-day TSPTW reordering
7. Meal insertion and underfull-day filling
8. Complexity and reproducibility
9. Limitations

The proposed method should be described as a **hybrid TOPTW-based planning
approach**, rather than as a single global optimization step, because it also
contains pre-clustering, post-optimization reordering, meal insertion, and
underfull-day filling.

### 6. Experimental Methodology

1. Research questions and hypotheses
2. Datasets and preprocessing
3. Cities, user profiles, and travel scenarios
4. Candidate-pool and trip-size configurations
5. Compared planning methods and ablations
6. Evaluation metrics
7. Statistical analysis
8. Reproducibility protocol

### 7. Results and Discussion

1. RQ1 results: utility, feasibility, and scalability
2. RQ1 factorial and ablation analysis
3. RQ2 results: behavioral alignment and personalization
4. Qualitative divergence analysis
5. Interpretation and practical implications
6. Threats to validity

### 8. Conclusions and Future Work

1. Answers to the research questions
2. Demonstrated contributions
3. Limitations
4. Future work

## Research questions

### RQ1 — Planning quality and feasibility

**Under identical planning constraints, how does the TOPTW-based planner
compare with the greedy baseline in terms of collected utility, real-world
feasibility, and scalability?**

#### RQ1a — Utility and optimality

How much additional utility does TOPTW collect, and what optimality gap does
each method exhibit on small instances for which an optimal solution can be
certified?

#### RQ1b — External feasibility

When itineraries are re-evaluated using a common matrix of API-derived travel
times, how frequently and by how much does each method violate POI time windows
or the daily time budget?

#### RQ1c — Scalability

How do solution quality, feasibility, and runtime change as the number of
candidate POIs and travel days increases?

#### RQ1 hypotheses

- **H1a:** TOPTW collects higher total utility than greedy.
- **H1b:** TOPTW produces fewer and smaller feasibility violations under
  API-derived travel times.
- **H1c:** The advantage of TOPTW increases with instance size, at the cost of
  higher runtime.

### RQ2 — Recommendation validity and personalization

**To what extent do the generated itineraries align with observed tourist
trajectories while remaining responsive to user preferences?**

#### RQ2a — Behavioral alignment

How closely do the selected POIs and their visiting order match held-out
reference trajectories?

#### RQ2b — Divergence analysis

When generated itineraries diverge from the reference trajectories, are the
differences associated with greater external feasibility or independently
assessed recommendation quality?

#### RQ2c — Personalization

To what extent do different preference profiles produce meaningfully different
itineraries rather than converging on the same popular POIs?

#### RQ2 hypotheses

- **H2a:** TOPTW aligns with observed trajectories at least as well as greedy
  while producing more feasible itineraries.
- **H2b:** Relevant divergences from the reference trajectories are primarily
  associated with improved external feasibility or independently assessed
  quality, rather than arbitrary errors.
- **H2c:** Changes in the user preference profile cause measurable and
  preference-consistent changes in the generated itineraries.

## RQ1 factorial design

| Planner | Estimated routing | API-derived routing |
|---|---|---|
| Greedy | Original baseline | Routing-aware greedy |
| TOPTW | TOPTW with estimated costs | Proposed system |

All four outputs must be re-evaluated using the same external travel-time
matrix. This separates the contribution of the planning algorithm from the
contribution of the routing data.

The thesis should distinguish two comparisons:

1. **System comparison:** complete greedy baseline versus the complete proposed
   system.
2. **Algorithm comparison:** greedy versus TOPTW while keeping all shared
   preprocessing, post-processing, constraints, routing data, and candidate
   pools fixed.

## Core evaluation metrics

### RQ1

- Collected utility
- Percentage optimality or bound gap
- Number of scheduled POIs
- Percentage of itineraries with at least one violation
- Time-window violations per day
- Total lateness in minutes
- Daily-budget overflow in minutes
- Travel time and route compactness
- Runtime, timeout rate, and memory use

### RQ2

- POI-set precision, recall, F1, and Jaccard similarity
- Order agreement on common POIs, such as Kendall rank correlation
- Intra-list diversity
- Inter-profile itinerary distance
- Catalog coverage
- Preference–itinerary alignment
- Popularity bias
- Qualitative or human pairwise assessment of divergences

## Methodological safeguards

1. **Certified optimum:** OR-Tools Routing does not certify a global optimum.
   RQ1a therefore requires an exact formulation for small instances that
   reports either a certified optimum or a valid upper bound.

2. **Gap terminology:** use
   \((U^*-U)/U^*\) only when the optimum \(U^*\) is known. If only an upper
   bound is known, report \((UB-U)/UB\) explicitly as a bound gap.

3. **Visit feasibility:** a visit is feasible only if it finishes before
   closing:
   \(a_i \leq start_i\) and \(start_i + \tau_i \leq close_i\).
   If the model uses \(b_i\) as a latest-start value, define
   \(b_i=close_i-\tau_i\) explicitly.

4. **Common evaluation oracle:** the same API-derived travel-time matrix and
   feasibility replay procedure must be used for all experimental arms.
   API-derived times should be described as network-based estimates rather
   than absolute ground truth.

5. **No circular validation:** a TOPTW divergence cannot be judged better only
   because it has a higher value under the same utility function optimized by
   TOPTW. RQ2b requires external feasibility, human assessment, or another
   independent criterion.

6. **Trajectory terminology:** Flickr and similar datasets provide observed
   reference trajectories and incomplete behavioral proxies, not exhaustive
   ground truth.

7. **Leakage prevention:** preference profiles and candidates must be derived
   without using the held-out visits later employed for evaluation.

8. **Controlled recommendation length:** set-based and order-based comparisons
   must control for itinerary length, temporal budget, and candidate
   availability.

9. **Statistical analysis:** use paired tests because the methods are evaluated
   on the same scenarios. Planned pairwise comparisons can use the Wilcoxon
   signed-rank test with rank-biserial effect size and confidence intervals.
   A factorial or mixed-effects analysis is required to estimate interactions
   between planner, routing model, candidate-pool size, and trip duration.

## Existing material placement

| Current material | Target location |
|---|---|
| Database architecture | Chapter 3 |
| POI pipeline | Chapter 4 |
| Greedy solver | Chapter 5 |
| TOPTW solver | Chapter 5 |
| Technical limitations | Chapters 4–5 and Chapter 7 |
| CLI flags, full prompts, and complete parameter lists | Appendices |

## Recommended work order

1. Freeze the research questions, hypotheses, utility definition, and
   feasibility criteria.
2. Rebuild the thesis skeleton around the proposed structure.
3. Define and implement the evaluation protocol.
4. Run the experiments and prepare the result tables.
5. Complete the missing introduction, related work, system, evaluation, and
   conclusion sections.
6. Resolve contradictions and move secondary implementation details to the
   appendices.
7. Translate and revise the complete thesis in consistent academic English.
8. Write the abstract last, after the results and conclusions are stable.
