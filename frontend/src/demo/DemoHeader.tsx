import { useCallback } from 'react'
import { useDemoStore } from './useDemoStore'
import { SCREEN_GLYPHS, SCREEN_LABELS, STEPS_PER_SCREEN } from './types'

export default function DemoHeader() {
  const {
    screenIdx, stepIdx, city, cities, citiesLoading, citiesError, techMode,
    setScreen, nextStep, prevStep, setCity, setTechMode,
  } = useDemoStore()

  const maxStep = STEPS_PER_SCREEN[screenIdx] - 1

  const toggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {})
    } else {
      document.exitFullscreen().catch(() => {})
    }
  }, [])

  return (
    <header className="demo-header">
      {/* Screen nav */}
      <nav className="screen-nav">
        {SCREEN_LABELS.map((label, i) => (
          <button
            key={i}
            onClick={() => setScreen(i)}
            className={`screen-tab ${screenIdx === i ? 'active' : ''}`}
          >
            <span className="tab-num">{SCREEN_GLYPHS[i]}</span>
            <span className="tab-label">{label}</span>
          </button>
        ))}
      </nav>

      <label className="city-picker">
        <span>City</span>
        <select
          value={city}
          onChange={(event) => setCity(event.target.value)}
          disabled={citiesLoading || cities.length === 0}
          title={citiesError ?? 'Choose a city from the database'}
          aria-label="Demo city"
        >
          {citiesLoading && <option value="">Loading…</option>}
          {!citiesLoading && cities.length === 0 && (
            <option value="">Unavailable</option>
          )}
          {cities.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
      </label>

      {/* Step controls (hidden on single-step screens) */}
      <div
        className={`step-controls ${maxStep === 0 ? 'hidden' : ''}`}
        aria-hidden={maxStep === 0}
      >
        <button
          className="step-btn prev"
          onClick={prevStep}
          disabled={stepIdx === 0}
          title="Previous (←)"
        >
          ←
        </button>
        <span className="step-indicator">
          Step {stepIdx + 1} / {maxStep + 1}
        </span>
        <button
          className="step-btn next"
          onClick={nextStep}
          disabled={stepIdx === maxStep}
          title="Next (→)"
        >
          →
        </button>
      </div>

      {/* Toggles */}
      <div className="header-toggles">
        <button
          className={`toggle-btn ${techMode ? 'on' : ''}`}
          onClick={() => setTechMode(!techMode)}
          title="Technical details"
        >
          {techMode ? 'Tech ON' : 'Tech'}
        </button>

        <button
          className="toggle-btn"
          onClick={toggleFullscreen}
          title="Fullscreen (F)"
        >
          ⛶
        </button>
      </div>
    </header>
  )
}
