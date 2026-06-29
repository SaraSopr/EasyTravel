# Onboarding Flow

How a new user is turned into a **preference vector** that drives every later
recommendation. Onboarding is a one-shot, post-registration step: the user picks
the kinds of *experiences* they love in their home city, and the system distils
those picks into a 7-dimensional taste profile (`UserPreference`).

Two distinct flows are involved:

- **Flow A — Experience discovery & serving** (`GET /api/onboarding/experiences`):
  produce, enrich, cache, and return the catalogue of experiences for a city.
- **Flow B — Choice submission & profiling** (`POST /api/onboarding/experiences/choices`):
  turn the user's selections into a stored preference vector.

Relevant files:

| Layer | File |
|---|---|
| Frontend page | `frontend/src/pages/Onboarding.tsx` |
| Frontend cards | `frontend/src/components/ExperienceCard.tsx`, `ExperienceDetailSheet.tsx` |
| Frontend API | `frontend/src/api/endpoints.ts` (`getExperiences`, `submitExperienceChoices`) |
| Backend router | `backend/app/routers/onboarding.py` |
| LLM prompt | `backend/app/prompts/experience_discovery_prompt.jinja2` |
| Profiling | `backend/app/services/recommendation.py` (`build_user_vector`, `nudge_user_preferences`, `rank_pois`) |
| Models | `backend/app/models/experience.py` (`CityExperience`, `UserExperienceChoice`), `app/models/preference.py` (`UserPreference`) |

---

## 0. Where onboarding sits

Onboarding runs **after registration, not after login**:

- Direct registration → `setAuth(...)` → `navigate('/onboarding')`
  (`Register.tsx`, register submit handler).
- Registration with email OTP → after `verifyEmail` → `navigate('/onboarding')`.
- A normal **login** goes straight to `/home` — onboarding is meant as a
  first-run step for new accounts.

The route is behind `ProtectedRoute` (`App.tsx`), so without a token the user is
bounced to `/login`. The key value carried over from registration is
**`user.home_city`**, which becomes the city the experiences are discovered for.

The submit endpoint is idempotent (it deletes prior choices first), so re-running
onboarding to re-pick experiences is safe.

---

## Flow A — Experience discovery & serving

### Frontend (`Onboarding.tsx`)

1. **Fetch on mount.** As soon as `user` is available, calls
   `getExperiences(user.home_city)` → `GET /api/onboarding/experiences?city=...`.
2. **Loading state.** A 2-column grid of 8 shimmer skeletons plus a gradient
   spinner ("Finding experiences…"). This matters because the first request for a
   city can be slow (LLM call + Google Places enrichment — see backend below).
3. **Card grid.** Each experience renders as an `ExperienceCard`.
   - The icon is resolved **dynamically**: `experience.icon` is used as a key into
     `* as LucideIcons`, falling back to `MapPin`. Valid tokens are the ones the
     prompt is constrained to emit (`tree, wine, mountain, museum, food, music,
     moon, waves, park, bike, camera, star, coffee, map, art, boat, fire, compass`).
   - **Asymmetric tap behaviour:** tapping an already-selected card *deselects* it
     immediately; tapping an unselected card *opens the detail sheet* instead of
     selecting it inline.
4. **Detail sheet** (`ExperienceDetailSheet`): centred modal with backdrop; locks
   body scroll while open. Shows photo (`photo_url`, falling back to the icon over
   a gradient), name, description, and a toggle button that selects **and** closes.
5. **Sticky bottom bar:** counts selections, shows up to 6 dots, and the
   **Continue** button is disabled until at least one experience is selected.
6. **Submit:** `submitExperienceChoices(selectedIds)` →
   `POST /api/onboarding/experiences/choices` → on success `navigate('/home')`.
   Note: the auth store is **not** refreshed with the returned `UserOut` — the
   frontend treats the response as `void`.

### Backend (`GET /onboarding/experiences`)

A 6-stage pipeline (`onboarding.py`, `get_experiences`). The catalogue is
**per-city and shared across all users** — discovery cost is paid once per city
per TTL window.

1. **Cache check.** Select `CityExperience` rows for the city where
   `is_deleted == False` and `created_at` is within `settings.cache_ttl_days`
   (default **30 days**). If present → return immediately (cache hit).
2. **Per-city lock + double-check.** An `asyncio.Lock` per city (`_get_city_lock`)
   prevents a *thundering herd*: two simultaneous requests for the same uncached
   city won't both call the LLM. After acquiring the lock, the cache is re-checked.
3. **LLM discovery with web search** (`fetch_experiences_with_web_search`):
   - Renders `experience_discovery_prompt.jinja2` with `city` and `max_results`
     (default 10).
   - Backend: `get_backend("openai", "gpt-5.4-mini", tool_use=True)` — OpenAI with
     integrated web search. Requires `OPENAI_API_KEY`, else `503`.
   - Defensive JSON parsing: if the response is not pure JSON, the first `{...}`
     block is extracted via regex; otherwise `502`.
   - A fire-and-forget `LlmLog` row records model, prompt summary, latency, tokens.
4. **Google Places enrichment** (gated by `GOOGLE_PLACES_ENABLED`, default off):
   - First builds an in-request **local place cache** (`_build_local_place_cache`)
     from historical `CityExperience` rows + the city's `Poi` rows, keyed by
     normalised name, to avoid re-calling Google for already-known places.
   - `enrich()` runs only for experiences that are `verifiable` and have a
     `search_query`. Cache hit → reuse; else `search_google_places` (Places API
     New, Text Search) with a tight field mask (id, location, address, phone,
     website, rating, photos). The first photo is uploaded to R2 idempotently.
   - Concurrency is bounded by `PLACES_SEMAPHORE` (5).
   - See **Discard policy** below for what happens when a place isn't found.
5. **Persistence.** Soft-delete (`is_deleted = True`) all live experiences for the
   city, then insert the new ones (filtered to valid model columns). Commit.
6. **Reload & return.** Re-read the fresh rows and serialise via `ExperienceOut`.

### The discovery prompt

`experience_discovery_prompt.jinja2` constrains the LLM to:

- Return **exactly `max_results`** experiences, distributed across **slots** in
  priority order: `urban_life → culture → nature → food_drink → night → wildcard`
  (max 2 per slot; under-filled slots backfill from the next slot).
- Write descriptions in the **official language of the city's country**.
- Emit, per experience, a **`feature_vector`** over 7 dimensions —
  `nature, culture, food, adventure, nightlife, relax, family_friendly` — values
  in `[0, 1]`, with at most 3 dimensions above 0.5.
- Set `verifiable` + `search_query` so the backend can ground the experience on
  Google Maps. Abstract concepts (a neighbourhood's "atmosphere", a recurring
  ritual) are `verifiable=false` with `search_query=null`.
- Only permanent/recurring places — no temporary exhibitions or one-off events —
  and specific named venues/trails, never generic categories.

### Discard policy

When `GOOGLE_PLACES_ENABLED` is on, a **`verifiable` experience that cannot be
found on Google Places is dropped**. The system then serves **fewer than
`max_results`** experiences rather than backfilling — this is acceptable because
the frontend only requires *at least one* selection.

> **History:** an earlier design grouped discards by slot and fetched
> replacements from a second LLM call. That path was removed because it was
> **dead/broken**: it called an undefined function
> (`fetch_replacements_from_perplexity`, never implemented or imported), so any
> discard under `GOOGLE_PLACES_ENABLED` would raise `NameError` and `500` the
> whole request *after* the expensive LLM+Google work — leaving nothing cached, so
> every retry re-paid the cost and re-failed. The orphaned prompt
> `experience_replacement_prompt.jinja2` is a leftover of that design and is no
> longer referenced. If slot-balanced replacement is wanted in the future, it
> should be reintroduced as a real implementation, not restored verbatim.

---

## Flow B — Choice submission & profiling

### Backend (`POST /onboarding/experiences/choices`)

Requires an authenticated user (`get_current_user`; the JWT `sub` is the user's
email). Steps (`submit_choices`):

1. **Reset.** Delete the user's existing `UserExperienceChoice` rows
   (makes re-onboarding idempotent).
2. **Insert.** One `UserExperienceChoice` row per selected `experience_id`.
3. **Build the preference vector.** Load the chosen `CityExperience` rows and
   average their `feature_vector` dicts via
   `recommendation_service.build_user_vector` (empty selection → all zeros).
4. **Upsert `UserPreference`.** Write the 7 averaged dimensions
   (`nature, culture, food, adventure, nightlife, relax, family_friendly`). Commit.
5. **Return** the `User` with preferences loaded (`selectinload`) as `UserOut`.

### How the profile drives the app

- `UserPreference` is the vector consumed by `rank_pois`
  (`recommendation.py`): cosine similarity between the user vector and each POI's
  feature vector, used to order recommendations on `/home`. POIs with
  `confidence == "failed"` or any missing feature are skipped.
- The profile is then refined **implicitly** by itinerary edits via
  `nudge_user_preferences` (EMA step, `lr = 0.15`, clamped to `[0, 1]`): keeping or
  adding a POI nudges the profile toward it; removing/replacing one nudges away at
  half strength. Onboarding provides the **initial signal**; edits fine-tune it
  without overwriting it.

---

## Data model

`backend/app/models/experience.py`:

- **`CityExperience`** — the per-city catalogue. LLM-generated fields
  (`name, description, icon, category, slot, why_locals_love_it, effort_level,
  time_of_day, price_range, verifiable, search_query, feature_vector`) plus Google
  Places fields (`google_place_id, latitude, longitude, address, phone, website,
  google_rating, photo_url, verified`). `is_deleted` + `created_at` implement the
  versioned soft-delete used by the cache.
- **`UserExperienceChoice`** — user↔experience join. FK uses
  `ondelete="SET NULL"` and has its own `is_deleted`, so choices survive if the
  underlying experience is removed.
- **`UserPreference`** (`app/models/preference.py`) — the live 7-float profile.
  The choices are *not* the profile; the profile is **derived** from them.

---

## Configuration

| Setting | Default | Effect |
|---|---|---|
| `OPENAI_API_KEY` | `""` | Required for discovery; absent → `503` on cache miss. |
| `GOOGLE_PLACES_ENABLED` | `false` | Enables Google Places enrichment + discard policy. |
| `GOOGLE_PLACES_API_KEY` | `""` | Used by enrichment; absent → enrichment no-ops. |
| `CACHE_TTL_DAYS` | `30` | Freshness window for the per-city experience cache. |

Discovery model: `gpt-5.4-mini` (`_EXPERIENCE_MODEL` in `onboarding.py`), OpenAI
backend with web search via `pipeline.llm_client.get_backend`.

---

## Known limitations / notes

- **Catalogue is global per city**, not personalised at discovery time;
  personalisation happens only via the user's selection in Flow B.
- **Variable result count** when enrichment is on (see Discard policy).
- The frontend does **not** refresh the auth store with the `UserOut` returned by
  the choices endpoint, so any client-side copy of `UserPreference` can be stale
  until the next fetch.
- Provider naming was previously inconsistent across comments/logs ("Perplexity",
  "Claude Sonnet") while the code uses OpenAI `gpt-5.4-mini`; comments and the
  cache-miss log line have been aligned to the actual backend.
