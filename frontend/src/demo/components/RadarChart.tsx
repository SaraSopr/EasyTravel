import { useEffect, useRef, useState } from 'react'
import gsap from 'gsap'
import type { PreferenceVector } from '../types'

const DIMS = ['nature', 'culture', 'food', 'adventure', 'nightlife', 'relax', 'family_friendly'] as const
const DIM_LABELS: Record<(typeof DIMS)[number], string> = {
  nature: 'Nature', culture: 'Culture', food: 'Food',
  adventure: 'Adventure', nightlife: 'Nightlife', relax: 'Relax',
  family_friendly: 'Family',
}

interface Props {
  vector: PreferenceVector
  overlay?: PreferenceVector
  size?: number
  color?: string
  overlayColor?: string
  animate?: boolean
  label?: string
  expandable?: boolean
  showValues?: boolean
}

function polarToXY(angle: number, r: number, cx: number, cy: number) {
  return {
    x: cx + r * Math.cos(angle - Math.PI / 2),
    y: cy + r * Math.sin(angle - Math.PI / 2),
  }
}

function vecToPath(
  vec: PreferenceVector,
  keys: readonly (keyof PreferenceVector)[],
  cx: number, cy: number, maxR: number,
): string {
  const pts = keys.map((k, i) => {
    const angle = (2 * Math.PI * i) / keys.length
    const r = (vec[k] ?? 0) * maxR
    return polarToXY(angle, r, cx, cy)
  })
  return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ') + ' Z'
}

export default function RadarChart({
  vector,
  overlay,
  size = 160,
  color = '#6366F1',
  overlayColor = '#EC4899',
  animate = false,
  label,
  expandable = false,
  showValues = false,
}: Props) {
  const [expanded, setExpanded] = useState(false)
  const pathRef = useRef<SVGPathElement>(null)
  const overlayRef = useRef<SVGPathElement>(null)
  const cx = size / 2
  const cy = size / 2
  const maxR = size / 2 - 20
  const N = DIMS.length

  const mainPath = vecToPath(vector, DIMS, cx, cy, maxR)
  const overlayPath = overlay
    ? vecToPath(overlay, DIMS, cx, cy, maxR)
    : null

  useEffect(() => {
    if (!animate || !pathRef.current) return
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced) return
    gsap.from(pathRef.current, {
      scale: 0,
      transformOrigin: `${cx}px ${cy}px`,
      duration: 0.6,
      ease: 'back.out(1.4)',
    })
  }, [animate, cx, cy])

  useEffect(() => {
    if (!expanded) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setExpanded(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [expanded])

  // Grid levels
  const levels = [0.25, 0.5, 0.75, 1.0]

  const chart = (
    <div className="radar-wrap">
      {label && <div className="radar-label">{label}</div>}
      <svg
        className="radar-chart"
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={DIMS.map(dim => `${DIM_LABELS[dim]} ${vector[dim].toFixed(1)}`).join(', ')}
      >
        {/* Grid */}
        {levels.map((lvl) => (
          <polygon
            key={lvl}
            points={DIMS.map((_, i) => {
              const angle = (2 * Math.PI * i) / N
              const { x, y } = polarToXY(angle, lvl * maxR, cx, cy)
              return `${x},${y}`
            }).join(' ')}
            fill="none"
            stroke="#e0dcd4"
            strokeWidth="1"
          />
        ))}

        {/* Axes */}
        {DIMS.map((_, i) => {
          const angle = (2 * Math.PI * i) / N
          const { x, y } = polarToXY(angle, maxR, cx, cy)
          return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="#e0dcd4" strokeWidth="1" />
        })}

        {/* Main polygon */}
        <path
          ref={pathRef}
          d={mainPath}
          fill={color}
          fillOpacity={0.25}
          stroke={color}
          strokeWidth={2}
        />

        {/* Overlay polygon */}
        {overlayPath && (
          <path
            ref={overlayRef}
            d={overlayPath}
            fill={overlayColor}
            fillOpacity={0.2}
            stroke={overlayColor}
            strokeWidth={1.5}
            strokeDasharray="4 2"
          />
        )}

        {/* Axis labels */}
        {DIMS.map((dim, i) => {
          const angle = (2 * Math.PI * i) / N
          const { x, y } = polarToXY(angle, maxR + 12, cx, cy)
          return (
            <text
              key={dim}
              x={x}
              y={y}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={9}
              fill="#666"
              fontWeight={600}
            >
              {DIM_LABELS[dim]}
            </text>
          )
        })}
      </svg>
      {showValues && (
        <dl className="radar-values">
          {DIMS.map(dim => (
            <div className="radar-value" key={dim}>
              <dt>{DIM_LABELS[dim]}</dt>
              <dd>{vector[dim].toFixed(1)}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )

  if (!expandable) return chart

  return (
    <>
      <button
        type="button"
        className="radar-expand-trigger"
        onClick={() => setExpanded(true)}
        aria-label={`Enlarge ${label ?? 'preference'} chart`}
        aria-haspopup="dialog"
      >
        {chart}
        <span className="radar-expand-hint" aria-hidden="true">↗ Enlarge</span>
      </button>

      {expanded && (
        <div
          className="radar-modal-backdrop"
          role="presentation"
          onMouseDown={event => {
            if (event.target === event.currentTarget) setExpanded(false)
          }}
        >
          <section
            className="radar-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="radar-modal-title"
          >
            <button
              type="button"
              className="radar-modal-close"
              onClick={() => setExpanded(false)}
              aria-label="Close enlarged chart"
              autoFocus
            >
              ×
            </button>
            <div className="radar-modal-heading">
              <span>Preference profile</span>
              <h2 id="radar-modal-title">{label ?? 'Traveler preferences'}</h2>
              <p>Values range from 0.0 (low interest) to 1.0 (high interest).</p>
            </div>
            <RadarChart
              vector={vector}
              overlay={overlay}
              size={360}
              color={color}
              overlayColor={overlayColor}
              animate
              showValues
            />
          </section>
        </div>
      )}
    </>
  )
}
