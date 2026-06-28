import client from './client'

// ── Types ─────────────────────────────────────────────
export interface ProfileContext {
  key: string
  label: string
  description?: string
  travel_mode?: string
  age_range?: string
  children?: boolean
  interests?: Record<string, number>
  note?: string
}

export interface PairOption {
  slot: 'a' | 'b'
  poi_id: string
  name: string
  description?: string | null
  types?: string[] | null
  rating?: number | null
  user_ratings_total?: number | null
  travel_category?: string | null
  google_maps_url?: string | null
}

export interface EvalPair {
  pair_id: string
  pair_type: string
  profile: ProfileContext
  city: string
  options: PairOption[]
}

export interface EvalStop {
  position: number
  name: string
  lat: number
  lng: number
  arrival_time: string | null
  departure_time: string | null
  transport_from_previous: string | null
  travel_minutes_from_previous: number | null
  visit_duration_minutes: number
  travel_category: string | null
  is_food: boolean
}

export interface EvalDay {
  day_number: number
  date: string
  stops: EvalStop[]
}

export interface EvalItinerary {
  itinerary_id: string
  profile: ProfileContext
  city: string
  num_days: number
  payload: { city: string; num_days: number; warnings: string[]; days: EvalDay[] }
}

// ── Pairwise ──────────────────────────────────────────
export async function getPairs(evaluator: string, limit = 30): Promise<EvalPair[]> {
  const { data } = await client.get('/evaluation/pairs', { params: { evaluator, limit } })
  return data.pairs
}

export async function postRating(
  pairId: string,
  evaluatorId: string,
  choice: 'a' | 'b' | 'equal',
): Promise<void> {
  await client.post('/evaluation/ratings', {
    pair_id: pairId,
    evaluator_id: evaluatorId,
    choice,
  })
}

// ── Likert ────────────────────────────────────────────
export async function getEvalItineraries(evaluator: string, limit = 10): Promise<EvalItinerary[]> {
  const { data } = await client.get('/evaluation/itineraries', { params: { evaluator, limit } })
  return data.itineraries
}

export async function postLikert(payload: {
  itinerary_id: string
  evaluator_id: string
  realism: number
  completeness: number
  profile_fit: number
  overall: number
}): Promise<void> {
  await client.post('/evaluation/likert', payload)
}
