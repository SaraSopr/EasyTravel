import { Component, useEffect, useCallback } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import { getCities } from '@/api/endpoints'
import DemoHeader from './DemoHeader'
import { useDemoStore } from './useDemoStore'
import { fetchPersonas, useIngestion, useTrace } from './useTrace'
import Screen0Ingestion from './screens/Screen0Ingestion'
import Screen1Persona from './screens/Screen1Persona'
import Screen2Greedy from './screens/Screen2Greedy'
import Screen3TOPTW from './screens/Screen3TOPTW'
import Screen4Compare from './screens/Screen4Compare'
import './demo.css'

const SCREENS = [Screen0Ingestion, Screen1Persona, Screen2Greedy, Screen3TOPTW, Screen4Compare]

// A rendering bug in one screen must never blank the whole presentation:
// show the error and keep the header working so the presenter can switch away.
class ScreenErrorBoundary extends Component<
  { screenIdx: number; children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidUpdate(prevProps: { screenIdx: number }) {
    if (prevProps.screenIdx !== this.props.screenIdx && this.state.error) {
      this.setState({ error: null })
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Demo screen crashed:', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="demo-error" role="alert">
          <strong>This screen failed to render.</strong>
          <span>{this.state.error.message}</span>
        </div>
      )
    }
    return this.props.children
  }
}

export default function DemoApp() {
  const {
    screenIdx, city, error,
    nextStep, prevStep, setScreen, toggleExpanded,
    setCities, setCitiesError, setPersonas,
  } = useDemoStore()

  // Keep the demo city list aligned with the database instead of maintaining a
  // second hard-coded copy in the frontend.
  useEffect(() => {
    let cancelled = false

    getCities()
      .then((cities) => {
        if (!cancelled) setCities(cities)
      })
      .catch(() => {
        if (!cancelled) setCitiesError('Could not load cities from the database')
      })

    // Personas come from the backend (single source of truth); the hardcoded
    // fallback in types.ts only covers the backend-down / baked-only case.
    fetchPersonas()
      .then((personas) => {
        if (!cancelled && personas.length > 0) setPersonas(personas)
      })
      .catch(() => { /* keep FALLBACK_PERSONAS */ })

    return () => { cancelled = true }
  }, [setCities, setCitiesError, setPersonas])

  // Load a new trace whenever city, persona, or data mode changes.
  useTrace(city, 3)
  // The ingestion summary only depends on the city.
  useIngestion(city)

  // Keyboard navigation
  const handleKey = useCallback(
    (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement
        || e.target instanceof HTMLTextAreaElement
        || e.target instanceof HTMLSelectElement
      ) return
      switch (e.key) {
        case 'ArrowRight': nextStep(); break
        case 'ArrowLeft':  prevStep(); break
        case '1': setScreen(0); break
        case '2': setScreen(1); break
        case '3': setScreen(2); break
        case '4': setScreen(3); break
        case '5': setScreen(4); break
        case 'f': case 'F':
          if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen().catch(() => {})
          } else {
            document.exitFullscreen().catch(() => {})
          }
          break
        case 'e': case 'E': toggleExpanded(); break
      }
    },
    [nextStep, prevStep, setScreen, toggleExpanded],
  )

  useEffect(() => {
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [handleKey])

  const ActiveScreen = SCREENS[screenIdx]
  // The ingestion screen has its own data source and error handling; a trace
  // failure must not blank it.
  const showTraceError = error && screenIdx > 0

  return (
    <div className="demo-root">
      <DemoHeader />
      <main className="demo-main">
        {showTraceError ? (
          <div className="demo-error" role="alert">
            <strong>Could not generate the demo for {city}.</strong>
            <span>{error}</span>
          </div>
        ) : (
          <ScreenErrorBoundary screenIdx={screenIdx}>
            <ActiveScreen />
          </ScreenErrorBoundary>
        )}
      </main>
    </div>
  )
}
