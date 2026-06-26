import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { MapPin } from 'lucide-react'
import { getItinerary } from '@/api/endpoints'
import ItineraryExplorer from '@/components/ItineraryExplorer'
import type { Itinerary as ItineraryType } from '@/types'

export default function Itinerary() {
  const { id } = useParams<{ id: string }>()

  const [itinerary, setItinerary] = useState<ItineraryType | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const refetch = useCallback(async () => {
    if (!id) return
    try {
      const data = await getItinerary(id)
      setItinerary(data)
    } catch {
      setError('Failed to load itinerary.')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    void refetch()
  }, [refetch])

  return (
    <div className="max-w-md mx-auto min-h-screen flex flex-col bg-gray-50 pb-28">
      {/* Header */}
      <div className="bg-gradient-to-br from-indigo-600 to-violet-600 px-6 pt-14 pb-16">
        <p className="text-indigo-200 text-sm font-medium mb-1.5">Your itinerary</p>
        <h1 className="text-2xl font-extrabold text-white tracking-tight">
          {itinerary?.city ?? '…'}
        </h1>
        {itinerary && (
          <p className="text-indigo-200 text-sm mt-2">
            {itinerary.num_days} {itinerary.num_days === 1 ? 'day' : 'days'}
          </p>
        )}
      </div>

      <div className="flex-1 bg-gray-50 rounded-t-3xl -mt-6 px-4 pt-6 overflow-hidden">
        {loading ? (
          <div className="relative">
            <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-4 pointer-events-none">
              <div className="gradient-ring w-16 h-16 animate-spin" />
              <span className="text-sm font-semibold text-indigo-500 tracking-wide">Building your itinerary…</span>
            </div>
            <div className="flex flex-col gap-5 opacity-30">
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
          <div className="flex flex-col gap-5">
            {!!itinerary.warnings?.length && (
              <div className="flex flex-col gap-2">
                {itinerary.warnings.map((w, i) => (
                  <div key={i} className="flex items-start gap-2 bg-amber-50 border border-amber-100 rounded-xl px-4 py-3">
                    <span className="text-amber-500 mt-0.5 shrink-0">⚠️</span>
                    <p className="text-xs text-amber-700">{w}</p>
                  </div>
                ))}
              </div>
            )}

            

            <ItineraryExplorer itinerary={itinerary} onChange={refetch} />
          </div>
        )}
      </div>
    </div>
  )
}
