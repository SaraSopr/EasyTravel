import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.preference import UserPreference
from app.models.user import User
from app.schemas.user import ChangePasswordRequest, PreferenceVector, UpdateProfileRequest, UserOut
from app.utils.auth import get_current_user, hash_password, verify_password

router = APIRouter(prefix="/users", tags=["users"])
logger = logging.getLogger(__name__)


@router.get("/me", response_model=UserOut)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User)
        .options(selectinload(User.preferences))
        .where(User.id == current_user.id)
    )
    user = result.scalar_one()
    return UserOut.model_validate(user)


@router.get("/me/preferences", response_model=PreferenceVector)
async def get_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == current_user.id)
    )
    pref = result.scalar_one_or_none()
    if pref is None:
        return PreferenceVector(
            nature=0.0, culture=0.0, food=0.0, adventure=0.0,
            nightlife=0.0, relax=0.0, family_friendly=0.0,
        )
    return PreferenceVector.model_validate(pref)


@router.put("/me/preferences", response_model=UserOut)
async def update_preferences(
    payload: PreferenceVector,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == current_user.id)
    )
    pref = result.scalar_one_or_none()

    if pref is None:
        pref = UserPreference(user_id=current_user.id)
        db.add(pref)

    pref.nature = payload.nature
    pref.culture = payload.culture
    pref.food = payload.food
    pref.adventure = payload.adventure
    pref.nightlife = payload.nightlife
    pref.relax = payload.relax
    pref.family_friendly = payload.family_friendly

    await db.commit()

    result = await db.execute(
        select(User)
        .options(selectinload(User.preferences))
        .where(User.id == current_user.id)
    )
    user = result.scalar_one()
    return UserOut.model_validate(user)


@router.patch("/me", response_model=UserOut)
async def update_profile(
    payload: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if payload.home_city is not None:
        current_user.home_city = payload.home_city
    if payload.age_range is not None:
        current_user.age_range = payload.age_range
    if payload.travel_with_children is not None:
        current_user.travel_with_children = payload.travel_with_children

    await db.commit()

    result = await db.execute(
        select(User)
        .options(selectinload(User.preferences))
        .where(User.id == current_user.id)
    )
    user = result.scalar_one()
    logger.info("profile updated user_id=%s", current_user.id)
    return UserOut.model_validate(user)


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    current_user.password_hash = hash_password(payload.new_password)
    await db.commit()
    logger.info("password changed user_id=%s", current_user.id)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import delete as sql_delete

    from app.models.experience import UserExperienceChoice
    from app.models.itinerary import Itinerary, ItineraryItem
    from app.models.preference import UserPreference

    # Delete itinerary_items first (FK on itineraries.id)
    itin_result = await db.execute(
        select(Itinerary.id).where(Itinerary.user_id == current_user.id)
    )
    itin_ids = [row[0] for row in itin_result.all()]
    if itin_ids:
        await db.execute(sql_delete(ItineraryItem).where(ItineraryItem.itinerary_id.in_(itin_ids)))

    await db.execute(sql_delete(Itinerary).where(Itinerary.user_id == current_user.id))
    await db.execute(sql_delete(UserExperienceChoice).where(UserExperienceChoice.user_id == current_user.id))
    await db.execute(sql_delete(UserPreference).where(UserPreference.user_id == current_user.id))
    await db.delete(current_user)
    await db.commit()
    logger.info("account deleted user_id=%s", current_user.id)
