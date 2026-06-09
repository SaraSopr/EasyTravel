import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Minus, Plus, Loader2, Search, Calendar } from 'lucide-react'
import axios from 'axios'
import { generateItinerary } from '@/api/endpoints'
import useAuthStore from '@/store/useAuthStore'
import useTripStore from '@/store/useTripStore'

function getGreeting() {
  const h = new Date().getHours()
  if (h >= 5 && h < 12) return { text: 'Good morning', icon: '☀️' }
  if (h >= 12 && h < 18) return { text: 'Good afternoon', icon: '⛅' }
  if (h >= 18 && h < 22) return { text: 'Good evening', icon: '🌆' }
  return { text: 'Good night', icon: '🌙' }
}

function getFirstName(email: string) {
  const name = email.split('@')[0]
  return name.charAt(0).toUpperCase() + name.slice(1)
}

function parseError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const msg: string | undefined = err.response?.data?.detail ?? err.response?.data?.message
    if (msg) return msg
    if (err.response?.status === 404) return 'City not found.'
    if (err.response?.status === 422) return 'Not enough places available for this city.'
  }
  return 'Could not generate itinerary. Please try again.'
}

export default function Home() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { setItinerary } = useTripStore()

  const [city, setCity] = useState('')
  const [numDays, setNumDays] = useState(1)
  const [travelMode, setTravelMode] = useState<'solo' | 'couple' | 'friends' | 'family'>('solo')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const decrement = () => setNumDays((d) => Math.max(1, d - 1))
  const increment = () => setNumDays((d) => Math.min(14, d + 1))

  const handleFindPlaces = async () => {
    if (!city.trim()) return
    setError('')
    setLoading(true)
    try {
      const itinerary = await generateItinerary({
        city: city.trim(),
        num_days: numDays,
        travel_mode: travelMode,
      })
      setItinerary(itinerary)
      navigate(`/itinerary/${itinerary.itinerary_id}`)
    } catch (err) {
      setError(parseError(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-md mx-auto min-h-screen flex flex-col bg-gray-50 pb-28">
      {/* Header */}
      <div className="bg-gradient-to-br from-indigo-600 to-violet-600 px-6 pt-14 pb-20">
        <p className="text-indigo-200 text-lg font-medium">
          {getGreeting().icon} {getGreeting().text},
        </p>
        <h1 className="text-3xl font-bold text-white mt-3">
          {user ? getFirstName(user.email) : 'Traveller'} ✈️
        </h1>
        <p className="text-indigo-200 text-lg mt-3">Where are you off to next?</p>
      </div>

      {/* Search card */}
      <div className="flex-1 bg-gray-50 rounded-t-3xl -mt-6 px-6 pt-6 flex flex-col gap-5">
        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-5 flex flex-col gap-5">
          {/* Destination */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide" htmlFor="destination">
              Destination
            </label>
            <div className="relative">
              <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                id="destination"
                type="text"
                value={city}
                onChange={(e) => setCity(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleFindPlaces()}
                placeholder="e.g. Roma, Barcelona…"
                className="w-full border border-gray-200 rounded-xl pl-10 pr-4 py-3 text-sm bg-gray-50 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:bg-white transition-colors"
              />
            </div>
          </div>

          {/* Days stepper */}
          <div className="flex flex-col gap-2">
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Duration
            </label>
            <div className="flex items-center justify-between bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5">
              <div className="flex items-center gap-2 text-gray-500">
                <Calendar size={15} />
                <span className="text-sm text-gray-700 font-medium">
                  {numDays} {numDays === 1 ? 'day' : 'days'}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={decrement}
                  disabled={numDays <= 1}
                  className="w-8 h-8 flex items-center justify-center rounded-lg bg-white border border-gray-200 text-gray-600 disabled:opacity-40 shadow-sm active:scale-95 transition-transform"
                >
                  <Minus size={14} />
                </button>
                <button
                  onClick={increment}
                  disabled={numDays >= 14}
                  className="w-8 h-8 flex items-center justify-center rounded-lg bg-white border border-gray-200 text-gray-600 disabled:opacity-40 shadow-sm active:scale-95 transition-transform"
                >
                  <Plus size={14} />
                </button>
              </div>
            </div>
          </div>

          {/* Travel mode */}
          <div className="flex flex-col gap-2">
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Travelling with
            </label>
            <div className="grid grid-cols-4 gap-2">
              {([
                { value: 'solo',    emoji: '🧍', label: 'Solo'    },
                { value: 'couple',  emoji: '👫', label: 'Couple'  },
                { value: 'friends', emoji: '👯', label: 'Friends' },
                { value: 'family',  emoji: '👨‍👩‍👧', label: 'Family'  },
              ] as const).map(({ value, emoji, label }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setTravelMode(value)}
                  className={`flex flex-col items-center gap-1 py-2.5 rounded-xl border text-xs font-semibold transition-all active:scale-95 ${
                    travelMode === value
                      ? 'border-indigo-400 bg-indigo-50 text-indigo-700'
                      : 'border-gray-200 bg-gray-50 text-gray-500'
                  }`}
                >
                  <span className="text-lg">{emoji}</span>
                  {label}
                </button>
              ))}
            </div>
          </div>


        </div>

        {error && (
          <div className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-xl px-4 py-3">
            {error}
          </div>
        )}

        <button
          onClick={handleFindPlaces}
          disabled={!city.trim() || loading}
          className="flex items-center justify-center gap-2 bg-gradient-to-r from-indigo-600 to-violet-600 text-white font-semibold rounded-xl py-4 disabled:opacity-50 shadow-md shadow-indigo-200 active:scale-[0.98] transition-transform"
        >
          {loading ? (
            <Loader2 size={18} className="animate-spin" />
          ) : (
            <Search size={18} />
          )}
          {loading ? 'Generating…' : 'Plan my trip'}
        </button>
      </div>
    </div>
  )
}
