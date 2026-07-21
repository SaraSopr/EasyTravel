import { useEffect, useRef } from 'react'
import gsap from 'gsap'
import { Flip } from 'gsap/Flip'
import type { DemoPoi, DemoStop } from '../types'
import { DAY_COLORS } from '../types'

gsap.registerPlugin(Flip)

// Fallback span when the trace doesn't carry one (solo/couple default: 09:00–22:00)
const DEFAULT_DAY_START = 540
const DEFAULT_DAY_END = 1320

function minToLabel(min: number) {
  const h = Math.floor(min / 60)
  const m = min % 60
  return `${h}:${String(m).padStart(2, '0')}`
}

interface Props {
  days: {
    stops: DemoStop[]
    idleMin?: number
  }[]
  pois: DemoPoi[]
  animate?: boolean
  expanded?: boolean
  onToggleExpand?: () => void
  onStopClick?: (poiId: string, dayIdx: number, stopIdx: number) => void
  activePoiId?: string
  excludedNotable?: { poiId: string; reason: string }[]
  daySpan?: [number, number]
  fillAddedIds?: Set<string>
}

export default function LaneBoard({
  days, pois, animate = false, expanded = false,
  onToggleExpand, onStopClick, activePoiId, excludedNotable = [],
  daySpan, fillAddedIds,
}: Props) {
  const boardRef = useRef<HTMLDivElement>(null)
  const prevExpanded = useRef(expanded)

  const [DAY_START, DAY_END] = daySpan ?? [DEFAULT_DAY_START, DEFAULT_DAY_END]
  const TOTAL_MIN = DAY_END - DAY_START
  const pct = (min: number) =>
    `${Math.max(0, Math.min(100, ((min - DAY_START) / TOTAL_MIN) * 100)).toFixed(2)}%`

  const poiMap = new Map(pois.map(p => [p.id, p]))
  const hasMeals = days.some(day => day.stops.some(stop => stop.kind === 'meal'))

  // GSAP Flip for expand/collapse
  useEffect(() => {
    if (prevExpanded.current === expanded) return
    prevExpanded.current = expanded
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced || !boardRef.current) return

    const state = Flip.getState(boardRef.current)
    // The CSS class has already changed by now (controlled by parent via `expanded` prop)
    Flip.from(state, {
      duration: 0.45,
      ease: 'power2.inOut',
    })
  }, [expanded])

  // Drop-in animation for stops
  useEffect(() => {
    if (!animate || !boardRef.current) return
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced) return

    const stops = boardRef.current.querySelectorAll<HTMLElement>('.lane-stop')
    gsap.fromTo(
      stops,
      { y: -30, opacity: 0 },
      {
        y: 0, opacity: 1,
        duration: 0.5,
        stagger: {
          amount: 0.9,
          from: 'start',
        },
        ease: 'back.out(1.2)',
        clearProps: 'transform',
      },
    )
  }, [animate])

  // A tick every two hours across the actual day span
  const TIME_TICKS: number[] = []
  for (let t = Math.ceil(DAY_START / 60) * 60; t <= DAY_END; t += 120) TIME_TICKS.push(t)
  const additionalDayCount = Math.max(0, days.length - 3)

  return (
    <div ref={boardRef} className={`lane-board ${expanded ? 'fullscreen' : ''}`}>
      <div className="lane-header">
        <span className="lane-title">Daily Schedule</span>
        {onToggleExpand && (
          <button className="lane-expand-btn" onClick={onToggleExpand}>
            {expanded
              ? '↙ Collapse'
              : `↗ Expand (+${additionalDayCount} ${additionalDayCount === 1 ? 'day' : 'days'})`}
          </button>
        )}
      </div>

      {/* Time axis — ticks share the stops' percentage scale so labels line up
          with the bands even when the day span doesn't start on the hour. */}
      <div style={{ position: 'relative', height: 12, marginLeft: 62, marginBottom: 4 }}>
        {TIME_TICKS.map(t => (
          <div
            key={t}
            style={{
              position: 'absolute',
              left: pct(t),
              transform: 'translateX(-50%)',
              fontSize: 9,
              color: '#bbb',
              fontVariantNumeric: 'tabular-nums',
              userSelect: 'none',
            }}
          >
            {minToLabel(t)}
          </div>
        ))}
      </div>

      {days.map((day, di) => {
        const color = DAY_COLORS[di % DAY_COLORS.length]
        const lastStop = day.stops[day.stops.length - 1]
        // Idle bands exclude the travel time carried by the destination stop.
        const idleBands: { startMin: number; widthMin: number }[] = []
        const firstStop = day.stops[0]
        if (firstStop && firstStop.arrivalMin - DAY_START >= 20) {
          idleBands.push({
            startMin: DAY_START,
            widthMin: firstStop.arrivalMin - DAY_START,
          })
        }
        for (let i = 1; i < day.stops.length; i++) {
          const gap = day.stops[i].arrivalMin - day.stops[i - 1].departMin
          const travel = day.stops[i].travelMinutesFromPrevious ?? 0
          const idle = Math.max(0, gap - travel)
          if (idle >= 20) {
            idleBands.push({
              startMin: day.stops[i - 1].departMin + travel,
              widthMin: idle,
            })
          }
        }
        if (lastStop && DAY_END - lastStop.departMin >= 20) {
          idleBands.push({ startMin: lastStop.departMin, widthMin: DAY_END - lastStop.departMin })
        }
        return (
          <div key={di} className="lane-row">
            <div className="lane-day-label" style={{ color: color.main }}>Day {di + 1}</div>
            <div className="lane-track">
              {/* Opening window bands */}
              {day.stops
                .filter(s => s.kind === 'visit')
                .map(s => {
                  const poi = poiMap.get(s.poiId)
                  const win = poi?.opening?.[di]
                  if (!win) return null
                  const [wStart, wEnd] = win
                  return (
                    <div
                      key={`win-${s.poiId}`}
                      className="lane-window-band"
                      style={{ left: pct(wStart), width: `${((wEnd - wStart) / TOTAL_MIN) * 100}%` }}
                      title={`Open ${minToLabel(wStart)}–${minToLabel(wEnd)}`}
                    />
                  )
                })}

              {/* Actual stops */}
              {day.stops.map((s, stopIdx) => {
                const poi = poiMap.get(s.poiId)
                const name = poi?.name ?? s.poiId.slice(0, 6)
                const isFillAdded = fillAddedIds?.has(s.poiId) ?? false
                return (
                  <button
                    type="button"
                    key={s.poiId}
                    className={`lane-stop ${s.kind} ${activePoiId === s.poiId ? 'active' : ''} ${isFillAdded ? 'fill-added' : ''}`}
                    style={{
                      left: pct(s.arrivalMin),
                      width: `${((s.departMin - s.arrivalMin) / TOTAL_MIN) * 100}%`,
                      background: isFillAdded ? '#D97706' : (s.kind === 'visit' ? color.main : '#0F766E'),
                    }}
                    title={`${stopIdx + 1}. ${name} ${minToLabel(s.arrivalMin)}–${minToLabel(s.departMin)}`}
                    aria-label={`Stop ${stopIdx + 1}, ${name}, ${minToLabel(s.arrivalMin)} to ${minToLabel(s.departMin)}`}
                    onClick={() => onStopClick?.(s.poiId, di, stopIdx)}
                  >
                    <span className="lane-stop-label">
                      <b>{stopIdx + 1}</b>
                      <span>{name}</span>
                    </span>
                  </button>
                )
              })}

              {/* Idle segments (mid-day gaps + tail) */}
              {idleBands.map((band, bi) => (
                <div
                  key={`idle-${bi}`}
                  className="lane-stop"
                  style={{
                    left: pct(band.startMin),
                    width: `${(band.widthMin / TOTAL_MIN) * 100}%`,
                    background: '#94A3B8',
                  }}
                  title={`Idle: ${band.widthMin} min`}
                />
              ))}
            </div>
          </div>
        )
      })}

      {/* Notable excluded POIs as ghosts in a separate row */}
      {excludedNotable.length > 0 && (
        <div style={{ marginTop: 8, fontSize: 11, color: '#aaa', paddingLeft: 62 }}>
          <strong style={{ color: '#888' }}>Excluded:</strong>{' '}
          {excludedNotable.map(e => {
            const poi = poiMap.get(e.poiId)
            const reasonLabel = e.reason === 'not_scheduled'
              ? 'not schedulable within opening hours and daily budget'
              : e.reason
            return <span key={e.poiId} title={reasonLabel}
              style={{ marginRight: 8, textDecoration: 'line-through' }}>
              {poi?.name ?? e.poiId.slice(0, 8)}
            </span>
          })}
        </div>
      )}

      {/* Legend: one swatch per day so every visit color has an exact label. */}
      <div style={{ marginTop: 8, fontSize: 10, color: '#64748B', paddingLeft: 62, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {[
          ...days.map((_, i) => ({
            label: `Day ${i + 1}`,
            bg: DAY_COLORS[i % DAY_COLORS.length].main,
          })),
          ...(hasMeals ? [{ label: 'Meal', bg: '#0F766E' }] : []),
          ...(fillAddedIds?.size ? [{ label: 'Gap fill', bg: '#D97706' }] : []),
          { label: 'Idle', bg: '#94A3B8' },
        ].map(({ label, bg }) => (
          <span key={label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: bg }} />
            {label}
          </span>
        ))}
      </div>
    </div>
  )
}
