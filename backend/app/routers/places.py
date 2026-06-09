import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.city import City
from app.models.poi import Poi
from app.models.user import User
from app.schemas.place import PlaceOut
from app.utils.auth import get_current_user

router = APIRouter(prefix="/places", tags=["places"])


@router.get("", response_model=list[PlaceOut])
async def list_places(
    city: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Poi).join(City).where(City.name == city).offset(offset).limit(limit)
    )
    return result.scalars().all()


@router.get("/{place_id}", response_model=PlaceOut)
async def get_place(
    place_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Poi).where(Poi.id == place_id)
    )
    poi = result.scalar_one_or_none()
    if poi is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Place not found"
        )
    return poi
