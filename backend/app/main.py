import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.limiter import limiter
from app.routers import auth, evaluation, itineraries, meta, onboarding, photos, places, recommendations, users
from app.utils.logging import LoggingMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("EasyTravel API starting up")
    yield
    logger.info("EasyTravel API shutting down")


app = FastAPI(title="EasyTravel API", lifespan=lifespan)

app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(LoggingMiddleware)

app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(onboarding.router, prefix="/api")
app.include_router(places.router, prefix="/api")
app.include_router(photos.router, prefix="/api")
app.include_router(recommendations.router, prefix="/api")
app.include_router(itineraries.router, prefix="/api")
app.include_router(evaluation.router, prefix="/api")
app.include_router(meta.router, prefix="/api")


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exception_handler(request, exc):
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please try again later."},
    )


@app.get("/api/health", tags=["health"])
async def health():
    from sqlalchemy import text
    from app.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        logger.error("Health check DB probe failed: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "error", "detail": "Database unavailable"},
        )
