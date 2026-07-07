"""Demo endpoints for the thesis defense visualiser.

No authentication required — these are public endpoints for the live demo.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.demo_ingestion import build_ingestion_summary
from app.services.demo_trace import DEMO_PERSONAS, build_trace

router = APIRouter(prefix="/demo", tags=["demo"])


class PlanTraceRequest(BaseModel):
    city: str = Field(default="Roma")
    persona_id: str = Field(default="couple_museums")
    num_days: int = Field(default=3, ge=1, le=5)
    solver: str = Field(default="both", pattern="^(greedy|toptw|both)$")
    # None → the schedule the app derives from the persona's travel mode.
    start_time: str | None = Field(default=None)
    end_time: str | None = Field(default=None)


@router.get("/personas")
async def list_personas():
    """Return the demo personas with their preference vectors and travel modes."""
    return list(DEMO_PERSONAS.values())


@router.get("/ingestion")
async def demo_ingestion(
    city: str = Query(default="Roma"),
    db: AsyncSession = Depends(get_db),
):
    """Replay the POI ingestion pipeline for a city from persisted DB metadata.

    Read-only: no Google Places or LLM calls — every stage of pipeline/pipeline.py
    persists its outcome on the pois table, so the funnel is reconstructed from
    is_touristic / travel_category / confidence / opening_hours columns.
    """
    try:
        summary = await build_ingestion_summary(db, city)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return summary


@router.post("/plan-trace")
async def plan_trace(
    req: PlanTraceRequest,
    db: AsyncSession = Depends(get_db),
):
    """Run the greedy and/or TOPTW planners with full instrumentation.

    Returns a single JSON with all intermediate snapshots for the frontend
    visualiser. One request → the frontend animates locally with Next/Back.
    """
    try:
        trace = await build_trace(
            db=db,
            city_name=req.city,
            persona_id=req.persona_id,
            num_days=req.num_days,
            solver=req.solver,
            start_time_str=req.start_time,
            end_time_str=req.end_time,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Trace generation failed: {e}",
        )
    return trace
