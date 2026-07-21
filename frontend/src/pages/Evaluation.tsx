import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Loader2, MapPin, Star, Check, Sparkles, Info, ChevronLeft } from 'lucide-react'
import {
  getPairs, postRating, getEvalItineraries, postLikert,
  type EvalPair, type EvalItinerary,
} from '@/api/evaluation'
import ItineraryExplorer from '@/components/ItineraryExplorer'
import { poiPhotoUrl } from '@/utils/photos'
import { getCategoryColor } from '@/utils/categoryColors'
import { visibleWarnings } from '@/utils/warnings'
import type { Itinerary } from '@/types'

type Tab = 'pairs' | 'likert'

// Reuses the app's own itinerary layout so realism reads the same here.
// `item_id` is forced null and `is_new_suggestion` true because these are
// unsaved snapshots — never persisted ItineraryItem rows — so the
// replace/remove/visited actions (gated on item_id) stay disabled.
function toItinerary(it: EvalItinerary): Itinerary {
  return {
    itinerary_id: it.itinerary_id,
    city: it.payload.city,
    num_days: it.payload.num_days,
    warnings: it.payload.warnings,
    days: it.payload.days.map((d) => ({
      day_number: d.day_number,
      stops: d.stops.map((s) => ({ ...s, is_new_suggestion: true, item_id: null })),
    })) as unknown as Itinerary['days'],
  }
}

function ProfileCard({ profile }: { profile: EvalPair['profile'] }) {
  const interests = Object.entries(profile.interests ?? {})
    .filter(([, v]) => v >= 0.5)
    .sort((a, b) => b[1] - a[1])
    .map(([k]) => k)
  return (
    <div className="glass glass-specular rounded-2xl px-4 py-3.5 mb-4">
      <p className="text-sm text-indigo-500 font-bold uppercase tracking-wide mb-1">Per chi è pensato questo viaggio</p>
      <p className="font-extrabold text-gray-900 text-lg leading-tight">{profile.label}</p>
      {profile.description && (
        <p className="text-base text-gray-600 leading-relaxed mt-2">{profile.description}</p>
      )}
      <div className="flex flex-wrap gap-1.5 mt-3">
        {profile.travel_mode && (
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-600 font-medium">
            {profile.travel_mode}
          </span>
        )}
        {profile.age_range && (
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-white/60 text-gray-500 font-medium">
            {profile.age_range}
          </span>
        )}
        {interests.map((i) => (
          <span key={i} className="text-[11px] px-2 py-0.5 rounded-full bg-violet-50 text-violet-600 font-medium">
            {i}
          </span>
        ))}
      </div>
    </div>
  )
}

function PoiOption({
  option, onPick, selected,
}: { option: EvalPair['options'][number]; onPick: () => void; selected: boolean }) {
  const [imgError, setImgError] = useState(false)
  const [flipped, setFlipped] = useState(false)
  const photo = poiPhotoUrl(option.poi_id)
  const showPhoto = photo && !imgError

  return (
    <div className="relative h-72 [perspective:1200px]">
      <div
        className="absolute inset-0 transition-transform duration-500 ease-out [transform-style:preserve-3d] motion-reduce:transition-none"
        style={{ transform: flipped ? 'rotateY(180deg)' : undefined }}
      >
        {/* ── Front: photo is the evidence ── */}
        <div className="absolute inset-0 [backface-visibility:hidden]">
          <div
            role="button"
            tabIndex={0}
            onClick={onPick}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPick() }
            }}
            className={`glass flex flex-col text-left w-full h-full rounded-2xl border-2 overflow-hidden active:scale-[0.98] transition-all cursor-pointer ${
              selected ? 'border-green-500 bg-green-50/90' : 'border-white/60 hover:border-indigo-400'
            }`}
          >
            <div className="relative w-full h-40 bg-gray-100 shrink-0">
              {showPhoto ? (
                <img
                  src={photo}
                  alt={option.name}
                  loading="lazy"
                  onError={() => setImgError(true)}
                  className="w-full h-full object-cover"
                />
              ) : (
                <div className="w-full h-full bg-gradient-to-br from-indigo-500 to-violet-500 flex items-center justify-center">
                  <MapPin size={26} className="text-white/90" />
                </div>
              )}
              {option.rating != null && (
                <span className="absolute top-2 right-2 flex items-center gap-1 text-xs font-semibold text-amber-600 bg-white/90 backdrop-blur px-2 py-0.5 rounded-full shadow-sm">
                  <Star size={12} className="fill-amber-400 stroke-amber-400" /> {option.rating}
                </span>
              )}
            </div>
            <div className="p-3 flex-1 flex flex-col">
              <p className="font-bold text-gray-800 leading-snug line-clamp-2 min-h-[2.75rem]">{option.name}</p>
              {option.travel_category && (
                <span className={`self-start mt-1.5 text-[11px] font-semibold px-2 py-0.5 rounded-full ${getCategoryColor(option.travel_category)}`}>
                  {option.travel_category}
                </span>
              )}
              {option.google_maps_url && (
                <a
                  href={option.google_maps_url}
                  target="_blank"
                  rel="noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="mt-auto pt-2 text-[11px] text-indigo-500 font-medium underline self-start"
                >
                  Vedi su Maps
                </a>
              )}
            </div>
          </div>
          {option.description && (
            <button
              onClick={() => setFlipped(true)}
              aria-label="Mostra descrizione"
              className="absolute top-2 left-2 w-7 h-7 rounded-full bg-white/90 backdrop-blur shadow-sm flex items-center justify-center text-indigo-600 active:scale-90 transition-transform"
            >
              <Info size={15} />
            </button>
          )}
        </div>

        {/* ── Back: the description ── */}
        <div className={`glass absolute inset-0 [backface-visibility:hidden] [transform:rotateY(180deg)] rounded-2xl border-2 p-3.5 flex flex-col ${
          selected ? 'border-green-500 bg-green-50/90' : 'border-indigo-100'
        }`}>
          <p className="text-[11px] font-bold text-indigo-400 uppercase tracking-wide mb-1.5 line-clamp-2">
            {option.name}
          </p>
          <p className="text-sm text-gray-600 leading-relaxed flex-1 overflow-y-auto">
            {option.description}
          </p>
          <button
            onClick={() => setFlipped(false)}
            className="mt-3 shrink-0 w-full flex items-center justify-center gap-1 py-2 rounded-xl border border-white/70 bg-white/55 text-gray-500 text-xs font-semibold hover:bg-white/80 active:scale-[0.98] transition-all"
          >
            <ChevronLeft size={15} /> Torna alla foto
          </button>
        </div>
      </div>
    </div>
  )
}

function PairwisePanel({ evaluator, city }: { evaluator: string; city?: string }) {
  const [pairs, setPairs] = useState<EvalPair[]>([])
  const [idx, setIdx] = useState(0)
  // Cumulative counts across the whole pool (not just this fetched page), so the
  // progress bar reflects reality across a page reload instead of resetting to 0 —
  // the backend already knows how many this evaluator has rated so far.
  const [ratedTotal, setRatedTotal] = useState(0)
  const [poolTotal, setPoolTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [fetchingMore, setFetchingMore] = useState(false)
  const [exhausted, setExhausted] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [pickedSlot, setPickedSlot] = useState<'a' | 'b' | null>(null)

  useEffect(() => {
    // Reset local per-batch state too: switching city keeps this component mounted
    // (just the tab content changes), so a stale idx/exhausted from the previous
    // city would otherwise survive the switch.
    setLoading(true)
    setIdx(0)
    setExhausted(false)
    void (async () => {
      try {
        const page = await getPairs(evaluator, city)
        setPairs(page.pairs)
        setRatedTotal(page.ratedTotal)
        setPoolTotal(page.poolTotal)
      } finally { setLoading(false) }
    })()
  }, [evaluator, city])

  // The backend excludes pairs this evaluator already rated, so this also covers
  // resuming after a reload — but within one session, once the fetched batch runs
  // out, ask for the next one instead of ending: the pool (hundreds of pairs) is
  // far bigger than a single page (30).
  useEffect(() => {
    if (loading || fetchingMore || exhausted || idx < pairs.length) return
    void (async () => {
      setFetchingMore(true)
      try {
        const page = await getPairs(evaluator, city)
        if (page.pairs.length === 0) setExhausted(true)
        else setPairs((prev) => [...prev, ...page.pairs])
      } finally {
        setFetchingMore(false)
      }
    })()
  }, [idx, pairs.length, loading, fetchingMore, exhausted, evaluator, city])

  const current = pairs[idx]

  const choose = async (choice: 'a' | 'b' | 'equal') => {
    if (!current || submitting) return
    setSubmitting(true)
    if (choice !== 'equal') setPickedSlot(choice)
    // Flash the chosen card green while the save happens, not before it: run the
    // animation and the request concurrently so the network round trip doesn't
    // add on top of the fixed 380ms, it overlaps with it.
    const minFlash = choice !== 'equal' ? new Promise((r) => setTimeout(r, 380)) : Promise.resolve()
    try {
      await Promise.all([postRating(current.pair_id, evaluator, choice), minFlash])
      setPickedSlot(null)
      setIdx((i) => i + 1)
      setRatedTotal((n) => n + 1)
    } finally { setSubmitting(false) }
  }

  if (loading) return <Centered><Loader2 className="animate-spin text-indigo-500" /></Centered>
  if (!current) {
    if (fetchingMore) return <Centered><Loader2 className="animate-spin text-indigo-500" /></Centered>
    return <Centered><Done count={ratedTotal} label="i confronti" /></Centered>
  }

  return (
    <div>
      <Progress done={ratedTotal} total={poolTotal} />
      <ProfileCard profile={current.profile} />
      <br></br>
      <p className="text-center text-lg font-bold text-gray-800 leading-snug text-balance mb-1.5">
        Quale posto è più adatto a questo viaggiatore?
      </p>
      <div className="grid grid-cols-2 gap-3 items-stretch">
        {current.options.map((o) => (
          <PoiOption
            key={o.poi_id}
            option={o}
            selected={pickedSlot === o.slot}
            onPick={() => void choose(o.slot)}
          />
        ))}
      </div>
      <button
        disabled={submitting}
        onClick={() => void choose('equal')}
        className="glass glass-specular w-full mt-4 text-center text-[15px] text-gray-700 font-semibold py-3.5 rounded-2xl border-2 border-white/60 hover:border-red-400 hover:text-red-500 hover:bg-red-50/85 active:scale-[0.99] transition-all disabled:opacity-50"
      >
        Equivalenti / non sono sicuro
      </button>
    </div>
  )
}

function LikertPanel({ evaluator, city }: { evaluator: string; city?: string }) {
  const [items, setItems] = useState<EvalItinerary[]>([])
  const [idx, setIdx] = useState(0)
  // Cumulative counts across the whole pool, same reasoning as PairwisePanel.
  const [ratedTotal, setRatedTotal] = useState(0)
  const [poolTotal, setPoolTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [fetchingMore, setFetchingMore] = useState(false)
  const [exhausted, setExhausted] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [scores, setScores] = useState({ realism: 3, completeness: 3, profile_fit: 3, overall: 3 })

  useEffect(() => {
    // Same reset as PairwisePanel: switching city keeps this component mounted.
    setLoading(true)
    setIdx(0)
    setExhausted(false)
    void (async () => {
      try {
        const page = await getEvalItineraries(evaluator, city)
        setItems(page.itineraries)
        setRatedTotal(page.ratedTotal)
        setPoolTotal(page.poolTotal)
      } finally { setLoading(false) }
    })()
  }, [evaluator, city])

  // Same resume-then-auto-continue pattern as PairwisePanel (see comment there).
  useEffect(() => {
    if (loading || fetchingMore || exhausted || idx < items.length) return
    void (async () => {
      setFetchingMore(true)
      try {
        const page = await getEvalItineraries(evaluator, city)
        if (page.itineraries.length === 0) setExhausted(true)
        else setItems((prev) => [...prev, ...page.itineraries])
      } finally {
        setFetchingMore(false)
      }
    })()
  }, [idx, items.length, loading, fetchingMore, exhausted, evaluator, city])

  const current = items[idx]
  // Stable reference: rebuilding this on every render (e.g. on each Likert
  // click) makes ItineraryExplorer treat it as new data and reset its state.
  const currentItinerary = useMemo(() => (current ? toItinerary(current) : null), [current])
  const dims: { key: keyof typeof scores; label: string }[] = [
    { key: 'realism', label: 'Realismo (la giornata è fattibile?)' },
    { key: 'completeness', label: 'Completezza (le giornate sono abbastanza piene?)' },
    { key: 'profile_fit', label: 'Adattamento al profilo' },
    { key: 'overall', label: 'Soddisfazione complessiva' },
  ]

  const submit = async () => {
    if (!current) return
    setSubmitting(true)
    try {
      await postLikert({ itinerary_id: current.itinerary_id, evaluator_id: evaluator, ...scores })
      setScores({ realism: 3, completeness: 3, profile_fit: 3, overall: 3 })
      setIdx((i) => i + 1)
      setRatedTotal((n) => n + 1)
    } finally { setSubmitting(false) }
  }

  if (loading) return <Centered><Loader2 className="animate-spin text-indigo-500" /></Centered>
  if (!current) {
    if (fetchingMore) return <Centered><Loader2 className="animate-spin text-indigo-500" /></Centered>
    return <Centered><Done count={ratedTotal} label="gli itinerari" /></Centered>
  }

  return (
    <div>
      <Progress done={ratedTotal} total={poolTotal} />
      <ProfileCard profile={current.profile} />
      <p className="text-xs text-gray-400 font-medium mb-2">{current.city} · {current.num_days} giorni</p>

      {/* Same explorer the app shows on /itinerary — realism reads the same here. */}
      {!!visibleWarnings(current.payload.warnings).length && (
        <div className="flex flex-col gap-2 mb-4">
          {visibleWarnings(current.payload.warnings).map((w, i) => (
            <div key={i} className="flex items-start gap-2 bg-amber-50/85 backdrop-blur border border-amber-100/80 rounded-xl px-4 py-3">
              <span className="text-amber-500 mt-0.5 shrink-0">⚠️</span>
              <p className="text-xs text-amber-700">{w}</p>
            </div>
          ))}
        </div>
      )}
      <div className="mb-5">
        {currentItinerary && <ItineraryExplorer itinerary={currentItinerary} onChange={() => {}} />}
      </div>
      <div className="space-y-4 mb-4">
        {dims.map((d) => (
          <div key={d.key}>
            <label className="text-sm font-medium text-gray-600">{d.label}</label>
            <div className="flex gap-1.5 mt-1.5">
              {[1, 2, 3, 4, 5].map((v) => (
                <button
                  key={v}
                  onClick={() => setScores((s) => ({ ...s, [d.key]: v }))}
                  className={`flex-1 py-2 rounded-lg text-sm font-semibold border-2 transition-all ${
                    scores[d.key] === v
                      ? 'border-indigo-500 bg-white/80 text-indigo-600 shadow-sm'
                      : 'border-white/60 bg-white/45 text-gray-400'
                  }`}
                >
                  {v}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
      <button
        disabled={submitting}
        onClick={() => void submit()}
        className="w-full bg-gradient-to-r from-indigo-600 to-violet-600 text-white font-semibold rounded-xl py-3 disabled:opacity-50 shadow-md shadow-indigo-200 active:scale-[0.98] transition-all"
      >
        {submitting ? 'Salvataggio…' : 'Invia e continua'}
      </button>
    </div>
  )
}

function Centered({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-col items-center justify-center py-24">{children}</div>
}
function Done({ count, label }: { count: number; label: string }) {
  return (
    <div className="glass glass-specular rounded-3xl px-7 py-8 flex flex-col items-center gap-3 text-center">
      <div className="w-14 h-14 rounded-2xl bg-white/60 border border-white/60 flex items-center justify-center">
        <Check size={26} className="text-emerald-500" />
      </div>
      <p className="font-bold text-gray-800">Hai completato tutti {label}.</p>
      <p className="text-sm text-gray-400">Grazie per l'aiuto! ({count} valutati)</p>
    </div>
  )
}
function Progress({ done, total }: { done: number; total: number }) {
  return (
    <div className="mb-4">
      <div className="h-1.5 bg-white/60 rounded-full overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-indigo-500 to-violet-500 transition-all"
          style={{ width: `${total ? (done / total) * 100 : 0}%` }}
        />
      </div>
      <p className="text-[11px] text-gray-400 mt-1 text-right">{done}/{total}</p>
    </div>
  )
}

// Matches evaluation/config.py CITIES — the 3 cities the harness was built for.
const EVAL_CITIES = ['Roma', 'Madrid', 'Porto']

export default function Evaluation() {
  const [params, setParams] = useSearchParams()
  const evaluator = params.get('evaluator') ?? ''
  const cityParam = params.get('city')
  // 'any' is a real, persisted choice ("I know them all / no preference"), distinct
  // from null ("hasn't answered yet") — both must survive a page reload.
  const city = cityParam && cityParam !== 'any' ? cityParam : undefined
  const [tab, setTab] = useState<Tab>('pairs')
  const [nameInput, setNameInput] = useState('')

  const headerTabs = useMemo(
    () => [
      { key: 'pairs' as Tab, label: 'Confronti' },
      { key: 'likert' as Tab, label: 'Itinerari' },
    ],
    [],
  )

  if (!evaluator) {
    const start = () => nameInput.trim() && setParams({ evaluator: nameInput.trim() })
    return (
      <div className="relative max-w-md mx-auto min-h-screen flex flex-col items-center justify-center overflow-hidden bg-gradient-to-b from-indigo-50 via-violet-50 to-gray-50 px-6">
        <div
          aria-hidden="true"
          className="absolute left-[-5rem] top-1/4 h-56 w-56 rounded-full bg-indigo-300/35 blur-3xl"
        />
        <div
          aria-hidden="true"
          className="absolute right-[-5rem] bottom-1/4 h-56 w-56 rounded-full bg-fuchsia-300/25 blur-3xl"
        />
        <div className="glass glass-specular relative w-full rounded-3xl px-7 py-8">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 flex items-center justify-center mb-5 shadow-md shadow-indigo-200">
            <Sparkles size={24} className="text-white" />
          </div>
          <h1 className="text-2xl font-extrabold text-gray-900 tracking-tight mb-1.5">Valutazione itinerari</h1>
          <p className="text-sm text-gray-500 mb-6">Inserisci un nome o un codice per iniziare a valutare.</p>
          <input
            value={nameInput}
            onChange={(e) => setNameInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && start()}
            placeholder="es. valutatore-01"
            className="w-full border border-white/60 bg-white/55 shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] rounded-xl px-4 py-3 mb-3 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:bg-white/85"
          />
          <button
            disabled={!nameInput.trim()}
            onClick={start}
            className="w-full bg-gradient-to-r from-indigo-600 to-violet-600 text-white font-semibold rounded-xl py-3 shadow-md shadow-indigo-200 disabled:opacity-50 active:scale-[0.98] transition-transform"
          >
            Inizia
          </button>
        </div>
      </div>
    )
  }

  if (cityParam === null) {
    const pick = (c: string) => setParams({ evaluator, city: c })
    return (
      <div className="relative max-w-md mx-auto min-h-screen flex flex-col items-center justify-center overflow-hidden bg-gradient-to-b from-indigo-50 via-violet-50 to-gray-50 px-6">
        <div
          aria-hidden="true"
          className="absolute left-[-5rem] top-1/4 h-56 w-56 rounded-full bg-indigo-300/35 blur-3xl"
        />
        <div
          aria-hidden="true"
          className="absolute right-[-5rem] bottom-1/4 h-56 w-56 rounded-full bg-fuchsia-300/25 blur-3xl"
        />
        <div className="glass glass-specular relative w-full rounded-3xl px-7 py-8">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 flex items-center justify-center mb-5 shadow-md shadow-indigo-200">
            <MapPin size={24} className="text-white" />
          </div>
          <h1 className="text-2xl font-extrabold text-gray-900 tracking-tight mb-1.5">Quale città conosci meglio?</h1>
          <p className="text-sm text-gray-500 mb-6">
            Concentreremo i tuoi confronti su quella città, così potrai giudicare posti che conosci davvero.
          </p>
          <div className="flex flex-col gap-2.5">
            {EVAL_CITIES.map((c) => (
              <button
                key={c}
                onClick={() => pick(c)}
                className="w-full text-left bg-white/55 border border-white/60 rounded-xl px-4 py-3 text-sm font-semibold text-gray-800 hover:border-indigo-400 hover:bg-white/80 active:scale-[0.98] transition-all"
              >
                {c}
              </button>
            ))}
            <button
              onClick={() => pick('any')}
              className="w-full text-center mt-1.5 text-[13px] text-gray-500 font-medium py-2 hover:text-indigo-500 transition-colors"
            >
              Nessuna preferenza / Le conosco tutte
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-md mx-auto min-h-screen flex flex-col bg-gradient-to-b from-indigo-50 via-gray-50 to-gray-50 pb-20">
      {/* Header */}
      <div className="bg-gradient-to-br from-indigo-600 via-violet-600 to-fuchsia-500 px-6 pt-14 pb-20">
        <p className="text-indigo-200 text-sm font-medium mb-1.5">
          Valutazione · {evaluator} ·{' '}
          <button
            onClick={() => setParams({ evaluator })}
            className="underline decoration-dotted underline-offset-2 hover:text-white transition-colors"
          >
            {city ?? 'cambia città'}
          </button>
        </p>
        <h1 className="text-2xl font-extrabold text-white tracking-tight">Aiutaci a valutare gli itinerari</h1>
        {/* Segmented tab control */}
        <div className="mt-5 glass glass-specular rounded-full p-1 flex gap-1">
          {headerTabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex-1 px-4 py-1.5 rounded-full text-sm font-semibold transition-all ${
                tab === t.key ? 'bg-white text-indigo-600 shadow-sm' : 'text-gray-600'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Content panel overlapping the header */}
      <div className="flex-1 bg-gray-50 rounded-t-3xl -mt-8 px-5 pt-6">
        {tab === 'pairs'
          ? <PairwisePanel evaluator={evaluator} city={city} />
          : <LikertPanel evaluator={evaluator} city={city} />}
      </div>
    </div>
  )
}
