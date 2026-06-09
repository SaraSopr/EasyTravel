from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.city import City
from app.models.poi import Poi
from app.models.preference import UserPreference
from app.models.user import User
from app.schemas.place import PlaceOut, PlaceOutWithScore
from app.schemas.user import PreferenceVector
from app.services import recommendation as recommendation_service
from app.utils.auth import get_current_user

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


class RecommendationRequest(BaseModel):
    city: str


@router.post("", response_model=list[PlaceOutWithScore])
async def get_recommendations(
    payload: RecommendationRequest,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pref_result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == current_user.id)
    )
    pref = pref_result.scalar_one_or_none()
    if pref is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User preferences not found",
        )

    user_prefs = PreferenceVector(
        nature=pref.nature,
        culture=pref.culture,
        food=pref.food,
        adventure=pref.adventure,
        nightlife=pref.nightlife,
        relax=pref.relax,
        family_friendly=pref.family_friendly,
    )

    pois_result = await db.execute(
        select(Poi).join(City).where(City.name == payload.city)
    )
    pois = pois_result.scalars().all()

    ranked = recommendation_service.rank_pois(user_prefs, pois)
    ranked.sort(key=lambda x: x[1], reverse=True)

    page = ranked[offset : offset + limit]
    return [
        PlaceOutWithScore(**PlaceOut.model_validate(poi).model_dump(), score=score)
        for poi, score in page
    ]
