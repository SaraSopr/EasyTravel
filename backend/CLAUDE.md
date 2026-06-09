# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment setup

All work is done from the repository root. A virtualenv lives at `.venv`.

```bash
source .venv/bin/activate
```

Copy `.env.example` to `.env` and fill in `DATABASE_URL` before starting the server.

## Common commands

```bash
# Start dev server
python -m uvicorn app.main:app --reload

# Run a single Alembic migration
alembic upgrade head

# Generate a new migration after model changes
alembic revision --autogenerate -m "describe change"

# Downgrade one step
alembic downgrade -1
```

## Architecture

The app is a FastAPI service under `app/` with async SQLAlchemy 2.0 (asyncpg driver) against PostgreSQL.

**Request flow:** `main.py` → `LoggingMiddleware` (logs every non-health request to `api_logs`) → router → service (optional) → DB via `AsyncSession`.

**Layers:**
- `app/models/` — SQLAlchemy ORM models. `models/__init__.py` imports all of them; this is what Alembic's `env.py` relies on to detect schema changes.
- `app/schemas/` — Pydantic v2 request/response models. Schemas are separate from ORM models; use `.model_validate(orm_obj)` to convert.
- `app/routers/` — One file per resource. All registered in `main.py` under the `/api` prefix.
- `app/services/` — Business logic decoupled from HTTP. Currently stubs: `recommendation.py` (cosine similarity placeholder) and `itinerary_planner.py` (VRPTW placeholder).
- `app/utils/auth.py` — JWT creation/decoding (`python-jose`) and bcrypt hashing (`passlib`). `get_current_user` is the FastAPI dependency used on all protected routes. JWT `sub` field stores the user's **email**.

**Database sessions:** `get_db` (in `database.py`) is an async generator dependency injected into routers. The logging middleware uses `AsyncSessionLocal` directly (not `get_db`) since it runs outside the dependency system.

**Migrations:** Alembic is configured for async via `run_async_migrations()` in `migrations/env.py`. The `sqlalchemy.url` is overridden at runtime from `settings.database_url` — the value in `alembic.ini` is ignored.

**Startup:** The lifespan handler in `main.py` calls `Base.metadata.create_all` via `conn.run_sync(...)` — never call it directly on the async engine.

## Key conventions

- UUID primary keys generated in Python (`default=uuid.uuid4`), not by the database.
- All models use `from __future__ import annotations` + `TYPE_CHECKING` guards to avoid circular imports at runtime.
- `PlaceOut.score` is not on the ORM model — it is set manually in the recommendations router after ranking.
- The `onboarding/choices` endpoint recomputes and upserts `UserPreference` by calling `recommendation_service.build_user_vector()` with experience names (not IDs).
