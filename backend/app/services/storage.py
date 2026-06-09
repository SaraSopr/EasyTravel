from __future__ import annotations

import logging

import httpx
from botocore.exceptions import ClientError

from app.config import settings

logger = logging.getLogger(__name__)


def _r2_configured() -> bool:
    return all([
        settings.cloudflare_r2_access_key_id,
        settings.cloudflare_r2_secret_access_key,
        settings.cloudflare_r2_account_id,
        settings.cloudflare_r2_bucket_name,
        settings.cloudflare_r2_public_url,
    ])


def _get_r2_client():
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.cloudflare_r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.cloudflare_r2_access_key_id,
        aws_secret_access_key=settings.cloudflare_r2_secret_access_key,
        region_name="auto",
    )


def get_public_url(place_id: str, city: str) -> str:
    key = f"experiences/{city}/{place_id}.jpg"
    return f"{settings.cloudflare_r2_public_url}/{key}"


async def upload_photo_from_url(photo_url: str, place_id: str, city: str) -> str | None:
    """
    Downloads a photo from Google Places and uploads it to Cloudflare R2.
    Returns the public R2 URL, or None if R2 is not configured or upload fails.
    Idempotent: if the file already exists on R2, returns the public URL directly.
    """
    if not _r2_configured():
        return None

    key = f"experiences/{city}/{place_id}.jpg"

    try:
        client = _get_r2_client()

        # Idempotency check — skip download/upload if already stored
        try:
            client.head_object(Bucket=settings.cloudflare_r2_bucket_name, Key=key)
            logger.debug("r2 photo already exists key=%s", key)
            return get_public_url(place_id, city)
        except ClientError as e:
            if e.response["Error"]["Code"] != "404":
                raise

        # Download from Google Places (follows redirect automatically)
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as http:
            resp = await http.get(photo_url)
            resp.raise_for_status()
            image_bytes = resp.content

        # Upload to R2
        client.put_object(
            Bucket=settings.cloudflare_r2_bucket_name,
            Key=key,
            Body=image_bytes,
            ContentType="image/jpeg",
        )
        logger.info("r2 photo uploaded key=%s bytes=%d", key, len(image_bytes))
        return get_public_url(place_id, city)

    except Exception:
        logger.exception("r2 upload failed place_id=%s city=%s", place_id, city)
        return None
