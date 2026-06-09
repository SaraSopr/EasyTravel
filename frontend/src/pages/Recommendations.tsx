import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, Wand2, MapPin, Calendar } from 'lucide-react'
import { generateItinerary } from '@/api/endpoints'
import useTripStore from '@/store/useTripStore'
import PlaceCard from '@/components/PlaceCard'

export default function Recommendations() {
  const navigate = useNavigate()
  const { city, numDays, recommendations, selectedPlaceIds, togglePlace, setItinerary } =
    useTripStore()

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleGenerate = async () => {
    setError('')
    setLoading(true)
    try {
      const itinerary = await generateItinerary({ city, num_days: numDays })
      setItinerary(itinerary)
      navigate(`/itinerary/${itinerary.itinerary_id}`)
    } catch {
      setError('Failed to generate itinerary. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative max-w-md mx-auto min-h-screen flex flex-col bg-gray-50 pb-36">
      {loading && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center gap-4 bg-gray-50/80 backdrop-blur-sm">
          <div className="gradient-ring w-16 h-16 animate-spin" />
          <span className="text-lg font-semibold text-indigo-500 tracking-wide">Generating your itinerary…</span>
        </div>
      )}
      {/* Header */}
      <div className="bg-gradient-to-br from-indigo-600 to-violet-600 px-6 pt-14 pb-16">
        <h1 className="text-2xl font-bold text-white">{city}</h1>
        <div className="flex items-center gap-3 mt-2">
          <span className="flex items-center gap-1 text-indigo-200 text-sm">
            <MapPin size={13} />
            {recommendations.length} places found
          </span>
          <span className="text-indigo-400">·</span>
          <span className="flex items-center gap-1 text-indigo-200 text-sm">
            <Calendar size={13} />
            {numDays} {numDays === 1 ? 'day' : 'days'}
          </span>
        </div>
      </div>

      <div className="flex-1 bg-gray-50 rounded-t-3xl -mt-6 px-6 pt-5 flex flex-col">
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
          Tap to select places
        </p>

        {error && (
          <div className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-xl px-4 py-3 mb-4">
            {error}
          </div>
        )}

        {recommendations.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center py-20 text-center">
            <MapPin size={40} className="text-gray-200 mb-3" />
            <p className="text-gray-400 text-sm">No places found for this destination.</p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {recommendations.map((place) => (
              <PlaceCard
                key={place.id}
                place={place}
                selected={selectedPlaceIds.includes(place.id)}
                onToggle={() => togglePlace(place.id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Sticky bottom */}
      <div className="fixed bottom-0 left-1/2 -translate-x-1/2 w-full max-w-md bg-white/80 backdrop-blur-md border-t border-gray-100 px-6 py-4">
        {selectedPlaceIds.length > 0 && (
          <p className="text-xs text-center text-gray-400 mb-2">
            {selectedPlaceIds.length} place{selectedPlaceIds.length !== 1 ? 's' : ''} selected
          </p>
        )}
        <button
          onClick={handleGenerate}
          disabled={selectedPlaceIds.length === 0 || loading}
          className="flex items-center justify-center gap-2 w-full bg-gradient-to-r from-indigo-600 to-violet-600 text-white font-semibold rounded-xl py-3.5 disabled:opacity-50 shadow-md shadow-indigo-200 active:scale-[0.98] transition-transform"
        >
          {loading ? (
            <Loader2 size={18} className="animate-spin" />
          ) : (
            <Wand2 size={18} />
          )}
          {loading ? 'Generating…' : 'Generate itinerary'}
        </button>
      </div>
    </div>
  )
}
