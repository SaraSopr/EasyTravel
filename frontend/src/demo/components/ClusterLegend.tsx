import { DAY_COLORS } from '../types'

interface Props {
  count: number
}

export default function ClusterLegend({ count }: Props) {
  return (
    <div className="cluster-legend" aria-label="Cluster legend">
      <div className="cluster-legend-title">Day zones</div>
      <div className="cluster-legend-items">
        {Array.from({ length: count }, (_, i) => (
          <div className="cluster-legend-item" key={i}>
            <span
              className={`cluster-swatch cluster-swatch-${i % DAY_COLORS.length}`}
              style={{ background: DAY_COLORS[i % DAY_COLORS.length].main }}
              aria-hidden="true"
            />
            <span>Day {i + 1}</span>
          </div>
        ))}
        <div className="cluster-legend-item">
          <span
            className="cluster-swatch"
            style={{ background: '#94A3B8' }}
            aria-hidden="true"
          />
          <span>Food (added later)</span>
        </div>
      </div>
      <div className="cluster-legend-hint">Color and shape identify each cluster</div>
    </div>
  )
}
