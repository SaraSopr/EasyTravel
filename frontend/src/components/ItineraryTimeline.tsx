import { useState } from 'react'
import { Repeat, Trash2, X } from 'lucide-react'
import type { ItineraryDay, PoiSuggestion } from '@/types'
import { getCategoryColor } from '@/utils/categoryColors'
import {
  markVisited,
  unmarkVisited,
  getStopAlternatives,
  replaceStop,
  removeStop,
} from '@/api/endpoints'

interface ItineraryTimelineProps {
  day: ItineraryDay
  itineraryId: string
  onChange?: () => void | Promise<void>
}

function transportLabel(mode: string | null): string {
  if (mode === 'driving') return '🚗'
  if (mode === 'transit') return '🚌'
  return '🚶'
}

export default function ItineraryTimeline({ day, itineraryId, onChange }: ItineraryTimelineProps) {
  const [visited, setVisited] = useState<Record<string, boolean>>({})
  const [loadingId, setLoadingId] = useState<string | null>(null)

  // Alternatives sheet state
  const [sheetItemId, setSheetItemId] = useState<string | null>(null)
  const [sheetStopName, setSheetStopName] = useState<string>('')
  const [alternatives, setAlternatives] = useState<PoiSuggestion[]>([])
  const [loadingAlts, setLoadingAlts] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)

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

  const openAlternatives = async (itemId: string, stopName: string) => {
    setSheetItemId(itemId)
    setSheetStopName(stopName)
    setAlternatives([])
    setLoadingAlts(true)
    try {
      const alts = await getStopAlternatives(itineraryId, itemId)
      setAlternatives(alts)
    } finally {
      setLoadingAlts(false)
    }
  }

  const closeSheet = () => {
    setSheetItemId(null)
    setAlternatives([])
  }

  const chooseAlternative = async (poiId: string) => {
    if (!sheetItemId) return
    setBusyId(poiId)
    try {
      await replaceStop(itineraryId, sheetItemId, poiId)
      closeSheet()
      await onChange?.()
    } finally {
      setBusyId(null)
    }
  }

  const handleRemove = async (itemId: string) => {
    setBusyId(itemId)
    try {
      await removeStop(itineraryId, itemId)
      await onChange?.()
    } finally {
      setBusyId(null)
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
                  <div className="mt-3 flex flex-col gap-2">
                    <div className="flex gap-2">
                      <button
                        onClick={() => openAlternatives(stop.item_id!, stop.name)}
                        disabled={busyId === stop.item_id}
                        className="flex-1 inline-flex items-center justify-center gap-1.5 text-xs font-semibold py-2 rounded-xl border border-indigo-100 bg-indigo-50 text-indigo-600 transition-all active:scale-[0.98] disabled:opacity-50"
                      >
                        <Repeat size={13} /> Replace
                      </button>
                      <button
                        onClick={() => handleRemove(stop.item_id!)}
                        disabled={busyId === stop.item_id}
                        className="inline-flex items-center justify-center gap-1.5 text-xs font-semibold py-2 px-3 rounded-xl border border-gray-200 bg-white text-gray-500 transition-all active:scale-[0.98] disabled:opacity-50"
                      >
                        <Trash2 size={13} /> Remove
                      </button>
                    </div>
                    <button
                      onClick={() => toggleVisited(stop.item_id!, isVisited)}
                      disabled={loadingId === stop.item_id}
                      className={`w-full text-xs font-semibold py-2 rounded-xl border transition-all active:scale-[0.98] disabled:opacity-50 ${
                        isVisited
                          ? 'bg-white border-gray-200 text-gray-500'
                          : 'bg-emerald-500 border-emerald-500 text-white'
                      }`}
                    >
                      {loadingId === stop.item_id
                        ? '…'
                        : isVisited
                          ? 'Mark as not visited'
                          : '✓ Mark as visited'}
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        )
      })}

      {/* Alternatives bottom sheet */}
      {sheetItemId && (
        <div className="fixed inset-0 z-50 flex items-end justify-center" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-black/40" onClick={closeSheet} />
          <div className="relative w-full max-w-md bg-white rounded-t-3xl max-h-[80vh] flex flex-col shadow-2xl">
            <div className="flex items-start justify-between gap-3 px-5 pt-5 pb-3 border-b border-gray-100">
              <div className="min-w-0">
                <p className="text-xs text-gray-400 font-medium">Replacing</p>
                <h3 className="text-base font-bold text-gray-900 truncate">{sheetStopName}</h3>
              </div>
              <button
                onClick={closeSheet}
                className="shrink-0 w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center text-gray-500 active:scale-95"
              >
                <X size={16} />
              </button>
            </div>

            <div className="overflow-y-auto px-4 py-3 flex flex-col gap-2">
              {loadingAlts ? (
                <div className="flex flex-col gap-2 py-2">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className="w-full h-16 rounded-2xl shimmer animate-pulse" />
                  ))}
                </div>
              ) : alternatives.length === 0 ? (
                <p className="text-sm text-gray-400 text-center py-10">No alternatives available.</p>
              ) : (
                alternatives.map((alt) => (
                  <button
                    key={alt.poi_id}
                    onClick={() => chooseAlternative(alt.poi_id)}
                    disabled={busyId !== null}
                    className="text-left bg-white border border-gray-100 rounded-2xl px-4 py-3 shadow-sm active:scale-[0.99] transition-transform disabled:opacity-50"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="font-bold text-sm text-gray-900 leading-tight flex-1 min-w-0">{alt.name}</p>
                      {alt.travel_category && (
                        <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full shrink-0 ${getCategoryColor(alt.travel_category)}`}>
                          {alt.travel_category}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                      {alt.rating != null && (
                        <span className="text-xs text-gray-500">⭐ {alt.rating.toFixed(1)}</span>
                      )}
                      {alt.address && (
                        <span className="text-xs text-gray-400 truncate">📍 {alt.address}</span>
                      )}
                    </div>
                    {busyId === alt.poi_id && (
                      <p className="text-xs text-indigo-500 mt-1">Sostituzione in corso…</p>
                    )}
                  </button>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
