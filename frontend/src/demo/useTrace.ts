import { useEffect } from 'react'
import axios from 'axios'
import { useDemoStore } from './useDemoStore'
import type { DemoIngestion, DemoPersona, DemoTrace, PersonaId } from './types'
import { INGESTION_VERSION, TRACE_VERSION } from './types'

const BACKEND = import.meta.env.VITE_API_URL ?? ''
// TOPTW solve on a full city takes several seconds — allow the live path
// to finish before falling back to baked traces.
const TRACE_TIMEOUT_MS = 30000

export async function fetchPersonas(): Promise<DemoPersona[]> {
  const res = await axios.get(`${BACKEND}/api/demo/personas`, { timeout: 8000 })
  return res.data as DemoPersona[]
}

async function fetchLiveTrace(
  personaId: PersonaId,
  city: string,
  numDays: number,
): Promise<DemoTrace> {
  const res = await axios.post(
    `${BACKEND}/api/demo/plan-trace`,
    { city, persona_id: personaId, num_days: numDays, solver: 'both' },
    { timeout: TRACE_TIMEOUT_MS },
  )
  return res.data as DemoTrace
}

async function fetchBakedTrace(personaId: PersonaId, city: string): Promise<DemoTrace> {
  const res = await fetch(`/demo-traces/${personaId}.json`)
  if (!res.ok) throw new Error(`Baked trace fetch failed: ${res.status}`)
  const data = await res.json()
  if (data._stub) throw new Error('Baked trace not yet generated')
  if (data.traceVersion !== TRACE_VERSION) {
    throw new Error(
      `Baked trace is outdated (v${data.traceVersion ?? 1}, expected v${TRACE_VERSION}) — `
      + 'regenerate with backend/scripts/generate_demo_traces.py',
    )
  }
  if (data.city?.name !== city) {
    throw new Error(`No baked trace is available for ${city}`)
  }
  return data as DemoTrace
}

function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
  }
  return error instanceof Error ? error.message : 'Failed to load trace'
}

export function useTrace(city: string, numDays = 3) {
  const { personaId, dataMode, setTrace, setLoading, setError } = useDemoStore()

  useEffect(() => {
    if (!city) return

    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)

      try {
        let trace: DemoTrace
        if (dataMode === 'live') {
          try {
            trace = await fetchLiveTrace(personaId, city, numDays)
          } catch (liveError) {
            // Roma can still use its baked presentation trace if the live
            // backend is unavailable. Never substitute Roma data for another
            // city selected by the user.
            if (city !== 'Roma') throw liveError
            trace = await fetchBakedTrace(personaId, city)
          }
        } else {
          try {
            trace = await fetchBakedTrace(personaId, city)
          } catch {
            // Fallback to live if baked not available
            trace = await fetchLiveTrace(personaId, city, numDays)
          }
        }
        if (!cancelled) setTrace(trace)
      } catch (err: unknown) {
        if (!cancelled) {
          setError(errorMessage(err))
          setLoading(false)
        }
      }
    }

    load()
    return () => { cancelled = true }
  }, [personaId, dataMode, city, numDays, setTrace, setLoading, setError])
}

async function fetchLiveIngestion(city: string): Promise<DemoIngestion> {
  const res = await axios.get(`${BACKEND}/api/demo/ingestion`, {
    params: { city },
    timeout: TRACE_TIMEOUT_MS,
  })
  return res.data as DemoIngestion
}

async function fetchBakedIngestion(city: string): Promise<DemoIngestion> {
  const res = await fetch('/demo-traces/ingestion.json')
  if (!res.ok) throw new Error(`Baked ingestion fetch failed: ${res.status}`)
  const data = await res.json()
  if (data.ingestionVersion !== INGESTION_VERSION) {
    throw new Error(
      `Baked ingestion data is outdated — regenerate with backend/scripts/generate_demo_traces.py`,
    )
  }
  if (data.city?.name !== city) {
    throw new Error(`No baked ingestion data is available for ${city}`)
  }
  return data as DemoIngestion
}

export function useIngestion(city: string) {
  const {
    dataMode, setIngestion, setIngestionLoading, setIngestionError,
  } = useDemoStore()

  useEffect(() => {
    if (!city) return

    let cancelled = false

    async function load() {
      setIngestionLoading(true)
      setIngestionError(null)

      try {
        let ingestion: DemoIngestion
        if (dataMode === 'live') {
          try {
            ingestion = await fetchLiveIngestion(city)
          } catch (liveError) {
            if (city !== 'Roma') throw liveError
            ingestion = await fetchBakedIngestion(city)
          }
        } else {
          try {
            ingestion = await fetchBakedIngestion(city)
          } catch {
            ingestion = await fetchLiveIngestion(city)
          }
        }
        if (!cancelled) setIngestion(ingestion)
      } catch (err: unknown) {
        if (!cancelled) setIngestionError(errorMessage(err))
      }
    }

    load()
    return () => { cancelled = true }
  }, [dataMode, city, setIngestion, setIngestionLoading, setIngestionError])
}
