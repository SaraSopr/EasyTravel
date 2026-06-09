import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { MapPin, Calendar, Wand2 } from 'lucide-react'
import { getItinerary } from '@/api/endpoints'
import ItineraryTimeline from '@/components/ItineraryTimeline'
import type { Itinerary as ItineraryType } from '@/types'

export default function Itinerary() {
  const { id } = useParams<{ id: string }>()

  const [itinerary, setItinerary] = useState<ItineraryType | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!id) return
    const fetch = async () => {
      try {
        const data = await getItinerary(id)
        setItinerary(data)
      } catch {
        setError('Failed to load itinerary.')
      } finally {
        setLoading(false)
      }
    }
    void fetch()
  }, [id])

  return (
    <div className="max-w-md mx-auto min-h-screen flex flex-col bg-gray-50 pb-28">
      {/* Header */}
      <div className="bg-gradient-to-br from-indigo-600 to-violet-600 px-6 pt-14 pb-16">
        <div className="flex items-center gap-2 mb-2">
          <Wand2 size={16} className="text-indigo-200" />
          <span className="text-indigo-200 text-sm font-medium">Your itinerary</span>
        </div>
        <h1 className="text-2xl font-bold text-white">
          {itinerary?.city ?? '…'}
        </h1>
        {itinerary && (
          <div className="flex items-center gap-3 mt-2">
            <span className="flex items-center gap-1 text-indigo-200 text-sm">
              <Calendar size={13} />
              {itinerary.start_date}
            </span>
            <span className="text-indigo-400">→</span>
            <span className="text-indigo-200 text-sm">{itinerary.end_date}</span>
          </div>
        )}
      </div>

      <div className="flex-1 bg-gray-50 rounded-t-3xl -mt-6 px-4 pt-6 overflow-hidden">
        {loading ? (
          <div className="relative">
            <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-4 pointer-events-none">
              <div className="gradient-ring w-16 h-16 animate-spin" />
              <span className="text-lg font-semibold text-indigo-500 tracking-wide">Building your itinerary…</span>
            </div>
            <div className="flex flex-col gap-5 opacity-40">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="flex flex-col gap-2">
                  <div className="w-20 h-5 rounded-lg shimmer animate-pulse" />
                  <div className="w-full h-24 rounded-2xl shimmer animate-pulse" />
                  <div className="w-full h-20 rounded-2xl shimmer animate-pulse" />
                </div>
              ))}
            </div>
          </div>
        ) : error ? (
          <div className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-xl px-4 py-3">
            {error}
          </div>
        ) : !itinerary || itinerary.days.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <MapPin size={40} className="text-gray-200 mb-3" />
            <p className="text-gray-400 text-sm">No itinerary data available.</p>
          </div>
        ) : (
          <div className="flex flex-col gap-8">
            {(itinerary.warnings ?? []).length > 0 && (
              <div className="flex flex-col gap-2">
                {(itinerary.warnings ?? []).map((w, i) => (
                  <div key={i} className="flex items-start gap-2 bg-amber-50 border border-amber-100 rounded-xl px-4 py-3">
                    <span className="text-amber-500 mt-0.5 shrink-0">⚠️</span>
                    <p className="text-xs text-amber-700">{w}</p>
                  </div>
                ))}
              </div>
            )}
            {itinerary.days.map((day) => (
              <section key={day.day_number}>
                <div className="flex items-center gap-2 mb-4">
                  <span className="bg-indigo-600 text-white text-xs font-bold px-3 py-1 rounded-full">
                    Day {day.day_number}
                  </span>
                  <span className="text-xs text-gray-400">{day.date}</span>
                  <div className="flex-1 h-px bg-gray-200" />
                </div>
                <ItineraryTimeline day={day} itineraryId={itinerary.itinerary_id} />
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
