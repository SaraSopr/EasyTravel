import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { MapPin, Map, ChevronRight, CheckCircle2, Trash2, X } from 'lucide-react'
import { listItineraries, deleteItinerary } from '@/api/endpoints'
import type { ItinerarySummary } from '@/types'

export default function Itineraries() {
  const [itineraries, setItineraries] = useState<ItinerarySummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const navigate = useNavigate()

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

  const handleDelete = async () => {
    if (!confirmDeleteId) return
    setDeleting(true)
    try {
      await deleteItinerary(confirmDeleteId)
      setItineraries((prev) => prev.filter((it) => it.itinerary_id !== confirmDeleteId))
      setConfirmDeleteId(null)
    } catch {
      // keep dialog open so user can retry
    } finally {
      setDeleting(false)
    }
  }

  const confirmTarget = itineraries.find((it) => it.itinerary_id === confirmDeleteId)

  return (
    <div className="max-w-md mx-auto min-h-screen flex flex-col bg-gradient-to-b from-indigo-50 via-gray-50 to-gray-50 pb-28">
      {/* Header */}
      <div className="bg-gradient-to-br from-indigo-600 via-violet-600 to-fuchsia-500 px-6 pt-14 pb-16">
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
          <div className="text-sm text-red-600 bg-red-50/85 backdrop-blur border border-red-100/80 rounded-xl px-4 py-3">
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
              <div key={it.itinerary_id} className="glass glass-specular relative flex items-center gap-3 rounded-2xl px-4 py-4">
                <button
                  onClick={() => navigate(`/itinerary/${it.itinerary_id}`)}
                  className="flex items-center gap-3 flex-1 min-w-0 text-left active:scale-[0.99] transition-transform"
                >
                  <div className="w-11 h-11 shrink-0 bg-white/60 border border-white/60 rounded-xl flex items-center justify-center">
                    <Map size={20} className="text-indigo-500" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-base font-bold text-gray-800 truncate">{it.city}</p>
                    <div className="flex items-center flex-wrap gap-x-3 gap-y-1 mt-1 text-xs text-gray-500">
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
                </button>
                <button
                  onClick={() => setConfirmDeleteId(it.itinerary_id)}
                  className="shrink-0 p-2 rounded-xl text-gray-300 hover:text-red-400 hover:bg-red-50 active:scale-95 transition-all"
                  aria-label="Delete itinerary"
                >
                  <Trash2 size={17} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Confirm delete dialog */}
      {confirmDeleteId && (
        <div className="fixed inset-0 z-50 flex items-end justify-center">
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={() => !deleting && setConfirmDeleteId(null)}
          />
          <div className="glass glass-specular relative w-full max-w-md rounded-t-3xl px-6 pt-6 pb-10">
            <button
              onClick={() => !deleting && setConfirmDeleteId(null)}
              className="absolute top-4 right-4 text-gray-400 hover:text-gray-600"
            >
              <X size={20} />
            </button>
            <div className="flex items-center justify-center w-12 h-12 rounded-2xl bg-red-50/80 border border-white/60 mb-4">
              <Trash2 size={22} className="text-red-500" />
            </div>
            <h2 className="text-lg font-bold text-gray-900 mb-1">Delete itinerary?</h2>
            <p className="text-sm text-gray-500 mb-6">
              <span className="font-medium text-gray-700">{confirmTarget?.city}</span>
              {' '}({confirmTarget?.num_days} {confirmTarget?.num_days === 1 ? 'day' : 'days'},{' '}
              {confirmTarget?.num_stops} {confirmTarget?.num_stops === 1 ? 'stop' : 'stops'}) will be permanently deleted.
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setConfirmDeleteId(null)}
                disabled={deleting}
                className="flex-1 py-3 rounded-xl border border-white/70 bg-white/55 text-sm font-semibold text-gray-600 active:scale-[0.98] transition-transform disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="flex-1 py-3 rounded-xl bg-red-500 text-white text-sm font-semibold active:scale-[0.98] transition-transform disabled:opacity-50"
              >
                {deleting ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
