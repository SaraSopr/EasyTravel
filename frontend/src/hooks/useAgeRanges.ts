import { useEffect, useState } from 'react'
import { getAgeRanges } from '@/api/endpoints'

// Fallback if the request fails so the form still renders. Mirrors AGE_RANGES in
// backend/app/constants.py; the live fetch is the source of truth.
const FALLBACK_AGE_RANGES = ['18-25', '26-35', '36-45', '46-55', '55-70', '70+']

/** Age buckets fetched from the backend, with an offline-safe fallback. */
export function useAgeRanges(): string[] {
  const [ranges, setRanges] = useState<string[]>(FALLBACK_AGE_RANGES)

  useEffect(() => {
    let active = true
    getAgeRanges()
      .then((r) => {
        if (active && r.length > 0) setRanges(r)
      })
      .catch(() => {
        /* keep fallback */
      })
    return () => {
      active = false
    }
  }, [])

  return ranges
}
