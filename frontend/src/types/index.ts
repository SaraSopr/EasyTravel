export interface PreferenceVector {
  nature: number
  culture: number
  food: number
  adventure: number
  nightlife: number
  relax: number
  family_friendly: number
}

export interface User {
  id: string
  email: string
  home_city: string
  age_range: string
  travel_with_children: boolean
  preferences: PreferenceVector
}

export interface Experience {
  id: string
  name: string
  city: string
  description: string
  icon: string
  photo_reference?: string
  photo_url?: string | null
}

export interface Place {
  id: string
  name: string
  city: string
  category: string
  description: string
  lat: number
  lon: number
  visit_duration_minutes: number
  score: number
}

export interface ItineraryStop {
  position: number
  poi_id: string
  name: string
  address: string
  lat: number
  lng: number
  travel_category: string
  rating: number | null
  photo_reference: string | null
  arrival_time: string | null
  departure_time: string | null
  transport_from_previous: string | null
  travel_minutes_from_previous: number | null
  google_maps_url: string | null
  visit_mode: 'indoor' | 'outdoor'
  visit_duration_minutes: number
  visit_note: string | null
  is_new_suggestion: boolean
  item_id: string | null
}

export interface PoiSuggestion {
  poi_id: string
  name: string
  address: string | null
  lat: number
  lng: number
  travel_category: string | null
  rating: number | null
  photo_reference: string | null
  google_maps_url: string | null
  similarity: number
}

export interface ItineraryDay {
  day_number: number
  stops: ItineraryStop[]
}

export interface Itinerary {
  itinerary_id: string
  city: string
  num_days: number
  warnings: string[]
  days: ItineraryDay[]
}

export interface ItinerarySummary {
  itinerary_id: string
  city: string
  num_days: number
  created_at: string
  num_stops: number
  num_visited: number
}
