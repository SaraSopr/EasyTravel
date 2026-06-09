# EasyTravel — Backend

Personalized travel itinerary generator. A FastAPI backend that discovers Points of Interest
via Google Places, classifies them with a 3-LLM ensemble, and plans optimized multi-day
itineraries using geographic clustering, Maximal Marginal Relevance selection, and
cosine-similarity-based preference matching.

---

## Table of Contents

1. [Stack](#stack)
2. [Prerequisites & Setup](#prerequisites--setup)
3. [Environment Variables](#environment-variables)
4. [Running the Server](#running-the-server)
5. [Database Migrations](#database-migrations)
6. [API Reference](#api-reference)
7. [Auth System](#auth-system)
8. [POI Pipeline](#poi-pipeline)
9. [LLM Classification](#llm-classification)
10. [Tourism Validation](#tourism-validation)
11. [Itinerary Planner](#itinerary-planner)
12. [Evaluation Dashboard](#evaluation-dashboard)
13. [Data Model Overview](#data-model-overview)
14. [Feature Vector & Categories](#feature-vector--categories)
15. [Security Notes](#security-notes)

---

## Stack

| Component | Technology |
|-----------|-----------|
| API framework | FastAPI + Uvicorn |
| ORM + DB driver | SQLAlchemy 2.x async + asyncpg |
| Database | PostgreSQL |
| Migrations | Alembic |
| Schemas | Pydantic v2 |
| Auth | JWT (python-jose) + bcrypt (passlib) |
| Rate limiting | slowapi |
| LLM prompts | Jinja2 templates |
| POI data | Google Places Nearby Search + Details API |
| Experience discovery | Anthropic Claude Sonnet 4.6 (web search tool) |
| LLM classifier | Anthropic Claude Haiku 4.5 (3-LLM ensemble) |
| Photo storage | Cloudflare R2 (S3-compatible, optional) |
| Email (OTP) | Resend API (optional) |
| Evaluation UI | Streamlit + Plotly |

---

## Prerequisites & Setup

**Requirements:** Python 3.14+, PostgreSQL.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip setuptools wheel
pip install -r requirements.txt
cp .env.example .env
# fill in DATABASE_URL and at minimum one LLM API key
alembic upgrade head
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | ✅ | `postgresql+asyncpg://user:pass@host:5432/db` |
| `SECRET_KEY` | ✅ | ≥32 random characters, used to sign JWTs |
| `ALGORITHM` | ✅ | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | ✅ | Default `10080` (7 days) |
| `ANTHROPIC_API_KEY` | ✅ | Used by both the onboarding discovery (Sonnet + web search) and the POI classifier (Haiku) |
| `GOOGLE_PLACES_API_KEY` | ✅ | Nearby Search + Details API |
| `GOOGLE_PLACES_ENABLED` | — | `true`/`false` — enables Google enrichment in onboarding |
| `CACHE_TTL_DAYS` | — | Fetch cache TTL in days (default `30`) |
| `PIPELINE_LLM_BACKEND` | ✅ | Always `anthropic` |
| `PIPELINE_LLM_MODEL` | — | Model used by the POI classifier (default `claude-haiku-4-5-20251001`) |
| `CLOUDFLARE_R2_ACCESS_KEY_ID` | — | R2 credentials (omit to skip photo upload) |
| `CLOUDFLARE_R2_SECRET_ACCESS_KEY` | — | |
| `CLOUDFLARE_R2_ACCOUNT_ID` | — | |
| `CLOUDFLARE_R2_BUCKET_NAME` | — | Default `travel-agent` |
| `CLOUDFLARE_R2_PUBLIC_URL` | — | CDN URL for serving stored photos |
| `RESEND_API_KEY` | — | OTP email delivery. If absent, email verification is skipped in dev |
| `FROM_EMAIL` | — | Sender address for OTP emails |

### LLM model reference

Two Anthropic models are used for different tasks:

| Model | Used for | Web search | Approx. cost |
|-------|---------|-----------|-------------|
| `claude-haiku-4-5-20251001` | POI classification pipeline (3-LLM ensemble) | No | $0.80 / M input tokens |
| `claude-sonnet-4-6` | Onboarding experience discovery | Yes (`web_search_20250305`) | $3 / M input tokens |
| `claude-opus-4-6` | Optional — swap via `PIPELINE_LLM_MODEL` for highest quality | No | $15 / M input tokens |

> `PIPELINE_LLM_MODEL` controls the classifier model only. The onboarding service always uses `claude-sonnet-4-6` with the built-in web search tool.

---

## Running the Server

```bash
source .venv/bin/activate
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Health check: `GET /api/health`
- Swagger UI: `/docs`
- OpenAPI schema: `/openapi.json`

---

## Database Migrations

```bash
alembic upgrade head                              # apply all pending migrations
alembic revision --autogenerate -m "description" # generate migration from model changes
alembic downgrade -1                              # revert last migration
```

Alembic reads `DATABASE_URL` from `.env` via `app.config.settings`.
The value in `alembic.ini` is ignored at runtime.

---

## API Reference

All routes are prefixed with `/api`.

### Auth — `/api/auth`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/auth/register` | — | Register a new user. **Dev** (no `RESEND_API_KEY`): auto-verifies and returns a JWT. **Prod**: sends a 6-digit OTP via email and returns `{"message": "Check your email"}` |
| `POST` | `/auth/verify-email` | — | Submit OTP code to verify email. Returns JWT + user profile on success |
| `POST` | `/auth/login` | — | Email + password login. Requires verified email. Returns JWT + user profile |
| `POST` | `/auth/logout` | Bearer | Blacklists the current token (by `jti`) until it expires |

**Registration payload:**
```json
{
  "email": "user@example.com",
  "password": "Secure1!",
  "home_city": "Roma",
  "age_range": "26-35",
  "travel_with_children": false
}
```

Password rules: ≥8 chars, at least one uppercase, one lowercase, one digit, one special character.

### Users — `/api/users`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/users/me` | Bearer | Current user profile + preferences |
| `PATCH` | `/users/me` | Bearer | Update `home_city`, `age_range`, `travel_with_children` |
| `GET` | `/users/me/preferences` | Bearer | Current preference vector (7 floats). Returns zero-vector if not yet set |
| `PUT` | `/users/me/preferences` | Bearer | Override preference vector manually |
| `PUT` | `/users/me/password` | Bearer | Change password (requires current password) |
| `DELETE` | `/users/me` | Bearer | Delete account and all associated data |

### Onboarding — `/api/onboarding`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/onboarding/experiences?city=...&max_results=10` | — | Curated experiences for a city. Generated once via Claude Sonnet 4.6 with web search, enriched with Google Places, cached for `CACHE_TTL_DAYS`. Subsequent calls hit the cache |
| `POST` | `/onboarding/experiences/choices` | Bearer | Submit selected experience IDs. Computes and saves the user preference vector by averaging the feature vectors of the chosen experiences |

### Places — `/api/places`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/places?city=...&limit=50&offset=0` | Bearer | Paginated list of classified POIs for a city |
| `GET` | `/places/{place_id}` | Bearer | Single POI detail |

### Recommendations — `/api/recommendations`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/recommendations` | Bearer | Ranked POI list for a city. Body: `{"city": "Roma"}`. Query params: `limit`, `offset`. Ranking: cosine similarity between user preference vector and POI feature vector. Excludes `confidence=failed` POIs |

### Itineraries — `/api/itineraries`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/itineraries/generate` | Bearer | Plan and persist a multi-day itinerary (see [Itinerary Planner](#itinerary-planner)) |
| `GET` | `/itineraries/{itinerary_id}` | Bearer | Retrieve a saved itinerary with all stops, arrival/departure times, transport modes, and visit durations |
| `POST` | `/itineraries/{itinerary_id}/items/{item_id}/visited` | Bearer | Check in to a stop (sets `visited_at`) |
| `DELETE` | `/itineraries/{itinerary_id}/items/{item_id}/visited` | Bearer | Undo check-in |

**Generate itinerary payload:**
```json
{
  "city": "Roma",
  "num_days": 3,
  "travel_mode": "family"
}
```

`travel_mode` — one of `solo` (default), `couple`, `friends`, `family`. Controls schedule hours, POI filtering, and preference bias (see [Itinerary Planner](#itinerary-planner)).

---

## Auth System

**JWT details:**
- `sub` = user email
- `jti` = unique token ID (used for logout blacklist)
- `exp` = `now + ACCESS_TOKEN_EXPIRE_MINUTES`
- Algorithm: HS256

**Registration flow:**

```
POST /auth/register
  ↓
Validate email (normalize lowercase) + password strength
  ↓
Hash password (bcrypt), insert User (is_verified=False), create empty UserPreference
  ↓
Dev mode (RESEND_API_KEY absent):
  → set is_verified=True, return JWT + profile
Prod mode:
  → generate 6-digit OTP (secrets), store in otp_verifications (10 min TTL, max 5 attempts)
  → send via Resend API
  → return {"message": "Check your email"}
```

**Email verification:**
```
POST /auth/verify-email  {email, code}
  ↓
Check: code matches, not expired, not used, attempts < 5
  ↓
Mark OTP used, set user.is_verified=True
  ↓
Return JWT + profile
```

**Logout:** extracts `jti` from the token, inserts into `token_blacklist` with the original expiry.
All subsequent requests with that token are rejected at the `get_current_user` dependency.

---

## POI Pipeline

The pipeline populates the `pois` table for a city through four sequential steps.

### Running the pipeline

```bash
source .venv/bin/activate

# Full pipeline (fetch → tourism → classify → hours)
python -m pipeline.pipeline --city "Roma" --country "Italy"

# With explicit coordinates (skips Nominatim geocoding)
python -m pipeline.pipeline --city "Roma" --country "Italy" --lat 41.9028 --lng 12.4964

# Re-run fetch even within the 30-day cache window
python -m pipeline.pipeline --city "Roma" --country "Italy" --force-refetch

# Skip fetch — classify existing unclassified POIs only
python -m pipeline.pipeline --city "Roma" --country "Italy" --classify-only

# Re-classify POIs that are missing is_indoor_visitable
python -m pipeline.pipeline --city "Roma" --country "Italy" --reclassify

# Only run tourism validation
python -m pipeline.pipeline --city "Roma" --country "Italy" --tourism-only

# Re-run tourism validation on all POIs (resets tourism_validated_at)
python -m pipeline.pipeline --city "Roma" --country "Italy" --reclassify-tourism

# Only fetch opening hours (Step 4)
python -m pipeline.pipeline --city "Roma" --country "Italy" --hours-only

# Classify only the most famous POIs (by review count)
python -m pipeline.pipeline --city "Roma" --country "Italy" --classify-only --min-ratings 500

# Limit total POIs fetched (useful for quick tests)
python -m pipeline.pipeline --city "Roma" --country "Italy" --limit 50

# Re-run tourism validation only for food-type POIs (after updating food prompts)
python -m pipeline.pipeline --city "Madrid" --country "Spain" --food-tourism

# Supplement Nearby Search with Text Search to catch missed landmarks (e.g. public squares)
python -m pipeline.pipeline --city "Madrid" --country "Spain" --classify-only --text-search
```

### Pipeline steps

**Step 1 — Fetch** (`pipeline/fetcher.py`)

Calls Google Places Nearby Search for 7 place-type groups mapped to travel categories
(culture, nature, food, adventure, nightlife, relax, family). Up to 3 pages per type group
(60 results max per group). Results are upserted with `ON CONFLICT (google_place_id) DO UPDATE`.
A city is not re-fetched if it was fetched within `CACHE_TTL_DAYS` days, unless `--force-refetch`.

**Step 1a — Text Search supplement** (`pipeline/fetcher.py`, opt-in with `--text-search`)

Runs 5 Text Search queries ("top tourist attractions", "famous landmarks", "historic sites",
"best restaurants", "parks and squares") to catch POIs that Nearby Search misses — primarily
public spaces like plazas and squares whose Google Places type is `point_of_interest` only.
For each result, checks the DB by `google_place_id` before inserting: existing POIs are
skipped entirely (no overwrites). Only new POIs are inserted and proceed through the normal
tourism validation and classification steps.

**Step 1.5 — Tourism Validation** (`pipeline/tourism_validator.py`)

Determines whether each POI is worth visiting as a tourist (see [Tourism Validation](#tourism-validation)).
Runs on **all** POIs including restaurants — food venues are evaluated for cultural/gastronomic
significance (notable local restaurants → `is_touristic=true`, fast-food chains → `is_touristic=false`).
Sets `is_touristic`, `tourism_visit_type`, `tourism_duration_minutes` on each POI.
Skipped if `--skip-tourism` is passed. Use `--food-tourism` to re-validate only food POIs.

**Step 2 — Classification** (`pipeline/classifier.py`)

Classifies each touristic POI into one of 7 travel categories and computes a 7-dimensional
feature vector using a 3-LLM ensemble (see [LLM Classification](#llm-classification)).
Skipped for already-classified POIs unless `--reclassify` is passed.
`--min-ratings N` restricts classification to POIs with `user_ratings_total >= N`.

**Step 3 — Opening Hours** (`pipeline/hours_fetcher.py`)

Calls Google Places Details API for all `is_indoor_visitable=True` POIs to retrieve weekly
opening hours. Up to 50 concurrent requests (semaphore). Skipped if `--skip-hours` is passed.

### Logs produced (`logs/`)

| File | Contents |
|------|----------|
| `pipeline_{city}_{date}.log` | Execution log (INFO to console, DEBUG to file) |
| `llm_calls_{city}_{date}.jsonl` | One JSON line per LLM call: prompt, response, token counts, latency, errors, attempt number |

---

## LLM Classification

**File:** `pipeline/classifier.py` | **Templates:** `pipeline/prompts/`

### Architecture: 3-LLM ensemble with arbitration

```
Batch of N POIs (default 10)
        │
   ┌────┴────┐
  LLM1      LLM2      (parallel, same prompt)
   └────┬────┘
        │
   Compare outputs per POI
        │
   ┌────┴──────────────┐
   │ Agree?            │
  YES                  NO
   │                   │
confidence=high     LLM3 arbitrates
avg(v1, v2)         confidence=medium
                    (or "failed" if LLM3 fails)
```

**Agreement condition:** `cosine_distance(v1, v2) < 0.2` AND same `travel_category`.

### Output per POI

```json
{
  "travel_category": "culture",
  "feature_vector": [0.0, 0.85, 0.0, 0.05, 0.0, 0.10, 0.0],
  "is_indoor_visitable": true,
  "confidence": "high",
  "reasoning": "primary: art history visit; secondary: slight relax; ..."
}
```

### Confidence levels

| Level | Meaning |
|-------|---------|
| `high` | LLM1 and LLM2 agreed (cosine distance < 0.2) |
| `medium` | LLM3 arbitrated between disagreeing outputs |
| `failed` | All retries exhausted or JSON parse failed |

`confidence=failed` POIs are excluded from recommendations and itinerary planning.

### Prompt templates

| File | Used for |
|------|---------|
| `classify_system.jinja2` | System prompt for LLM1 and LLM2. Accepts `batch=True/False` to toggle single-object vs. JSON-array output format |
| `classify_batch.jinja2` | User message — numbered list of POIs (name, types, rating, address) |
| `arbitrate_system.jinja2` | System prompt for LLM3 arbitration |
| `arbitrate_poi.jinja2` | Per-POI arbitration prompt — includes LLM1 and LLM2 outputs and highlights the exact point of disagreement (category mismatch vs. vector/indoor difference) |

### Retry logic

- Max 2 retries (3 total attempts) per LLM call
- Backoff: 2 s, then 4 s
- On HTTP 429 (rate limit): sleep 60 s then retry
- JSON parse failure retries with the same prompt

### Logging to database

Every classification writes a `PoiClassificationLog` row containing the full LLM1, LLM2,
and LLM3 outputs, agreement metrics, and final outcome. Used by the evaluation dashboard.

---

## Tourism Validation

**File:** `pipeline/tourism_validator.py` | **Templates:** `pipeline/prompts/tourism_*.jinja2`

Determines if a POI is worth visiting as a tourist and, if so, how to visit it.

### Architecture: 2-LLM conservative pipeline

```
Every POI
   │
  LLM1 (always runs)
   │
   ├── confidence = high → use LLM1 result directly
   │
   └── confidence = low → LLM2 runs (second opinion)
          │
          ├── LLM1 and LLM2 agree → use LLM1 values
          └── LLM1 and LLM2 disagree → conservative merge (is_touristic = false)
```

### Output per POI

| Field | Type | Description |
|-------|------|-------------|
| `is_touristic` | bool | Whether the POI is worth visiting |
| `tourism_visit_type` | `indoor` / `outdoor` / `both` | How to visit it |
| `tourism_duration_minutes` | int | Suggested visit duration |

### What LLM1 flags as non-touristic

- Private residences or diplomatic buildings not open to the public
- Generic services with no tourist appeal (banks, gyms, supermarkets)
- Permanently closed or derelict venues
- Duplicates or redirects (e.g., "Colosseo entrance" when the Colosseo itself is nearby)
- Fast-food chains and generic international restaurant chains (KFC, McDonald's, Sushi Shop, etc.)

### Restaurant handling

Restaurants and cafes are included in tourism validation and filtered by cultural significance:

| Type | `is_touristic` | Example |
|------|---------------|---------|
| Historic tavern / iconic local restaurant | `true` | Taberna de La Daniela, Corral de la Morería |
| Traditional regional cuisine, gastronomic destination | `true` | century-old tapas bar, flamenco dinner venue |
| Generic fast-food chain | `false` | KFC, McDonald's, Burger King, Subway |
| International chain with no local identity | `false` | Sushi Shop, Wagamama, TGI Fridays |

Only `is_touristic=true` restaurants are included as meal stops in itinerary generation.

### Logging

Every successful validation writes a `PoiTourismValidationLog` row: LLM1 and LLM2 outputs,
`llm2_was_needed`, `decision_source` (one of `llm1`, `llm2`, `disagreement`, `llm1_fallback`).

---

## Itinerary Planner

**File:** `app/services/itinerary_planner.py`

Plans a multi-day itinerary using two-level geographic clustering, MMR-based POI selection,
and a greedy day scheduler with TSP optimization.

### POI eligibility for itineraries

POIs are split into two pools with different eligibility rules:

**Activity POIs** (sightseeing, museums, parks, etc.):
- `classified_at IS NOT NULL` and `confidence != 'failed'`
- `is_touristic = true` or legacy unvalidated (`NULL`)
- `rating >= 3.5` and `user_ratings_total >= 200` (or `NULL`)
- `business_status != 'CLOSED_PERMANENTLY'`
- Not in the type blacklist (hospitals, gyms, hotels, shopping malls, petrol stations, etc.)
- Stadium / race track: require `user_ratings_total >= 5000` (avoid local sports venues)

**Food POIs** (lunch and dinner stops):
- Has at least one food type (`restaurant`, `cafe`, `bar`, `bakery`, `meal_takeaway`, etc.)
- `is_touristic = true` or unvalidated (`NULL`) — chains marked `false` are excluded
- `rating >= 3.5` and `user_ratings_total >= 200` (or `NULL`)
- No classification required (tourism validator alone determines eligibility)

### Travel mode personalization

The `travel_mode` field drives three layers of personalization simultaneously:

**1. Schedule hours** — derived automatically, no manual input needed:

| Mode | Start | End | Rationale |
|------|-------|-----|-----------|
| `solo` | 09:00 | 22:00 | Flexible, own pace, long evenings |
| `couple` | 09:30 | 22:00 | Slight morning delay, long evenings |
| `friends` | 10:00 | 23:00 | Late start, extended nights |
| `family` | 08:30 | 20:00 | Early with children, finish before dark |

**2. POI filtering:**

- `family`: nightlife POIs (`travel_category = nightlife`) are excluded from activities. POIs explicitly marked `suitable_for_children = false` (set by tourism validation) are excluded at the SQL level.
- Other modes: no hard exclusions beyond the global touristic filter.

**3. Preference vector bias** — a fixed bias is added to the user's cosine-similarity vector before ranking, then re-normalized:

| Mode | Effect |
|------|--------|
| `solo` | No bias — pure user preferences |
| `couple` | Boosts food (+0.1) and relax (+0.15), reduces family_friendly weight |
| `friends` | Boosts adventure (+0.15) and nightlife (+0.2), reduces family_friendly weight |
| `family` | Strongly boosts family_friendly (+0.3), lightly boosts nature/adventure/food, penalizes nightlife (−0.5) |

This means two users with identical preference profiles will receive meaningfully different itineraries when they select different travel modes.

---

### Step 1 — Popularity scoring (Bayesian average)

```
score(v, R) = (v × R + m × C) / (v + m)

v = user_ratings_total
R = rating (Google)
m = global median of user_ratings_total across all candidate POIs
C = global mean rating across all candidate POIs
```

POIs with no rating or no review count receive a neutral score of `0.5`.

### Step 2 — Geographic clustering (KMeans)

Activity POIs are divided into `num_days` geographic clusters. Each cluster represents one day.
POIs are assigned to the cluster whose center is geographically closest, balancing spatial
coherence with preference relevance.

### Step 3 — MMR selection (diversity + relevance)

For each day's cluster, up to 8 candidates are selected via Maximal Marginal Relevance:

```
MMR score = λ × relevance − (1 − λ) × redundancy

λ = 0.6   (60% relevance, 40% diversity)

relevance  = combined_score(poi) = 0.5 × cosine_sim + 0.3 × proximity + 0.2 × popularity
redundancy = max cosine similarity between candidate and any already-selected POI
             + 0.3 extra penalty if same travel_category
```

**Combined score breakdown:**

| Component | Weight | Formula |
|-----------|--------|---------|
| Cosine similarity | 50% | `dot(user_pref_vec, poi_feature_vec) / (‖u‖ × ‖p‖)` |
| Proximity | 30% | `1 − min(dist_m / (proximity_km × 1000), 1.0)` |
| Popularity | 20% | Bayesian average score (0–1) |

**Landmark boost:** POIs with `user_ratings_total >= 10,000` receive a `+0.15` bonus on top of
the combined score (capped at 1.0). This ensures globally famous venues (Colosseum, Vatican, etc.)
remain competitive even for users with low preference alignment for their primary category.

### Step 4 — Profile-based proximity tightening

The proximity reference distance is derived from the user's travel profile:

| Profile | proximity_km | Effect |
|---------|-------------|--------|
| Default | 5.0 km | Standard geographic spread |
| `travel_with_children = true` | 3.0 km | Tighter clusters, less daily walking |
| `age_range` in `{"60-70", "65+", "70+", "70-80", "80+"}` | 2.5 km | Compact clusters for seniors |

### Step 5 — Novelty filtering

| Situation | Score multiplier |
|-----------|-----------------|
| POI confirmed visited (checked in by this user) | × 0.0 (ranked last, never hard-excluded) |
| POI previously suggested within 365 days | × 0.6 (downweighted) |
| Never seen | × 1.0 (no penalty) |

### Step 6 — Day scheduling

The scheduler greedily builds each day from the MMR-selected candidates:

- **Time window:** derived from `travel_mode` (e.g. 09:00–22:00 for solo, 08:30–20:00 for family)
- **Meal insertion:** lunch target 13:00 (search window opens at 12:30), dinner at 20:00 (19:30)
- **Transport mode selection:**

| Distance | Mode | Speed |
|----------|------|-------|
| ≤ 800 m | Walking | 1.39 m/s |
| 800 m – 5 km | Transit | 5.56 m/s |
| > 5 km | Taxi | 8.33 m/s |

- **Visit duration source priority:** `tourism_duration_minutes` (LLM-estimated) → category lookup table → fallback default

**Visit mode resolution per stop:**

| POI type | Cosine sim | Mode | Duration |
|----------|-----------|------|---------|
| Food | any | indoor | 15–75 min (restaurant/cafe/bar/bakery) |
| `is_indoor_visitable=false` | any | outdoor | 20–45 min |
| `is_indoor_visitable=true` | ≥ 0.3 | indoor | 45–180 min (by Google type) |
| `is_indoor_visitable=true` | < 0.3 | outdoor (exterior) | 30–45 min + note: "Suggested as an exterior visit" |

**Day type cap** — prevents fatigue from repeated types in one day:

| Google primary type | Max per day |
|--------------------|------------|
| `church` / `place_of_worship` | 2 |
| `tourist_attraction` | 5 |

- **TSP optimization:** after greedy insertion, a 2-opt pass reorders the day's stops to minimize total travel distance.
- **Deferred POIs:** stops that don't fit within the time window are carried over to the next day's candidate pool.

---

## Evaluation Dashboard

**File:** `pipeline/dashboard.py` | **Requires:** `pip install -r requirements_dashboard.txt`

```bash
source .venv/bin/activate
streamlit run pipeline/dashboard.py --server.port 8501
```

The sidebar accepts an optional city filter (leave blank for all cities).

### Sections

**Summary** — 4 metric cards: mean preference score, std preference score, mean Shannon entropy,
mean distance per day (km). Preference score = cosine similarity between user preferences and
recommended POIs (higher = more personalized). Shannon entropy = category diversity per itinerary
(max ≈ 2.8 for 7 categories).

**Preference Score Distribution** — histogram of per-itinerary mean preference scores.

**Category Distribution** — pie chart of category spread across all itineraries + box plot of
per-itinerary Shannon entropy.

**Per-Stop Preference Scores** — box plot of preference scores by category, excluding food stops
(mandatory, not preference-driven).

**Geographic Coherence** — box plot of km/day by city. Lower = more geographically compact days.

**LLM Classification Quality** — summary cards (agreement rate, mean cosine distance, arbitration
rate, failed rate) + confidence distribution pie + top 5 disagreement pairs bar chart +
per-category vector consistency bar chart.

**Tourism Validation Quality** — touristic rate, LLM2 needed rate, disagreement rate +
visit type distribution pie + mean duration bar chart.

**Itinerary Detail** — select any itinerary to inspect: user preference radar chart,
per-stop preference score bar chart, raw stop table with full feature vector as named columns.

**Export** — download all itinerary metrics as CSV.

### Running the evaluation report (CLI)

```bash
python pipeline/evaluation.py --city Roma
```

Prints: agreement rate, cosine distance stats, confidence distribution, top disagreement pairs,
per-category vector consistency, category distribution, tourism validation stats.

---

## Data Model Overview

```
users ──────────────── user_preferences (1:1)
  │
  ├─── user_experience_choices ── city_experiences
  │
  ├─── itineraries ──────────────── itinerary_items ── pois
  │                                                      │
  │                                               poi_classification_logs
  │                                               poi_tourism_validation_logs
  │
  └─── token_blacklist (logout)
       otp_verifications (email verification)
       api_logs (request logging middleware)
```

### Key fields

**`pois`** — the central classification table:

| Column | Type | Description |
|--------|------|-------------|
| `google_place_id` | string | Deduplication key |
| `types` | string[] | Google Places type array |
| `rating` | float | 0–5 |
| `user_ratings_total` | int | Review count (popularity proxy) |
| `is_touristic` | bool? | Tourism validation result (null = not yet validated) |
| `tourism_visit_type` | string | `indoor` / `outdoor` / `both` |
| `tourism_duration_minutes` | int | LLM-estimated visit time |
| `travel_category` | string | Primary category (one of 7) |
| `nature` … `family_friendly` | float×7 | Feature vector as explicit columns |
| `is_indoor_visitable` | bool? | Requires entering a building |
| `confidence` | string | `high` / `medium` / `failed` |
| `opening_hours` | JSONB | Weekly schedule from Google Details |

**`user_preferences`** — 7 float columns (`nature`, `culture`, `food`, `adventure`, `nightlife`,
`relax`, `family_friendly`), normalized to sum ≈ 1.0. Computed from onboarding experience
choices or set manually.

**`itinerary_items`** — `day_number` (1-based), `position` (order within day),
`arrival_time`, `departure_time`, `visited_at` (check-in timestamp).

---

## Feature Vector & Categories

7 travel preference dimensions, stored as explicit float columns on both `pois` and `user_preferences`:

| Dimension | Represents |
|-----------|-----------|
| `nature` | Parks, natural features, outdoor activities |
| `culture` | Museums, galleries, churches, historical sites |
| `food` | Restaurants, cafes, food markets, bakeries |
| `adventure` | Sports, amusement parks, extreme activities |
| `nightlife` | Clubs, bars, live music venues |
| `relax` | Spas, thermal baths, leisure venues |
| `family_friendly` | Zoos, aquariums, playgrounds, family parks |

Each vector is normalized (values sum ≈ 1.0). Ranking and planning use cosine similarity
between the user preference vector and each POI feature vector.

---

## Security Notes

- **Password rules:** ≥8 characters, uppercase + lowercase + digit + special character
- **Email normalization:** stored and compared in lowercase
- **Rate limiting:** 5 req/min on `/register` and `/verify-email`; 10 req/min on `/login`
- **OTP:** 6-digit code generated via `secrets` (cryptographically secure), 10-minute expiry, max 5 attempts
- **JWT logout:** token blacklisted by `jti` until the original expiry; no re-use possible after logout
- **Email verification:** required before login. Bypassed in dev environments without `RESEND_API_KEY`
- **UUID primary keys:** generated in Python (`default=uuid.uuid4`), never exposed in sequential form

---

## Implementation Notes

- `city_experiences` and `user_experience_choices` use soft-delete (`is_deleted` flag): old rows
  are retained when caches refresh, preserving history.
- The logging middleware records every non-health, non-docs request to the `api_logs` table
  (method, path, status, duration, user ID).
- Alembic's `sqlalchemy.url` is overridden at runtime from `settings.database_url`; the value
  in `alembic.ini` is ignored.
- The lifespan handler in `main.py` calls `Base.metadata.create_all` via `conn.run_sync()` —
  never call it directly on the async engine.
- `PlaceOut.score` is not on the ORM model; it is set manually in the recommendations router
  after cosine similarity ranking.
- Streamlit dashboard uses `NullPool` (SQLAlchemy) to avoid asyncpg event-loop conflicts when
  `asyncio.run()` is called multiple times from the same process.
