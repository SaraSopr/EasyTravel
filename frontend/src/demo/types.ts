export interface PreferenceVector {
  nature: number
  culture: number
  food: number
  adventure: number
  nightlife: number
  relax: number
  family_friendly: number
}

export interface DemoPoi {
  id: string
  name: string
  lat: number
  lng: number
  category: string
  isFood?: boolean
  vector: PreferenceVector
  popularity: number
  landmark: boolean
  visit_min: number
  // per-day opening windows [startMin, endMin] or null = closed; minutes from midnight
  opening: ([number, number] | null)[]
  prize: number
}

export interface DemoStop {
  poiId: string
  arrivalMin: number
  departMin: number
  kind: 'visit' | 'meal'
  transportFromPrevious?: TransportMode | null
  travelMinutesFromPrevious?: number | null
}

export type TransportMode = 'walking' | 'transit' | 'taxi'

export interface DemoRouteLeg {
  fromPoiId: string
  toPoiId: string
  transport: TransportMode
  travelMinutes: number
  estimatedTravelMinutes?: number
}

export interface GreedyReplay {
  stops: {
    poiId: string
    arrivalMin: number
    departMin: number
    transportFromPrevious?: TransportMode | null
    travelMinutesFromPrevious?: number | null
  }[]
  overrunMin: number
  closedOnArrival: string[]
  totalLegs: number
  realLegs: number
  fallbackLegs: number
  cachedFallbackLegs: number
  uncachedFallbackLegs: number
}

export interface GreedyDay {
  stops: DemoStop[]
  route: string[]
  idleMin?: number
  replayReal: GreedyReplay
}

export interface GreedyTrace {
  clusters: Record<string, number>   // poiId → dayIdx
  selected: string[]                 // MMR order
  days: GreedyDay[]
  refill: string[]
}

export interface ToptwDay {
  sourceDayIdx: number
  preReorderRoute: string[]
  route: string[]
  reorderStops: DemoStop[]
  preMealStops: DemoStop[]
  stops: DemoStop[]
  idleMin: number
  travelSavedPct: number
}

export type ToptwFillStatus =
  | 'disabled'
  | 'not_applicable_global'
  | 'empty_no_anchor'
  | 'above_threshold'
  | 'underfull_no_candidates'
  | 'underfull_candidates_rejected'
  | 'resolve_failed'
  | 'fill_reverted'
  | 'filled'
  | 'partially_filled'
  | 'not_evaluated'

export interface ToptwFillDay {
  status: ToptwFillStatus
  usedMinBefore: number
  usedMinAfter: number
  injected: string[]
  scheduled: string[]
}

export interface ToptwRefill {
  enabled: boolean
  applicable: boolean
  ratio: number
  budgetMin: number
  thresholdMin: number
  injected: string[]       // candidates offered to the second solve
  added: string[]          // injected candidates actually retained
  byDay: Record<string, string[]>
  days: Record<string, ToptwFillDay>
}

export interface ToptwTrace {
  candidates: string[]
  zones: Record<string, number>      // poiId → dayIdx
  balance: number
  preClusterActive: boolean
  pruned: string[]
  excludedNotable: { poiId: string; reason: string }[]
  days: ToptwDay[]
  refill: ToptwRefill
}

export interface DemoMetrics {
  overrunRate: { greedy: number; toptw: number }
  stopsPerDay: { greedy: number; toptw: number }
  diversity: { greedy: number; toptw: number }
  idleMin: { greedy: number; toptw: number }
}

export interface DemoCity {
  name: string
  center: [number, number]
  bounds: [[number, number], [number, number]]
}

export interface DemoPersona {
  id: string
  label: string
  vector: PreferenceVector
  blurb: string
  travel_mode: 'solo' | 'couple' | 'family'
}

export interface DemoPreprocessing {
  initialCount: number
  finalCount: number
  radiusM: number
  dedupRadiusM: number
  familyMode: boolean
  radiusExcluded: string[]
  familyExcluded: string[]
  duplicates: { removedId: string; keptId: string }[]
  finalActivityIds: string[]
  finalFoodIds: string[]
  filteredBounds: [[number, number], [number, number]]
}

/** Runtime planner parameters carried in the trace so captions never drift
 *  from the backend config. */
export interface DemoParams {
  wSim: number
  wPop: number
  landmarkBoost: number
  mmrLambda: number
  timeLimitS: number
  balanceMin: number
}

export interface DemoTrace {
  traceVersion?: number
  city: DemoCity
  persona: DemoPersona
  /** [dayStartMin, dayEndMin] — the schedule the app derives from the travel mode */
  daySpan?: [number, number]
  schedule?: { start: string; end: string }
  params?: DemoParams
  pois: DemoPoi[]
  preprocessing?: DemoPreprocessing
  greedy: GreedyTrace
  toptw: ToptwTrace
  metrics: DemoMetrics
}

/** Must match TRACE_VERSION in backend/app/services/demo_trace.py. Baked
 *  traces with a different version are rejected instead of crashing screens. */
export const TRACE_VERSION = 3

// ---------------------------------------------------------------------------
// POI ingestion pipeline (GET /api/demo/ingestion)
// ---------------------------------------------------------------------------

export interface IngestionPoi {
  id: string
  name: string
  lat: number
  lng: number
  category: string | null
  confidence: 'high' | 'medium' | 'failed' | null
  hasHours: boolean
  visitType: 'indoor' | 'outdoor' | 'both' | null
  /** Tourism-validation flag: false = excluded by the family-mode SQL filter. */
  suitableForChildren: boolean | null
  /** Google Places canonical type — the main evidence behind the LLM flags. */
  primaryType: string | null
  vector: PreferenceVector
  rating: number | null
  ratingsTotal: number | null
}

export interface IngestionDiscardedPoi {
  id: string
  name: string
  lat: number
  lng: number
  primaryType: string | null
  ratingsTotal: number | null
}

export interface DemoIngestion {
  ingestionVersion: number
  city: DemoCity
  funnel: {
    fetched: number
    tourism: {
      kept: number
      discarded: number
      unvalidated: number
      children: { suitable: number; notSuitable: number; unknown: number }
      withDuration: number
    }
    classified: { total: number; high: number; medium: number; failed: number }
    planning?: {
      source: string
      input: number
      candidateQuery: number
      displayPool: number
      activity: number
      food: number
      removedByCandidateQuery: number
      candidateQueryRules: string[]
      candidateQueryReasons: Record<string, number>
    }
    hours: { withHours: number; withoutHours: number }
  }
  categories: Record<string, number>
  pois: IngestionPoi[]
  /** Capped sample for the map — funnel counts cover the full truth. */
  discardedSample: IngestionDiscardedPoi[]
}

export const INGESTION_VERSION = 4

export type PersonaId =
  | 'couple_museums'
  | 'young_solo_outdoor'
  | 'couple_generalist'
  | 'family_with_kids'

// Offline fallback only: the store replaces this with GET /api/demo/personas
// at startup so the backend's DEMO_PERSONAS stays the single source of truth.
export const FALLBACK_PERSONAS: DemoPersona[] = [
  {
    id: 'couple_museums',
    label: 'Culture Couple',
    blurb: 'A couple deeply passionate about art, history, and architecture.',
    travel_mode: 'couple',
    vector: { nature: 0.2, culture: 1.0, food: 0.4, adventure: 0.1, nightlife: 0.1, relax: 0.3, family_friendly: 0.5 },
  },
  {
    id: 'young_solo_outdoor',
    label: 'Solo Adventurer',
    blurb: 'A young solo traveler craving outdoor experiences and thrills.',
    travel_mode: 'solo',
    vector: { nature: 0.8, culture: 0.3, food: 0.4, adventure: 0.9, nightlife: 0.6, relax: 0.2, family_friendly: 0.0 },
  },
  {
    id: 'couple_generalist',
    label: 'Balanced Couple',
    blurb: 'A couple who enjoys a bit of everything — no strong preferences.',
    travel_mode: 'couple',
    vector: { nature: 0.6, culture: 0.6, food: 0.6, adventure: 0.5, nightlife: 0.3, relax: 0.5, family_friendly: 0.6 },
  },
  {
    id: 'family_with_kids',
    label: 'Family with Kids',
    blurb: 'Parents traveling with children, favoring relaxed and family-friendly places.',
    travel_mode: 'family',
    vector: { nature: 0.7, culture: 0.5, food: 0.6, adventure: 0.3, nightlife: 0.0, relax: 0.6, family_friendly: 1.0 },
  },
]

// Day colors reuse the app's itinerary palette while keeping adjacent clusters distinct.
export const DAY_COLORS = [
  { main: '#6366F1', light: '#C7D2FE', label: 'Day 1' },
  { main: '#B45309', light: '#FDE68A', label: 'Day 2' },
  { main: '#BE185D', light: '#FBCFE8', label: 'Day 3' },
]

export const STEPS_PER_SCREEN = [5, 1, 5, 6, 1] as const

export const SCREEN_LABELS = ['Ingestion', 'Profile', 'Greedy', 'TOPTW', 'Comparison'] as const

export const SCREEN_GLYPHS = '①②③④⑤'
