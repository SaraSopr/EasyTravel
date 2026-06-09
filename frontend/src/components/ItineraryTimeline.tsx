import { useState } from 'react'
import type { ItineraryDay } from '@/types'
import { getCategoryColor } from '@/utils/categoryColors'
import { markVisited, unmarkVisited } from '@/api/endpoints'

interface ItineraryTimelineProps {
  day: ItineraryDay
  itineraryId: string
}

function transportLabel(mode: string | null): string {
  if (mode === 'driving') return '🚗'
  if (mode === 'transit') return '🚌'
  return '🚶'
}

export default function ItineraryTimeline({ day, itineraryId }: ItineraryTimelineProps) {
  const [visited, setVisited] = useState<Record<string, boolean>>({})
  const [loadingId, setLoadingId] = useState<string | null>(null)

  const toggleVisited = async (itemId: string, currentlyVisited: boolean) => {
    setLoadingId(itemId)
    try {
      if (currentlyVisited) {
        await unmarkVisited(itineraryId, itemId)
        setVisited((v) => ({ ...v, [itemId]: false }))
      } else {
        await markVisited(itineraryId, itemId)
        setVisited((v) => ({ ...v, [itemId]: true }))
      }
    } finally {
      setLoadingId(null)
    }
  }

  return (
    <div className="flex flex-col">
      {day.stops.map((stop, idx) => {
        const isVisited = stop.item_id ? (visited[stop.item_id] ?? false) : false
        return (
          <div key={stop.poi_id} className="flex gap-4">
            {/* Timeline spine */}
            <div className="flex flex-col items-center w-12 shrink-0 pt-1">
              <div
                className={`w-2.5 h-2.5 rounded-full ring-4 shrink-0 mt-2 ${
                  isVisited
                    ? 'bg-emerald-500 ring-emerald-100'
                    : 'bg-indigo-500 ring-indigo-100'
                }`}
              />
              {idx < day.stops.length - 1 && (
                <div className="w-px flex-1 bg-gradient-to-b from-indigo-200 to-gray-100 mt-1 min-h-6" />
              )}
            </div>

            {/* Stop card */}
            <div className="flex-1 min-w-0 pb-5">
              {stop.arrival_time && (
                <span className="text-xs font-semibold text-indigo-500 mb-1.5 block">
                  {stop.arrival_time}
                  {stop.departure_time && ` – ${stop.departure_time}`}
                </span>
              )}

              {stop.transport_from_previous != null && stop.travel_minutes_from_previous != null && (
                <div className="flex items-center gap-1.5 text-xs text-gray-400 mb-2 ml-1">
                  <span>{transportLabel(stop.transport_from_previous)}</span>
                  <span>{Math.round(stop.travel_minutes_from_previous)} min</span>
                </div>
              )}

              <div
                className={`bg-white border rounded-2xl p-4 shadow-sm transition-colors ${
                  isVisited ? 'border-emerald-100 bg-emerald-50/30' : 'border-gray-100'
                }`}
              >
                <div className="flex items-start justify-between gap-2 mb-2">
                  <p className={`font-bold text-sm leading-tight flex-1 min-w-0 ${isVisited ? 'text-gray-400 line-through' : 'text-gray-900'}`}>
                    {stop.name}
                  </p>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {!stop.is_new_suggestion && (
                      <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">
                        seen
                      </span>
                    )}
                    {stop.travel_category && (
                      <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full ${getCategoryColor(stop.travel_category)}`}>
                        {stop.travel_category}
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2 flex-wrap">
                  <span className="inline-flex items-center gap-1 text-xs bg-gray-50 text-gray-500 px-2.5 py-1 rounded-lg font-medium border border-gray-100">
                    {stop.visit_mode === 'outdoor' ? '☀️' : '🎟️'} {stop.visit_duration_minutes} min
                  </span>
                  {stop.rating != null && (
                    <span className="inline-flex items-center gap-1 text-xs bg-gray-50 text-gray-500 px-2.5 py-1 rounded-lg font-medium border border-gray-100">
                      ⭐ {stop.rating.toFixed(1)}
                    </span>
                  )}
                  {stop.google_maps_url && (
                    <a
                      href={stop.google_maps_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-xs text-indigo-500 font-medium px-2.5 py-1 bg-indigo-50 rounded-lg border border-indigo-100 active:scale-95 transition-transform"
                    >
                      Maps ↗
                    </a>
                  )}
                </div>

                {stop.address && (
                  <p className="text-xs text-gray-400 mt-1.5 truncate">📍 {stop.address}</p>
                )}
                {stop.visit_note && (
                  <p className="text-xs text-amber-600 bg-amber-50 rounded-lg px-2.5 py-1.5 mt-1.5 border border-amber-100">
                    {stop.visit_note}
                  </p>
                )}

                {stop.item_id && (
                  <button
                    onClick={() => toggleVisited(stop.item_id!, isVisited)}
                    disabled={loadingId === stop.item_id}
                    className={`mt-3 w-full text-xs font-semibold py-2 rounded-xl border transition-colors active:scale-[0.98] disabled:opacity-50 ${
                      isVisited
                        ? 'bg-white border-gray-200 text-gray-500'
                        : 'bg-emerald-500 border-emerald-500 text-white'
                    }`}
                  >
                    {loadingId === stop.item_id
                      ? '…'
                      : isVisited
                        ? 'Segna come non visitato'
                        : '✓ Segna come visitato'}
                  </button>
                )}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
