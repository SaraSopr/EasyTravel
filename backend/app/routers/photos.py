import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.poi import Poi
from app.services.storage import get_poi_public_url, poi_photo_cached_url, store_poi_photo

router = APIRouter(prefix="/photos", tags=["photos"])

# Photos resolved/cached at a single generous size; the client downscales as needed.
_CACHE_WIDTH = 800
_CACHE_CONTROL = "public, max-age=604800"


async def _resolve_fresh_photo(place_id: str) -> bytes | None:
    """Resolve a POI's current photo via Places API (New).

    The ``photo_reference`` stored on older POIs is a legacy token the New API
    rejects, so we look the place up fresh by ``google_place_id`` to get its
    current photo resource name, then fetch the media bytes. Returns None when
    the place has no photo.
    """
    key = settings.google_places_api_key
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as http:
        details = await http.get(
            f"https://places.googleapis.com/v1/places/{place_id}",
            params={"fields": "photos", "key": key},
        )
        details.raise_for_status()
        photos = details.json().get("photos") or []
        if not photos:
            return None
        name = photos[0].get("name")
        if not name:
            return None

        media = await http.get(
            f"https://places.googleapis.com/v1/{name}/media",
            params={"maxWidthPx": _CACHE_WIDTH, "key": key},
        )
        media.raise_for_status()
        return media.content


@router.get("/poi")
async def get_poi_photo(
    poi_id: uuid.UUID = Query(..., description="EasyTravel POI id"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Serve a POI photo, resolving it lazily and caching to R2.

    Public (no auth) so plain ``<img>`` tags work. First hit resolves the photo
    from Google and stores it on R2; later hits redirect straight to the cached
    R2 object. The Google API key never reaches the client.
    """
    poi = await db.get(Poi, poi_id)
    if poi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="POI not found")

    place_id = poi.google_place_id

    cached = await poi_photo_cached_url(place_id)
    if cached:
        return RedirectResponse(cached, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    if not settings.google_places_api_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Photos not configured")

    try:
        image_bytes = await _resolve_fresh_photo(place_id)
    except httpx.HTTPError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Photo fetch failed")

    if image_bytes is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No photo for this place")

    stored = await store_poi_photo(place_id, image_bytes)
    if stored:
        # Point the browser at the durable R2 copy for this and future loads.
        return RedirectResponse(get_poi_public_url(place_id), status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    return Response(content=image_bytes, media_type="image/jpeg", headers={"Cache-Control": _CACHE_CONTROL})
