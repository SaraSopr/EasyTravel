/**
 * Build the URL for a POI photo, served by the backend (which resolves the
 * photo from Google by the POI's id and caches it to R2). Keyed on our own
 * `poi_id` because the stored Google `photo_reference` is a stale legacy token.
 * Returns null when no id is available.
 */
export function poiPhotoUrl(poiId: string | null | undefined): string | null {
  if (!poiId) return null
  return `/api/photos/poi?poi_id=${encodeURIComponent(poiId)}`
}
