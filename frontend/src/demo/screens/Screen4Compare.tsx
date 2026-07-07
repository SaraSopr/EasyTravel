import { useEffect, useMemo, useRef, useState } from 'react'
import gsap from 'gsap'
import { useDemoStore } from '../useDemoStore'
import { DAY_COLORS } from '../types'
import type { DemoRouteLeg, DemoStop, GreedyDay, ToptwDay, TransportMode } from '../types'
import DemoMap from '../components/DemoMap'
import TimelineBar from '../components/TimelineBar'

function legsForStops(stops: DemoStop[]): DemoRouteLeg[] {
  return stops.flatMap((stop, index) => {
    if (
      index === 0
      || !stop.transportFromPrevious
      || stop.travelMinutesFromPrevious == null
    ) return []
    return [{
      fromPoiId: stops[index - 1].poiId,
      toPoiId: stop.poiId,
      transport: stop.transportFromPrevious as TransportMode,
      travelMinutes: stop.travelMinutesFromPrevious,
    }]
  })
}

// TimelineBar renders greedy days; wrap a TOPTW day in the same shape
// (its schedule is already feasible, so the "replay" is the plan itself).
function toptwAsGreedyDay(day: ToptwDay): GreedyDay {
  return {
    stops: day.stops,
    route: day.route,
    replayReal: {
      stops: day.stops.map(s => ({
        poiId: s.poiId,
        arrivalMin: s.arrivalMin,
        departMin: s.departMin,
        transportFromPrevious: s.transportFromPrevious,
        travelMinutesFromPrevious: s.travelMinutesFromPrevious,
      })),
      overrunMin: 0,
      closedOnArrival: [],
      totalLegs: Math.max(0, day.stops.length - 1),
      realLegs: Math.max(0, day.stops.length - 1),
      fallbackLegs: 0,
      cachedFallbackLegs: 0,
      uncachedFallbackLegs: 0,
    },
  }
}

export default function Screen4Compare() {
  const { trace, techMode, personaId, personas, setPersona } = useDemoStore()
  const allPois = trace?.pois ?? []
  const finalPoiIds = new Set([
    ...(trace?.preprocessing?.finalActivityIds ?? []),
    ...(trace?.preprocessing?.finalFoodIds ?? []),
  ])
  const pois = trace?.preprocessing
    ? allPois.filter(poi => finalPoiIds.has(poi.id))
    : allPois
  const greedy = trace?.greedy
  const toptw = trace?.toptw
  const metrics = trace?.metrics

  // Day filter: null = all days, otherwise a single day across maps + timelines.
  const numDays = Math.max(greedy?.days?.length ?? 0, toptw?.days?.length ?? 0)
  const [selectedDay, setSelectedDay] = useState<number | null>(null)
  // Expand one half (map + timeline) to full width; null = side-by-side.
  const [expanded, setExpanded] = useState<'greedy' | 'toptw' | null>(null)
  useEffect(() => {
    setSelectedDay(null)
    setExpanded(null)
  }, [personaId])
  const activeDay = selectedDay != null && selectedDay < numDays ? selectedDay : null

  // Keep each day's original index so colors stay stable under the day filter.
  const visibleDays = <T,>(days: T[] | undefined) =>
    (days ?? [])
      .map((day, dayIdx) => ({ day, dayIdx }))
      .filter(({ dayIdx }) => activeDay == null || dayIdx === activeDay)

  // Day routes per solver, with markers colored by the day each POI is
  // actually scheduled in — so marker colors always match the polylines.
  const foodIds = useMemo(() => new Set(
    pois.filter(p => p.isFood ?? p.category === 'food').map(p => p.id),
  ), [pois])
  const buildView = (days: { route: string[]; stops: DemoStop[] }[] | undefined) => {
    const routes = visibleDays(days).map(({ day, dayIdx }) => ({
      // Use the full stop sequence (meals included) so the polyline connects
      // through food stops instead of leaving them as orphan grey dots.
      route: day.stops.map(s => s.poiId),
      dayIdx,
      legs: legsForStops(day.stops),
    }))
    const dayByPoi: Record<string, number> = {}
    routes.forEach(({ route, dayIdx }) => route.forEach(poiId => {
      if (!foodIds.has(poiId)) dayByPoi[poiId] = dayIdx
    }))
    return { routes, dayByPoi }
  }
  const greedyView = buildView(greedy?.days)
  const toptwView = buildView(toptw?.days)

  // Each map shows only the POIs its solver actually scheduled (like the
  // solver screens); both maps share the same bounds so routes compare fairly.
  const scheduledIds = (days: { stops: DemoStop[] }[] | undefined) =>
    new Set(visibleDays(days).flatMap(({ day }) => day.stops.map(stop => stop.poiId)))
  const greedyIds = scheduledIds(greedy?.days)
  const toptwIds = scheduledIds(toptw?.days)
  const greedyPois = pois.filter(poi => greedyIds.has(poi.id))
  const toptwPois = pois.filter(poi => toptwIds.has(poi.id))
  const scheduledPois = pois.filter(
    poi => greedyIds.has(poi.id) || toptwIds.has(poi.id),
  )
  const bounds = scheduledPois.length > 0
    ? [
        [
          Math.min(...scheduledPois.map(poi => poi.lat)) - 0.005,
          Math.min(...scheduledPois.map(poi => poi.lng)) - 0.005,
        ],
        [
          Math.max(...scheduledPois.map(poi => poi.lat)) + 0.005,
          Math.max(...scheduledPois.map(poi => poi.lng)) + 0.005,
        ],
      ] as [[number, number], [number, number]]
    : trace?.preprocessing?.filteredBounds ?? trace?.city.bounds

  const scoreboardRef = useRef<HTMLDivElement>(null)

  // Animate scoreboard on mount
  useEffect(() => {
    if (!scoreboardRef.current) return
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced) return
    const cards = scoreboardRef.current.querySelectorAll<HTMLElement>('.score-card')
    gsap.from(cards, {
      y: 20, opacity: 0,
      duration: 0.4,
      stagger: 0.08,
      ease: 'power2.out',
    })
  }, [])

  if (!trace) {
    return (
      <div className="demo-loading">
        <div className="spinner" />
        Loading trace…
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0, height: '100%', overflow: 'hidden' }}>
      {/* Persona switcher */}
      <div style={{ display: 'flex', gap: 8, padding: '8px 16px', borderBottom: '1px solid #e0dcd4', background: '#faf9f6', flexShrink: 0 }}>
        <span style={{ fontSize: '0.9rem', color: '#888', alignSelf: 'center', marginRight: 4 }}>Persona:</span>
        {personas.map(p => (
          <button
            key={p.id}
            onClick={() => setPersona(p.id as typeof personaId)}
            style={{
              padding: '4px 12px',
              border: '1px solid',
              borderColor: personaId === p.id ? '#6366F1' : '#ddd',
              borderRadius: 20,
              background: personaId === p.id ? '#6366F1' : 'transparent',
              color: personaId === p.id ? '#fff' : '#555',
              fontSize: '0.93rem',
              cursor: 'pointer',
              transition: 'all 0.15s',
            }}
          >
            {p.label}
          </button>
        ))}

        {/* Day filter: maps and timelines follow it together */}
        {numDays > 1 && (
          <div className="day-tabs" style={{ marginLeft: 'auto', alignItems: 'center' }}>
            <button
              className={`day-tab ${activeDay == null ? 'active' : ''}`}
              onClick={() => setSelectedDay(null)}
              style={activeDay == null ? {
                background: '#312E81',
                borderColor: '#312E81',
              } : {
                color: '#312E81',
                borderColor: '#C7D2FE',
              }}
            >
              All
            </button>
            {Array.from({ length: numDays }, (_, i) => (
              <button
                key={i}
                className={`day-tab ${activeDay === i ? 'active' : ''}`}
                onClick={() => setSelectedDay(i)}
                style={activeDay === i ? {
                  background: DAY_COLORS[i % DAY_COLORS.length].main,
                  borderColor: DAY_COLORS[i % DAY_COLORS.length].main,
                } : {
                  color: DAY_COLORS[i % DAY_COLORS.length].main,
                  borderColor: DAY_COLORS[i % DAY_COLORS.length].light,
                }}
              >
                Day {i + 1}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Maps row */}
      <div
        className="compare-layout"
        style={{ flex: 1, minHeight: 0, gridTemplateColumns: expanded ? '1fr' : '1fr 1fr' }}
      >
        {expanded !== 'toptw' && (
          <div className="compare-half">
            <div className="compare-label">
              Greedy baseline
              <button
                className="compare-expand-btn"
                onClick={() => setExpanded(expanded === 'greedy' ? null : 'greedy')}
                title={expanded === 'greedy' ? 'Back to side-by-side' : 'Expand to full width'}
              >
                {expanded === 'greedy' ? '⤡ Split view' : '⤢ Expand'}
              </button>
            </div>
            <div className="compare-map">
              <DemoMap
                centerLat={trace.city.center[0]}
                centerLng={trace.city.center[1]}
                bounds={bounds}
                pois={greedyPois}
                clusters={greedyView.dayByPoi}
                routePolylines={greedyView.routes}
                showRoute
                showLegend={false}
                techMode={techMode}
                prizeParams={trace.params}
              />
            </div>
          </div>
        )}
        {expanded !== 'greedy' && (
          <div className="compare-half">
            <div className="compare-label">
              TOPTW solver
              <button
                className="compare-expand-btn"
                onClick={() => setExpanded(expanded === 'toptw' ? null : 'toptw')}
                title={expanded === 'toptw' ? 'Back to side-by-side' : 'Expand to full width'}
              >
                {expanded === 'toptw' ? '⤡ Split view' : '⤢ Expand'}
              </button>
            </div>
            <div className="compare-map">
              <DemoMap
                centerLat={trace.city.center[0]}
                centerLng={trace.city.center[1]}
                bounds={bounds}
                pois={toptwPois}
                clusters={toptwView.dayByPoi}
                routePolylines={toptwView.routes}
                showRoute
                showLegend={false}
                techMode={techMode}
                prizeParams={trace.params}
              />
            </div>
          </div>
        )}
      </div>

      {/* Timeline bars — one row per visible day, same day filter as the maps */}
      {greedy?.days && toptw?.days && (
        <div
          className={`compare-timelines${expanded ? ' expanded' : ''}`}
          style={{ display: 'grid', gridTemplateColumns: expanded ? '1fr' : '1fr 1fr', borderTop: '1px solid #e0dcd4', flexShrink: 0 }}
        >
          {expanded !== 'toptw' && (
          <div style={{ borderRight: expanded ? 'none' : '1px solid #e0dcd4', overflow: 'hidden', padding: '6px 0 4px' }}>
            {visibleDays(greedy.days).map(({ day, dayIdx }) => (
              <div key={dayIdx} style={{ display: 'flex', alignItems: 'center' }}>
                <span style={{
                  width: 46,
                  flexShrink: 0,
                  paddingLeft: 12,
                  fontSize: '0.72rem',
                  fontWeight: 700,
                  color: DAY_COLORS[dayIdx % DAY_COLORS.length].main,
                }}>
                  Day {dayIdx + 1}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <TimelineBar
                    day={day}
                    pois={pois}
                    daySpan={trace?.daySpan}
                    useReplay
                    animate
                    dayIdx={dayIdx}
                    showLegend={false}
                    compact={expanded == null}
                  />
                </div>
              </div>
            ))}
            <div className="timeline-legend" style={{ margin: '2px 0 0 58px' }}>
              <span><i className="tl-segment meal" />Meal</span>
              <span><i className="tl-segment travel" />Travel</span>
              <span><i className="tl-segment idle" />Idle</span>
              {visibleDays(greedy.days).some(({ day }) => day.replayReal.overrunMin > 0) && (
                <span><i className="tl-segment overrun" />Overrun</span>
              )}
              <em>Real replay (routing cache)</em>
            </div>
          </div>
          )}
          {expanded !== 'greedy' && (
          <div style={{ overflow: 'hidden', padding: '6px 0 4px' }}>
            {visibleDays(toptw.days).map(({ day, dayIdx }) => (
              <div key={dayIdx} style={{ display: 'flex', alignItems: 'center' }}>
                <span style={{
                  width: 46,
                  flexShrink: 0,
                  paddingLeft: 12,
                  fontSize: '0.72rem',
                  fontWeight: 700,
                  color: DAY_COLORS[dayIdx % DAY_COLORS.length].main,
                }}>
                  Day {dayIdx + 1}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <TimelineBar
                    day={toptwAsGreedyDay(day)}
                    pois={pois}
                    daySpan={trace?.daySpan}
                    animate
                    dayIdx={dayIdx}
                    showLegend={false}
                    compact={expanded == null}
                  />
                </div>
              </div>
            ))}
            <div className="timeline-legend" style={{ margin: '2px 0 0 58px' }}>
              <span><i className="tl-segment meal" />Meal</span>
              <span><i className="tl-segment travel" />Travel</span>
              <span><i className="tl-segment idle" />Idle</span>
              <em>As planned (never overruns)</em>
            </div>
          </div>
          )}
        </div>
      )}

      {/* Scoreboard */}
      <div ref={scoreboardRef} className="scoreboard" style={{ flexShrink: 0 }}>
        <div className="score-card">
          <div className="score-label">Overrun days</div>
          <div className="score-values">
            <div>
              <div className="score-val bad">{((metrics?.overrunRate.greedy ?? 0.144) * 100).toFixed(1)}%</div>
              <div className="score-side-label">Greedy</div>
            </div>
            <div>
              <div className="score-val good">{((metrics?.overrunRate.toptw ?? 0) * 100).toFixed(1)}%</div>
              <div className="score-side-label">TOPTW</div>
            </div>
          </div>
        </div>

        <div className="score-card">
          <div className="score-label">Stops / day</div>
          <div className="score-values">
            <div>
              <div className="score-val">{(metrics?.stopsPerDay.greedy ?? 7.86).toFixed(1)}</div>
              <div className="score-side-label">Greedy</div>
            </div>
            <div>
              <div className="score-val">{(metrics?.stopsPerDay.toptw ?? 7.19).toFixed(1)}</div>
              <div className="score-side-label">TOPTW</div>
            </div>
          </div>
        </div>

        <div className="score-card">
          <div className="score-label">Diversity (thesis eval)</div>
          <div className="score-values">
            <div>
              <div className="score-val">{(metrics?.diversity.greedy ?? 0.43).toFixed(2)}</div>
              <div className="score-side-label">Greedy</div>
            </div>
            <div>
              <div className="score-val">{(metrics?.diversity.toptw ?? 0.34).toFixed(2)}</div>
              <div className="score-side-label">TOPTW</div>
            </div>
          </div>
        </div>

        <div className="score-card">
          <div className="score-label">Idle min / day</div>
          <div className="score-values">
            <div>
              <div className="score-val good">{Math.round(metrics?.idleMin.greedy ?? 29)}</div>
              <div className="score-side-label">Greedy</div>
            </div>
            <div>
              <div className="score-val">{Math.round(metrics?.idleMin.toptw ?? 76)}</div>
              <div className="score-side-label">TOPTW</div>
            </div>
          </div>
        </div>

        {techMode && (
          <div className="tech-overlay" style={{ gridColumn: '1 / -1' }}>
            Overrun, stops and idle are computed from this {greedy?.days?.length ?? 3}-day run. Diversity comes from the thesis evaluation across Madrid + Porto (mean pairwise cosine distance in category embedding space). Idle = waits + unused tail of the day budget.
          </div>
        )}
      </div>
    </div>
  )
}
