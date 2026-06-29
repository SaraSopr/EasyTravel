"""Public metadata endpoints — config values the frontend needs to render forms.

Exposing these from the single backend source of truth (app.constants) lets the
frontend drop its hard-coded copies, so the input contract can't drift.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AGE_RANGES
from app.database import get_db
from app.models.city import City

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/age-ranges")
async def get_age_ranges() -> dict[str, list[str]]:
    """Canonical age buckets accepted by registration / profile update."""
    return {"age_ranges": list(AGE_RANGES)}


@router.get("/cities")
async def get_cities(db: AsyncSession = Depends(get_db)) -> dict[str, list[str]]:
    """Cities that have been imported into the database."""
    result = await db.execute(select(City.name).order_by(City.name))
    return {"cities": list(result.scalars().all())}
