import type { Itinerary } from '@/types'

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

const prefetchedPhotos = new Set<string>()
const pendingPhotos = new Map<string, HTMLImageElement>()

/**
 * Start loading every photo as soon as an itinerary is available, including
 * stops from days that have not been selected yet.
 */
export function prefetchItineraryPhotos(itinerary: Itinerary): void {
  if (typeof Image === 'undefined') return

  itinerary.days
    .flatMap((day) => day.stops)
    .forEach((stop, index) => {
      const url = poiPhotoUrl(stop.poi_id)
      if (!url || prefetchedPhotos.has(url) || pendingPhotos.has(url)) return

      const image = new Image()
      image.loading = 'eager'
      image.decoding = 'async'
      image.setAttribute('fetchpriority', index === 0 ? 'high' : 'auto')

      pendingPhotos.set(url, image)
      image.onload = () => {
        pendingPhotos.delete(url)
        prefetchedPhotos.add(url)
      }
      image.onerror = () => {
        pendingPhotos.delete(url)
      }
      image.src = url
    })
}
