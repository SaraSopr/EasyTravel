import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { useDemoStore } from '../useDemoStore'
import { DAY_COLORS } from '../types'
import type {
  DemoPreprocessing,
  DemoRouteLeg,
  GreedyDay,
  TransportMode,
} from '../types'
import DemoMap from '../components/DemoMap'
import RadarChart from '../components/RadarChart'
import TimelineBar from '../components/TimelineBar'
import ClusterLegend from '../components/ClusterLegend'
import LaneBoard from '../components/LaneBoard'

const CAPTIONS = [
  {
    simple: 'Before creating the day zones, the candidate pool is cleaned: distant, family-incompatible, and duplicate places are removed.',
    tech: 'Eligibility pipeline: adaptive city radius → family suitability/nightlife guard → {dedup} m near-duplicate collapse.',
  },
  {
    simple: 'The city is split into zones — one per day. Each color is one day.',
    tech: 'Leiden k-NN geographic clustering → rebalanced to {n} clusters. Color = cluster/day.',
  },
  {
    simple: 'The most relevant and diverse places are selected — one at a time, picking the next one that adds the most without repeating the same type.',
    tech: 'Maximal Marginal Relevance: argmax λ·relevance − (1−λ)·redundancy, λ=0.6. Non-selected fade to 20% opacity.',
  },
  {
    simple: 'The greedy scheduler turns each day shortlist into a complete, ordered, and timed itinerary.',
    tech: 'Greedy time-aware scheduler → TSP reorder → meal insertion. Times use haversine travel estimates.',
  },
  {
    simple: 'The itinerary built with straight-line estimates is replayed against the common routing cache. The difference reveals where Haversine was too optimistic.',
    tech: 'Thesis feasibility protocol: build on Haversine → replay the same stops/order with the API-derived matrix (ORS by default) → measure travel-time delta and budget overrun. No re-optimisation.',
  },
]

function FilterSummary({
  data,
  phase,
}: {
  data: DemoPreprocessing
  phase: number
}) {
  const rows = [
    {
      label: `Inside ${(data.radiusM / 1000).toFixed(1)} km radius`,
      value: `−${data.radiusExcluded.length}`,
      active: phase >= 1,
      color: '#F97316',
    },
    {
      label: data.familyMode ? 'Family suitability' : 'Family filter inactive',
      value: data.familyMode ? `−${data.familyExcluded.length}` : '—',
      active: phase >= 2,
      color: '#EF4444',
    },
    {
      label: 'Near-duplicate collapse',
      value: `−${data.duplicates.length}`,
      active: phase >= 3,
      color: '#EAB308',
      textColor: '#854D0E',
    },
  ]

  return (
    <div className="filter-summary">
      <div className="filter-summary-title">Candidate cleanup</div>
      <div className="filter-count filter-count-start">
        <span>Starting pool</span>
        <strong>{data.initialCount}</strong>
      </div>
      {rows.map((row, index) => (
        <div
          className={`filter-count ${row.active ? 'active' : ''}`}
          key={row.label}
          style={{
            '--filter-color': row.color,
            '--filter-text-color': row.textColor ?? row.color,
          } as CSSProperties}
        >
          <span>
            <i aria-hidden="true" />
            {row.label}
          </span>
          <strong>{row.active ? row.value : '…'}</strong>
          <em>{phase === index + 1 ? 'applying' : row.active ? 'done' : 'waiting'}</em>
        </div>
      ))}
      <div className={`filter-total ${phase >= 3 ? 'active' : ''}`}>
        <span>Eligible for planning</span>
        <strong>{phase >= 3 ? data.finalCount : '—'}</strong>
      </div>
      <div className="filter-food-note">
        Food POIs remain grey and are inserted later as meals.
      </div>
    </div>
  )
}

function GreedyCompletionSummary({
  days,
  phase,
  techMode,
}: {
  days: GreedyDay[]
  phase: number
  techMode: boolean
}) {
  const activityCount = days.reduce(
    (total, day) => total + day.stops.filter(stop => stop.kind === 'visit').length,
    0,
  )
  const mealCount = days.reduce(
    (total, day) => total + day.stops.filter(stop => stop.kind === 'meal').length,
    0,
  )
  // Mirrors _schedule_day: Pass 1 activities → Pass 2 TSP → Pass 3 meals at
  // the TSP positions → refill → time propagation.
  const steps = [
    {
      title: 'Choose feasible activities',
      detail: `${activityCount} activities fit opening hours and daily budgets`,
    },
    {
      title: 'Reorder with TSP',
      detail: `${days.length} day routes compacted geographically`,
    },
    {
      title: 'Insert lunch and dinner',
      detail: `${mealCount} meal stops placed at the reordered positions`,
    },
    {
      title: 'Refill freed time',
      detail: 'Skipped candidates are re-checked after TSP shortens travel',
    },
    {
      title: 'Recalculate all times',
      detail: 'Arrival, visit, travel, and departure times propagated',
    },
    {
      title: 'Save final itinerary',
      detail: 'The production generate endpoint persists every stop',
    },
  ]

  return (
    <div className="greedy-completion">
      <div className="greedy-completion-title">Greedy itinerary complete</div>
      <div className="greedy-completion-steps">
        {steps.map((step, index) => {
          const complete = phase >= index + 1
          const running = phase === index
          return (
            <div
              className={`greedy-completion-step ${complete ? 'complete' : ''} ${running ? 'running' : ''}`}
              key={step.title}
            >
              <span className="greedy-completion-check" aria-hidden="true">
                {complete ? '✓' : index + 1}
              </span>
              <div>
                <strong>{step.title}</strong>
                <small>{step.detail}</small>
              </div>
            </div>
          )
        })}
      </div>
      {techMode && (
        <div className="greedy-completion-note">
          The demo trace stops before the database write; production persists here.
        </div>
      )}
    </div>
  )
}

function RealismAuditSummary({
  day,
  dayIdx,
  dayStartMin,
}: {
  day: GreedyDay
  dayIdx: number
  dayStartMin: number
}) {
  const plannedEnd = day.stops[day.stops.length - 1]?.departMin ?? dayStartMin
  const replayEnd =
    day.replayReal.stops[day.replayReal.stops.length - 1]?.departMin ?? dayStartMin
  const plannedTravelMin = day.stops.reduce(
    (total, stop) => total + (stop.travelMinutesFromPrevious ?? 0),
    0,
  )
  const replayTravelMin = day.replayReal.stops.reduce(
    (total, stop) => total + (stop.travelMinutesFromPrevious ?? 0),
    0,
  )
  const travelDelta = replayTravelMin - plannedTravelMin
  const travelDeltaPct = plannedTravelMin > 0
    ? (travelDelta / plannedTravelMin) * 100
    : 0
  const signed = (value: number) => `${value >= 0 ? '+' : ''}${value.toFixed(1)}`
  const formatTime = (minute: number) => (
    `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`
  )

  return (
    <div className="realism-audit">
      <div className="realism-audit-badge">Evaluation only</div>
      <div className="realism-audit-title">Day {dayIdx + 1} feasibility replay</div>
      <div className="realism-model-flow">
        <div className="haversine">
          <span>Built with</span>
          <strong>Haversine</strong>
          <b>{plannedTravelMin.toFixed(1)} min travel</b>
        </div>
        <div className="realism-model-arrow" aria-hidden="true">→</div>
        <div className="network">
          <span>Evaluated with</span>
          <strong>Network matrix</strong>
          <b>{replayTravelMin.toFixed(1)} min travel</b>
        </div>
        <div className={`realism-model-delta ${travelDelta > 0 ? 'slower' : 'faster'}`}>
          <span>Travel delta</span>
          <strong>{signed(travelDelta)} min</strong>
          <b>{signed(travelDeltaPct)}%</b>
        </div>
      </div>
      <div className="realism-audit-grid">
        <div>
          <span>Planned end</span>
          <strong>{formatTime(plannedEnd)}</strong>
        </div>
        <div>
          <span>Replay end</span>
          <strong>{formatTime(replayEnd)}</strong>
        </div>
        <div className={day.replayReal.overrunMin > 0 ? 'warning' : 'safe'}>
          <span>Overrun</span>
          <strong>+{day.replayReal.overrunMin} min</strong>
        </div>
      </div>
      <div className="realism-audit-method">
        Same stops and order · routing cache · no re-optimisation
      </div>
      <div className="realism-audit-coverage">
        <strong>{day.replayReal.realLegs}/{day.replayReal.totalLegs}</strong>
        {' '}legs use API-derived travel times
        {day.replayReal.fallbackLegs > 0 && (
          <span> · {day.replayReal.fallbackLegs} Haversine fallback</span>
        )}
      </div>
      {day.replayReal.closedOnArrival.length > 0 && (
        <div className="realism-audit-closed">
          {day.replayReal.closedOnArrival.length} stop(s) closed on replay arrival
        </div>
      )}
    </div>
  )
}

export default function Screen2Greedy() {
  const {
    stepIdx, selectedDay, setSelectedDay, city, trace, techMode,
    expanded, toggleExpanded, personaId, personas,
  } = useDemoStore()
  // Prefer the persona actually used by the backend run over the local list.
  const persona = trace?.persona
    ?? personas.find(p => p.id === personaId)
    ?? personas[0]
  const pois = trace?.pois ?? []
  const preprocessing = trace?.preprocessing
  const greedy = trace?.greedy
  const numDays = greedy?.days?.length ?? 0
  const cityName = trace?.city.name ?? city
  const [filterPhase, setFilterPhase] = useState(0)
  const [mapFocus, setMapFocus] = useState<{
    poiId: string
    request: number
  } | null>(null)
  const [showAllDays, setShowAllDays] = useState(true)
  const [schedulePhase, setSchedulePhase] = useState(0)

  useEffect(() => {
    if (stepIdx !== 0 || !preprocessing) return
    setFilterPhase(0)
    const timers = [1, 2, 3].map(phase => window.setTimeout(
      () => setFilterPhase(phase),
      phase * 850,
    ))
    return () => timers.forEach(window.clearTimeout)
  }, [preprocessing, stepIdx, trace?.persona.id])

  useEffect(() => {
    if (stepIdx !== 3) return
    setShowAllDays(true)
    setSchedulePhase(0)
    const timers = [1, 2, 3, 4, 5, 6].map(phase => window.setTimeout(
      () => setSchedulePhase(phase),
      phase * 500,
    ))
    return () => timers.forEach(window.clearTimeout)
  }, [stepIdx, trace?.persona.id])

  useEffect(() => {
    if (stepIdx !== 4) return
    setSelectedDay(0)
    setShowAllDays(false)
  }, [setSelectedDay, stepIdx, trace?.persona.id])

  const finalPoiIds = useMemo(() => new Set([
    ...(preprocessing?.finalActivityIds ?? []),
    ...(preprocessing?.finalFoodIds ?? []),
  ]), [preprocessing])
  const mapPois = stepIdx === 0 || !preprocessing
    ? pois
    : pois.filter(poi => finalPoiIds.has(poi.id))
  const dayData = greedy?.days?.[selectedDay]
  const routeIds = dayData?.route ?? []
  const routeLegsForDay = (day: GreedyDay): DemoRouteLeg[] => {
    const stops = stepIdx === 4 ? day.replayReal.stops : day.stops
    const estimatedByDestination = new Map(
      day.stops.map(stop => [stop.poiId, stop.travelMinutesFromPrevious]),
    )
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
        estimatedTravelMinutes: stepIdx === 4
          ? (estimatedByDestination.get(stop.poiId) ?? undefined)
          : undefined,
      }]
    })
  }
  const displayedRoutes = showAllDays
    ? (greedy?.days ?? []).map((day, dayIdx) => ({
        route: day.route,
        dayIdx,
        legs: routeLegsForDay(day),
      }))
    : [{
        route: routeIds,
        dayIdx: selectedDay,
        legs: dayData ? routeLegsForDay(dayData) : [],
      }]
  const routeIdSet = new Set(displayedRoutes.flatMap(day => day.route))
  const visibleMapPois = stepIdx >= 3
    ? mapPois.filter(poi => routeIdSet.has(poi.id))
    : stepIdx === 2
      ? mapPois.filter(poi => !(poi.isFood ?? poi.category === 'food'))
      : mapPois
  const routeBounds = visibleMapPois.length > 0
    ? [
        [
          Math.min(...visibleMapPois.map(poi => poi.lat)) - 0.005,
          Math.min(...visibleMapPois.map(poi => poi.lng)) - 0.005,
        ],
        [
          Math.max(...visibleMapPois.map(poi => poi.lat)) + 0.005,
          Math.max(...visibleMapPois.map(poi => poi.lng)) + 0.005,
        ],
      ] as [[number, number], [number, number]]
    : undefined
  const bounds = stepIdx === 0
    ? trace?.city.bounds
    : stepIdx >= 3
      ? routeBounds
      : (preprocessing?.filteredBounds ?? trace?.city.bounds)

  const caption = CAPTIONS[stepIdx]
  const simpleText = caption?.simple.replace('{city}', cityName).replace('{n}', String(numDays))
  const techText = caption?.tech
    ?.replace('{n}', String(numDays))
    .replace('{dedup}', String(preprocessing?.dedupRadiusM ?? 30))

  // Deferred POIs can be scheduled on a different day than their original
  // cluster, so from the scheduling step onward markers follow the day each
  // POI actually ended up in. Food stays unmapped to keep the grey circles.
  const scheduledDayByPoi = useMemo(() => {
    if (!greedy?.days) return undefined
    const foodIds = new Set(
      pois.filter(p => p.isFood ?? p.category === 'food').map(p => p.id),
    )
    const mapping: Record<string, number> = {}
    greedy.days.forEach((day, dayIdx) => {
      day.route.forEach(poiId => {
        if (!foodIds.has(poiId)) mapping[poiId] = dayIdx
      })
    })
    return mapping
  }, [greedy?.days, pois])

  // Clusters dict for step 2+
  const clusters = stepIdx >= 3
    ? scheduledDayByPoi
    : stepIdx >= 1
      ? greedy?.clusters
      : undefined

  // Selected POIs set for step 3+
  const selectedSet: Set<string> | undefined =
    stepIdx === 2 && greedy?.selected
      ? new Set(greedy.selected)
      : undefined
  const mmrDayStats = useMemo(() => {
    if (!greedy?.selected || !greedy.clusters) return []
    const poiById = new Map(pois.map(poi => [poi.id, poi]))
    return Array.from({ length: numDays }, (_, dayIdx) => {
      const selectedIds = greedy.selected.filter(
        poiId => greedy.clusters[poiId] === dayIdx,
      )
      const categoryCounts = selectedIds.reduce<Record<string, number>>(
        (counts, poiId) => {
          const category = poiById.get(poiId)?.category ?? 'other'
          counts[category] = (counts[category] ?? 0) + 1
          return counts
        },
        {},
      )
      const topCategories = Object.entries(categoryCounts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 2)
        .map(([category, count]) => `${category.replace(/_/g, ' ')} ${count}`)
        .join(' · ')
      return { dayIdx, count: selectedIds.length, topCategories }
    })
  }, [greedy?.clusters, greedy?.selected, numDays, pois])

  const showRoute = stepIdx >= 3
  const showReplay = stepIdx >= 4
  const replayTravelDelta = dayData
    ? (
        dayData.replayReal.stops.reduce(
          (total, stop) => total + (stop.travelMinutesFromPrevious ?? 0),
          0,
        )
        - dayData.stops.reduce(
          (total, stop) => total + (stop.travelMinutesFromPrevious ?? 0),
          0,
        )
      )
    : 0
  const visibleCollapsedDays = Math.min(numDays, 3)
  const hasAdditionalDays = numDays > 3
  const collapsedScheduleHeight = 100 + visibleCollapsedDays * 80 + (hasAdditionalDays ? 0 : 24)
  const focusScheduledPoi = (poiId: string, dayIdx: number) => {
    setSelectedDay(dayIdx)
    setShowAllDays(false)
    setMapFocus(previous => ({
      poiId,
      request: (previous?.request ?? 0) + 1,
    }))
    if (expanded) toggleExpanded()
  }

  return (
    <div className="screen-layout">
      {/* Map */}
      <div className="demo-map-wrap">
        {pois.length > 0 ? (
          <DemoMap
            centerLat={trace?.city.center[0] ?? 41.9}
            centerLng={trace?.city.center[1] ?? 12.48}
            bounds={bounds}
            pois={visibleMapPois}
            clusters={clusters}
            filtering={stepIdx === 0 ? preprocessing : undefined}
            filterPhase={filterPhase}
            softenFoodMarkers={stepIdx === 1}
            selectedIds={selectedSet}
            routePolylines={showRoute ? displayedRoutes : undefined}
            showRoute={showRoute}
            routeDayIdx={selectedDay}
            focusPoiId={mapFocus?.poiId}
            focusRequest={mapFocus?.request}
            techMode={techMode}
            prizeParams={trace?.params}
          />
        ) : (
          <div className="demo-loading"><div className="spinner" />Loading…</div>
        )}
      </div>

      {/* Side panel */}
      <div className="demo-side-panel">
        {/* Pinned persona radar */}
        <RadarChart vector={persona.vector} size={140} label={persona.label} />

        {/* Caption */}
        <p className="demo-caption">{simpleText}</p>
        {techMode && techText && <div className="tech-overlay">{techText}</div>}

        {stepIdx === 0 && preprocessing && (
          <FilterSummary data={preprocessing} phase={filterPhase} />
        )}

        {/* Day selector before the step summaries so it never scrolls out of
            view under the taller cards (same order as the TOPTW screen) */}
        {stepIdx >= 3 && numDays > 1 && (
          <div className="day-tabs">
            {stepIdx === 3 && (
              <button
                className={`day-tab ${showAllDays ? 'active' : ''}`}
                onClick={() => setShowAllDays(true)}
                style={showAllDays ? {
                  background: '#312E81',
                  borderColor: '#312E81',
                } : {
                  color: '#312E81',
                  borderColor: '#C7D2FE',
                }}
              >
                All
              </button>
            )}
            {Array.from({ length: numDays }, (_, i) => (
              <button
                key={i}
                className={`day-tab ${!showAllDays && selectedDay === i ? 'active' : ''}`}
                onClick={() => {
                  setSelectedDay(i)
                  setShowAllDays(false)
                }}
                style={!showAllDays && selectedDay === i ? {
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

        {stepIdx === 3 && greedy?.days && (
          <GreedyCompletionSummary
            days={greedy.days}
            phase={schedulePhase}
            techMode={techMode}
          />
        )}

        {stepIdx === 4 && dayData && (
          <RealismAuditSummary
            day={dayData}
            dayIdx={selectedDay}
            dayStartMin={trace?.daySpan?.[0] ?? 540}
          />
        )}

        {/* Step 2: cluster legend */}
        {stepIdx === 1 && (
          <ClusterLegend count={numDays} />
        )}

        {/* Step 3: MMR counter */}
        {stepIdx === 2 && greedy?.selected && (
          <div className="mmr-summary">
            <div className="mmr-summary-title">
              {greedy.selected.length} places shortlisted by MMR
            </div>
            <div className="mmr-summary-subtitle">
              Selection runs independently inside each day cluster.
            </div>
            <div className="mmr-day-list">
              {mmrDayStats.map(({ dayIdx, count, topCategories }) => (
                <div className="mmr-day-row" key={dayIdx}>
                  <span
                    className={`mmr-day-marker mmr-day-marker-${dayIdx % DAY_COLORS.length}`}
                    style={{ background: DAY_COLORS[dayIdx % DAY_COLORS.length].main }}
                    aria-hidden="true"
                  />
                  <div>
                    <strong>Day {dayIdx + 1}</strong>
                    <span>{count} places</span>
                    <small>{topCategories}</small>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Step 4: all greedy days, using the same schedule board as TOPTW */}
      {stepIdx === 3 && greedy?.days && (
        <div
          className="demo-bottom"
          style={expanded ? {} : { height: collapsedScheduleHeight }}
        >
          <LaneBoard
            days={greedy.days}
            pois={pois}
            daySpan={trace?.daySpan}
            animate
            expanded={expanded}
            onToggleExpand={expanded || hasAdditionalDays ? toggleExpanded : undefined}
            onStopClick={focusScheduledPoi}
            activePoiId={mapFocus?.poiId}
          />
        </div>
      )}

      {/* Step 5: thesis-aligned network feasibility replay */}
      {stepIdx === 4 && dayData && (
        <div className="demo-bottom realism-audit-timelines">
          <div className="realism-timeline-row">
            <div className="realism-timeline-label">
              Planned
              <span>Haversine estimates</span>
            </div>
            <TimelineBar
              day={dayData}
              pois={pois}
              daySpan={trace?.daySpan}
              useReplay={false}
              dayIdx={selectedDay}
              showLegend={false}
            />
          </div>
          <div className="realism-timeline-row">
            <div className="realism-timeline-label replay">
              Real replay
              <span>routing cache</span>
              <strong className={`realism-travel-delta ${replayTravelDelta > 0 ? 'slower' : 'faster'}`}>
                {replayTravelDelta >= 0 ? '+' : ''}{replayTravelDelta.toFixed(1)} min travel
              </strong>
              {dayData.replayReal.overrunMin > 0 && (
                <strong className="realism-overrun">
                  +{dayData.replayReal.overrunMin} min overrun
                </strong>
              )}
            </div>
            <TimelineBar
              day={dayData}
              pois={pois}
              daySpan={trace?.daySpan}
              useReplay={showReplay}
              animate
              dayIdx={selectedDay}
              showLegend={false}
            />
          </div>
          <div className="realism-shared-legend">
            <span><i className="visit" style={{
              background: DAY_COLORS[selectedDay % DAY_COLORS.length].main,
            }} />Activity</span>
            <span><i className="meal" />Meal</span>
            <span><i className="travel" />Travel</span>
            <span><i className="idle" />Idle</span>
            {dayData.replayReal.overrunMin > 0 && (
              <span><i className="overrun" />Overrun</span>
            )}
            <em>Same stops and visit durations — only travel times change</em>
          </div>
        </div>
      )}
    </div>
  )
}
