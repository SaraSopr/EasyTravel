import { create } from 'zustand'
import type { DemoIngestion, DemoPersona, DemoTrace, PersonaId } from './types'
import { FALLBACK_PERSONAS, STEPS_PER_SCREEN } from './types'

interface DemoState {
  screenIdx: number
  stepIdx: number
  city: string
  cities: string[]
  citiesLoading: boolean
  citiesError: string | null
  personaId: PersonaId
  personas: DemoPersona[]
  trace: DemoTrace | null
  loading: boolean
  error: string | null
  ingestion: DemoIngestion | null
  ingestionLoading: boolean
  ingestionError: string | null
  techMode: boolean
  dataMode: 'live' | 'baked'
  expanded: boolean
  selectedDay: number

  setScreen: (idx: number) => void
  nextStep: () => void
  prevStep: () => void
  setCity: (city: string) => void
  setCities: (cities: string[]) => void
  setCitiesError: (error: string) => void
  setPersona: (id: PersonaId) => void
  setPersonas: (personas: DemoPersona[]) => void
  setTrace: (trace: DemoTrace) => void
  setLoading: (v: boolean) => void
  setError: (v: string | null) => void
  setIngestion: (ingestion: DemoIngestion) => void
  setIngestionLoading: (v: boolean) => void
  setIngestionError: (v: string | null) => void
  setTechMode: (v: boolean) => void
  setDataMode: (v: 'live' | 'baked') => void
  setExpanded: (v: boolean) => void
  toggleExpanded: () => void
  setSelectedDay: (day: number) => void
}

export const useDemoStore = create<DemoState>((set, get) => ({
  screenIdx: 0,
  stepIdx: 0,
  city: '',
  cities: [],
  citiesLoading: true,
  citiesError: null,
  personaId: 'couple_museums',
  personas: FALLBACK_PERSONAS,
  trace: null,
  loading: false,
  error: null,
  ingestion: null,
  ingestionLoading: false,
  ingestionError: null,
  techMode: false,
  dataMode: 'live',
  expanded: false,
  selectedDay: 0,

  setScreen: (idx) => set({ screenIdx: idx, stepIdx: 0, expanded: false }),

  nextStep: () => {
    const { screenIdx, stepIdx } = get()
    const max = STEPS_PER_SCREEN[screenIdx] - 1
    if (stepIdx < max) set({ stepIdx: stepIdx + 1 })
  },

  prevStep: () => {
    const { stepIdx } = get()
    if (stepIdx > 0) set({ stepIdx: stepIdx - 1 })
  },

  setCity: (city) => set((state) => ({
    city,
    trace: null,
    error: null,
    ingestion: null,
    ingestionError: null,
    stepIdx: 0,
    selectedDay: 0,
    // Baked traces currently exist only for Roma. Other database cities must
    // be planned by the backend so the UI never displays a mismatched trace.
    dataMode: city === 'Roma' ? state.dataMode : 'live',
  })),

  setCities: (cities) => set((state) => {
    const city = state.city && cities.includes(state.city)
      ? state.city
      : (cities.includes('Roma') ? 'Roma' : (cities[0] ?? ''))

    return {
      cities,
      citiesLoading: false,
      citiesError: null,
      city,
      dataMode: city === 'Roma' ? state.dataMode : 'live',
    }
  }),

  setCitiesError: (error) => set({
    citiesLoading: false,
    citiesError: error,
  }),

  setPersona: (id) => set({ personaId: id, trace: null, stepIdx: 0, selectedDay: 0 }),

  setPersonas: (personas) => set({ personas }),

  setTrace: (trace) => set({ trace, loading: false, error: null }),

  setLoading: (v) => set({ loading: v }),

  setError: (v) => set({ error: v, loading: false }),

  setIngestion: (ingestion) => set({
    ingestion,
    ingestionLoading: false,
    ingestionError: null,
  }),

  setIngestionLoading: (v) => set({ ingestionLoading: v }),

  setIngestionError: (v) => set({ ingestionError: v, ingestionLoading: false }),

  setTechMode: (v) => set({ techMode: v }),

  setDataMode: (v) => set({ dataMode: v }),

  setExpanded: (v) => set({ expanded: v }),

  toggleExpanded: () => set((s) => ({ expanded: !s.expanded })),

  setSelectedDay: (day) => set({ selectedDay: day }),
}))
