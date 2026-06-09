import { create } from 'zustand'
import type { Place, Itinerary } from '@/types'

interface TripState {
  city: string
  numDays: number
  recommendations: Place[]
  selectedPlaceIds: string[]
  itinerary: Itinerary | null
  setTrip: (city: string, numDays: number) => void
  setRecommendations: (places: Place[]) => void
  togglePlace: (id: string) => void
  setItinerary: (itinerary: Itinerary) => void
  reset: () => void
}

const useTripStore = create<TripState>((set) => ({
  city: '',
  numDays: 1,
  recommendations: [],
  selectedPlaceIds: [],
  itinerary: null,
  setTrip: (city, numDays) => set({ city, numDays }),
  setRecommendations: (places) => set({ recommendations: places, selectedPlaceIds: [] }),
  togglePlace: (id) =>
    set((state) => ({
      selectedPlaceIds: state.selectedPlaceIds.includes(id)
        ? state.selectedPlaceIds.filter((pid) => pid !== id)
        : [...state.selectedPlaceIds, id],
    })),
  setItinerary: (itinerary) => set({ itinerary }),
  reset: () =>
    set({
      city: '',
      numDays: 1,
      recommendations: [],
      selectedPlaceIds: [],
      itinerary: null,
    }),
}))

export default useTripStore
