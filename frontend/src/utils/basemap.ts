/**
 * CARTO Voyager raster basemap, shared by every Leaflet map in the app.
 *
 * CARTO requires an API key on the raster tile endpoint: without one the CDN
 * still answers 200, but every tile is a grey "API KEY REQUIRED" placeholder
 * instead of the map. Keeping the URL here means a map can't be added with the
 * key accidentally left off — which is how the itinerary explorer ended up
 * rendering watermarked tiles while the other maps worked.
 *
 * Set VITE_CARTO_API_KEY in the frontend env (see .env.example).
 */
const CARTO_KEY = import.meta.env.VITE_CARTO_API_KEY ?? ''

export const BASEMAP_URL =
  `https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png?key=${CARTO_KEY}`

export const BASEMAP_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OSM</a> &copy; <a href="https://carto.com/attributions" target="_blank">CARTO</a>'

export const BASEMAP_MAX_ZOOM = 20
