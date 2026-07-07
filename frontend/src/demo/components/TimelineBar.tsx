import { useEffect, useRef } from 'react'
import gsap from 'gsap'
import type { GreedyDay, DemoPoi } from '../types'
import { DAY_COLORS } from '../types'

// Fallback span when the trace doesn't carry one (solo/couple default: 09:00–22:00)
const DEFAULT_DAY_START = 540
const DEFAULT_DAY_END = 1320

function minToLabel(min: number): string {
  const h = Math.floor(min / 60)
  const m = min % 60
  return `${h}:${String(m).padStart(2, '0')}`
}

interface Segment {
  kind: 'visit' | 'meal' | 'travel' | 'idle' | 'overrun'
  startMin: number
  widthMin: number
  label?: string
  poiId?: string
}

interface Props {
  day: GreedyDay
  pois: DemoPoi[]
  useReplay?: boolean
  animate?: boolean
  dayIdx?: number
  showLegend?: boolean
  daySpan?: [number, number]
  /** Tight padding for stacked multi-day lists (comparison screen). */
  compact?: boolean
  onPoiClick?: (poiId: string) => void
}

function buildSegments(
  day: GreedyDay, pois: DemoPoi[], useReplay: boolean,
  DAY_START: number, DAY_END: number,
): Segment[] {
  const stops = useReplay ? day.replayReal.stops : day.stops
  const segs: Segment[] = []

  let prev = DAY_START

  for (let i = 0; i < stops.length; i++) {
    const s = stops[i]
    const poiId = 'poiId' in s ? s.poiId : ''
    const poi = pois.find(p => p.id === poiId)
    const arrival = s.arrivalMin
    const depart = s.departMin

    // Gap before this stop = travel + any wait (opening hours, dinner floor).
    // Split them so the bar matches the LaneBoard's travel/idle distinction.
    // No travel data (e.g. the first stop of the day) means the whole gap is
    // waiting — typically for the POI to open — not travel.
    if (arrival > prev) {
      const gap = arrival - prev
      const travel = Math.min(gap, Math.max(0, s.travelMinutesFromPrevious ?? 0))
      const idle = gap - travel
      if (travel > 0) {
        segs.push({ kind: 'travel', startMin: prev, widthMin: travel })
      }
      if (idle > 0) {
        segs.push({ kind: 'idle', startMin: prev + travel, widthMin: idle })
      }
    }

    const kind = (day.stops.find(st => st.poiId === poiId)?.kind ?? 'visit') as 'visit' | 'meal'
    segs.push({
      kind,
      startMin: arrival,
      widthMin: depart - arrival,
      label: poi?.name ?? '',
      poiId,
    })
    prev = depart
  }

  // Overflow or idle
  if (prev > DAY_END) {
    segs.push({ kind: 'overrun', startMin: DAY_END, widthMin: prev - DAY_END })
  } else if (prev < DAY_END) {
    segs.push({ kind: 'idle', startMin: prev, widthMin: DAY_END - prev })
  }

  return segs
}

export default function TimelineBar({
  day, pois, useReplay = false, animate = false, dayIdx = 0,
  showLegend = true, daySpan, compact = false, onPoiClick,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [DAY_START, DAY_END] = daySpan ?? [DEFAULT_DAY_START, DEFAULT_DAY_END]
  const TOTAL_MIN = DAY_END - DAY_START
  const segments = buildSegments(day, pois, useReplay, DAY_START, DAY_END)
  const overrunMin = day.replayReal?.overrunMin ?? 0
  const totalWidth = TOTAL_MIN + Math.max(0, overrunMin)
  const visitColor = DAY_COLORS[dayIdx % DAY_COLORS.length].main

  useEffect(() => {
    if (!animate || !containerRef.current) return
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    if (useReplay && overrunMin > 0) {
      // Animate travel segments stretching to reveal overrun
      const travelSegs = containerRef.current.querySelectorAll<HTMLElement>('.tl-segment.travel')
      if (reduced) return

      gsap.fromTo(
        travelSegs,
        { scaleX: 0.5 },
        {
          scaleX: 1,
          duration: 0.8,
          stagger: 0.1,
          ease: 'power2.inOut',
          transformOrigin: 'left center',
        },
      )

      // Flash the overrun segment
      const overrunEl = containerRef.current.querySelector<HTMLElement>('.tl-segment.overrun')
      if (overrunEl) {
        gsap.fromTo(
          overrunEl,
          { opacity: 0, scaleX: 0 },
          { opacity: 1, scaleX: 1, duration: 0.5, delay: 0.6, ease: 'back.out(1.2)', transformOrigin: 'left center' },
        )
      }
    } else {
      // Animate segments drawing in left-to-right
      const segs = containerRef.current.querySelectorAll<HTMLElement>('.tl-segment')
      if (reduced) return
      gsap.fromTo(
        segs,
        { scaleX: 0 },
        {
          scaleX: 1,
          duration: 0.4,
          stagger: 0.06,
          ease: 'power2.out',
          transformOrigin: 'left center',
        },
      )
    }
  }, [animate, useReplay, overrunMin])

  // Hourly ticks across the actual day span
  const TIME_TICKS: number[] = []
  for (let t = Math.ceil(DAY_START / 60) * 60; t <= DAY_END; t += 60) TIME_TICKS.push(t)

  return (
    <div className={`timeline-wrap ${compact ? 'compact' : ''}`}>
      {/* Time axis — relative so the tick labels anchor to this bar, not an ancestor */}
      <div style={{ position: 'relative', height: 12, marginBottom: 4 }}>
        {TIME_TICKS.map((t) => (
          <div
            key={t}
            style={{
              position: 'absolute',
              left: `${((t - DAY_START) / totalWidth) * 100}%`,
              fontSize: 9,
              color: '#bbb',
              fontVariantNumeric: 'tabular-nums',
              transform: 'translateX(-50%)',
              userSelect: 'none',
            }}
          >
            {minToLabel(t)}
          </div>
        ))}
      </div>

      <div ref={containerRef} style={{ position: 'relative', height: 40, marginTop: 2 }}>
        {/* Budget line */}
        <div
          className="timeline-budget-line"
          style={{ left: `${(TOTAL_MIN / totalWidth) * 100}%` }}
          title={`${minToLabel(DAY_END)} budget`}
        />

        {/* Bar */}
        <div
          className="timeline-bar-row"
          style={{ position: 'absolute', inset: 0, minWidth: 0, overflow: 'visible' }}
        >
          {segments.map((seg, i) => {
            const leftPct = ((seg.startMin - DAY_START) / totalWidth) * 100
            const widthPct = (seg.widthMin / totalWidth) * 100
            const clickable = (seg.kind === 'visit' || seg.kind === 'meal') && !!seg.poiId && !!onPoiClick
            return (
              <div
                key={i}
                className={`tl-segment ${seg.kind}`}
                style={{
                  position: 'absolute',
                  left: `${leftPct}%`,
                  width: `${widthPct}%`,
                  top: 0, bottom: 0,
                  cursor: clickable ? 'pointer' : undefined,
                  ...(seg.kind === 'visit' ? { background: visitColor } : {}),
                }}
                title={seg.label ? `${seg.label} (${minToLabel(seg.startMin)}–${minToLabel(seg.startMin + seg.widthMin)})` : seg.kind}
                onClick={clickable ? () => onPoiClick!(seg.poiId!) : undefined}
              >
                {seg.widthMin > 25 && seg.label && (
                  <span className="timeline-segment-label">
                    {seg.label}
                  </span>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {showLegend && (
        <div className="timeline-legend">
          {[
            { label: `Day ${dayIdx + 1}`, cls: 'visit', bg: visitColor },
            { label: 'Meal', cls: 'meal' },
            { label: 'Travel', cls: 'travel' },
            { label: 'Idle', cls: 'idle' },
            ...(useReplay && overrunMin > 0 ? [{ label: `Overrun +${overrunMin}min`, cls: 'overrun' }] : []),
          ].map(({ label, cls, bg }) => (
            <span key={cls}>
              <i
                className={`tl-segment ${cls}`}
                style={bg ? { background: bg } : undefined}
              />
              {label}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
