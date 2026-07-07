import { Fragment, useMemo } from 'react'
import { useDemoStore } from '../useDemoStore'
import DemoMap from '../components/DemoMap'
import type { DemoPoi, PreferenceVector } from '../types'

// One color per travel_category (the classifier's closed vocabulary).
const CATEGORY_COLORS: Record<string, string> = {
  culture: '#6366F1',
  nature: '#16A34A',
  food: '#0F766E',
  adventure: '#D97706',
  nightlife: '#7C3AED',
  relax: '#0EA5E9',
  family: '#BE185D',
}
const UNCLASSIFIED_COLOR = '#94A3B8'

const EMPTY_VECTOR: PreferenceVector = {
  nature: 0, culture: 0, food: 0, adventure: 0,
  nightlife: 0, relax: 0, family_friendly: 0,
}

// Marker size from review volume: log10 scale so a 100k-review landmark
// reads large without flattening everything else.
const sizeFor = (ratings: number | null | undefined) =>
  Math.max(0.15, Math.min(1, Math.log10((ratings ?? 0) + 1) / 5))

const CAPTIONS = [
  {
    simple: 'Everything Google knows about {city} is fetched — monuments and museums, but also pharmacies, gyms, and offices. The pipeline starts from this raw pool.',
    tech: 'pipeline.py step 1: Places Nearby Search over a city grid (+ optional Text Search supplement) → upsert into the pois table. {fetched} places fetched.',
  },
  {
    simple: 'An LLM reads each place and decides: is this worth a tourist\'s time? Hotels, supermarkets, and service businesses are discarded — and every kept place is also flagged as suitable for children or not.',
    tech: 'tourism_validator.py: LLM batch validation → is_touristic, visit type, visit duration, suitable_for_children. {kept} kept / {discarded} discarded (map shows the {sample} most-reviewed rejections); {withDuration}/{kept} with a suggested visit duration.',
  },
  {
    simple: 'Each surviving place gets a category and a 7-dimension experience profile — the same dimensions used to describe the traveler.',
    tech: 'classifier.py: LLM → travel_category + feature vector [nature, culture, food, adventure, nightlife, relax, family_friendly] + confidence. Inter-rater agreement (aggregated): κ=0.953, n=1049.',
  },
  {
    simple: 'Finally, official opening hours are attached — the time windows the planners must respect. Faded places have no data.',
    tech: 'hours_fetcher.py: Places Details → opening_hours JSON. {withHours}/{kept} covered; missing data is treated as always open by both planners.',
  },
  {
    simple: 'Before planning starts, the production candidate query keeps only places with enough signal to rank and schedule reliably.',
    tech: 'candidate_query.py: fetch_candidate_pois applies status, rating, review-count, vector, and Google type filters before the planner sees the city.',
  },
]

const PLANNING_REASON_LABELS: Record<string, string> = {
  under_200_reviews: '<200 reviews',
  business_status_missing_or_closed: 'status missing/closed',
  excluded_google_type: 'blocked type',
  rating_missing_or_under_3_5: 'rating missing/<3.5',
  missing_vector_or_classified_at: 'missing profile',
  confidence_missing_or_failed: 'confidence missing/failed',
  high_popularity_type_under_5000_reviews: 'stadium/race track <5000 reviews',
  other: 'other',
}

const PLANNING_RULE_CHIPS = ['status', 'rating', 'reviews', 'profile', 'type']

function FunnelPanel({ step }: { step: number }) {
  const ingestion = useDemoStore(s => s.ingestion)
  if (!ingestion) return null
  const { funnel } = ingestion
  const rows = [
    {
      label: 'Google Places fetch',
      value: `${funnel.fetched}`,
      color: '#64748B',
      active: true,
    },
    {
      label: 'Tourism validation',
      value: `${funnel.tourism.kept} kept · −${funnel.tourism.discarded}`,
      color: '#DC2626',
      active: step >= 1,
    },
    {
      label: 'LLM classification',
      value: `${funnel.classified.total} classified`,
      color: '#6366F1',
      active: step >= 2,
    },
    {
      label: 'Opening hours',
      value: `${funnel.hours.withHours}/${funnel.tourism.kept} with hours`,
      color: '#0F766E',
      active: step >= 3,
    },
    ...(funnel.planning ? [
      {
        label: 'Candidate query',
        value: `${funnel.planning.candidateQuery} pass`,
        color: '#D97706',
        active: step >= 4,
      },
    ] : []),
  ]
  return (
    <div className="filter-summary">
      <div className="filter-summary-title">Ingestion funnel</div>
      {rows.map((row, index) => (
        <div
          key={row.label}
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 8,
            padding: '5px 0',
            fontSize: '0.95rem',
            opacity: row.active ? 1 : 0.35,
            transition: 'opacity 0.4s ease',
          }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{
              display: 'inline-flex',
              width: 16,
              height: 16,
              borderRadius: 8,
              background: row.active ? row.color : '#cbd5e1',
              color: '#fff',
              fontSize: 10,
              fontWeight: 700,
              alignItems: 'center',
              justifyContent: 'center',
            }}>
              {index + 1}
            </span>
            {row.label}
          </span>
          <strong style={{ fontVariantNumeric: 'tabular-nums' }}>
            {row.active ? row.value : '…'}
          </strong>
        </div>
      ))}
    </div>
  )
}

export default function Screen0Ingestion() {
  const {
    stepIdx, city, techMode, ingestion, ingestionLoading, ingestionError,
  } = useDemoStore()

  const keptPois: DemoPoi[] = useMemo(() => (ingestion?.pois ?? []).map(p => ({
    id: p.id,
    name: p.name,
    lat: p.lat,
    lng: p.lng,
    category: p.category ?? 'unclassified',
    isFood: false,
    vector: p.vector,
    popularity: 0,
    landmark: false,
    visit_min: 0,
    opening: [],
    prize: sizeFor(p.ratingsTotal),
  })), [ingestion])

  const discardedPois: DemoPoi[] = useMemo(
    () => (ingestion?.discardedSample ?? []).map(p => ({
      id: p.id,
      name: p.name,
      lat: p.lat,
      lng: p.lng,
      category: p.primaryType?.replace(/_/g, ' ') ?? 'place',
      isFood: false,
      vector: EMPTY_VECTOR,
      popularity: 0,
      landmark: false,
      visit_min: 0,
      opening: [],
      prize: sizeFor(p.ratingsTotal),
    })),
    [ingestion],
  )

  const discardedIds = useMemo(
    () => new Set(discardedPois.map(p => p.id)),
    [discardedPois],
  )
  const categoryColors = useMemo(() => {
    const colors: Record<string, string> = {}
    for (const p of ingestion?.pois ?? []) {
      colors[p.id] = p.category
        ? (CATEGORY_COLORS[p.category] ?? UNCLASSIFIED_COLOR)
        : UNCLASSIFIED_COLOR
    }
    return colors
  }, [ingestion])
  const withHoursIds = useMemo(
    () => new Set((ingestion?.pois ?? []).filter(p => p.hasHours).map(p => p.id)),
    [ingestion],
  )
  // Kept POIs the validator flagged as unsuitable for children: the family-mode
  // candidate query excludes exactly these.
  const notForKids = useMemo(
    () => (ingestion?.pois ?? [])
      .filter(p => p.suitableForChildren === false)
      .sort((a, b) => (b.ratingsTotal ?? 0) - (a.ratingsTotal ?? 0)),
    [ingestion],
  )
  const planningReasons = useMemo(() => {
    const entries = Object.entries(ingestion?.funnel.planning?.candidateQueryReasons ?? {})
      .slice(0, 4)
    const max = Math.max(1, ...entries.map(([, count]) => count))
    return entries.map(([reason, count]) => ({
      reason,
      count,
      width: `${Math.max(8, (count / max) * 100)}%`,
    }))
  }, [ingestion])

  const mapPois = stepIdx <= 1 ? [...keptPois, ...discardedPois] : keptPois

  const funnel = ingestion?.funnel
  const caption = CAPTIONS[stepIdx]
  const simpleText = caption?.simple.replace('{city}', ingestion?.city.name ?? city)
  const techText = caption?.tech
    ?.replace('{fetched}', String(funnel?.fetched ?? 0))
    ?.replace('{kept}', String(funnel?.tourism.kept ?? 0))
    ?.replace('{discarded}', String(funnel?.tourism.discarded ?? 0))
    ?.replace('{sample}', String(ingestion?.discardedSample.length ?? 0))
    ?.replace('{withDuration}', String(funnel?.tourism.withDuration ?? 0))
    ?.replace('{withHours}', String(funnel?.hours.withHours ?? 0))
    ?.replace('{kept}', String(funnel?.tourism.kept ?? 0))

  if (ingestionError) {
    return (
      <div className="demo-error" role="alert">
        <strong>Could not load the ingestion data for {city}.</strong>
        <span>{ingestionError}</span>
      </div>
    )
  }

  if (!ingestion || ingestionLoading) {
    return <div className="demo-loading"><div className="spinner" />Loading ingestion data…</div>
  }

  return (
    <div className="screen-layout">
      {/* Map */}
      <div className="demo-map-wrap">
        <DemoMap
          centerLat={ingestion.city.center[0]}
          centerLng={ingestion.city.center[1]}
          bounds={ingestion.city.bounds}
          pois={mapPois}
          excludedIds={stepIdx === 1 ? discardedIds : undefined}
          poiColors={stepIdx >= 2 ? categoryColors : undefined}
          selectedIds={stepIdx === 3 ? withHoursIds : undefined}
          techMode={techMode}
          minimalPopup
          showFoodDescription={false}
        />
      </div>

      {/* Side panel */}
      <div className="demo-side-panel">
        <div style={{ fontSize: '0.9rem', fontWeight: 700, color: '#6366F1', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          How the system learns a city
        </div>

        <p className="demo-caption">{simpleText}</p>
        {techMode && techText && <div className="tech-overlay">{techText}</div>}

        <FunnelPanel step={stepIdx} />

        {/* Step 2: most-reviewed rejections make the point concrete */}
        {stepIdx === 1 && (ingestion?.discardedSample.length ?? 0) > 0 && (
          <div>
            <div style={{ fontSize: '0.93rem', color: '#888', marginBottom: 6 }}>
              Famous, yet not tourism — top rejections
            </div>
            {ingestion!.discardedSample.slice(0, 6).map(p => (
              <div key={p.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: '0.93rem', marginBottom: 3 }}>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</span>
                <span style={{ color: '#aaa', flexShrink: 0 }}>
                  {p.primaryType?.replace(/_/g, ' ') ?? 'place'}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Step 2: child-suitability flag decided by the same LLM pass.
            The extra truthiness check keeps the screen alive against a live
            backend still serving the v1 payload during a deploy window. */}
        {stepIdx === 1 && funnel?.tourism.children && (
          <div>
            <div style={{ fontSize: '0.93rem', color: '#888', marginBottom: 6 }}>
              Also decided here: suitable for children?
            </div>
            <div style={{ fontSize: '0.95rem', marginBottom: 6, fontVariantNumeric: 'tabular-nums' }}>
              <strong>{funnel.tourism.children.suitable}</strong> suitable
              {' · '}
              <strong style={{ color: '#DC2626' }}>{funnel.tourism.children.notSuitable}</strong> not for kids
              {' · '}
              <strong style={{ color: '#94A3B8' }}>{funnel.tourism.children.unknown}</strong> unknown
            </div>
            {notForKids.slice(0, 4).map(p => (
              <div key={p.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: '0.93rem', marginBottom: 3 }}>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</span>
                <span style={{ color: '#aaa', flexShrink: 0 }}>
                  {p.primaryType?.replace(/_/g, ' ') ?? 'place'}
                </span>
              </div>
            ))}
            <div style={{ fontSize: '0.9rem', color: '#aaa', marginTop: 6 }}>
              Family trips exclude these at the candidate query, before any planning starts.
            </div>
          </div>
        )}

        {/* Step 3: category legend with counts */}
        {stepIdx === 2 && ingestion && (
          <div>
            <div style={{ fontSize: '0.93rem', color: '#888', marginBottom: 6 }}>
              Categories assigned by the classifier
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {Object.entries(ingestion.categories).map(([category, count]) => (
                <span
                  key={category}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    fontSize: '1rem',
                    padding: '4px 10px',
                    borderRadius: 14,
                    background: '#f1f5f9',
                  }}
                >
                  <span style={{
                    width: 11,
                    height: 11,
                    borderRadius: '50%',
                    background: CATEGORY_COLORS[category] ?? UNCLASSIFIED_COLOR,
                  }} />
                  {category} <strong>{count}</strong>
                </span>
              ))}
            </div>
            {techMode && funnel && (
              <div style={{ fontSize: '0.9rem', color: '#888', marginTop: 8 }}>
                Confidence: {funnel.classified.high} high · {funnel.classified.medium} medium · {funnel.classified.failed} failed
              </div>
            )}
          </div>
        )}

        {/* Step 4: hours coverage */}
        {stepIdx === 3 && funnel && (
          <div>
            <div style={{ fontSize: '0.93rem', color: '#888', marginBottom: 4 }}>
              Opening-hours coverage
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ flex: 1, height: 10, background: '#e8e4dc', borderRadius: 5, overflow: 'hidden' }}>
                <div style={{
                  height: '100%',
                  width: `${funnel.tourism.kept ? (funnel.hours.withHours / funnel.tourism.kept) * 100 : 0}%`,
                  background: '#0F766E',
                  borderRadius: 5,
                  transition: 'width 0.6s ease',
                }} />
              </div>
              <span style={{ fontSize: '0.95rem', fontWeight: 700, color: '#0F766E', fontVariantNumeric: 'tabular-nums' }}>
                {funnel.tourism.kept
                  ? Math.round((funnel.hours.withHours / funnel.tourism.kept) * 100)
                  : 0}%
              </span>
            </div>
            <div style={{ fontSize: '0.9rem', color: '#aaa', marginTop: 6 }}>
              Places without data are treated as always open by the planners.
            </div>
          </div>
        )}

        {/* Step 5: candidate query */}
        {stepIdx === 4 && funnel?.planning && (
          <div>
            <div style={{
              display: 'flex',
              alignItems: 'baseline',
              justifyContent: 'space-between',
              gap: 8,
              marginBottom: 8,
            }}>
              <div style={{ fontSize: '0.93rem', color: '#888' }}>
                Candidate query
              </div>
              {techMode && (
                <code style={{ fontSize: '0.78rem', color: '#999' }}>
                  {funnel.planning.source}
                </code>
              )}
            </div>
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 22px 1fr',
              alignItems: 'stretch',
              gap: 6,
              marginBottom: 10,
            }}>
              {[
                { label: 'Validated', value: funnel.planning.input, color: '#6366F1' },
                { label: 'Query pass', value: funnel.planning.candidateQuery, color: '#D97706' },
              ].map(({ label, value, color }, index) => (
                <Fragment key={label}>
                  <div style={{
                    minWidth: 0,
                    padding: '8px 10px',
                    borderRadius: 8,
                    background: '#f8fafc',
                    border: '1px solid #e2e8f0',
                  }}>
                    <div style={{ fontSize: '0.74rem', color: '#888', lineHeight: 1.1 }}>
                      {label}
                    </div>
                    <strong style={{ color, fontSize: '1.18rem', lineHeight: 1.25, fontVariantNumeric: 'tabular-nums' }}>
                      {value}
                    </strong>
                  </div>
                  {index < 1 && (
                    <div key={`${label}-arrow`} style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: '#bbb',
                      fontWeight: 700,
                    }}>
                      →
                    </div>
                  )}
                </Fragment>
              ))}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: 10 }}>
              {PLANNING_RULE_CHIPS.map(rule => (
                <span key={rule} style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  borderRadius: 999,
                  padding: '3px 8px',
                  background: '#fff7ed',
                  color: '#9a3412',
                  fontSize: '0.78rem',
                  fontWeight: 700,
                }}>
                  {rule}
                </span>
              ))}
            </div>
            <div style={{ fontSize: '0.88rem', color: '#888', marginBottom: 6 }}>
              Removed by query: <strong>{funnel.planning.removedByCandidateQuery}</strong>
            </div>
            <div style={{ display: 'grid', gap: 5 }}>
              {planningReasons.map(({ reason, count, width }) => (
                <div key={reason} style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 8, alignItems: 'center' }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: '0.86rem', lineHeight: 1.15 }}>
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {PLANNING_REASON_LABELS[reason] ?? reason.replace(/_/g, ' ')}
                      </span>
                    </div>
                    <div style={{ height: 5, background: '#f1f5f9', borderRadius: 999, overflow: 'hidden', marginTop: 3 }}>
                      <div style={{ width, height: '100%', background: '#D97706', borderRadius: 999 }} />
                    </div>
                  </div>
                  <strong style={{ fontVariantNumeric: 'tabular-nums', fontSize: '0.9rem' }}>{count}</strong>
                </div>
              ))}
            </div>
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: 6,
              marginTop: 10,
            }}>
              <div style={{
                padding: '8px 10px',
                borderRadius: 8,
                background: '#f0fdf4',
                color: '#166534',
              }}>
                <div style={{ fontSize: '0.74rem', lineHeight: 1.1 }}>Activity pool</div>
                <strong style={{ fontSize: '1.08rem', fontVariantNumeric: 'tabular-nums' }}>
                  {funnel.planning.activity}
                </strong>
              </div>
              <div style={{
                padding: '8px 10px',
                borderRadius: 8,
                background: '#f0fdfa',
                color: '#0f766e',
              }}>
                <div style={{ fontSize: '0.74rem', lineHeight: 1.1 }}>Food pool</div>
                <strong style={{ fontSize: '1.08rem', fontVariantNumeric: 'tabular-nums' }}>
                  {funnel.planning.food}
                </strong>
              </div>
            </div>
            {techMode && (
              <div style={{ fontSize: '0.82rem', color: '#aaa', marginTop: 6 }}>
                Rules: {funnel.planning.candidateQueryRules.join(' · ')}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
