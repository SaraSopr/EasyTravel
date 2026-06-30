import { Fragment, useEffect, useState } from 'react'
import { MapContainer, TileLayer, Marker, Polyline, Popup, ZoomControl, useMap } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { ItineraryDay } from '@/types'
import { getCategoryColor } from '@/utils/categoryColors'

const DAY_PALETTE = [
  { color: '#6366F1', colorLight: '#EEF2FF' },  // indigo-500 — brand day 1
  { color: '#0369A1', colorLight: '#E0F2FE' },  // sky-700
  { color: '#B45309', colorLight: '#FFFBEB' },  // amber-700
  { color: '#BE185D', colorLight: '#FDF2F8' },  // pink-800
  { color: '#6D28D9', colorLight: '#EDE9FE' },  // violet-700
  { color: '#0F766E', colorLight: '#F0FDFA' },  // teal-700
  { color: '#C2410C', colorLight: '#FFF7ED' },  // orange-700
]

function createPinIcon(color: string, colorLight: string, label: string) {
  return L.divIcon({
    className: '',
    html: `<div style="position:relative;width:32px;height:40px;filter:drop-shadow(0 3px 6px rgba(0,0,0,0.25))">
      <svg viewBox="0 0 32 40" fill="none" xmlns="http://www.w3.org/2000/svg" width="32" height="40">
        <path d="M16 0C7.163 0 0 7.163 0 16C0 27 16 40 16 40C16 40 32 27 32 16C32 7.163 24.837 0 16 0Z" fill="${color}"/>
        <circle cx="16" cy="16" r="9" fill="${colorLight}"/>
        <text x="16" y="20.5" text-anchor="middle"
          font-family="'Plus Jakarta Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif"
          font-size="10" font-weight="800" fill="${color}">${label}</text>
      </svg>
    </div>`,
    iconSize: [32, 40],
    iconAnchor: [16, 40],
    popupAnchor: [0, -44],
  })
}

function FitBounds({ coords }: { coords: [number, number][] }) {
  const map = useMap()
  useEffect(() => {
    if (coords.length === 1) {
      map.setView(coords[0], 15)
    } else if (coords.length > 1) {
      map.fitBounds(L.latLngBounds(coords), { padding: [48, 48], maxZoom: 15, animate: false })
    }
  }, [map, coords])
  return null
}

interface ItineraryMapProps {
  days: ItineraryDay[]
}

export default function ItineraryMap({ days }: ItineraryMapProps) {
  const allStops = days.flatMap(d => d.stops).filter(s => s.lat && s.lng)
  if (allStops.length === 0) return null

  const [visibleDays, setVisibleDays] = useState<Set<number>>(() => new Set(days.map(d => d.day_number)))

  const toggleDay = (dayNumber: number) => {
    setVisibleDays(prev => {
      const next = new Set(prev)
      if (next.has(dayNumber)) {
        if (next.size === 1) return prev // keep at least one visible
        next.delete(dayNumber)
      } else {
        next.add(dayNumber)
      }
      return next
    })
  }

  const visibleStops = days
    .filter(d => visibleDays.has(d.day_number))
    .flatMap(d => d.stops)
    .filter(s => s.lat && s.lng)

  const center: [number, number] = [allStops[0].lat, allStops[0].lng]
  const allCoords: [number, number][] = visibleStops.map(s => [s.lat, s.lng])

  // A "ride" leg (transit/taxi) is drawn dotted: those legs are optimised on real
  // travel time, so a long straight connector is intentional, not a routing error.
  const isRideLeg = (mode: string | null) => mode === 'transit' || mode === 'taxi'
  const hasRide = visibleStops.some(s => isRideLeg(s.transport_from_previous))

  return (
    <div className="flex flex-col gap-3">
      {days.length > 1 && (
        <div className="flex items-center gap-3 flex-wrap px-1">
          {days.map((day, dayIndex) => {
            const { color } = DAY_PALETTE[dayIndex % DAY_PALETTE.length]
            const active = visibleDays.has(day.day_number)
            return (
              <button
                key={day.day_number}
                onClick={() => toggleDay(day.day_number)}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-semibold transition-all ${
                  active
                    ? 'border-transparent text-white shadow-sm'
                    : 'border-gray-200 text-gray-400 bg-white'
                }`}
                style={active ? { backgroundColor: color } : {}}
              >
                Day {day.day_number}
              </button>
            )
          })}
        </div>
      )}

      {hasRide && (
        <div className="flex items-center gap-4 px-1 text-[11px] text-gray-400">
          <span className="flex items-center gap-1.5">
            <span className="w-5 border-t-[3px] border-gray-400 rounded-full" />
            Walk
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-5 border-t-[3px] border-dotted border-gray-400" />
            Transit
          </span>
        </div>
      )}

      <div className="rounded-2xl overflow-hidden border border-gray-100 shadow-md">
        <MapContainer
          center={center}
          zoom={13}
          style={{ height: 340, width: '100%' }}
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
          <FitBounds coords={allCoords} />

          {days.map((day, dayIndex) => {
            if (!visibleDays.has(day.day_number)) return null
            const { color, colorLight } = DAY_PALETTE[dayIndex % DAY_PALETTE.length]
            const validStops = day.stops.filter(s => s.lat && s.lng)

            return (
              <Fragment key={day.day_number}>
                {validStops.slice(1).map((stop, i) => {
                  const from = validStops[i]
                  const ride = isRideLeg(stop.transport_from_previous)
                  return (
                    <Polyline
                      key={`${day.day_number}-leg-${i}`}
                      positions={[[from.lat, from.lng], [stop.lat, stop.lng]]}
                      pathOptions={{
                        color,
                        weight: ride ? 3 : 4,
                        opacity: ride ? 0.65 : 0.75,
                        dashArray: ride ? '1 7' : undefined,
                        lineCap: 'round',
                        lineJoin: 'round',
                      }}
                    />
                  )
                })}
                {validStops.map((stop, stopIdx) => (
                  <Marker
                    key={stop.poi_id}
                    position={[stop.lat, stop.lng]}
                    icon={createPinIcon(color, colorLight, String(stopIdx + 1))}
                  >
                    <Popup minWidth={200} maxWidth={240}>
                      <div className="p-0">
                        <div className="px-3 py-2 flex items-center gap-2" style={{ backgroundColor: colorLight }}>
                          <span className="text-xs font-bold px-2 py-0.5 rounded-full text-white" style={{ backgroundColor: color }}>
                            Day {day.day_number} · #{stopIdx + 1}
                          </span>
                          {stop.arrival_time && (
                            <span className="text-xs text-gray-500 font-medium">{stop.arrival_time}</span>
                          )}
                        </div>
                        <div className="px-3 py-2.5">
                          <div className="flex items-start justify-between gap-2 mb-1.5">
                            <p className="font-bold text-sm text-gray-900 leading-tight">{stop.name}</p>
                            {stop.travel_category && (
                              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full shrink-0 ${getCategoryColor(stop.travel_category)}`}>
                                {stop.travel_category}
                              </span>
                            )}
                          </div>
                          {stop.address && (
                            <p className="text-xs text-gray-500 mb-2 flex items-start gap-1">
                              <span className="shrink-0">📍</span>
                              <span>{stop.address}</span>
                            </p>
                          )}
                          <div className="flex items-center gap-1.5 flex-wrap mb-2.5">
                            <span className="text-xs text-gray-600 bg-gray-50 px-2 py-0.5 rounded-lg border border-gray-100 font-medium">
                              {stop.visit_mode === 'outdoor' ? '☀️' : '🎟️'} {stop.visit_duration_minutes} min
                            </span>
                            {stop.rating != null && (
                              <span className="text-xs text-gray-600 bg-gray-50 px-2 py-0.5 rounded-lg border border-gray-100 font-medium">
                                ⭐ {stop.rating.toFixed(1)}
                              </span>
                            )}
                          </div>
                          {stop.google_maps_url && (
                            <a
                              href={stop.google_maps_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="flex items-center justify-center gap-1.5 text-xs font-semibold text-white rounded-xl py-2 transition-opacity active:opacity-80"
                              style={{ backgroundColor: color }}
                            >
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>
                                <circle cx="12" cy="10" r="3"/>
                              </svg>
                              Open in Maps
                            </a>
                          )}
                        </div>
                      </div>
                    </Popup>
                  </Marker>
                ))}
              </Fragment>
            )
          })}
        </MapContainer>
      </div>
    </div>
  )
}
