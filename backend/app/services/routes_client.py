"""Google Routes API client + cached travel-time access.

Replaces the haversine-÷-fixed-speed estimate used by the itinerary scheduler
with real on-road travel times from Google Routes API (Compute Route Matrix),
persisted per (origin, dest, mode) in the ``poi_travel_times`` table so each pair
is paid for only once.

Design principles (see docs/routes-api-travel-times-spec.md):
- Cache lookup FIRST; the API is called only for missing pairs.
- A fallback to haversine is mandatory: itinerary generation must NEVER fail
  because of routing. If the API key is missing/disabled or a call fails, we
  fall back to the haversine estimate.
- Only the mode actually needed per pair is computed.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
import uuid
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.models.poi_travel_time import PoiTravelTime

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.poi import Poi

logger = logging.getLogger(__name__)

ROUTE_MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
FIELD_MASK = "originIndex,destinationIndex,duration,distanceMeters,condition"
MAX_ELEMENTS = 625  # origins × destinations per request (safe for Google & ORS)

# OpenRouteService Matrix v2 — hosted, free key, no billing. Profile is appended.
ORS_MATRIX_URL = "https://api.openrouteservice.org/v2/matrix"

# DB mode -> Google Routes travelMode.
# TRANSIT requires the Routes API Advanced SKU; omitting it makes transit pairs
# fall through to haversine automatically. Add "transit": "TRANSIT" to upgrade.
_ROUTES_TRAVEL_MODE: dict[str, str] = {
    "walking": "WALK",
    "driving": "DRIVE",
}

# DB mode -> OpenRouteService profile. ORS has no public-transit profile, so
# transit pairs fall through to haversine (request builder returns None).
_ORS_PROFILE: dict[str, str] = {
    "walking": "foot-walking",
    "driving": "driving-car",
}

# Fallback speeds (m/s) per DB mode — mirror SPEED_MS in itinerary_planner,
# with "driving" == the scheduler's "taxi" speed.
_FALLBACK_SPEED_MS: dict[str, float] = {"walking": 1.39, "transit": 5.56, "driving": 8.33}

_DURATION_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)s$")

# Circuit breaker — only for AUTH failures (401/403): a bad/disabled key won't
# fix itself by retrying, so once we see one we short-circuit the rest of this
# run's calls straight to haversine instead of making dozens of failing requests.
# Quota (429) is NOT an auth failure: it is transient (per-minute) and handled by
# retry+throttle below, so it must never open the circuit.
_CIRCUIT_OPEN_UNTIL: float = 0.0
_CIRCUIT_COOLDOWN_S: int = 300  # 5 minutes


def _circuit_open() -> bool:
    return time.monotonic() < _CIRCUIT_OPEN_UNTIL


def _open_circuit(reason: str) -> None:
    global _CIRCUIT_OPEN_UNTIL
    _CIRCUIT_OPEN_UNTIL = time.monotonic() + _CIRCUIT_COOLDOWN_S
    logger.warning("Routes API circuit open for %ds: %s", _CIRCUIT_COOLDOWN_S, reason)


# Throttle — space out calls to stay under the project's per-minute rate so we
# don't trip 429 during a cold-cache warm-up. One call at a time, globally.
_THROTTLE_LOCK = asyncio.Lock()
_LAST_CALL_TS: float = 0.0
_MIN_CALL_INTERVAL_S: float = 1.6   # ≈ 37 calls/min — under ORS free 40/min
_RATE_LIMIT_BACKOFF_S: float = 20.0  # 429 → wait for the per-minute window to clear


async def _throttle() -> None:
    """Block until at least _MIN_CALL_INTERVAL_S has passed since the last call."""
    global _LAST_CALL_TS
    async with _THROTTLE_LOCK:
        wait = _MIN_CALL_INTERVAL_S - (time.monotonic() - _LAST_CALL_TS)
        if wait > 0:
            await asyncio.sleep(wait)
        _LAST_CALL_TS = time.monotonic()


def _provider() -> str:
    """Active routing provider: "ors" (default) or "google"."""
    return (settings.routing_provider or "ors").lower()


def _api_key() -> str:
    """API key for the active provider."""
    if _provider() == "google":
        return settings.google_routes_api_key or settings.google_places_api_key
    return settings.openrouteservice_api_key


def _routing_available() -> bool:
    return settings.routes_api_enabled and bool(_api_key()) and not _circuit_open()


def parse_duration(value: str | None) -> int | None:
    """Parse a Routes API duration string like ``"412s"`` → 412 (seconds).

    Returns None if the value is missing or malformed.
    """
    if not value:
        return None
    m = _DURATION_RE.match(value.strip())
    if not m:
        return None
    return int(round(float(m.group(1))))


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _haversine_fallback(origin: "Poi", dest: "Poi", mode: str) -> tuple[float, int]:
    """(minutes, meters) estimate when no real route is available."""
    dist = _haversine_m(origin.lat, origin.lng, dest.lat, dest.lng)
    speed = _FALLBACK_SPEED_MS.get(mode, _FALLBACK_SPEED_MS["walking"])
    minutes = (dist / speed) / 60
    return minutes, int(dist)


# ---------------------------------------------------------------------------
# HTTP with throttle + retry (provider-agnostic)
# ---------------------------------------------------------------------------

async def _post_json(url: str, headers: dict, body: dict, max_retries: int):
    """POST ``body`` and return parsed JSON, or None on failure.

    Shared by every routing provider: applies the global throttle before each
    attempt, retries 429 (per-minute quota) and 5xx with backoff, opens the
    circuit on auth failures (401/403), and gives up on other 4xx.
    """
    backoff = 2.0
    for attempt in range(max_retries):
        await _throttle()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=body, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            body_text = ""
            try:
                body_text = e.response.text
            except Exception:
                pass
            status = e.response.status_code
            if status in (401, 403):
                # Auth failure: a bad/disabled key won't recover by retrying.
                _open_circuit(f"HTTP {status}: {body_text[:200]}")
                return None
            if status != 429 and status < 500:
                # Deterministic client error — retrying won't help.
                logger.error("Routing API client error %d: %s | response: %s", status, e, body_text)
                return None
            # Retryable: 429 (per-minute quota) or 5xx. Wait longer on 429 so the
            # rate-limit window clears before the next attempt.
            if attempt < max_retries - 1:
                wait = max(backoff, _RATE_LIMIT_BACKOFF_S) if status == 429 else backoff
                logger.warning(
                    "Routing API %d (%s), retry %d/%d in %.0fs | response: %s",
                    status, e, attempt + 1, max_retries, wait, body_text,
                )
                await asyncio.sleep(wait)
                backoff *= 2
            else:
                logger.error("Routing API failed after %d retries: %d %s | response: %s", max_retries, status, e, body_text)
                return None
        except httpx.RequestError as e:
            if attempt < max_retries - 1:
                logger.warning(
                    "Routing API request error (%s), retry %d/%d in %.0fs", e, attempt + 1, max_retries, backoff
                )
                await asyncio.sleep(backoff)
                backoff *= 2
            else:
                logger.error("Routing API failed after %d retries: %s", max_retries, e)
                return None
    return None


# ---------------------------------------------------------------------------
# Provider: Google Routes API (Compute Route Matrix)
# ---------------------------------------------------------------------------

def _google_request(origins, destinations, mode) -> tuple[str, dict, dict] | None:
    travel_mode = _ROUTES_TRAVEL_MODE.get(mode)
    if travel_mode is None:
        return None

    def _wp(point: tuple[float, float]) -> dict:
        return {"waypoint": {"location": {"latLng": {"latitude": point[0], "longitude": point[1]}}}}

    body: dict = {
        "origins": [_wp(p) for p in origins],
        "destinations": [_wp(p) for p in destinations],
        "travelMode": travel_mode,
    }
    if travel_mode == "DRIVE":
        # Stay in the cheaper Essentials SKU — real-time traffic is irrelevant
        # for cacheable static times.
        body["routingPreference"] = "TRAFFIC_UNAWARE"
    headers = {
        "X-Goog-Api-Key": _api_key(),
        "Content-Type": "application/json",
        "X-Goog-FieldMask": FIELD_MASK,
    }
    return ROUTE_MATRIX_URL, headers, body


def _google_parse(data) -> list[tuple[int, int, int, int]]:
    results: list[tuple[int, int, int, int]] = []
    for element in data:
        if element.get("condition") != "ROUTE_EXISTS":
            continue
        seconds = parse_duration(element.get("duration"))
        if seconds is None:
            continue
        meters = int(element.get("distanceMeters", 0))
        results.append(
            (int(element.get("originIndex", 0)), int(element.get("destinationIndex", 0)), seconds, meters)
        )
    return results


# ---------------------------------------------------------------------------
# Provider: OpenRouteService (Matrix v2) — hosted, free key, foot + car profiles
# ---------------------------------------------------------------------------

def _ors_request(origins, destinations, mode) -> tuple[str, dict, dict] | None:
    profile = _ORS_PROFILE.get(mode)
    if profile is None:
        return None
    # ORS uses [lng, lat] order. Send origins then destinations as one location
    # list and index into it with sources/destinations.
    locations = [[lng, lat] for lat, lng in origins] + [[lng, lat] for lat, lng in destinations]
    n_o = len(origins)
    body = {
        "locations": locations,
        "sources": list(range(n_o)),
        "destinations": list(range(n_o, n_o + len(destinations))),
        "metrics": ["duration", "distance"],
        "units": "m",
    }
    headers = {"Authorization": _api_key(), "Content-Type": "application/json"}
    return f"{ORS_MATRIX_URL}/{profile}", headers, body


def _ors_parse(data, n_origins: int, n_destinations: int) -> list[tuple[int, int, int, int]]:
    durations = data.get("durations") or []
    distances = data.get("distances") or []
    results: list[tuple[int, int, int, int]] = []
    for i in range(min(n_origins, len(durations))):
        row_dur = durations[i] or []
        row_dist = distances[i] if i < len(distances) else []
        for j in range(min(n_destinations, len(row_dur))):
            dur = row_dur[j]
            if dur is None:  # unreachable → genuine no-route
                continue
            dist = row_dist[j] if j < len(row_dist) and row_dist[j] is not None else 0
            results.append((i, j, int(round(dur)), int(round(dist))))
    return results


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

async def compute_route_matrix(
    origins: list[tuple[float, float]],
    destinations: list[tuple[float, float]],
    mode: str,
    max_retries: int = 3,
) -> list[tuple[int, int, int, int]] | None:
    """Compute a travel-time matrix for ``origins`` × ``destinations`` in one mode.

    Routes to the configured provider (``settings.routing_provider``: "ors" or
    "google"). Args take (lat, lng) tuples; ``mode`` is a DB mode
    ("walking" | "transit" | "driving").

    Return value distinguishes the three outcomes the caller must treat
    differently (see docs/routes-api-travel-times-spec.md §5):
    - ``list`` (possibly empty): the API responded. Each tuple
      (origin_idx, dest_idx, seconds, meters) is a reachable pair. A pair
      *absent* from the list is a genuine no-route → the caller may cache an
      haversine fallback so it is not retried.
    - ``None``: the call FAILED (HTTP/timeout/exception, or a mode the provider
      doesn't support). This is NOT a no-route signal → the caller must use a
      runtime haversine fallback WITHOUT caching it, so the pair is retried.
    """
    if not origins or not destinations:
        return []
    if len(origins) * len(destinations) > MAX_ELEMENTS:
        raise ValueError(
            f"Route matrix request exceeds {MAX_ELEMENTS} elements "
            f"({len(origins)}×{len(destinations)}); chunk the request"
        )

    provider = _provider()
    req = _google_request(origins, destinations, mode) if provider == "google" \
        else _ors_request(origins, destinations, mode)
    if req is None:
        logger.warning("Mode %r unsupported by routing provider %r → haversine", mode, provider)
        return None

    url, headers, body = req
    data = await _post_json(url, headers, body, max_retries)
    if data is None:
        return None

    if provider == "google":
        return _google_parse(data)
    return _ors_parse(data, len(origins), len(destinations))


# ---------------------------------------------------------------------------
# Cached access
# ---------------------------------------------------------------------------

async def _load_cached(
    session: "AsyncSession",
    keys: list[tuple[uuid.UUID, uuid.UUID, str]],
) -> dict[tuple[uuid.UUID, uuid.UUID, str], tuple[float, int]]:
    """Bulk-load cached rows for the given (origin_id, dest_id, mode) keys."""
    if not keys:
        return {}
    origin_ids = {k[0] for k in keys}
    dest_ids = {k[1] for k in keys}
    modes = {k[2] for k in keys}
    result = await session.execute(
        select(PoiTravelTime).where(
            PoiTravelTime.origin_poi_id.in_(origin_ids),
            PoiTravelTime.dest_poi_id.in_(dest_ids),
            PoiTravelTime.mode.in_(modes),
        )
    )
    wanted = set(keys)
    out: dict[tuple[uuid.UUID, uuid.UUID, str], tuple[float, int]] = {}
    for row in result.scalars():
        key = (row.origin_poi_id, row.dest_poi_id, row.mode)
        if key in wanted:
            out[key] = (row.seconds / 60.0, row.meters)
    return out


async def _insert_rows(session: "AsyncSession", rows: list[dict]) -> None:
    """Bulk-insert cache rows, ignoring rows that already exist."""
    if not rows:
        return
    stmt = pg_insert(PoiTravelTime).values(rows).on_conflict_do_nothing(
        constraint="uq_travel_origin_dest_mode"
    )
    await session.execute(stmt)
    await session.commit()


async def get_travel_time(
    session: "AsyncSession",
    origin: "Poi",
    dest: "Poi",
    mode: str,
    allow_api: bool = True,
) -> tuple[float, int]:
    """Return (minutes, meters) for origin→dest in ``mode``, cache-first.

    1. origin == dest → (0.0, 0).
    2. Lookup ``poi_travel_times``; return on hit.
    3. If routing is enabled and a key is present (and ``allow_api``), call the
       Routes API. Three outcomes (see compute_route_matrix):
       - real route → cache ``routes_api`` and return it;
       - explicit no-route (API responded, empty) → cache ``haversine_fallback``
         so the missing route is not retried every run;
       - API error (``None``) → use haversine at runtime but DO NOT cache, so the
         pair is retried next run.
    4. Routing disabled / no key → pure haversine, no DB write, no network.
    """
    if origin.id == dest.id:
        return 0.0, 0

    cached = await _load_cached(session, [(origin.id, dest.id, mode)])
    hit = cached.get((origin.id, dest.id, mode))
    if hit is not None:
        return hit

    if allow_api and _routing_available():
        matrix = await compute_route_matrix(
            [(origin.lat, origin.lng)], [(dest.lat, dest.lng)], mode
        )
        if matrix:  # real route found
            _, _, seconds, meters = matrix[0]
            await _insert_rows(session, [{
                "id": uuid.uuid4(),
                "origin_poi_id": origin.id,
                "dest_poi_id": dest.id,
                "mode": mode,
                "seconds": seconds,
                "meters": meters,
                "source": "routes_api",
            }])
            return seconds / 60.0, meters

        minutes, meters = _haversine_fallback(origin, dest, mode)
        if matrix is not None:
            # API responded with no route → cache fallback (genuine no-route).
            await _insert_rows(session, [{
                "id": uuid.uuid4(),
                "origin_poi_id": origin.id,
                "dest_poi_id": dest.id,
                "mode": mode,
                "seconds": int(minutes * 60),
                "meters": meters,
                "source": "haversine_fallback",
            }])
        # else: matrix is None (API error) → do NOT cache, retry next run.
        return minutes, meters

    # Routing disabled / no key → pure haversine, no DB write, no network.
    return _haversine_fallback(origin, dest, mode)


async def get_travel_times_batch(
    session: "AsyncSession",
    pairs: list[tuple["Poi", "Poi"]],
    mode: str,
) -> dict[tuple[uuid.UUID, uuid.UUID, str], tuple[float, int]]:
    """Resolve many same-mode pairs at once: cache-first, one batched API call.

    Returns a lookup keyed by (origin_id, dest_id, mode) → (minutes, meters).
    Only pairs that resolve to a real or fallback time are included; identical
    origin/dest pairs are skipped (callers treat a miss as 0/haversine).
    """
    lookup: dict[tuple[uuid.UUID, uuid.UUID, str], tuple[float, int]] = {}
    if not pairs:
        return lookup

    # Deduplicate and drop self-pairs.
    poi_by_id: dict[uuid.UUID, "Poi"] = {}
    keys: list[tuple[uuid.UUID, uuid.UUID, str]] = []
    seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for origin, dest in pairs:
        if origin.id == dest.id:
            continue
        pk = (origin.id, dest.id)
        if pk in seen:
            continue
        seen.add(pk)
        poi_by_id[origin.id] = origin
        poi_by_id[dest.id] = dest
        keys.append((origin.id, dest.id, mode))

    if not keys:
        return lookup

    cached = await _load_cached(session, keys)
    lookup.update(cached)
    missing = [k for k in keys if k not in cached]
    if not missing:
        return lookup

    if not _routing_available():
        # Pure haversine for the missing ones; no DB writes, no network.
        for o_id, d_id, _m in missing:
            lookup[(o_id, d_id, mode)] = _haversine_fallback(poi_by_id[o_id], poi_by_id[d_id], mode)
        return lookup

    # Build a compact origins×destinations matrix over only the POIs involved in
    # the missing pairs, then chunk to respect the 625-element limit.
    missing_origins = sorted({o for o, _d, _m in missing}, key=str)
    missing_dests = sorted({d for _o, d, _m in missing}, key=str)
    missing_set = {(o, d) for o, d, _m in missing}

    resolved: dict[tuple[uuid.UUID, uuid.UUID], tuple[int, int]] = {}
    errored: set[tuple[uuid.UUID, uuid.UUID]] = set()  # pairs whose API call failed
    chunk_dests = max(1, MAX_ELEMENTS // max(1, len(missing_origins)))
    for o_start in range(0, len(missing_origins), MAX_ELEMENTS):
        o_chunk = missing_origins[o_start:o_start + MAX_ELEMENTS]
        for d_start in range(0, len(missing_dests), chunk_dests):
            d_chunk = missing_dests[d_start:d_start + chunk_dests]
            origin_coords = [(poi_by_id[o].lat, poi_by_id[o].lng) for o in o_chunk]
            dest_coords = [(poi_by_id[d].lat, poi_by_id[d].lng) for d in d_chunk]
            matrix = await compute_route_matrix(origin_coords, dest_coords, mode)
            if matrix is None:
                # Transient API error: mark this chunk's missing pairs so we use a
                # runtime fallback WITHOUT caching it (retry next run).
                for o_id in o_chunk:
                    for d_id in d_chunk:
                        if (o_id, d_id) in missing_set:
                            errored.add((o_id, d_id))
                continue
            for oi, di, seconds, meters in matrix:
                o_id, d_id = o_chunk[oi], d_chunk[di]
                if (o_id, d_id) in missing_set:
                    resolved[(o_id, d_id)] = (seconds, meters)

    rows: list[dict] = []
    fallback_n = 0
    for o_id, d_id, _m in missing:
        if (o_id, d_id) in resolved:
            seconds, meters = resolved[(o_id, d_id)]
            lookup[(o_id, d_id, mode)] = (seconds / 60.0, meters)
            rows.append({
                "id": uuid.uuid4(),
                "origin_poi_id": o_id,
                "dest_poi_id": d_id,
                "mode": mode,
                "seconds": seconds,
                "meters": meters,
                "source": "routes_api",
            })
            continue

        minutes, meters = _haversine_fallback(poi_by_id[o_id], poi_by_id[d_id], mode)
        lookup[(o_id, d_id, mode)] = (minutes, meters)
        if (o_id, d_id) in errored:
            # API error → runtime fallback only, no cache row (retry next run).
            continue
        # Genuine no-route → cache the fallback so we don't retry every run.
        fallback_n += 1
        rows.append({
            "id": uuid.uuid4(),
            "origin_poi_id": o_id,
            "dest_poi_id": d_id,
            "mode": mode,
            "seconds": int(minutes * 60),
            "meters": meters,
            "source": "haversine_fallback",
        })

    await _insert_rows(session, rows)

    logger.info(
        "Routes cache fill (mode=%s): %d hits, %d api, %d no-route fallback, %d api-error (uncached)",
        mode, len(cached), len(rows) - fallback_n, fallback_n, len(errored),
    )
    return lookup
