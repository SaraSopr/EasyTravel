import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { Circle, MapContainer, Popup, TileLayer, useMap, ZoomControl } from 'react-leaflet'
import L from 'leaflet'
import type { Map as LeafletMap } from 'leaflet'
import type {
  DemoPoi,
  DemoPreprocessing,
  DemoRouteLeg,
  TransportMode,
} from '../types'
import { DAY_COLORS } from '../types'

interface MarkerState {
  id: string
  lat: number
  lng: number
  prize: number
  opacity: number
  isFood: boolean
  filterReason?: FilterReason
  dayColor?: string    // hex color from DAY_COLORS
  dayIdx?: number
  routePosition?: number
  highlight: boolean
  ghost: boolean
}

const FOOD_COLOR = '#94A3B8'
type FilterReason = 'radius' | 'family' | 'duplicate' | 'discarded'

const FILTER_COLORS: Record<FilterReason, string> = {
  radius: '#F97316',
  family: '#EF4444',
  duplicate: '#EAB308',
  discarded: '#DC2626',
}

const FILTER_OUTLINES: Record<FilterReason, string> = FILTER_COLORS

const FILTER_FOREGROUNDS: Record<FilterReason, string> = {
  radius: '#FFFFFF',
  family: '#FFFFFF',
  duplicate: '#FFFFFF',
  discarded: '#FFFFFF',
}

const FILTER_LABELS: Record<FilterReason, string> = {
  radius: 'outside the activity radius',
  family: 'not suitable for the family profile',
  duplicate: 'near-duplicate of another place',
  discarded: 'rejected by the LLM tourism validation',
}

function getFilterReason(
  poiId: string,
  filtering?: DemoPreprocessing,
  filterPhase = 0,
): FilterReason | undefined {
  if (filterPhase >= 1 && filtering?.radiusExcluded.includes(poiId)) return 'radius'
  if (filterPhase >= 2 && filtering?.familyExcluded.includes(poiId)) return 'family'
  if (
    filterPhase >= 3
    && filtering?.duplicates.some(pair => pair.removedId === poiId)
  ) return 'duplicate'
  return undefined
}

export interface DemoMapHandle {
  setMarkers: (states: MarkerState[]) => void
  animatePersonaWeighting: (pois: DemoPoi[], centerLat: number, centerLng: number) => void
  animateMMRSelection: (selectedIds: Set<string>, allIds: string[]) => void
  clearCanvas: () => void
  fitBounds: (bounds: [[number, number], [number, number]]) => void
}

interface Props {
  centerLat: number
  centerLng: number
  bounds?: [[number, number], [number, number]]
  pois?: DemoPoi[]
  clusters?: Record<string, number>
  filtering?: DemoPreprocessing
  filterPhase?: number
  softenFoodMarkers?: boolean
  selectedIds?: Set<string>
  /** Explicit per-POI marker color (hex); takes precedence over clusters. */
  poiColors?: Record<string, string>
  /** POIs drawn as excluded (red X) — used by the ingestion screen. */
  excludedIds?: Set<string>
  routePolyline?: string[]     // ordered POI ids to draw route
  routePolylines?: { route: string[]; dayIdx: number; legs?: DemoRouteLeg[] }[]
  routeLegs?: DemoRouteLeg[]
  showRoute?: boolean
  routeDayIdx?: number
  focusPoiId?: string
  focusRequest?: number
  techMode?: boolean
  showFoodDescription?: boolean
  /** Hide the marker legend — for small side-by-side maps where it would cover the view. */
  showLegend?: boolean
  /** Popup shows only name/category — for POIs without planner stats. */
  minimalPopup?: boolean
  /** Actual runtime prize weights (trace.params) for the tech legend. */
  prizeParams?: { wSim: number; wPop: number; landmarkBoost: number }
  dayColors?: typeof DAY_COLORS
  onPoiClick?: (poi: DemoPoi) => void
}

// Canvas overlay that GSAP tweens directly
class CanvasPOILayer extends L.Layer {
  private _canvas: HTMLCanvasElement | null = null
  private _markers: MarkerState[] = []
  private _pois: Map<string, DemoPoi> = new Map()

  onAdd(map: LeafletMap) {
    const canvas = document.createElement('canvas')
    canvas.style.position = 'absolute'
    canvas.style.top = '0'
    canvas.style.left = '0'
    canvas.style.pointerEvents = 'none'
    canvas.style.zIndex = '400'
    this._canvas = canvas
    const pane = map.getPane('overlayPane')
    if (pane) pane.appendChild(canvas)
    // 'move'/'zoom' fire on every frame of a flyTo: without a per-frame
    // redraw the dots detach from the tiles for the whole flight.
    map.on('move zoom moveend zoomend resize', this._redraw, this)
    this._resize(map)
    return this
  }

  onRemove(map: LeafletMap) {
    map.off('move zoom moveend zoomend resize', this._redraw, this)
    if (this._canvas) this._canvas.remove()
    this._canvas = null
    return this
  }

  private _resize(map: LeafletMap) {
    if (!this._canvas) return
    const size = map.getSize()
    // Assigning width/height reallocates the buffer even when unchanged —
    // too costly now that redraws run on every animation frame.
    if (this._canvas.width !== size.x) this._canvas.width = size.x
    if (this._canvas.height !== size.y) this._canvas.height = size.y
    L.DomUtil.setPosition(
      this._canvas,
      map.containerPointToLayerPoint([0, 0]),
    )
  }

  setData(pois: DemoPoi[]) {
    this._pois.clear()
    pois.forEach(p => this._pois.set(p.id, p))
  }

  setMarkers(markers: MarkerState[]) {
    this._markers = markers
  }

  redraw(map: LeafletMap) {
    this._redraw.call(this, { target: map })
  }

  hitTest(map: LeafletMap, point: L.Point): DemoPoi | null {
    let closest: { poi: DemoPoi; distance: number; excluded: boolean } | null = null

    for (const marker of this._markers) {
      const poi = this._pois.get(marker.id)
      if (!poi || marker.opacity <= 0) continue

      const markerPoint = map.latLngToContainerPoint([poi.lat, poi.lng])
      const radius = Math.max(9, Math.min(22, 8 + marker.prize * 14))
      const distance = markerPoint.distanceTo(point)
      const excluded = marker.filterReason !== undefined

      if (
        distance <= radius
        && (
          !closest
          || (excluded && !closest.excluded)
          || (excluded === closest.excluded && distance < closest.distance)
        )
      ) {
        closest = { poi, distance, excluded }
      }
    }

    return closest?.poi ?? null
  }

  private _redraw(e: { target: LeafletMap }) {
    const map = e.target
    const canvas = this._canvas
    if (!canvas) return
    this._resize(map)

    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.clearRect(0, 0, canvas.width, canvas.height)

    const mapOrigin = map.containerPointToLayerPoint([0, 0])

    // Excluded markers are painted last so a duplicate at the same coordinates
    // remains visible and clickable above its canonical survivor.
    const orderedMarkers = [...this._markers].sort(
      (a, b) => Number(Boolean(a.filterReason)) - Number(Boolean(b.filterReason)),
    )
    for (const m of orderedMarkers) {
      const poi = this._pois.get(m.id)
      if (!poi) continue
      const pt = map.latLngToLayerPoint([poi.lat, poi.lng])
      const x = pt.x - mapOrigin.x
      const y = pt.y - mapOrigin.y

      const baseRadius = Math.max(4, Math.min(18, 4 + m.prize * 14))
      const r = m.routePosition ? Math.max(11, baseRadius) : baseRadius
      const alpha = m.opacity

      if (m.filterReason === 'radius') {
        ctx.globalAlpha = alpha
        ctx.fillStyle = FILTER_COLORS.radius
      } else if (m.filterReason === 'family') {
        ctx.globalAlpha = alpha
        ctx.fillStyle = FILTER_COLORS.family
      } else if (m.filterReason === 'duplicate') {
        ctx.globalAlpha = alpha
        ctx.fillStyle = FILTER_COLORS.duplicate
      } else if (m.ghost) {
        ctx.globalAlpha = alpha * 0.35
        ctx.fillStyle = '#94A3B8'
      } else if (m.isFood) {
        ctx.globalAlpha = alpha
        ctx.fillStyle = FOOD_COLOR
      } else if (m.dayColor) {
        ctx.globalAlpha = alpha
        ctx.fillStyle = m.dayColor
      } else if (m.highlight) {
        ctx.globalAlpha = alpha
        ctx.fillStyle = '#EC4899'
      } else {
        ctx.globalAlpha = alpha
        const t = m.prize
        ctx.fillStyle = `rgb(${Math.round(129 - t * 50)}, ${Math.round(140 - t * 70)}, ${Math.round(248 - t * 19)})`
      }

      ctx.beginPath()
      if (m.dayIdx !== undefined && m.dayIdx % DAY_COLORS.length === 1) {
        const side = r * 1.65
        ctx.rect(x - side / 2, y - side / 2, side, side)
      } else if (m.dayIdx !== undefined && m.dayIdx % DAY_COLORS.length === 2) {
        ctx.moveTo(x, y - r)
        ctx.lineTo(x + r, y)
        ctx.lineTo(x, y + r)
        ctx.lineTo(x - r, y)
        ctx.closePath()
      } else {
        ctx.arc(x, y, r, 0, Math.PI * 2)
      }
      ctx.fill()

      if (m.filterReason) {
        ctx.globalAlpha = 1
        ctx.strokeStyle = FILTER_OUTLINES[m.filterReason]
        ctx.lineWidth = 2.5
        ctx.stroke()
        ctx.strokeStyle = FILTER_FOREGROUNDS[m.filterReason]
        ctx.lineWidth = 2.5
        ctx.beginPath()
        ctx.moveTo(x - r * 0.45, y - r * 0.45)
        ctx.lineTo(x + r * 0.45, y + r * 0.45)
        ctx.moveTo(x + r * 0.45, y - r * 0.45)
        ctx.lineTo(x - r * 0.45, y + r * 0.45)
        ctx.stroke()
      }

      // A light keyline keeps dense clusters readable over the map tiles.
      if (m.dayColor && !m.ghost) {
        ctx.globalAlpha = alpha
        ctx.strokeStyle = '#FFFFFF'
        ctx.lineWidth = 2
        ctx.stroke()
      }

      // Landmark ring
      const poi_ = this._pois.get(m.id)
      if (poi_?.landmark && !m.ghost && !m.filterReason) {
        ctx.globalAlpha = alpha * 0.75
        ctx.strokeStyle = '#312E81'
        ctx.lineWidth = 1.75
        ctx.beginPath()
        ctx.arc(x, y, r + 2.5, 0, Math.PI * 2)
        ctx.stroke()
      }

      if (m.routePosition) {
        ctx.globalAlpha = alpha
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.font = `800 ${m.routePosition >= 10 ? 9 : 11}px Inter, sans-serif`
        ctx.lineWidth = 3
        ctx.strokeStyle = 'rgba(15, 23, 42, 0.55)'
        ctx.strokeText(String(m.routePosition), x, y + 0.5)
        ctx.fillStyle = '#FFFFFF'
        ctx.fillText(String(m.routePosition), x, y + 0.5)
      }

      ctx.globalAlpha = 1
    }
  }
}

// Internal component that gets the map instance
function CanvasOverlay({
  pois,
  clusters,
  filtering,
  filterPhase,
  routeOrders,
  softenFoodMarkers,
  selectedIds,
  poiColors,
  excludedIds,
  onPoiClick,
  layerRef,
}: {
  pois: DemoPoi[]
  clusters?: Record<string, number>
  filtering?: DemoPreprocessing
  filterPhase?: number
  routeOrders?: string[][]
  softenFoodMarkers?: boolean
  selectedIds?: Set<string>
  poiColors?: Record<string, string>
  excludedIds?: Set<string>
  onPoiClick: (poi: DemoPoi) => void
  layerRef: React.MutableRefObject<CanvasPOILayer | null>
}) {
  const map = useMap()

  useEffect(() => {
    const layer = new CanvasPOILayer()
    layerRef.current = layer
    layer.addTo(map)
    layer.setData(pois)

    const initial: MarkerState[] = pois.map(p => ({
      id: p.id,
      lat: p.lat,
      lng: p.lng,
      prize: p.prize,
      opacity: 1,
      isFood: p.isFood ?? p.category === 'food',
      highlight: false,
      ghost: false,
    }))
    layer.setMarkers(initial)
    layer.redraw(map)

    return () => {
      layer.remove()
      layerRef.current = null
    }
  }, [map, pois, layerRef])

  // Update colors when clusters change
  useEffect(() => {
    if (!layerRef.current) return
    const layer = layerRef.current
    const routePositions = new Map(
      (routeOrders ?? []).flatMap(route => (
        route.map((poiId, index) => [poiId, index + 1] as const)
      )),
    )
    layer.setMarkers(
      pois.map(p => {
        const dayIdx = clusters ? clusters[p.id] : undefined
        const isFood = p.isFood ?? p.category === 'food'
        const filterReason = excludedIds?.has(p.id)
          ? 'discarded' as const
          : getFilterReason(p.id, filtering, filterPhase)
        return {
          id: p.id,
          lat: p.lat,
          lng: p.lng,
          prize: p.prize,
          opacity: filterReason ? 0.95 : (softenFoodMarkers && isFood ? 0.28 : 1),
          isFood,
          filterReason,
          dayColor: poiColors?.[p.id]
            ?? (dayIdx !== undefined ? DAY_COLORS[dayIdx % DAY_COLORS.length].main : undefined),
          dayIdx,
          routePosition: routePositions.get(p.id),
          highlight: false,
          ghost: false,
        }
      }),
    )
    layer.redraw(map)
  }, [
    clusters, filtering, filterPhase, map, pois, routeOrders, layerRef,
    softenFoodMarkers, poiColors, excludedIds,
  ])

  // Update opacity for MMR selection
  useEffect(() => {
    if (!layerRef.current || !selectedIds) return
    const layer = layerRef.current
    const routePositions = new Map(
      (routeOrders ?? []).flatMap(route => (
        route.map((poiId, index) => [poiId, index + 1] as const)
      )),
    )
    layer.setMarkers(
      pois.map(p => {
        const dayIdx = clusters ? clusters[p.id] : undefined
        return {
          id: p.id,
          lat: p.lat,
          lng: p.lng,
          prize: p.prize,
          opacity: selectedIds.has(p.id) ? 1 : 0.18,
          isFood: p.isFood ?? p.category === 'food',
          dayColor: poiColors?.[p.id]
            ?? (dayIdx !== undefined
              ? DAY_COLORS[dayIdx % DAY_COLORS.length].main
              : undefined),
          dayIdx,
          routePosition: routePositions.get(p.id),
          highlight: false,
          ghost: false,
        }
      }),
    )
    layer.redraw(map)
  }, [clusters, selectedIds, map, pois, routeOrders, layerRef, poiColors])

  useEffect(() => {
    const handleClick = (event: L.LeafletMouseEvent) => {
      const poi = layerRef.current?.hitTest(map, event.containerPoint)
      if (poi) onPoiClick(poi)
    }
    const handleMouseMove = (event: L.LeafletMouseEvent) => {
      const poi = layerRef.current?.hitTest(map, event.containerPoint)
      map.getContainer().style.cursor = poi ? 'pointer' : ''
    }
    const resetCursor = () => {
      map.getContainer().style.cursor = ''
    }

    map.on('click', handleClick)
    map.on('mousemove', handleMouseMove)
    map.on('mouseout', resetCursor)

    return () => {
      map.off('click', handleClick)
      map.off('mousemove', handleMouseMove)
      map.off('mouseout', resetCursor)
      resetCursor()
    }
  }, [layerRef, map, onPoiClick])

  return null
}

// Route polyline using SVG renderer
function RoutePolyline({ pois, route, dayIdx = 0, legs = [] }: {
  pois: DemoPoi[]
  route: string[]
  dayIdx?: number
  legs?: DemoRouteLeg[]
}) {
  const map = useMap()

  useEffect(() => {
    if (!route.length) return
    const poiMap = new Map(pois.map(p => [p.id, p]))
    const color = DAY_COLORS[dayIdx % DAY_COLORS.length].main
    const legByDestination = new Map(legs.map(leg => [leg.toPoiId, leg]))
    const polylines: L.Polyline[] = []

    route.slice(1).forEach((toPoiId, index) => {
      const fromPoiId = route[index]
      const from = poiMap.get(fromPoiId)
      const to = poiMap.get(toPoiId)
      if (!from || !to) return

      const leg = legByDestination.get(toPoiId)
      const ride = leg?.transport === 'transit' || leg?.transport === 'taxi'
      const travelDelta = (
        leg?.estimatedTravelMinutes != null
          ? leg.travelMinutes - leg.estimatedTravelMinutes
          : undefined
      )
      const comparisonColor = travelDelta == null
        ? undefined
        : travelDelta > 2
          ? '#DC2626'
          : travelDelta > 0.5
            ? '#F59E0B'
            : '#0F766E'
      const polyline = L.polyline(
        [[from.lat, from.lng], [to.lat, to.lng]],
        {
          color: comparisonColor ?? color,
          weight: travelDelta != null && travelDelta > 2 ? 5 : (ride ? 3 : 4),
          opacity: travelDelta != null ? 0.9 : (ride ? 0.68 : 0.82),
          dashArray: ride ? '1 7' : undefined,
          lineCap: 'round',
          lineJoin: 'round',
        },
      )
      if (leg) {
        const label = TRANSPORT_LABELS[leg.transport]
        const comparison = leg.estimatedTravelMinutes != null
          ? (
              ` · Haversine ${Math.round(leg.estimatedTravelMinutes)} min`
              + ` → real ${Math.round(leg.travelMinutes)} min`
              + ` (${travelDelta! >= 0 ? '+' : ''}${travelDelta!.toFixed(1)})`
            )
          : ` · ${Math.round(leg.travelMinutes)} min`
        polyline.bindTooltip(
          `${label.icon} ${label.name}${comparison}`,
          { sticky: true, className: 'route-mode-tooltip' },
        )
      }
      polyline.addTo(map)
      polylines.push(polyline)
    })

    return () => {
      polylines.forEach(polyline => polyline.remove())
    }
  }, [dayIdx, legs, map, pois, route])

  return null
}

const TRANSPORT_LABELS: Record<TransportMode, { icon: string; name: string }> = {
  walking: { icon: '🚶', name: 'Walk' },
  transit: { icon: '🚌', name: 'Transit' },
  taxi: { icon: '🚕', name: 'Taxi' },
}

const CARTO_URL = 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png'
const CARTO_ATTR = '&copy; <a href="https://carto.com/">CARTO</a>'

export default function DemoMap({
  centerLat, centerLng, bounds, pois = [], clusters, filtering, filterPhase,
  softenFoodMarkers, selectedIds, poiColors, excludedIds,
  routePolyline, routePolylines, routeLegs, showRoute, routeDayIdx = 0,
  focusPoiId, focusRequest = 0,
  techMode = false,
  showFoodDescription = true, showLegend = true, minimalPopup = false, prizeParams, onPoiClick,
}: Props) {
  const layerRef = useRef<CanvasPOILayer | null>(null)
  const [selectedPoi, setSelectedPoi] = useState<DemoPoi | null>(null)
  const selectedFilterReason = selectedPoi
    ? (excludedIds?.has(selectedPoi.id)
        ? 'discarded' as const
        : getFilterReason(selectedPoi.id, filtering, filterPhase))
    : undefined

  const handlePoiClick = useCallback((poi: DemoPoi) => {
    setSelectedPoi(poi)
    onPoiClick?.(poi)
  }, [onPoiClick])

  useEffect(() => {
    setSelectedPoi(current => (
      current && pois.some(poi => poi.id === current.id) ? current : null
    ))
  }, [pois])

  // No popup may be open while FocusPoi flies: an open popup's autoPan snaps
  // the map when the offset exceeds the viewport, and keepInView drags it back
  // toward the old POI on landing. Close on takeoff, open on arrival.
  const closePopup = useCallback(() => setSelectedPoi(null), [])
  const openFocusedPopup = useCallback((poi: DemoPoi) => {
    setSelectedPoi(poi)
  }, [])

  const focusedPoi = focusPoiId
    ? pois.find(poi => poi.id === focusPoiId)
    : undefined
  // Legend counts only still-eligible markers: POIs the cleanup animation has
  // already struck out (or externally excluded ones) stop counting, so the
  // numbers converge to the pool the following screens start from.
  const eligiblePois = pois.filter(poi => (
    !excludedIds?.has(poi.id)
    && getFilterReason(poi.id, filtering, filterPhase) === undefined
  ))
  const legendFoodCount = eligiblePois.filter(
    poi => poi.isFood ?? poi.category === 'food',
  ).length
  const visibleRouteLegs = routePolylines?.flatMap(route => route.legs ?? [])
    ?? routeLegs
    ?? []
  const visibleTransportModes = new Set(
    visibleRouteLegs.map(leg => leg.transport),
  )
  const comparesTravelModels = visibleRouteLegs.some(
    leg => leg.estimatedTravelMinutes != null,
  )

  return (
    <MapContainer
      center={[centerLat, centerLng]}
      zoom={13}
      // Fractional zoom lets fitBounds frame a route tightly instead of
      // snapping a whole level out and leaving the map mostly empty.
      zoomSnap={0.25}
      style={{ width: '100%', height: '100%' }}
      zoomControl={false}
    >
      <TileLayer url={CARTO_URL} attribution={CARTO_ATTR} />
      <ZoomControl position="bottomright" />
      {filtering?.radiusM ? (
        <Circle
          center={[centerLat, centerLng]}
          radius={filtering.radiusM}
          pathOptions={{
            color: '#6366F1',
            weight: 2,
            opacity: 0.7,
            fillColor: '#6366F1',
            fillOpacity: 0.035,
            dashArray: '8 7',
          }}
          interactive={false}
        />
      ) : null}
      <CanvasOverlay
        pois={pois}
        clusters={clusters}
        filtering={filtering}
        filterPhase={filterPhase}
        routeOrders={
          showRoute
            ? (
                routePolylines?.map(route => route.route)
                ?? (routePolyline ? [routePolyline] : undefined)
              )
            : undefined
        }
        softenFoodMarkers={softenFoodMarkers}
        selectedIds={selectedIds}
        poiColors={poiColors}
        excludedIds={excludedIds}
        onPoiClick={handlePoiClick}
        layerRef={layerRef}
      />
      {showRoute && (
        routePolylines?.length
          ? routePolylines.map(({ route, dayIdx, legs }) => (
              route.length > 1 && (
                <RoutePolyline
                  key={dayIdx}
                  pois={pois}
                  route={route}
                  dayIdx={dayIdx}
                  legs={legs}
                />
              )
            ))
          : routePolyline && routePolyline.length > 1 && (
              <RoutePolyline
                pois={pois}
                route={routePolyline}
                dayIdx={routeDayIdx}
                legs={routeLegs}
              />
            )
      )}
      {showRoute && visibleTransportModes.size > 0 && (
        <TransportLegend
          modes={visibleTransportModes}
          compareTravelModels={comparesTravelModels}
        />
      )}
      {selectedPoi && (
        <Popup
          position={[selectedPoi.lat, selectedPoi.lng]}
          offset={[0, -8]}
          closeButton={false}
          autoPan
          autoPanPadding={[30, 30]}
          className="demo-poi-popup"
          keepInView
          minWidth={320}
          maxWidth={320}
          eventHandlers={{ remove: () => setSelectedPoi(null) }}
        >
          <PoiDetails
            poi={selectedPoi}
            minimal={minimalPopup}
            exclusionReason={
              selectedFilterReason ? FILTER_LABELS[selectedFilterReason] : undefined
            }
            exclusionColor={
              selectedFilterReason ? FILTER_COLORS[selectedFilterReason] : undefined
            }
            exclusionForeground={
              selectedFilterReason
                ? FILTER_FOREGROUNDS[selectedFilterReason]
                : undefined
            }
            onClose={() => setSelectedPoi(null)}
          />
        </Popup>
      )}
      {showLegend && (
        pois.some(poi => poi.landmark)
        || pois.some(poi => poi.isFood ?? poi.category === 'food')
      ) && (
        <LandmarkLegend
          showLandmark={pois.some(poi => poi.landmark)}
          showFood={pois.some(poi => poi.isFood ?? poi.category === 'food')}
          totalCount={eligiblePois.length}
          foodCount={legendFoodCount}
          showFoodDescription={showFoodDescription}
          techMode={techMode}
          prizeParams={prizeParams}
        />
      )}
      <InvalidateOnResize />
      {bounds && <FitBoundsOnce key={bounds.flat().join(',')} bounds={bounds} />}
      {focusedPoi && (
        <FocusPoi
          poi={focusedPoi}
          request={focusRequest}
          onFlightStart={closePopup}
          onSettled={openFocusedPopup}
        />
      )}
    </MapContainer>
  )
}

function TransportLegend({
  modes,
  compareTravelModels,
}: {
  modes: Set<TransportMode>
  compareTravelModels: boolean
}) {
  return (
    <aside className="transport-map-legend" aria-label="Transport mode legend">
      <div className="transport-map-legend-modes">
        {(['walking', 'transit', 'taxi'] as TransportMode[])
          .filter(mode => modes.has(mode))
          .map(mode => {
            const label = TRANSPORT_LABELS[mode]
            const ride = mode !== 'walking'
            return (
              <div className="transport-map-legend-row" key={mode}>
                <span aria-hidden="true">{label.icon}</span>
                <i className={ride ? 'ride' : 'walk'} aria-hidden="true" />
                <strong>{label.name}</strong>
              </div>
            )
          })}
      </div>
      {compareTravelModels && (
        <div className="travel-model-legend">
          <strong>Real time − Haversine</strong>
          <span><i className="close" />close (≤ 0.5 min)</span>
          <span><i className="slight" />slower (+0.5–2 min)</span>
          <span><i className="slow" />underestimated (&gt; 2 min)</span>
        </div>
      )}
    </aside>
  )
}

function FocusPoi({ poi, request, onFlightStart, onSettled }: {
  poi: DemoPoi
  request: number
  onFlightStart: () => void
  onSettled: (poi: DemoPoi) => void
}) {
  const map = useMap()

  useEffect(() => {
    // A popup must never be open mid-flight (autoPan snaps, keepInView drags
    // the map back), and the new one opens only once the fly lands.
    let settled = false
    const settle = () => {
      if (settled) return
      settled = true
      onSettled(poi)
    }
    onFlightStart()
    map.flyTo(
      [poi.lat, poi.lng],
      Math.max(map.getZoom(), 16),
      { duration: 0.55 },
    )
    // Listen only after flyTo: its internal stop() of a running pan animation
    // fires a synchronous moveend that would open the popup immediately.
    map.once('moveend', settle)
    // Fallback in case the map is already at the target and never moves.
    const timer = window.setTimeout(settle, 800)
    return () => {
      map.off('moveend', settle)
      window.clearTimeout(timer)
    }
  }, [map, poi, request, onFlightStart, onSettled])

  return null
}

function LandmarkLegend({
  showLandmark,
  showFood,
  totalCount,
  foodCount,
  showFoodDescription,
  techMode,
  prizeParams,
}: {
  showLandmark: boolean
  showFood: boolean
  totalCount: number
  foodCount: number
  showFoodDescription: boolean
  techMode: boolean
  prizeParams?: { wSim: number; wPop: number; landmarkBoost: number }
}) {
  return (
    <aside className="landmark-legend" aria-label="Map marker legend">
      {/* Activities and food are counted separately so the numbers stay
          comparable across screens that intentionally hide food markers. */}
      <div className="map-legend-counts">
        <div>
          <strong>{totalCount - foodCount}</strong>
          <span>Activities</span>
        </div>
        {foodCount > 0 && (
          <div>
            <strong>{foodCount}</strong>
            <span>Food</span>
          </div>
        )}
      </div>
      {showLandmark && (
        <div className="map-legend-row">
          <span className="landmark-legend-marker" aria-hidden="true" />
          <div className="landmark-legend-definition">
            <strong>Landmark</strong>
            <span>Globally known place with at least 10,000 Google ratings.</span>
          </div>
        </div>
      )}
      {showFood && (
        <div className="map-legend-row">
          <span className="food-legend-marker" aria-hidden="true" />
          <div className="landmark-legend-definition">
            <strong>Food</strong>
            {showFoodDescription && (
              <span>Not clustered; added later as lunch or dinner.</span>
            )}
          </div>
        </div>
      )}
      <div className="prize-score-hint" aria-label="Circle size and color encode prize score">
        <span className="prize-circles" aria-hidden="true">
          <span className="prize-circle-low" />
          <span className="prize-circle-high" />
        </span>
        <span>Larger = higher prize score</span>
      </div>
      {techMode && showLandmark && (
        <div className="landmark-legend-formula">
          Prize = {prizeParams?.wSim ?? 0.7} × match + {prizeParams?.wPop ?? 0.3} × popularity + {prizeParams?.landmarkBoost ?? 0.15} landmark bonus
        </div>
      )}
    </aside>
  )
}

function formatMinute(minute: number): string {
  const hour = Math.floor(minute / 60)
  const minutes = minute % 60
  return `${String(hour).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
}

function PoiDetails({
  poi,
  minimal = false,
  exclusionReason,
  exclusionColor,
  exclusionForeground,
  onClose,
}: {
  poi: DemoPoi
  /** Hide planner stats/hours — for POIs that carry only ingestion metadata. */
  minimal?: boolean
  exclusionReason?: string
  exclusionColor?: string
  exclusionForeground?: string
  onClose: () => void
}) {
  const openingLabels = poi.opening.map(window => (
    window ? `${formatMinute(window[0])}–${formatMinute(window[1])}` : 'closed'
  ))
  const sameOpeningEveryDay = openingLabels.every(label => label === openingLabels[0])

  const googleMapsUrl = `https://www.google.com/maps/search/${encodeURIComponent(poi.name)}/@${poi.lat},${poi.lng},17z`

  return (
    <article
      className={`poi-popup ${exclusionReason ? 'excluded' : ''}`}
      style={
        exclusionColor
          ? ({
              '--exclusion-color': exclusionColor,
              '--exclusion-foreground': exclusionForeground ?? '#FFFFFF',
            } as CSSProperties)
          : undefined
      }
    >
      <button
        type="button"
        className="poi-popup-close"
        aria-label="Close place details"
        onClick={onClose}
      >
        ×
      </button>
      <div className="poi-popup-category">{poi.category}</div>
      {exclusionReason && (
        <div className="poi-popup-exclusion">
          <strong>Excluded</strong>
          <span>{exclusionReason}</span>
        </div>
      )}
      <h3 className="poi-popup-name">
        {poi.name}
        {poi.landmark && <span className="poi-popup-landmark">Landmark</span>}
      </h3>

      {!minimal && (
        <div className="poi-popup-stats">
          <div>
            <span>Visit</span>
            <strong>{poi.visit_min} min</strong>
          </div>
          <div>
            <span>Popularity</span>
            <strong>{Math.round(poi.popularity * 100)}%</strong>
          </div>
          <div>
            <span>Prize score</span>
            <strong>{poi.prize.toFixed(2)}</strong>
          </div>
        </div>
      )}

      {!minimal && poi.opening.length > 0 && (
        <div className="poi-popup-hours">
          <span>Planner windows (clamped to the day span)</span>
          <div>
            {sameOpeningEveryDay ? (
              <span>Days 1–{poi.opening.length}: {openingLabels[0]}</span>
            ) : (
              openingLabels.map((label, dayIdx) => (
                <span key={dayIdx}>Day {dayIdx + 1}: {label}</span>
              ))
            )}
          </div>
        </div>
      )}

      <a
        href={googleMapsUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-center justify-center gap-1.5 text-xs font-semibold !text-white rounded-xl py-2 mt-3 transition-opacity active:opacity-80 bg-indigo-500"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>
          <circle cx="12" cy="10" r="3"/>
        </svg>
        Open in Maps
      </a>
    </article>
  )
}

function FitBoundsOnce({ bounds }: { bounds: [[number, number], [number, number]] }) {
  const map = useMap()
  const fittedRef = useRef(false)
  useEffect(() => {
    if (fittedRef.current) return
    fittedRef.current = true
    // The step layouts show/hide bottom panels, so the container may have
    // resized since Leaflet last measured it — refresh before fitting or the
    // view centers on the stale size.
    map.invalidateSize()
    map.fitBounds(bounds, { padding: [30, 30] })
  }, [map, bounds])
  return null
}

// Keeps Leaflet's cached size in sync when the surrounding flex layout
// changes (bottom lane board appearing, panel collapse), which Leaflet only
// detects on window resize by itself.
function InvalidateOnResize() {
  const map = useMap()
  useEffect(() => {
    const observer = new ResizeObserver(() => map.invalidateSize())
    observer.observe(map.getContainer())
    return () => observer.disconnect()
  }, [map])
  return null
}
