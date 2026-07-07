import { useEffect, useMemo, useState } from 'react'
import { useDemoStore } from '../useDemoStore'
import { DAY_COLORS } from '../types'
import type { DemoRouteLeg, ToptwDay, TransportMode } from '../types'
import DemoMap from '../components/DemoMap'
import RadarChart from '../components/RadarChart'
import LaneBoard from '../components/LaneBoard'
import ClusterLegend from '../components/ClusterLegend'

const CAPTIONS = [
  {
    simple: 'Only the most promising places enter the game — the rest are set aside.',
    tech: 'select_candidates: top-N by prize ρᵢ = {wSim}·cos(vᵢ,u) + {wPop}·pop + {lb}·landmark.',
  },
  {
    simple: '{zoneSimple}',
    tech: '{zoneTech}',
  },
  {
    simple: "A prize game with a clock: every place is worth points (more if it matches you), every visit costs time, some places open only at certain hours, and the day ends at {end}. Greedy fills one day at a time — this solver looks at the whole trip at once.",
    tech: 'OR-Tools VRPTW: vehicles=days, optional nodes with penalty=prize, per-day replicas enforce at-most-once disjunctions. Time limit {tl}s.',
  },
  {
    simple: "The whole trip appears — one compact route per day. Select a day to see its route before the untangling: the solver found a crossing and fixed it.",
    tech: 'TSPTW reorder: OR-Tools TSP with time-window constraints per day. Travel reduction: {saved}%.',
  },
  {
    simple: '{fillSimple}',
    tech: 'fill_underfull_days: compact-route load < {fillRatio}·budget → borrow nearby unused POIs and re-solve. {fillInjected} injected; {fillAdded} retained.',
  },
  {
    simple: 'Restaurants are inserted along the already-fixed route. Some slack always remains — the price of never overrunning.',
    tech: 'Meal insertion: nearest open restaurant at target hour (floor 19:00 for dinner).',
  },
]

export default function Screen3TOPTW() {
  const { stepIdx, trace, techMode, expanded, toggleExpanded, personas } = useDemoStore()
  const personaId = useDemoStore(s => s.personaId)
  // Prefer the persona actually used by the backend run over the local list.
  const persona = trace?.persona
    ?? personas.find(p => p.id === personaId)
    ?? personas[0]
  const allPois = trace?.pois ?? []
  const finalPoiIds = new Set([
    ...(trace?.preprocessing?.finalActivityIds ?? []),
    ...(trace?.preprocessing?.finalFoodIds ?? []),
  ])
  const pois = trace?.preprocessing
    ? allPois.filter(poi => finalPoiIds.has(poi.id))
    : allPois
  const toptw = trace?.toptw
  const bounds = trace?.preprocessing?.filteredBounds ?? trace?.city.bounds
  const [selectedDay, setSelectedDay] = useState(0)
  const [showAllDays, setShowAllDays] = useState(true)
  const [mapFocus, setMapFocus] = useState<{
    poiId: string
    request: number
  } | null>(null)

  useEffect(() => {
    if (stepIdx >= 3) setShowAllDays(true)
  }, [stepIdx, trace?.persona.id])

  const caption = CAPTIONS[stepIdx]
  const balance = toptw?.balance ?? 0
  const balanceMin = trace?.params?.balanceMin ?? 0.35
  const tSaved = toptw?.days?.[selectedDay]?.travelSavedPct ?? 0
  const refill = toptw?.refill
  const fillInjected = refill?.injected ?? []
  const fillAdded = toptw?.refill?.added ?? []
  const fillAddedSet = new Set(fillAdded)
  const fillByDay = toptw?.refill?.byDay ?? {}
  const fillStates = Object.entries(refill?.days ?? {})
  // refill.days is keyed by *solver* day index; empty days are omitted from the
  // returned list, so translate through sourceDayIdx before labeling.
  const solverIdxToDisplay = new Map(
    (toptw?.days ?? []).map((d, i) => [d.sourceDayIdx ?? i, i + 1]),
  )
  const dayLabelFor = (solverKey: string) =>
    `Day ${solverIdxToDisplay.get(Number(solverKey)) ?? Number(solverKey) + 1}`
  const fillDayLabels = fillStates
    .filter(([, state]) => state.injected.length > 0)
    .map(([k]) => dayLabelFor(k))
    .join(', ')
  const underfullWithoutResult = fillStates.filter(([, state]) =>
    ['underfull_no_candidates', 'underfull_candidates_rejected', 'resolve_failed', 'fill_reverted'].includes(state.status),
  )
  const unresolvedDayLabels = underfullWithoutResult
    .map(([k]) => dayLabelFor(k))
    .join(', ')
  const hasReverted = fillStates.some(([, state]) => state.status === 'fill_reverted')
  const fillSimple = !refill?.enabled
    ? 'The under-full pass is disabled for this run.'
    : !refill.applicable
      ? 'The solver stayed global, so zone-based borrowing was not applicable.'
      : fillInjected.length > 0
        ? `${fillDayLabels} fell below the activity-load threshold. ${fillInjected.length} nearby candidate${fillInjected.length > 1 ? 's were' : ' was'} offered to the second solve; ${
          hasReverted && fillAdded.length === 0
            ? 'the borrowed result left the day worse off, so it was rolled back'
            : `${fillAdded.length} ${fillAdded.length === 1 ? 'was' : 'were'} retained in amber`
        }.`
        : underfullWithoutResult.length > 0
          ? `${unresolvedDayLabels} fell below the activity-load threshold, but no feasible nearby addition was retained.`
          : 'Every compact activity route was already above the load threshold, so no fill pass was needed.'
  const zoneSimple = toptw?.preClusterActive
    ? 'Geographic pre-clustering is active, so each place stays pinned to one compact day.'
    : 'The zone split did not pass the balance gate, so the solver kept a global assignment across days.'
  const zoneTech = toptw?.preClusterActive
    ? `Leiden clustering: balance=${balance.toFixed(2)}; pre-clustering ON.`
    : `Leiden clustering: balance=${balance.toFixed(2)}; pre-clustering OFF → global TOPTW.`
  const simpleText = caption?.simple
    ?.replace('{end}', trace?.schedule?.end ?? '22:00')
    ?.replace('{fillSimple}', fillSimple)
    ?.replace('{zoneSimple}', zoneSimple)
  const techText = caption?.tech
    ?.replace('{balance:.2f}', balance.toFixed(2))
    ?.replace('{tl}', String(trace?.params?.timeLimitS ?? 20))
    ?.replace('{wSim}', String(trace?.params?.wSim ?? 0.7))
    ?.replace('{wPop}', String(trace?.params?.wPop ?? 0.3))
    ?.replace('{lb}', String(trace?.params?.landmarkBoost ?? 0.15))
    ?.replace('{saved}', String(tSaved))
    ?.replace('{zoneTech}', zoneTech)
    ?.replace('{fillRatio}', String(refill?.ratio ?? 0.7))
    ?.replace('{fillInjected}', String(fillInjected.length))
    ?.replace('{fillAdded}', String(fillAdded.length))

  // Step 1: candidates only
  const candidateSet = stepIdx >= 0 && toptw?.candidates
    ? new Set(toptw.candidates)
    : undefined

  // The solver can assign a POI to a different day than its original zone, so
  // from the solve step onward markers follow the day each POI actually ended
  // up in. Food stays unmapped to keep the grey circles. All per-day snapshots
  // (reorder, pre-meal, final) contribute, since fill can add stops.
  const solvedDayByPoi = useMemo(() => {
    if (!toptw?.days) return undefined
    const foodIds = new Set(
      pois.filter(p => p.isFood ?? p.category === 'food').map(p => p.id),
    )
    const mapping: Record<string, number> = {}
    toptw.days.forEach((day, dayIdx) => {
      // Defensive ?? []: never let a malformed/older trace blank the screen.
      const snapshots = [day.reorderStops ?? [], day.preMealStops ?? [], day.stops]
      snapshots.forEach(stops => stops.forEach(stop => {
        if (!foodIds.has(stop.poiId)) mapping[stop.poiId] = dayIdx
      }))
    })
    return mapping
  }, [pois, toptw?.days])

  // Step 2: zones
  const zones = stepIdx >= 3
    ? solvedDayByPoi
    : stepIdx >= 1
      ? toptw?.zones
      : undefined

  // Step 4+: solved itineraries — show lane board (the solve step keeps the map only)
  const showLanes = stepIdx >= 3

  // Step 4: all final day routes, like the greedy scheduling step; tabbing into a
  // single day reveals that day's pre-reorder route (the crossing the TSPTW fixed)
  const showReorder = stepIdx === 3
  const showFill = stepIdx === 4
  const showMeals = stepIdx === 5
  const dayData = toptw?.days?.[selectedDay]
  const preReorderRoute = dayData?.preReorderRoute

  // Candidates stay highlighted through the zone/solve steps: the rest of the
  // pool dims so the day-zones read against the discarded candidates.
  const selectedIds = stepIdx <= 2 ? candidateSet : undefined

  const routeForStops = (stops: ToptwDay['stops']) =>
    stops.map(stop => stop.poiId)
  const legsForStops = (stops: ToptwDay['stops']): DemoRouteLeg[] =>
    stops.flatMap((stop, index) => {
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

  const dayCount = toptw?.days?.length ?? 0

  const routeSnapshot = (
    dayIdx: number,
    stops: ToptwDay['stops'],
  ) => ({
    route: routeForStops(stops),
    dayIdx,
    legs: legsForStops(stops),
  })

  // Each screen now uses the matching production snapshot:
  // reorder=initial compact activities, fill=post-fill activities, meals=final stops.
  const displayedRoutes = showMeals
    ? showAllDays
      ? (toptw?.days ?? []).map((day, dayIdx) =>
          routeSnapshot(dayIdx, day.stops))
      : dayData
        ? [routeSnapshot(selectedDay, dayData.stops)]
        : []
    : showFill
      ? showAllDays
        ? (toptw?.days ?? []).map((day, dayIdx) =>
            routeSnapshot(dayIdx, day.preMealStops ?? []))
        : dayData
          ? [routeSnapshot(selectedDay, dayData.preMealStops ?? [])]
          : []
      : showReorder
        ? showAllDays
          ? (toptw?.days ?? []).map((day, dayIdx) =>
              routeSnapshot(dayIdx, day.reorderStops ?? []))
          : [{ route: preReorderRoute ?? [], dayIdx: selectedDay, legs: [] }]
        : []

  // Food plays no role until the meal step; route steps show scheduled POIs only.
  const routeIdSet = new Set(displayedRoutes.flatMap(day => day.route))
  const visibleMapPois = stepIdx >= 3
    ? pois.filter(poi => routeIdSet.has(poi.id))
    : pois.filter(poi => !(poi.isFood ?? poi.category === 'food'))
  const laneDays = (toptw?.days ?? []).map(day => ({
    ...day,
    stops: showMeals
      ? day.stops
      : showFill
        ? (day.preMealStops ?? [])
        : (day.reorderStops ?? []),
  }))
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
  const mapBounds = stepIdx >= 3 ? routeBounds : bounds
  const visibleCollapsedDays = Math.min(dayCount, 3)
  const hasAdditionalDays = dayCount > 3
  const collapsedScheduleHeight =
    100
    + visibleCollapsedDays * 80
    + (hasAdditionalDays ? 0 : 24)
    + (!hasAdditionalDays && toptw?.excludedNotable?.length ? 26 : 0)
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
      {/* Map — hidden when lane board is fullscreen */}
      {!expanded && (
        <div className="demo-map-wrap">
          {pois.length > 0 ? (
            <DemoMap
              centerLat={trace?.city.center[0] ?? 41.9}
              centerLng={trace?.city.center[1] ?? 12.48}
              bounds={mapBounds}
              pois={visibleMapPois}
              clusters={zones}
              selectedIds={selectedIds}
              routePolylines={stepIdx >= 3 ? displayedRoutes : undefined}
              showRoute={stepIdx >= 3}
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
      )}

      {/* Side panel */}
      {!expanded && (
        <div className="demo-side-panel">
          <RadarChart vector={persona.vector} size={140} label={persona.label} />

          <p className="demo-caption">{simpleText}</p>
          {techMode && techText && <div className="tech-overlay">{techText}</div>}

          {/* Day selector for the reorder/meal steps */}
          {stepIdx >= 3 && dayCount > 1 && (
            <div className="day-tabs">
              {stepIdx >= 3 && (
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
              {Array.from({ length: dayCount }, (_, i) => {
                const active = !showAllDays && selectedDay === i
                return (
                  <button
                    key={i}
                    className={`day-tab ${active ? 'active' : ''}`}
                    onClick={() => {
                      setSelectedDay(i)
                      setShowAllDays(false)
                    }}
                    style={active ? {
                      background: DAY_COLORS[i % DAY_COLORS.length].main,
                      borderColor: DAY_COLORS[i % DAY_COLORS.length].main,
                    } : {
                      color: DAY_COLORS[i % DAY_COLORS.length].main,
                      borderColor: DAY_COLORS[i % DAY_COLORS.length].light,
                    }}
                  >
                    Day {i + 1}
                  </button>
                )
              })}
            </div>
          )}

          {/* Step 2: balance gauge */}
          {stepIdx === 1 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <ClusterLegend count={toptw?.days?.length ?? 0} />
              <div>
                <div style={{ fontSize: '0.93rem', color: '#888', marginBottom: 4 }}>Zone balance</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{ flex: 1, height: 10, background: '#e8e4dc', borderRadius: 5, overflow: 'hidden' }}>
                    <div style={{
                      height: '100%',
                      width: `${balance * 100}%`,
                      background: balance >= balanceMin ? '#6366F1' : '#EF4444',
                      borderRadius: 5,
                      transition: 'width 0.6s ease',
                    }} />
                  </div>
                  <span style={{ fontVariantNumeric: 'tabular-nums', fontSize: '0.95rem', fontWeight: 700, color: balance >= balanceMin ? '#6366F1' : '#EF4444' }}>
                    {balance.toFixed(2)} {balance >= balanceMin ? '✓' : '✗'}
                  </span>
                </div>
                {toptw?.pruned?.length ? (
                  <div style={{ fontSize: '0.9rem', color: '#aaa', marginTop: 6 }}>
                    {toptw.pruned.length} outlier(s) pruned
                  </div>
                ) : null}
              </div>
            </div>
          )}

          {/* Step 4: reorder stats (single-day view shows the pre-reorder route) */}
          {stepIdx === 3 && (
            showAllDays ? (
              <div style={{ fontSize: '0.93rem', color: '#888' }}>
                Compact activity routes before the fill pass. Select a day to see its route before the
                TSPTW untangling.
              </div>
            ) : (
              <div style={{ display: 'flex', gap: 16 }}>
                <div>
                  <div style={{ fontSize: '0.87rem', color: '#888' }}>Before reorder</div>
                  <div style={{ fontSize: '0.95rem', fontWeight: 700, color: '#aaa' }}>crossing</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.87rem', color: '#888' }}>Travel saved</div>
                  <div style={{ fontSize: '0.95rem', fontWeight: 700, color: '#6366F1' }}>{tSaved}%</div>
                </div>
              </div>
            )
          )}

          {/* Step 5: fill underfull days */}
          {showFill && toptw?.days?.length && (
            <div>
              <div style={{ fontSize: '0.93rem', color: '#888', marginBottom: 6 }}>
                Activity load before meals · threshold {refill?.thresholdMin ?? 0} min
              </div>
              {toptw.days.map((d, i) => {
                const sourceDayIdx = d.sourceDayIdx ?? i
                const state = refill?.days?.[String(sourceDayIdx)]
                const filledHere = fillByDay[String(sourceDayIdx)]?.length ?? 0
                const usedMin = state?.usedMinAfter ?? state?.usedMinBefore ?? 0
                const budgetMin = refill?.budgetMin || 1
                const statusLabel = state?.status
                  ?.replace(/_/g, ' ')
                  ?? 'not evaluated'
                return (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{ width: 44, fontSize: '0.9rem', color: '#666' }}>Day {i + 1}</span>
                    <div
                      title={statusLabel}
                      style={{ flex: 1, height: 8, background: '#e8e4dc', borderRadius: 4, overflow: 'hidden' }}
                    >
                      <div style={{
                        height: '100%',
                        width: `${Math.min(100, (usedMin / budgetMin) * 100)}%`,
                        background: filledHere ? '#D97706' : '#94A3B8',
                        borderRadius: 4,
                      }} />
                    </div>
                    <span
                      title={statusLabel}
                      style={{ fontSize: '0.9rem', color: filledHere ? '#D97706' : '#888', minWidth: 64, fontVariantNumeric: 'tabular-nums' }}
                    >
                      {Math.round(usedMin)} min{filledHere ? ` · +${filledHere}` : ''}
                    </span>
                  </div>
                )
              })}
            </div>
          )}

          {/* Step 6: idle stats after meals */}
          {showMeals && toptw?.days?.length && (
            <div>
              <div style={{ fontSize: '0.93rem', color: '#888', marginBottom: 6 }}>Idle per day (the price of feasibility)</div>
              {toptw.days.map((d, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <span style={{ width: 44, fontSize: '0.9rem', color: '#666' }}>Day {i + 1}</span>
                  <div style={{ flex: 1, height: 8, background: '#e8e4dc', borderRadius: 4, overflow: 'hidden' }}>
                    <div style={{
                      height: '100%',
                      width: `${Math.min(100, (d.idleMin / 120) * 100)}%`,
                      background: '#94A3B8',
                      borderRadius: 4,
                    }} />
                  </div>
                  <span style={{ fontSize: '0.9rem', color: '#888', minWidth: 36, fontVariantNumeric: 'tabular-nums' }}>
                    {d.idleMin} min
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Bottom: lane board (expandable) */}
      {showLanes && toptw?.days && (
        <div
          className="demo-bottom"
          style={expanded ? {} : { height: collapsedScheduleHeight }}
        >
          <LaneBoard
            days={laneDays}
            pois={pois}
            daySpan={trace?.daySpan}
            animate={stepIdx === 3}
            expanded={expanded}
            onToggleExpand={expanded || hasAdditionalDays ? toggleExpanded : undefined}
            onStopClick={focusScheduledPoi}
            activePoiId={mapFocus?.poiId}
            excludedNotable={toptw.excludedNotable ?? []}
            fillAddedIds={showFill && fillAddedSet.size > 0 ? fillAddedSet : undefined}
          />
        </div>
      )}
    </div>
  )
}
