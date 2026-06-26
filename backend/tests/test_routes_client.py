"""Unit tests for the Routes API client + cached travel-time access.

These tests do not touch the database or the network: the cache loader and the
Routes API call are monkeypatched. See docs/routes-api-travel-times-spec.md.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.services import routes_client


def _poi(lat: float, lng: float):
    return SimpleNamespace(id=uuid.uuid4(), lat=lat, lng=lng)


def _recording_insert(store: list):
    """Return an async stand-in for routes_client._insert_rows that records rows."""
    async def _insert(session, rows):
        store.extend(rows)
    return _insert


class _FakeSession:
    """Stand-in AsyncSession that records writes and never hits a DB."""

    def __init__(self):
        self.inserted = []
        self.committed = False

    async def execute(self, stmt):
        self.inserted.append(stmt)
        return None

    async def commit(self):
        self.committed = True


# ── parse_duration ───────────────────────────────────────────────────

def test_parse_duration_valid():
    assert routes_client.parse_duration("412s") == 412


def test_parse_duration_fractional_rounds():
    assert routes_client.parse_duration("90.7s") == 91


@pytest.mark.parametrize("bad", [None, "", "412", "abc", "12m"])
def test_parse_duration_invalid(bad):
    assert routes_client.parse_duration(bad) is None


# ── compute_route_matrix parsing / condition handling ────────────────

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    payload: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json, headers):
        return _FakeResponse(_FakeAsyncClient.payload)


@pytest.mark.asyncio
async def test_compute_route_matrix_skips_non_existing_routes(monkeypatch):
    _FakeAsyncClient.payload = [
        {"originIndex": 0, "destinationIndex": 0, "duration": "300s",
         "distanceMeters": 500, "condition": "ROUTE_EXISTS"},
        {"originIndex": 0, "destinationIndex": 1, "duration": "0s",
         "distanceMeters": 0, "condition": "ROUTE_NOT_FOUND"},
    ]
    monkeypatch.setattr(routes_client.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(routes_client.settings, "google_routes_api_key", "k", raising=False)

    out = await routes_client.compute_route_matrix(
        [(41.0, 12.0)], [(41.1, 12.1), (41.2, 12.2)], "walking"
    )
    # Only the ROUTE_EXISTS element is returned.
    assert out == [(0, 0, 300, 500)]


class _RaisingAsyncClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json, headers):
        import httpx
        raise httpx.RequestError("boom")


@pytest.mark.asyncio
async def test_compute_route_matrix_error_returns_none(monkeypatch):
    # An API error must return None (NOT []), so the caller can tell a transient
    # failure apart from a genuine no-route.
    monkeypatch.setattr(routes_client.httpx, "AsyncClient", _RaisingAsyncClient)
    monkeypatch.setattr(routes_client.settings, "google_routes_api_key", "k", raising=False)
    out = await routes_client.compute_route_matrix(
        [(41.0, 12.0)], [(41.1, 12.1)], "walking", max_retries=1
    )
    assert out is None


@pytest.mark.asyncio
async def test_compute_route_matrix_no_route_returns_empty_list(monkeypatch):
    # API responded but the only element has no route → empty list (not None).
    _FakeAsyncClient.payload = [
        {"originIndex": 0, "destinationIndex": 0, "duration": "0s",
         "distanceMeters": 0, "condition": "ROUTE_NOT_FOUND"},
    ]
    monkeypatch.setattr(routes_client.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(routes_client.settings, "google_routes_api_key", "k", raising=False)
    out = await routes_client.compute_route_matrix([(41.0, 12.0)], [(41.1, 12.1)], "walking")
    assert out == []


@pytest.mark.asyncio
async def test_compute_route_matrix_too_many_elements_raises():
    origins = [(0.0, 0.0)] * 26
    dests = [(0.0, 0.0)] * 26  # 676 > 625
    with pytest.raises(ValueError):
        await routes_client.compute_route_matrix(origins, dests, "walking")


# ── get_travel_time: cache-first + fallback ──────────────────────────

@pytest.mark.asyncio
async def test_get_travel_time_returns_cache_without_api(monkeypatch):
    origin, dest = _poi(41.0, 12.0), _poi(41.1, 12.1)

    async def fake_load(session, keys):
        return {(origin.id, dest.id, "walking"): (7.0, 600)}

    async def boom(*a, **k):
        raise AssertionError("API must not be called on a cache hit")

    monkeypatch.setattr(routes_client, "_load_cached", fake_load)
    monkeypatch.setattr(routes_client, "compute_route_matrix", boom)
    monkeypatch.setattr(routes_client.settings, "routes_api_enabled", True, raising=False)
    monkeypatch.setattr(routes_client.settings, "google_routes_api_key", "k", raising=False)

    minutes, meters = await routes_client.get_travel_time(
        _FakeSession(), origin, dest, "walking"
    )
    assert (minutes, meters) == (7.0, 600)


@pytest.mark.asyncio
async def test_get_travel_time_disabled_uses_haversine_no_network(monkeypatch):
    origin, dest = _poi(41.0, 12.0), _poi(41.0, 12.0118)  # ~1 km east

    async def fake_load(session, keys):
        return {}

    async def boom(*a, **k):
        raise AssertionError("network must not be touched when routing disabled")

    monkeypatch.setattr(routes_client, "_load_cached", fake_load)
    monkeypatch.setattr(routes_client, "compute_route_matrix", boom)
    monkeypatch.setattr(routes_client.settings, "routes_api_enabled", False, raising=False)

    session = _FakeSession()
    minutes, meters = await routes_client.get_travel_time(session, origin, dest, "walking")

    # Haversine fallback: ~1 km, transit speed not used (mode passed is walking).
    assert meters > 900 and meters < 1100
    assert minutes > 0
    # No cache write when routing is disabled.
    assert session.inserted == []


@pytest.mark.asyncio
async def test_get_travel_time_identical_poi_is_zero(monkeypatch):
    p = _poi(41.0, 12.0)
    out = await routes_client.get_travel_time(_FakeSession(), p, p, "walking")
    assert out == (0.0, 0)


# ── get_travel_times_batch: cache fill + lookup ──────────────────────

@pytest.mark.asyncio
async def test_batch_calls_api_for_missing_and_caches(monkeypatch):
    a, b = _poi(41.0, 12.0), _poi(41.1, 12.1)
    calls = {"n": 0}

    async def fake_load(session, keys):
        return {}  # all missing

    async def fake_matrix(origins, destinations, mode):
        calls["n"] += 1
        # origin 0 → dest 0 has a real route of 600 s / 800 m
        return [(0, 0, 600, 800)]

    monkeypatch.setattr(routes_client, "_load_cached", fake_load)
    monkeypatch.setattr(routes_client, "compute_route_matrix", fake_matrix)
    monkeypatch.setattr(routes_client.settings, "routes_api_enabled", True, raising=False)
    monkeypatch.setattr(routes_client.settings, "google_routes_api_key", "k", raising=False)

    session = _FakeSession()
    lookup = await routes_client.get_travel_times_batch(session, [(a, b)], "walking")

    assert lookup[(a.id, b.id, "walking")] == (10.0, 800)  # 600s → 10 min
    assert calls["n"] == 1
    assert session.committed is True  # cache row written


@pytest.mark.asyncio
async def test_batch_no_route_caches_fallback(monkeypatch):
    # API responds with NO route (empty list) → cache an haversine_fallback row
    # so the missing route is not retried every run.
    a, b = _poi(41.0, 12.0), _poi(41.0, 12.0118)
    rows_written = []

    async def fake_load(session, keys):
        return {}

    async def empty_matrix(origins, destinations, mode):
        return []  # responded, but no route

    monkeypatch.setattr(routes_client, "_load_cached", fake_load)
    monkeypatch.setattr(routes_client, "compute_route_matrix", empty_matrix)
    monkeypatch.setattr(routes_client, "_insert_rows", _recording_insert(rows_written))
    monkeypatch.setattr(routes_client.settings, "routes_api_enabled", True, raising=False)
    monkeypatch.setattr(routes_client.settings, "google_routes_api_key", "k", raising=False)

    lookup = await routes_client.get_travel_times_batch(_FakeSession(), [(a, b)], "walking")
    assert (a.id, b.id, "walking") in lookup
    assert len(rows_written) == 1
    assert rows_written[0]["source"] == "haversine_fallback"


@pytest.mark.asyncio
async def test_batch_api_error_does_not_cache(monkeypatch):
    # API ERROR (None) → runtime fallback only, NO cache row, so it retries.
    a, b = _poi(41.0, 12.0), _poi(41.0, 12.0118)
    rows_written = []

    async def fake_load(session, keys):
        return {}

    async def error_matrix(origins, destinations, mode):
        return None  # transient API failure

    monkeypatch.setattr(routes_client, "_load_cached", fake_load)
    monkeypatch.setattr(routes_client, "compute_route_matrix", error_matrix)
    monkeypatch.setattr(routes_client, "_insert_rows", _recording_insert(rows_written))
    monkeypatch.setattr(routes_client.settings, "routes_api_enabled", True, raising=False)
    monkeypatch.setattr(routes_client.settings, "google_routes_api_key", "k", raising=False)

    lookup = await routes_client.get_travel_times_batch(_FakeSession(), [(a, b)], "walking")
    assert (a.id, b.id, "walking") in lookup  # still usable at runtime
    assert rows_written == []  # but nothing cached → retried next run


@pytest.mark.asyncio
async def test_get_travel_time_api_error_does_not_cache(monkeypatch):
    a, b = _poi(41.0, 12.0), _poi(41.0, 12.0118)
    rows_written = []

    async def fake_load(session, keys):
        return {}

    async def error_matrix(*a, **k):
        return None

    monkeypatch.setattr(routes_client, "_load_cached", fake_load)
    monkeypatch.setattr(routes_client, "compute_route_matrix", error_matrix)
    monkeypatch.setattr(routes_client, "_insert_rows", _recording_insert(rows_written))
    monkeypatch.setattr(routes_client.settings, "routes_api_enabled", True, raising=False)
    monkeypatch.setattr(routes_client.settings, "google_routes_api_key", "k", raising=False)

    minutes, meters = await routes_client.get_travel_time(_FakeSession(), a, b, "walking")
    assert minutes > 0 and meters > 0
    assert rows_written == []


@pytest.mark.asyncio
async def test_batch_disabled_uses_haversine_no_network(monkeypatch):
    a, b = _poi(41.0, 12.0), _poi(41.0, 12.0118)

    async def fake_load(session, keys):
        return {}

    async def boom(*a, **k):
        raise AssertionError("no network when disabled")

    monkeypatch.setattr(routes_client, "_load_cached", fake_load)
    monkeypatch.setattr(routes_client, "compute_route_matrix", boom)
    monkeypatch.setattr(routes_client.settings, "routes_api_enabled", False, raising=False)

    session = _FakeSession()
    lookup = await routes_client.get_travel_times_batch(session, [(a, b)], "walking")
    minutes, meters = lookup[(a.id, b.id, "walking")]
    assert 900 < meters < 1100
    assert session.inserted == []  # no writes
