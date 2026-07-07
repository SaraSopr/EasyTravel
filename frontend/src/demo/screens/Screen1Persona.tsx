import { useDemoStore } from '../useDemoStore'
import RadarChart from '../components/RadarChart'
import DemoMap from '../components/DemoMap'

export default function Screen1Persona() {
  const { city, personaId, personas, setPersona, trace, techMode } = useDemoStore()

  const selected = personas.find(p => p.id === personaId) ?? personas[0]
  const pois = trace?.pois ?? []
  const bounds = trace?.city.bounds

  const wSim = trace?.params?.wSim ?? 0.7
  const wPop = trace?.params?.wPop ?? 0.3
  const landmarkBoost = trace?.params?.landmarkBoost ?? 0.15

  const caption = `Every place the system knows in ${trace?.city.name ?? city}, already weighted by how much they match this traveler.`
  const techCaption = `Prize ρᵢ = ${wSim}·cos(vᵢ, u) + ${wPop}·popularity + ${landmarkBoost}·landmark. Persona vector: [${Object.values(selected.vector).map(v => v.toFixed(1)).join(', ')}].`

  if (pois.length === 0) {
    return (
      <div className="demo-loading">
        <div className="spinner" />
        Loading map…
      </div>
    )
  }

  return (
    <div className="screen-layout">
      {/* Map */}
      <div className="demo-map-wrap">
        <DemoMap
          centerLat={trace?.city.center[0] ?? 41.9}
          centerLng={trace?.city.center[1] ?? 12.48}
          bounds={bounds}
          pois={pois}
          techMode={techMode}
          showFoodDescription={false}
          prizeParams={trace?.params}
        />
      </div>

      {/* Side panel */}
      <div className="demo-side-panel">
        <div>
          <div style={{ fontSize: '0.9rem', fontWeight: 700, color: '#6366F1', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
            Who is traveling?
          </div>
          <div className="persona-grid">
            {personas.map(p => (
              <div
                key={p.id}
                className={`persona-card ${personaId === p.id ? 'selected' : ''}`}
                onClick={() => setPersona(p.id as typeof personaId)}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{ flex: 1 }}>
                    <div className="persona-name">{p.label}</div>
                    <div className="persona-blurb">{p.blurb}</div>
                  </div>
                  <RadarChart
                    vector={p.vector}
                    size={70}
                    color={personaId === p.id ? '#6366F1' : '#aaa'}
                    animate={personaId === p.id}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Pinned radar for selected persona */}
        <div style={{ borderTop: '1px solid #e8e4dc', paddingTop: 14 }}>
          <RadarChart
            vector={selected.vector}
            size={160}
            animate
            label={selected.label}
            expandable
          />
        </div>

        {/* Caption */}
        <p className="demo-caption">{caption}</p>

        {techMode && (
          <div className="tech-overlay">{techCaption}</div>
        )}
      </div>
    </div>
  )
}
