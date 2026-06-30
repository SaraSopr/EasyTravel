# EasyTravel

Personalized, mobile-first AI travel planner. EasyTravel discovers Points of Interest via
Google Places, classifies them with an LLM ensemble, and plans optimized multi-day itineraries
using geographic clustering, Maximal Marginal Relevance selection, and cosine-similarity
preference matching. A React SPA consumes a FastAPI backend.

```
EasyTravel/
├── backend/    # FastAPI + PostgreSQL  (deployed on Railway)
└── frontend/   # React + Vite SPA      (deployed on Vercel)
```

---

## Table of Contents

**Getting started**
1. [Stack](#stack)
2. [Quick Start](#quick-start)
3. [Environment Variables](#environment-variables)
4. [Deployment](#deployment)

**Backend**
5. [Running the Server](#running-the-server)
6. [Database Migrations](#database-migrations)
7. [API Reference](#api-reference)
8. [Auth System](#auth-system)
9. [POI Pipeline](#poi-pipeline)
10. [LLM Classification](#llm-classification)
11. [Tourism Validation](#tourism-validation)
12. [Itinerary Planner](#itinerary-planner)
13. [TOPTW Solver](#toptw-solver)
14. [Evaluation Dashboard](#evaluation-dashboard)
15. [Evaluation Harness (Greedy vs TOPTW)](#evaluation-harness-greedy-vs-toptw)
15. [Data Model Overview](#data-model-overview)
16. [Feature Vector & Categories](#feature-vector--categories)
17. [Security Notes](#security-notes)

**Frontend**
18. [Frontend Architecture](#frontend-architecture)
19. [Pages & Routing](#pages--routing)
20. [Trip Flow](#trip-flow)

---

## Stack

### Backend

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
| Experience discovery | OpenAI `gpt-5.4-mini` (web search tool) |
| LLM classifier | OpenAI `gpt-5.4-mini` (3-call ensemble) |
| Photo storage | Cloudflare R2 (S3-compatible, optional) |
| Email (OTP) | Resend API (optional) |
| Evaluation UI | Streamlit + Plotly |

### Frontend

- **React 18** + **TypeScript** (strict)
- **Vite** — dev server + build
- **TailwindCSS v3** — styling
- **react-router-dom v6** — routing
- **axios** — HTTP client with auth interceptors
- **zustand** — global state (auth + trip)
- **lucide-react** — icons
- **react-leaflet v4** + **leaflet v1.9** — itinerary map

---

## Quick Start

**Requirements:** Python 3.14+, PostgreSQL, Node 18+.

```bash
# ── Backend ──────────────────────────────────
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip setuptools wheel
pip install -r requirements.txt
cp .env.example .env          # fill in DATABASE_URL + at least one LLM API key
alembic upgrade head
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# ── Frontend (separate terminal) ─────────────
cd frontend
npm install
npm run dev                   # localhost:5173, proxies /api → http://localhost:8000
```

- Health check: `GET /api/health`
- Swagger UI: `/docs`
- OpenAPI schema: `/openapi.json`

---

## Environment Variables

Backend variables live in `backend/.env`:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | ✅ | `postgresql+asyncpg://user:pass@host:5432/db` |
| `SECRET_KEY` | ✅ | ≥32 random characters, used to sign JWTs |
| `ALGORITHM` | ✅ | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | ✅ | Default `10080` (7 days) |
| `OPENAI_API_KEY` | ✅ | Used by onboarding discovery (with web search) and the POI classifier |
| `OPENAI_STRUCTURED_OUTPUT` | — | `true`/`false` — enables strict JSON-schema output for classification and tourism validation |
| `GOOGLE_PLACES_API_KEY` | ✅ | Nearby Search + Details API |
| `GOOGLE_PLACES_ENABLED` | — | `true`/`false` — enables Google enrichment in onboarding |
| `CACHE_TTL_DAYS` | — | Fetch cache TTL in days (default `30`) |
| `PIPELINE_LLM_BACKEND` | ✅ | LLM provider used by the POI pipeline (default `openai`) |
| `PIPELINE_LLM_MODEL` | — | Model used by the POI pipeline (default `gpt-5.4-mini`) |
| `PIPELINE_REASONING_EFFORT` | — | OpenAI reasoning effort used by the POI pipeline (default `none`) |
| `CLOUDFLARE_R2_ACCESS_KEY_ID` | — | R2 credentials (omit to skip photo upload) |
| `CLOUDFLARE_R2_SECRET_ACCESS_KEY` | — | |
| `CLOUDFLARE_R2_ACCOUNT_ID` | — | |
| `CLOUDFLARE_R2_BUCKET_NAME` | — | Default `travel-agent` |
| `CLOUDFLARE_R2_PUBLIC_URL` | — | CDN URL for serving stored photos |
| `RESEND_API_KEY` | — | OTP email delivery. If absent, email verification is skipped in dev |
| `FROM_EMAIL` | — | Sender address for OTP emails |

### LLM model reference

| Model | Used for | Web search |
|-------|----------|------------|
| `gpt-5.4-mini` | POI classification pipeline (3-call ensemble) and onboarding experience discovery | Onboarding only |

> `PIPELINE_LLM_MODEL` controls the POI pipeline model only. The onboarding
> service uses `gpt-5.4-mini` directly with OpenAI's built-in web search tool.

---

## Deployment

- **Frontend** → **Vercel** — set Root Directory to `frontend`. `vercel.json` rewrites `/api/*`
  to the Railway backend and `/*` to `index.html` (SPA fallback).
- **Backend + DB** → **Railway** — set Root Directory to `backend`.

---

## Running the Server

```bash
cd backend
source .venv/bin/activate
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Database Migrations

```bash
alembic upgrade head                              # apply all pending migrations
alembic revision --autogenerate -m "description"  # generate migration from model changes
alembic downgrade -1                              # revert last migration
```

Alembic reads `DATABASE_URL` from `.env` via `app.config.settings`. The value in `alembic.ini`
is ignored at runtime.

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
| `GET` | `/onboarding/experiences?city=...&max_results=10` | — | Curated experiences for a city. Generated once via OpenAI `gpt-5.4-mini` with web search, enriched with Google Places, and cached for `CACHE_TTL_DAYS`. Subsequent calls hit the cache |
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
| `GET` | `/itineraries/{itinerary_id}/items/{item_id}/alternatives` | Bearer | Ranked alternative POIs for a stop (same eligible candidate set, minus everything already in the itinerary, ordered by preference similarity with a same-category boost) |
| `PUT` | `/itineraries/{itinerary_id}/items/{item_id}` | Bearer | Swap the POI in a stop for a chosen alternative (`{"poi_id": "..."}`). Implicit feedback: the user's preference profile moves toward the chosen POI and away from the replaced one |
| `DELETE` | `/itineraries/{itinerary_id}/items/{item_id}` | Bearer | Remove a stop and shift the rest of the day up. Implicit negative feedback: the profile moves away from the removed POI's features |
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

`travel_mode` — one of `solo` (default), `couple`, `friends`, `family`. Controls schedule hours,
POI filtering, and preference bias (see [Itinerary Planner](#itinerary-planner)).

> **In-itinerary editing & implicit feedback.** Each stop can be swapped for a ranked alternative
> or removed. These edits are treated as implicit feedback and nudge the stored `user_preferences`
> vector (EMA step, clamped to `[0, 1]`): a swap rewards the chosen POI and penalizes the replaced
> one; a removal applies a half-strength penalty. Subsequent recommendations and generations reflect
> the updated profile.

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
cd backend
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

## TOPTW Solver

**File:** `app/services/toptw_solver.py` | **Activated by:** `itinerary_solver=toptw` (default)

The TOPTW solver replaces the greedy pipeline with a single global optimisation over all days simultaneously. Where the greedy pipeline chains three local heuristics (cluster → MMR → schedule), each optimising a sub-objective, the TOPTW maximises total relevance subject to opening-hour windows, visit durations, real travel times, and a daily time budget — all at once.

### Problem formulation

The itinerary planning problem is modelled as a **Team Orienteering Problem with Time Windows (TOPTW)**:

- Each **day** is a vehicle with its own time budget.
- Each **POI** is an optional node with a prize (relevance score) and a time window derived from its opening hours on that weekday.
- The solver selects which POIs to visit, assigns each to a day, and sequences them to **maximise total prize collected** subject to all constraints.
- A POI can be visited **at most once** across all days.

The TOPTW is NP-hard (it generalises TSP), so the implementation uses OR-Tools' routing solver with Guided Local Search rather than solving to optimality.

### Prize computation

Each POI's prize encodes its relevance to the user:

```
prize = w_sim · cosine(poi_vector, user_vector) + w_pop · popularity + landmark_boost
```

- `w_sim = 0.7`, `w_pop = 0.3` (configurable)
- `popularity` = Bayesian average of rating × review count, normalised to [0,1]
- `landmark_boost = +0.15` for POIs with > 10,000 reviews (ensures must-sees remain competitive)
- A **novelty penalty** reduces the prize of previously visited or suggested POIs

Only the top-N candidates by prize (`toptw_num_candidates = 80`) are passed to the solver to keep the model tractable.

### OR-Tools mapping

| TOPTW concept | OR-Tools construct |
|---|---|
| Day | vehicle |
| POI visit on day k | replica node (POI, day k) |
| Prize | disjunction penalty = ⌊prize × scale⌋ |
| Visit at most once | disjunction (max cardinality 1) over replicas |
| Opening hours window | `CumulVar` of Time dimension in [open, close] |
| Wait until opening | Time dimension slack ≤ 4 h |
| Daily budget | `CumulVar(End(k))` ≤ budget |
| POI pinned to its day | `VehicleVar` ∈ {−1, k} |
| Travel + service time | transit callback / arc cost |

The solver **minimises** `arc_costs + sum(prizes of unvisited POIs)` — equivalent to maximising collected prize with travel time as a tiebreaker. The prize scale (`toptw_prize_scale = 100,000`) makes prize dominate over travel cost.

Search: `PATH_CHEAPEST_ARC` initial solution + `GUIDED_LOCAL_SEARCH` metaheuristic, stopped by a wall-clock limit (`toptw_time_limit_s = 20 s`) or, for reproducible thesis runs, by a solution count limit (`toptw_solution_limit`).

### Real travel times

The solver uses **real road travel times** (OpenRouteService by default, Google Routes API as alternative) fetched in a single batch before solving and cached in the database. Each pair of POIs is resolved once; subsequent requests are cache hits.

Transport mode per leg is chosen by distance with a personalised walking threshold (age + relax preference):

| Distance | Mode |
|---|---|
| ≤ threshold (default 800 m) | Walking (ORS foot profile) |
| threshold – 5 km | Transit (approximated as driving × 1.5) |
| > 5 km | Taxi / driving |

Transit uses the driving matrix scaled by `transit_driving_factor = 1.5` — a declared approximation (no GTFS engine available). Cache misses fall back to haversine estimates.

### Geographic pre-clustering

The unconstrained TOPTW is free to assign any POI to any day, which can produce geographically scattered days. An optional **pre-clustering** step pins each POI to one geographic zone (one per day) to keep days spatially compact.

**Zone construction:** the full activity pool (not just the prize-filtered top-N) is clustered with the Leiden algorithm and rebalanced. Zones are ordered deterministically west→east by centroid longitude. Per-zone candidate selection (`ceil(N / num_days)` per zone) prevents a novelty-skewed global top-N from starving sparse zones.

**Automatic gating:** pre-clustering is only applied when the zones are balanced. Balance is measured as:

```
balance = min(candidates per day) / mean(candidates per day)
```

- `toptw_pre_cluster_mode = auto` (default): pre-cluster only if `balance ≥ 0.35`; fall back to global TOPTW otherwise.
- `on` / `off`: force the choice (thesis A/B arms).

**Outlier pruning:** when pre-clustering is active, a POI too far from the rest of its zone is dropped if its nearest intra-zone neighbour exceeds `toptw_cluster_outlier_max_nn_m = 1500 m` **or** its distance from the zone centroid exceeds `toptw_cluster_outlier_max_centroid_m = 2000 m`. Landmark-class POIs are protected. Pruned POIs are removed entirely from candidates (not just un-pinned).

### Selection–sequencing decomposition

The multi-vehicle solver optimises POI selection and day assignment well but leaves each day's visiting order ~1.6× longer than a tight TSP. A second **single-vehicle TSPTW pass** re-sequences each day to minimise real travel time while respecting opening hours, without changing which POIs are on the day. This runs in milliseconds on a typical day (8–12 nodes) and is executed before meal insertion so meals are placed along the final compact route.

### Meal insertion

Meals are **not** solver nodes — they are inserted as a post-pass. The daily budget reserves `toptw_meal_reserve_min = 150 min` for meals (`budget = day_duration − 150 min`). After sequencing, times are propagated from the day start using real travel times; when the clock reaches the lunch or dinner window, the best open restaurant near the current route position is inserted (scored by proximity + rating, with a takeaway penalty). The food pool is shared across days.

### Under-full day filling

With pre-clustering active, a compact zone with short visits can exhaust its POIs by mid-afternoon while other days run full. When a day's used time falls below `toptw_underfull_fill_ratio × budget` (default 70%), the solver borrows extra unused POIs from the activity pool within `toptw_underfull_borrow_radius_m = 2000 m` of the day's centroid, pins them to that day, and re-solves. Already-full days keep their pins. Active by default; disable via env for thesis A/B baseline runs.

### Approximations and limitations

- **Transit times are approximated** as driving × 1.5. No real public-transport schedules are used.
- **Split opening hours** (e.g. closed for lunch) are collapsed to `[min open, max close]` — a single OR-Tools time window. Availability during intermediate closure periods may be overestimated.
- **GLS is not exact** — the solution is not guaranteed optimal within the time budget.
- **Pre-clustering trades prize flexibility for spatial compactness.** The automatic gating limits the downside on degenerate splits.

### Key hyperparameters

| Parameter | Default | Purpose |
|---|---|---|
| `itinerary_solver` | `toptw` | Switch between `toptw` and `greedy` |
| `toptw_num_candidates` | 80 | Top-N POIs fed to the solver |
| `toptw_prize_scale` | 100,000 | Weight of prize vs. travel cost |
| `toptw_time_limit_s` | 20 | Solver wall-clock budget (seconds) |
| `toptw_solution_limit` | 0 | Stop after N improving solutions (0 = off; set > 0 for reproducible thesis runs) |
| `toptw_meal_reserve_min` | 150 | Time reserved for meals (minutes) |
| `toptw_w_sim` / `toptw_w_pop` | 0.7 / 0.3 | Prize weights (similarity / popularity) |
| `toptw_pre_cluster_mode` | `auto` | `auto` / `on` / `off` — geographic pre-clustering |
| `toptw_cluster_balance_min` | 0.35 | Balance threshold for auto gating |
| `toptw_prune_outliers` | `true` | Drop isolated POIs from their zone |
| `toptw_cluster_outlier_max_nn_m` | 1500 | Nearest-neighbour outlier threshold (m) |
| `toptw_cluster_outlier_max_centroid_m` | 2000 | Centroid outlier threshold (m) |
| `toptw_reorder_days` | `true` | Per-day TSPTW re-sequencing |
| `toptw_fill_underfull_days` | `true` | Borrow POIs for sparse days |
| `toptw_underfull_fill_ratio` | 0.7 | Under-full threshold (fraction of budget) |
| `transit_driving_factor` | 1.5 | Transit time approximation multiplier |
| `routes_api_enabled` | `false` | Enable real road times (vs haversine) |
| `routing_provider` | `ors` | `ors` (OpenRouteService) or `google` |

---

## Evaluation Dashboard

**File:** `pipeline/dashboard.py` | **Requires:** `pip install -r requirements_dashboard.txt`

```bash
cd backend
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

## Evaluation Harness (Greedy vs TOPTW)

**Package:** `backend/evaluation/` | **Tables:** `evaluation_itineraries`, `evaluation_pairs`,
`evaluation_ratings`, `evaluation_likert`

The harness compares the two itinerary solvers — the greedy baseline
(clustering → MMR → greedy scheduling) and the TOPTW solver (OR-Tools, real travel
times) — for the thesis. It generates itineraries over a controlled test matrix,
computes automatic metrics, and feeds a blind human-evaluation dashboard.

### The 2×2 ablation

The new system changed **two** things at once: the **algorithm** (greedy → TOPTW)
*and* the **routing** (haversine estimate → real cached road times). Comparing only
"old system vs new system" confounds the two. The harness therefore crosses both
axes so each effect can be attributed independently:

| | Routing `estimated` (haversine) | Routing `real` (cached road times) |
|---|---|---|
| **`greedy`** | A — baseline | B |
| **`toptw`** | C | D — production |

- **A → C** isolates the *algorithm* effect (same routing).
- **A → B** isolates the *routing* effect (same algorithm).
- A large gap between D and A+B (separately) indicates *synergy* (TOPTW exploits real
  routing better than greedy does).

The two axes map directly to existing settings, toggled per cell by the runner:
`itinerary_solver` (`greedy`/`toptw`) and `routes_api_enabled` (`true`=real /
`false`=haversine).

### Test matrix

Defined in `evaluation/config.py`:

| Dimension | Values |
|-----------|--------|
| Cities | `Roma`, `Londra`, `Madrid`, `Porto` (3 dense capitals + 1 medium to stress POI scarcity) |
| Durations | `2`, `4` days (must-see prioritisation vs completeness) |
| Profiles | frozen user profiles in `evaluation/profiles.py` (vector + travel_mode + age_range) |
| Solvers | `greedy`, `toptw` |
| Routings | `real`, `estimated` |

Each cell = `profile × city × num_days × solver × routing`. Generation is **idempotent
per cell** (re-running replaces the row).

### Running it

```bash
cd backend
source .venv/bin/activate
alembic upgrade head                      # ensure the routing column exists
```

#### Automatic evaluation (offline — no human needed)

Run one city at a time to stay within the ORS free-tier rate limit (40 req/min, 500/day).
The cache warms on the first `real`-routing run; subsequent cells reuse it.

```bash
python -m evaluation.run_eval --cities Roma
python -m evaluation.run_eval --cities Madrid
python -m evaluation.run_eval --cities Londra
python -m evaluation.run_eval --cities Porto

# Export one CSV row per cell — the thesis source table for RQ1 and RQ3
python -m evaluation.export_metrics --out metrics_2x2.csv
```

If ORS returns 429 (rate limit), the runner falls back to haversine and logs a warning — it
won't crash. Re-run the affected city after an hour.

#### Other useful commands

```bash
# Scoped test run (one profile, one city, 2 days)
python -m evaluation.run_eval --cities Roma --profiles couple_foodie --durations 2

# Skip the ablation — real-routing arm only
python -m evaluation.run_eval --routings real

# Generate human-eval pairs (real arm only) — do this AFTER the automatic run
python -m evaluation.run_eval --cities Roma Madrid Londra Porto --pairs --routings real
```

### Automatic metrics

Computed per cell in `evaluation/metrics.py` and stored in `metrics_json`:

| Metric | Axis | Thesis use |
|--------|------|-----------|
| `avg_relevance` | **selection quality** | **Primary RQ1 metric.** Mean prize per included POI — isolates *selection quality* independent of how many POIs were included. `total_relevance` confounds quality and quantity (a solver that crams more stops wins the total even if each stop is worse); the mean neutralises that bias. |
| `total_relevance` | selection | Sum of included POI prizes — kept as reference, but read alongside `num_activities_included`. On its own it is biased toward solvers that include more stops. |
| `num_activities_included` | selection | Number of activity POIs in the itinerary — the quantity dimension that `avg_relevance` deliberately ignores. Pair with `avg_relevance` to decompose total = quality × quantity. |
| `landmark_coverage` | selection | Share of the city's top-N by popularity that made the trip. |
| `intra_list_diversity` | selection | `1 − mean pairwise cosine` over included POIs (filter-bubble check). |
| `real_overrun_day_rate` / `real_overrun_min_avg` | **feasibility** | Re-walks the planned route with the **real** travel cache (cache-first, no API) and reports how often / by how much a day no longer fits its budget. **Always measured against reality**, so an `estimated` plan is scored against real travel times — the feasibility oracle for RQ1b / RQ3. |
| `stops_per_day`, `budget_fill_rate`, `idle_minutes_per_day`, `meals_complete_rate` | completeness | Day-shape sanity — quantifies how full the day is without conflating it with selection quality. |
| `solve_time_ms` | cost | Solver wall-clock per cell. |

### Human evaluation (blind)

`run_eval --pairs` builds A(included)–B(excluded) POI pairs in three flavours
(`substitutable`, `famous_skipped`, `margin`) that control the relevance-vs-logistics
confound. Only the **real-routing** arm feeds the study — evaluators judge
production-quality itineraries, not haversine-planned cells. Served by the
`/api/evaluation` endpoints (blind: solver name stripped, options randomised):

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/evaluation/pairs?evaluator=<id>` | Unrated pairs for an evaluator (blinded, shuffled) |
| `POST` | `/evaluation/ratings` | Submit a pairwise choice (`a`/`b`/`equal`) |
| `GET` | `/evaluation/itineraries?evaluator=<id>` | Whole itineraries for Likert rating (solver hidden) |
| `POST` | `/evaluation/likert` | Submit Likert scores (realism, completeness, profile_fit, overall; 1–5) |
| `GET` | `/evaluation/export` | CSV of all human ratings joined to pair + solver + profile |

### Reproducibility

- **Determinism:** set `TOPTW_SOLUTION_LIMIT > 0` (e.g. `50`) in `.env` for thesis runs.
  With the default `0` the solver stops on wall-clock time, so the same input can yield
  different itineraries across runs/machines (see `app/config.py`).
- **Warm the routing cache:** the `real` arm and the `real_overrun` metric read the
  travel cache with `allow_api=False`. Pre-populate it for the test cities, otherwise
  legs silently fall back to haversine and the A/B/C/D cells collapse together.
- `RANDOM_SEED` in `config.py` fixes the human-eval pair sampling.

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
choices, nudged by in-itinerary edits, or set manually.

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

## Frontend Architecture

Mobile-first SPA. Every page root uses `max-w-md mx-auto min-h-screen`; styling is Tailwind-only.

### Key files

| Path | Purpose |
|---|---|
| `src/types/index.ts` | Shared TypeScript interfaces (User, Place, Itinerary, PoiSuggestion, etc.) |
| `src/api/client.ts` | Axios instance — Bearer token injection (`auth_token` localStorage key), 401 redirect |
| `src/api/endpoints.ts` | One typed async function per backend route |
| `src/store/useAuthStore.ts` | Auth state — `user`, `token`, persisted in localStorage |
| `src/store/useTripStore.ts` | Trip state — `city`, `numDays`, `recommendations`, `selectedPlaceIds`, `itinerary` |
| `src/components/ProtectedRoute.tsx` | Guards auth-required routes |
| `src/components/BottomNav.tsx` | Fixed bottom navigation (Home / Explore / Trip / Profile) |
| `src/components/ItineraryTimeline.tsx` | Day-by-day stop list with swap / remove / check-in actions |
| `src/components/ItineraryMap.tsx` | Leaflet route map, one color per day |

### Auth flow

1. `POST /api/auth/register` → email verification (OTP) → token saved → `/onboarding`
2. `POST /api/auth/login` → token saved → `/home`
3. `ProtectedRoute` wraps all routes except `/login` and `/register`; redirects to `/login` if no token
4. 401 from any API call → clears localStorage token + hard redirect to `/login`
5. `POST /api/auth/logout` invalidates the token server-side on logout

---

## Pages & Routing

| Route | Page | Description |
|---|---|---|
| `/login` | Login | Email + password sign in |
| `/register` | Register | Sign up with OTP email verification |
| `/onboarding` | Onboarding | Pick travel experience preferences |
| `/home` | Home | Enter destination + trip duration (number of **days**, not dates) |
| `/recommendations` | Recommendations | Browse and select places |
| `/itinerary/:id` | Itinerary | AI-generated day-by-day timeline + route map |
| `/profile` | Profile | Edit profile, change password, delete account |

---

## Trip Flow

```
/home  →  enter city + number of days  →  fetch recommendations
   →  /recommendations  →  select places  →  generate itinerary
   →  /itinerary/:id  →  view day-by-day timeline + map
```

On the itinerary screen the trip is presented **by day** ("Day 1", "Day 2", ...) — calendar
dates are intentionally not shown. Each stop offers three actions:

- **Replace** — opens a sheet of ranked alternative POIs; picking one swaps the stop and nudges the
  preference profile toward the chosen place (see [Itineraries API](#itineraries--apiitineraries)).
- **Remove** — removes the stop and nudges the profile away from it.
- **Mark as visited** — checks in / undoes a check-in.

After any edit the itinerary is re-fetched so times, transport legs, and the map stay consistent.
```
