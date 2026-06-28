"""Public metadata endpoints — config values the frontend needs to render forms.

Exposing these from the single backend source of truth (app.constants) lets the
frontend drop its hard-coded copies, so the input contract can't drift.
"""
from fastapi import APIRouter

from app.constants import AGE_RANGES

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/age-ranges")
async def get_age_ranges() -> dict[str, list[str]]:
    """Canonical age buckets accepted by registration / profile update."""
    return {"age_ranges": list(AGE_RANGES)}
