import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { MapPin, Map, ChevronRight, CheckCircle2, Calendar } from 'lucide-react'
import { listItineraries } from '@/api/endpoints'
import type { ItinerarySummary } from '@/types'

function formatRange(start: string, end: string): string {
  const fmt = (d: string) =>
    new Date(d).toLocaleDateString('en-US', { day: 'numeric', month: 'short' })
  return start === end ? fmt(start) : `${fmt(start)} – ${fmt(end)}`
}

export default function Itineraries() {
  const [itineraries, setItineraries] = useState<ItinerarySummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    listItineraries()
      .then((data) => {
        if (active) setItineraries(data)
      })
      .catch(() => {
        if (active) setError('Unable to load your itineraries.')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  return (
    <div className="max-w-md mx-auto min-h-screen flex flex-col bg-gray-50 pb-28">
      {/* Header */}
      <div className="bg-gradient-to-br from-indigo-600 to-violet-600 px-6 pt-14 pb-16">
        <p className="text-indigo-200 text-sm font-medium mb-1.5">Your trips</p>
        <h1 className="text-2xl font-extrabold text-white tracking-tight">Itinerari</h1>
        {!loading && !error && (
          <p className="text-indigo-200 text-sm mt-2">
            {itineraries.length}{' '}
            {itineraries.length === 1 ? 'saved itinerary' : 'saved itineraries'}
          </p>
        )}
      </div>

      <div className="flex-1 bg-gray-50 rounded-t-3xl -mt-6 px-4 pt-6">
        {loading ? (
          <div className="flex flex-col gap-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="w-full h-24 rounded-2xl shimmer animate-pulse" />
            ))}
          </div>
        ) : error ? (
          <div className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-xl px-4 py-3">
            {error}
          </div>
        ) : itineraries.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <MapPin size={40} className="text-gray-200 mb-3" />
            <p className="text-gray-400 text-sm mb-4">You have not generated any itineraries yet.</p>
            <Link
              to="/home"
              className="bg-gradient-to-br from-indigo-600 to-violet-600 text-white text-sm font-semibold px-5 py-2.5 rounded-xl shadow-sm active:scale-[0.98] transition-transform"
            >
              Create an itinerary
            </Link>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {itineraries.map((it) => (
              <Link
                key={it.itinerary_id}
                to={`/itinerary/${it.itinerary_id}`}
                className="flex items-center gap-3 bg-white border border-gray-100 rounded-2xl px-4 py-4 shadow-sm active:scale-[0.99] transition-transform"
              >
                <div className="w-11 h-11 shrink-0 bg-indigo-50 rounded-xl flex items-center justify-center">
                  <Map size={20} className="text-indigo-500" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-base font-bold text-gray-800 truncate">{it.city}</p>
                  <div className="flex items-center flex-wrap gap-x-3 gap-y-1 mt-1 text-xs text-gray-500">
                    <span className="flex items-center gap-1">
                      <Calendar size={12} className="text-gray-400" />
                      {formatRange(it.start_date, it.end_date)}
                    </span>
                    <span>
                      {it.num_days} {it.num_days === 1 ? 'day' : 'days'} · {it.num_stops}{' '}
                      {it.num_stops === 1 ? 'stop' : 'stops'}
                    </span>
                    {it.num_visited > 0 && (
                      <span className="flex items-center gap-1 text-emerald-600 font-medium">
                        <CheckCircle2 size={12} />
                        {it.num_visited} visited
                      </span>
                    )}
                  </div>
                </div>
                <ChevronRight size={18} className="text-gray-300 shrink-0" />
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
