import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { CSSProperties } from 'react'
import { MapContainer, TileLayer, Marker, Polyline, ZoomControl, useMap } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { Repeat, Trash2, X, Star, Check, Navigation, ImageOff } from 'lucide-react'
import type { Itinerary, ItineraryStop, PoiSuggestion } from '@/types'
import { getCategoryColor } from '@/utils/categoryColors'
import { poiPhotoUrl } from '@/utils/photos'
import {
  markVisited,
  unmarkVisited,
  getStopAlternatives,
  replaceStop,
  removeStop,
} from '@/api/endpoints'

const DAY_PALETTE = [
  { color: '#6366F1', colorLight: '#EEF2FF' }, // indigo-500 — brand day 1
  { color: '#0369A1', colorLight: '#E0F2FE' }, // sky-700
  { color: '#B45309', colorLight: '#FFFBEB' }, // amber-700
  { color: '#BE185D', colorLight: '#FDF2F8' }, // pink-800
  { color: '#6D28D9', colorLight: '#EDE9FE' }, // violet-700
  { color: '#0F766E', colorLight: '#F0FDFA' }, // teal-700
  { color: '#C2410C', colorLight: '#FFF7ED' }, // orange-700
]

function dayPalette(index: number) {
  return DAY_PALETTE[index % DAY_PALETTE.length]
}

function transportLabel(mode: string | null): string {
  if (mode === 'driving') return '🚗'
  if (mode === 'transit') return '🚌'
  return '🚶'
}

function createPinIcon(color: string, colorLight: string, label: string, active: boolean) {
  const w = active ? 40 : 30
  const h = active ? 50 : 38
  return L.divIcon({
    className: '',
    html: `<div style="position:relative;width:${w}px;height:${h}px;filter:drop-shadow(0 3px 6px rgba(0,0,0,${active ? 0.35 : 0.22}));transition:all .2s ease">
      <svg viewBox="0 0 32 40" fill="none" xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}">
        <path d="M16 0C7.163 0 0 7.163 0 16C0 27 16 40 16 40C16 40 32 27 32 16C32 7.163 24.837 0 16 0Z" fill="${color}"/>
        <circle cx="16" cy="16" r="9" fill="${colorLight}"/>
        <text x="16" y="20.5" text-anchor="middle"
          font-family="'Plus Jakarta Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif"
          font-size="10" font-weight="800" fill="${color}">${label}</text>
      </svg>
    </div>`,
    iconSize: [w, h],
    iconAnchor: [w / 2, h],
    popupAnchor: [0, -h],
  })
}

/** Hands the Leaflet map instance up to the parent for imperative control. */
function MapBridge({ onReady }: { onReady: (map: L.Map) => void }) {
  const map = useMap()
  useEffect(() => {
    onReady(map)
  }, [map, onReady])
  return null
}

/** Flies the mini-map to a new position when lat/lng change. */
function FlyToAlt({ lat, lng }: { lat: number; lng: number }) {
  const map = useMap()
  useEffect(() => {
    map.flyTo([lat, lng], Math.max(map.getZoom(), 14), { duration: 0.45 })
  }, [lat, lng, map])
  return null
}

/** Re-measures a Leaflet map once it has settled into its container. */
function InvalidateOnMount() {
  const map = useMap()
  useEffect(() => {
    const t = window.setTimeout(() => map.invalidateSize(), 200)
    return () => window.clearTimeout(t)
  }, [map])
  return null
}

interface ItineraryExplorerProps {
  itinerary: Itinerary
  onChange: () => void | Promise<void>
}

export default function ItineraryExplorer({ itinerary, onChange }: ItineraryExplorerProps) {
  const days = itinerary.days
  const [selectedDayNumber, setSelectedDayNumber] = useState(days[0]?.day_number ?? 1)
  const [activeIndex, setActiveIndex] = useState(0)
  const [visited, setVisited] = useState<Record<string, boolean>>({})
  const [loadingId, setLoadingId] = useState<string | null>(null)

  // Alternatives sheet
  const [sheetItemId, setSheetItemId] = useState<string | null>(null)
  const [sheetStopName, setSheetStopName] = useState('')
  const [alternatives, setAlternatives] = useState<PoiSuggestion[]>([])
  const [loadingAlts, setLoadingAlts] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [hoveredAlt, setHoveredAlt] = useState<PoiSuggestion | null>(null)

  const mapRef = useRef<L.Map | null>(null)
  const carouselRef = useRef<HTMLDivElement | null>(null)
  const rafRef = useRef<number | null>(null)
  const suppressScrollSync = useRef(false)
  const activeIndexRef = useRef(0)
  activeIndexRef.current = activeIndex

  const selectedIndex = Math.max(0, days.findIndex((d) => d.day_number === selectedDayNumber))
  const selectedDay = days[selectedIndex] ?? days[0]
  const { color, colorLight } = dayPalette(selectedIndex)

  const replacingStop = useMemo(
    () => selectedDay.stops.find((s) => s.item_id === sheetItemId) ?? null,
    [selectedDay.stops, sheetItemId],
  )

  const stops = useMemo(
    () => selectedDay.stops.filter((s) => s.lat && s.lng),
    [selectedDay],
  )

  const dayCoords = useMemo<[number, number][]>(
    () => stops.map((s) => [s.lat, s.lng]),
    [stops],
  )

  // Transit/taxi legs are drawn dotted: optimised on real travel time, so a long
  // straight connector is intentional, not a routing error.
  const isRideLeg = (mode: string | null) => mode === 'transit' || mode === 'taxi'
  const hasRide = useMemo(() => stops.some((s) => isRideLeg(s.transport_from_previous)), [stops])

  // Keep the latest coords reachable from callbacks that run on map (re)mount.
  const dayCoordsRef = useRef(dayCoords)
  dayCoordsRef.current = dayCoords

  const fitToDay = useCallback((map: L.Map, animate: boolean) => {
    const coords = dayCoordsRef.current
    if (coords.length === 0) return
    if (coords.length === 1) {
      map.setView(coords[0], 15, { animate })
    } else {
      map.fitBounds(L.latLngBounds(coords), { padding: [56, 56], maxZoom: 15, animate })
    }
  }, [])

  const onMapReady = useCallback((map: L.Map) => {
    mapRef.current = map
    // Leaflet measures the container before it has settled into the rounded
    // card, leaving the tile/overlay panes out of sync (tiles spill out, the
    // route is drawn askew). Re-measure, then frame the day. This also restores
    // the view after the map remounts when the Replace sheet closes.
    window.setTimeout(() => {
      map.invalidateSize()
      fitToDay(map, false)
    }, 0)
  }, [fitToDay])

  // Fit the map to the selected day's route whenever the day changes.
  useEffect(() => {
    setActiveIndex(0)
    const map = mapRef.current
    if (map) fitToDay(map, true)
    // Reset carousel to the first card.
    const el = carouselRef.current
    if (el) el.scrollTo({ left: 0, behavior: 'auto' })
  }, [dayCoords, fitToDay])

  const focusStop = useCallback(
    (index: number, fly: boolean) => {
      const map = mapRef.current
      const stop = stops[index]
      if (!map || !stop) return
      const target: [number, number] = [stop.lat, stop.lng]
      if (fly) {
        map.flyTo(target, Math.max(map.getZoom(), 14), { duration: 0.6 })
      } else {
        map.panTo(target, { animate: true, duration: 0.35 })
      }
    },
    [stops],
  )

  // Scroll → active card. Center-nearest, throttled with rAF.
  const handleScroll = useCallback(() => {
    if (suppressScrollSync.current) return
    if (rafRef.current != null) return
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null
      const el = carouselRef.current
      if (!el) return
      const center = el.scrollLeft + el.clientWidth / 2
      let nearest = 0
      let best = Infinity
      Array.from(el.children).forEach((child, i) => {
        const node = child as HTMLElement
        const childCenter = node.offsetLeft + node.offsetWidth / 2
        const dist = Math.abs(childCenter - center)
        if (dist < best) {
          best = dist
          nearest = i
        }
      })
      if (nearest !== activeIndexRef.current) {
        setActiveIndex(nearest)
        focusStop(nearest, false)
      }
    })
  }, [focusStop])

  const scrollToIndex = useCallback((index: number) => {
    const el = carouselRef.current
    const child = el?.children[index] as HTMLElement | undefined
    if (!el || !child) return
    suppressScrollSync.current = true
    const left = child.offsetLeft - (el.clientWidth - child.offsetWidth) / 2
    el.scrollTo({ left, behavior: 'smooth' })
    window.setTimeout(() => {
      suppressScrollSync.current = false
    }, 450)
  }, [])

  const selectStop = useCallback(
    (index: number) => {
      setActiveIndex(index)
      scrollToIndex(index)
      focusStop(index, true)
    },
    [scrollToIndex, focusStop],
  )

  // --- Stop actions (ported from the timeline) ---
  const toggleVisited = async (itemId: string, currentlyVisited: boolean) => {
    setLoadingId(itemId)
    try {
      if (currentlyVisited) {
        await unmarkVisited(itinerary.itinerary_id, itemId)
        setVisited((v) => ({ ...v, [itemId]: false }))
      } else {
        await markVisited(itinerary.itinerary_id, itemId)
        setVisited((v) => ({ ...v, [itemId]: true }))
      }
    } finally {
      setLoadingId(null)
    }
  }

  const openAlternatives = async (itemId: string, stopName: string) => {
    setSheetItemId(itemId)
    setSheetStopName(stopName)
    setAlternatives([])
    setHoveredAlt(null)
    setLoadingAlts(true)
    try {
      setAlternatives(await getStopAlternatives(itinerary.itinerary_id, itemId))
    } finally {
      setLoadingAlts(false)
    }
  }

  const closeSheet = () => {
    setSheetItemId(null)
    setAlternatives([])
    setHoveredAlt(null)
  }

  const chooseAlternative = async (poiId: string) => {
    if (!sheetItemId) return
    setBusyId(poiId)
    try {
      await replaceStop(itinerary.itinerary_id, sheetItemId, poiId)
      closeSheet()
      await onChange()
    } finally {
      setBusyId(null)
    }
  }

  const handleRemove = async (itemId: string) => {
    setBusyId(itemId)
    try {
      await removeStop(itinerary.itinerary_id, itemId)
      await onChange()
    } finally {
      setBusyId(null)
    }
  }

  if (stops.length === 0) return null

  const center: [number, number] = [stops[0].lat, stops[0].lng]

  return (
    <div className="flex flex-col gap-4">
      {/* Map with floating glass day selector. Unmounted while the Replace
          sheet is open, so only the sheet's mini-map is mounted at that time
          (one Leaflet map on screen, never two). */}
      {!sheetItemId && (
      <div className="relative rounded-3xl overflow-hidden shadow-lg border border-white/40">
        <MapContainer
          center={center}
          zoom={13}
          style={{ height: 380, width: '100%' }}
          zoomControl={false}
          scrollWheelZoom={false}
          attributionControl={true}
        >
          <TileLayer
            url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OSM</a> &copy; <a href="https://carto.com/attributions" target="_blank">CARTO</a>'
            maxZoom={20}
          />
          <ZoomControl position="bottomright" />
          <MapBridge onReady={onMapReady} />

          {stops.slice(1).map((stop, i) => {
            const from = stops[i]
            const ride = isRideLeg(stop.transport_from_previous)
            return (
              <Polyline
                key={`leg-${stop.poi_id}`}
                positions={[[from.lat, from.lng], [stop.lat, stop.lng]]}
                pathOptions={{
                  color,
                  weight: ride ? 3 : 4,
                  opacity: ride ? 0.7 : 0.8,
                  dashArray: ride ? '1 7' : undefined,
                  lineCap: 'round',
                  lineJoin: 'round',
                }}
              />
            )
          })}
          {stops.map((stop, i) => (
            <Marker
              key={stop.poi_id}
              position={[stop.lat, stop.lng]}
              icon={createPinIcon(color, colorLight, String(i + 1), i === activeIndex)}
              zIndexOffset={i === activeIndex ? 1000 : 0}
              eventHandlers={{ click: () => selectStop(i) }}
            />
          ))}
        </MapContainer>

        {/* Day selector — glass, floating over the map */}
        {days.length > 1 && (
          <div className="absolute top-3 left-3 right-3 z-[400] flex gap-1.5 overflow-x-auto snap-carousel">
            <div className="glass glass-specular rounded-full p-1 flex gap-1">
              {days.map((day, dayIndex) => {
                const active = day.day_number === selectedDayNumber
                const dayColor = dayPalette(dayIndex).color
                return (
                  <button
                    key={day.day_number}
                    onClick={() => setSelectedDayNumber(day.day_number)}
                    className={`shrink-0 px-3.5 py-1.5 rounded-full text-xs font-bold transition-all ${
                      active ? 'text-white shadow-sm' : 'text-gray-600'
                    }`}
                    style={active ? { backgroundColor: dayColor } : {}}
                  >
                    Day {day.day_number}
                  </button>
                )
              })}
            </div>
          </div>
        )}

        {/* Progress dots — glass, bottom center */}
        <div className="absolute bottom-3 left-1/2 -translate-x-1/2 z-[400] glass glass-specular rounded-full px-2.5 py-1.5 flex items-center gap-1.5">
          {stops.map((stop, i) => (
            <button
              key={stop.poi_id}
              onClick={() => selectStop(i)}
              aria-label={`Vai alla tappa ${i + 1}`}
              className="p-0.5"
            >
              <span
                className={`block rounded-full transition-all ${
                  i === activeIndex ? 'w-5 h-1.5' : 'w-1.5 h-1.5 bg-gray-400/70'
                }`}
                style={i === activeIndex ? { backgroundColor: color } : {}}
              />
            </button>
          ))}
        </div>
      </div>
      )}

      {/* Walk/transit legend — below the map, only when a ride leg exists */}
      {!sheetItemId && hasRide && (
        <div className="flex items-center justify-center gap-4 px-1 text-xs font-medium text-gray-500">
          <span className="flex items-center gap-1.5">
            <span className="w-5 border-t-[3px] border-gray-500 rounded-full" />
            Walk
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-5 border-t-[3px] border-dotted border-gray-500" />
            Transit
          </span>
        </div>
      )}

      {/* Stop carousel — synced to the map */}
      <div
        ref={carouselRef}
        onScroll={handleScroll}
        className="snap-carousel flex gap-3 overflow-x-auto px-1 pb-1"
      >
        {stops.map((stop, i) => (
          <StopCard
            key={stop.poi_id}
            stop={stop}
            index={i}
            color={color}
            active={i === activeIndex}
            visited={stop.item_id ? (visited[stop.item_id] ?? false) : false}
            loadingVisited={loadingId === stop.item_id}
            busy={busyId === stop.item_id}
            onToggleVisited={toggleVisited}
            onChangeStop={openAlternatives}
            onRemove={handleRemove}
            onActivate={() => selectStop(i)}
          />
        ))}
      </div>

      {/* Alternatives bottom sheet — portaled to <body> so its mini-map lives
          outside the main map's DOM subtree and tears down cleanly on close. */}
      {sheetItemId && createPortal(
        <div className="fixed inset-0 z-50 flex justify-center" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={closeSheet} />
          <div className="glass glass-specular relative w-full max-w-md h-full flex flex-col">
            <div className="flex items-start justify-between gap-3 px-5 pt-5 pb-3 border-b border-white/60 shrink-0">
              <div className="min-w-0">
                <p className="text-xs text-gray-500 font-medium">Replacing</p>
                <h3 className="text-base font-bold text-gray-900 truncate">{sheetStopName}</h3>
              </div>
              <button
                onClick={closeSheet}
                className="shrink-0 w-8 h-8 rounded-full bg-white/65 border border-white/70 shadow-sm flex items-center justify-center text-gray-600 active:scale-95"
              >
                <X size={16} />
              </button>
            </div>

            {/* Mini-map — shows the day route with the replacing stop and hovered alternative */}
            {replacingStop && (
              <div className="overflow-hidden border-b border-white/60 h-[45vh] shrink-0">
                <MapContainer
                  key={sheetItemId!}
                  center={[replacingStop.lat, replacingStop.lng]}
                  zoom={14}
                  style={{ height: '100%', width: '100%' }}
                  zoomControl={false}
                  scrollWheelZoom={true}
                  attributionControl={false}
                >
                  <TileLayer
                    url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
                    maxZoom={20}
                  />
                  <ZoomControl position="bottomright" />
                  {stops.length > 1 && (
                    <Polyline
                      positions={stops.map((s) => [s.lat, s.lng] as [number, number])}
                      pathOptions={{ color: '#CBD5E1', weight: 2, opacity: 0.6, dashArray: '5 5' }}
                    />
                  )}
                  {stops.map((s, i) => {
                    const isReplacing = s.item_id === sheetItemId
                    return (
                      <Marker
                        key={s.poi_id}
                        position={[s.lat, s.lng]}
                        icon={createPinIcon(
                          isReplacing ? '#EF4444' : '#94A3B8',
                          isReplacing ? '#FEE2E2' : '#F8FAFC',
                          isReplacing ? '×' : String(i + 1),
                          isReplacing,
                        )}
                        zIndexOffset={isReplacing ? 200 : 0}
                      />
                    )
                  })}
                  {hoveredAlt && (
                    <Marker
                      position={[hoveredAlt.lat, hoveredAlt.lng]}
                      icon={createPinIcon(color, colorLight, '★', true)}
                      zIndexOffset={500}
                    />
                  )}
                  <InvalidateOnMount />
                  <FlyToAlt
                    lat={hoveredAlt?.lat ?? replacingStop.lat}
                    lng={hoveredAlt?.lng ?? replacingStop.lng}
                  />
                </MapContainer>
              </div>
            )}

            <div className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-2">
              {loadingAlts ? (
                <div className="flex flex-col gap-2 py-2">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className="w-full h-16 rounded-2xl shimmer animate-pulse" />
                  ))}
                </div>
              ) : alternatives.length === 0 ? (
                <p className="text-sm text-gray-500 text-center py-10">No alternatives available.</p>
              ) : (
                alternatives.map((alt) => {
                  const altPhoto = poiPhotoUrl(alt.poi_id)
                  return (
                    <button
                      key={alt.poi_id}
                      onClick={() => chooseAlternative(alt.poi_id)}
                      onPointerEnter={() => setHoveredAlt(alt)}
                      onPointerLeave={() => setHoveredAlt(null)}
                      disabled={busyId !== null}
                      className="text-left bg-white/60 border border-white/70 rounded-2xl p-2.5 shadow-sm active:scale-[0.99] transition-transform disabled:opacity-50 flex gap-3 items-center"
                    >
                      <div className="w-14 h-14 rounded-xl overflow-hidden shrink-0 bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center">
                        {altPhoto ? (
                          <img src={altPhoto} alt="" loading="lazy" className="w-full h-full object-cover" />
                        ) : (
                          <ImageOff size={18} className="text-white/80" />
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-start justify-between gap-2">
                          <p className="font-bold text-sm text-gray-900 leading-tight flex-1 min-w-0">{alt.name}</p>
                          {alt.travel_category && (
                            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full shrink-0 ${getCategoryColor(alt.travel_category)}`}>
                              {alt.travel_category}
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-2 mt-1 flex-wrap">
                          {alt.rating != null && (
                            <span className="text-xs text-gray-600 inline-flex items-center gap-0.5">
                              <Star size={11} className="fill-amber-400 text-amber-400" /> {alt.rating.toFixed(1)}
                            </span>
                          )}
                          {alt.address && (
                            <span className="text-xs text-gray-400 truncate">{alt.address}</span>
                          )}
                        </div>
                        {busyId === alt.poi_id && (
                          <p className="text-xs text-indigo-500 mt-1">Replacing stop…</p>
                        )}
                      </div>
                    </button>
                  )
                })
              )}
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  )
}

interface StopCardProps {
  stop: ItineraryStop
  index: number
  color: string
  active: boolean
  visited: boolean
  loadingVisited: boolean
  busy: boolean
  onToggleVisited: (itemId: string, currentlyVisited: boolean) => void
  onChangeStop: (itemId: string, stopName: string) => void
  onRemove: (itemId: string) => void
  onActivate: () => void
}

function StopCard({
  stop,
  index,
  color,
  active,
  visited,
  loadingVisited,
  busy,
  onToggleVisited,
  onChangeStop,
  onRemove,
  onActivate,
}: StopCardProps) {
  const [imgError, setImgError] = useState(false)
  const photo = poiPhotoUrl(stop.poi_id)
  const showPhoto = photo && !imgError

  return (
    <article
      className={`snap-item shrink-0 w-[84%] flex flex-col bg-white rounded-3xl overflow-hidden shadow-md transition-all duration-300 ${
        active ? 'ring-2 ring-offset-2 ring-offset-gray-50' : 'opacity-95'
      }`}
      style={active ? ({ boxShadow: `0 12px 32px ${color}33`, '--tw-ring-color': color } as CSSProperties) : {}}
    >
      {/* Hero photo */}
      <button onClick={onActivate} className="relative block w-full h-40 text-left">
        {showPhoto ? (
          <img
            src={photo}
            alt={stop.name}
            loading="eager"
            fetchPriority={active ? 'high' : 'auto'}
            decoding="async"
            onError={() => setImgError(true)}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="w-full h-full bg-gradient-to-br from-indigo-500 via-indigo-600 to-violet-600 flex items-center justify-center">
            <span className="text-4xl drop-shadow">{stop.visit_mode === 'outdoor' ? '🏞️' : '🏛️'}</span>
          </div>
        )}
        {/* Legibility scrim */}
        <div className="absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-black/55 to-transparent" />

        {/* Stop number — glass chip */}
        <span
          className="absolute top-3 left-3 w-8 h-8 rounded-full glass-dark glass-specular flex items-center justify-center text-sm font-extrabold"
          style={{ color: '#fff' }}
        >
          {index + 1}
        </span>

        {stop.travel_category && (
          <span className={`absolute top-3 right-3 text-xs font-semibold px-2.5 py-1 rounded-full ${getCategoryColor(stop.travel_category)}`}>
            {stop.travel_category}
          </span>
        )}

        <div className="absolute inset-x-0 bottom-0 px-4 pb-3">
          {stop.arrival_time && (
            <span className="text-xs font-semibold text-white/90">
              {stop.arrival_time}
              {stop.departure_time && ` – ${stop.departure_time}`}
            </span>
          )}
          <h3 className={`text-white font-extrabold text-lg leading-tight drop-shadow ${visited ? 'line-through opacity-80' : ''}`}>
            {stop.name}
          </h3>
        </div>
      </button>

      {/* Body */}
      <div className="p-4 flex flex-col gap-3 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="inline-flex items-center gap-1 text-xs bg-gray-50 text-gray-600 px-2.5 py-1 rounded-lg font-medium border border-gray-100">
            {stop.visit_mode === 'outdoor' ? '☀️' : '🎟️'} {stop.visit_duration_minutes} min
          </span>
          {stop.rating != null && (
            <span className="inline-flex items-center gap-1 text-xs bg-gray-50 text-gray-600 px-2.5 py-1 rounded-lg font-medium border border-gray-100">
              <Star size={11} className="fill-amber-400 text-amber-400" /> {stop.rating.toFixed(1)}
            </span>
          )}
          {stop.transport_from_previous != null && stop.travel_minutes_from_previous != null && index > 0 && (
            <span className="inline-flex items-center gap-1 text-xs bg-gray-50 text-gray-600 px-2.5 py-1 rounded-lg font-medium border border-gray-100">
              {transportLabel(stop.transport_from_previous)} {Math.round(stop.travel_minutes_from_previous)} min
            </span>
          )}
          {!stop.is_new_suggestion && (
            <span className="text-xs font-semibold px-2 py-1 rounded-lg bg-gray-100 text-gray-500">already seen</span>
          )}
        </div>

        {stop.address && (
          <p className="text-xs text-gray-500 truncate">📍 {stop.address}</p>
        )}
        {stop.visit_note && (
          <p className="text-xs text-amber-700 bg-amber-50 rounded-lg px-2.5 py-1.5 border border-amber-100">
            {stop.visit_note}
          </p>
        )}

        <div className="flex gap-2 mt-auto">
          {stop.google_maps_url && (
            <a
              href={stop.google_maps_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex-1 inline-flex items-center justify-center gap-1.5 text-xs font-semibold py-2.5 rounded-xl border border-indigo-100 bg-indigo-50 text-indigo-600 active:scale-[0.98] transition-transform"
            >
              <Navigation size={13} /> Directions
            </a>
          )}
          {stop.item_id && (
            <>
              <button
                onClick={() => onChangeStop(stop.item_id!, stop.name)}
                disabled={busy}
                className="inline-flex items-center justify-center gap-1.5 text-xs font-semibold py-2.5 px-3 rounded-xl border border-gray-200 bg-white text-gray-600 active:scale-[0.98] transition-transform disabled:opacity-50"
              >
                <Repeat size={13} /> Replace
              </button>
              <button
                onClick={() => onRemove(stop.item_id!)}
                disabled={busy}
                aria-label="Remove stop"
                className="inline-flex items-center justify-center py-2.5 px-3 rounded-xl border border-gray-200 bg-white text-gray-500 active:scale-[0.98] transition-transform disabled:opacity-50"
              >
                <Trash2 size={13} />
              </button>
            </>
          )}
        </div>

        {stop.item_id && (
          <button
            onClick={() => onToggleVisited(stop.item_id!, visited)}
            disabled={loadingVisited}
            className={`w-full inline-flex items-center justify-center gap-1.5 text-xs font-semibold py-2.5 rounded-xl border transition-all active:scale-[0.98] disabled:opacity-50 ${
              visited
                ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                : 'bg-emerald-500 border-emerald-500 text-white'
            }`}
          >
            {loadingVisited ? (
              '…'
            ) : visited ? (
              <>
                <Check size={13} /> Visited
              </>
            ) : (
              'Mark as visited'
            )}
          </button>
        )}
      </div>
    </article>
  )
}
