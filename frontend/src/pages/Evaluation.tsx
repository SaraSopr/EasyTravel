import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Loader2, MapPin, Star, Check, Sparkles, Info, ChevronLeft } from 'lucide-react'
import {
  getPairs, postRating, getEvalItineraries, postLikert,
  type EvalPair, type EvalItinerary,
} from '@/api/evaluation'
import ItineraryMap from '@/components/ItineraryMap'
import { poiPhotoUrl } from '@/utils/photos'
import { getCategoryColor } from '@/utils/categoryColors'
import type { ItineraryDay } from '@/types'

type Tab = 'pairs' | 'likert'

// Mirror ItineraryTimeline's transport glyphs so realism reads the same here.
function transportLabel(mode: string | null): string {
  if (mode === 'driving' || mode === 'taxi') return '🚗'
  if (mode === 'transit') return '🚌'
  return '🚶'
}

function ProfileCard({ profile }: { profile: EvalPair['profile'] }) {
  const interests = Object.entries(profile.interests ?? {})
    .filter(([, v]) => v >= 0.5)
    .sort((a, b) => b[1] - a[1])
    .map(([k]) => k)
  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm px-4 py-3.5 mb-4">
      <p className="text-sm text-indigo-500 font-bold uppercase tracking-wide mb-1">Who this trip is for</p>
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
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-gray-100 text-gray-500 font-medium">
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
            className={`flex flex-col text-left w-full h-full rounded-2xl border-2 shadow-sm overflow-hidden active:scale-[0.98] transition-all cursor-pointer ${
              selected ? 'border-green-500 bg-green-50' : 'bg-white border-gray-100 hover:border-indigo-400'
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
                  View on Maps
                </a>
              )}
            </div>
          </div>
          {option.description && (
            <button
              onClick={() => setFlipped(true)}
              aria-label="Show description"
              className="absolute top-2 left-2 w-7 h-7 rounded-full bg-white/90 backdrop-blur shadow-sm flex items-center justify-center text-indigo-600 active:scale-90 transition-transform"
            >
              <Info size={15} />
            </button>
          )}
        </div>

        {/* ── Back: the description ── */}
        <div className={`absolute inset-0 [backface-visibility:hidden] [transform:rotateY(180deg)] rounded-2xl border-2 shadow-sm p-3.5 flex flex-col ${
          selected ? 'border-green-500 bg-green-50' : 'bg-white border-indigo-100'
        }`}>
          <p className="text-[11px] font-bold text-indigo-400 uppercase tracking-wide mb-1.5 line-clamp-2">
            {option.name}
          </p>
          <p className="text-sm text-gray-600 leading-relaxed flex-1 overflow-y-auto">
            {option.description}
          </p>
          <button
            onClick={() => setFlipped(false)}
            className="mt-3 shrink-0 w-full flex items-center justify-center gap-1 py-2 rounded-xl border border-gray-200 text-gray-500 text-xs font-semibold hover:bg-gray-50 active:scale-[0.98] transition-all"
          >
            <ChevronLeft size={15} /> Back to photo
          </button>
        </div>
      </div>
    </div>
  )
}

function PairwisePanel({ evaluator }: { evaluator: string }) {
  const [pairs, setPairs] = useState<EvalPair[]>([])
  const [idx, setIdx] = useState(0)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [pickedSlot, setPickedSlot] = useState<'a' | 'b' | null>(null)

  useEffect(() => {
    void (async () => {
      try { setPairs(await getPairs(evaluator)) } finally { setLoading(false) }
    })()
  }, [evaluator])

  const current = pairs[idx]

  const choose = async (choice: 'a' | 'b' | 'equal') => {
    if (!current || submitting) return
    setSubmitting(true)
    // Flash the chosen card green before advancing, as confirmation.
    if (choice !== 'equal') {
      setPickedSlot(choice)
      await new Promise((r) => setTimeout(r, 380))
    }
    try {
      await postRating(current.pair_id, evaluator, choice)
      setPickedSlot(null)
      setIdx((i) => i + 1)
    } finally { setSubmitting(false) }
  }

  if (loading) return <Centered><Loader2 className="animate-spin text-indigo-500" /></Centered>
  if (!current)
    return <Centered><Done count={pairs.length} label="comparisons" /></Centered>

  return (
    <div>
      <Progress done={idx} total={pairs.length} />
      <ProfileCard profile={current.profile} />
      <br></br>
      <p className="text-center text-lg font-bold text-gray-800 leading-snug text-balance mb-1.5">
        Which place is better suited for this traveler?
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
        className="w-full mt-4 text-center text-[15px] text-gray-700 font-semibold py-3.5 rounded-2xl border-2 border-gray-100 bg-white hover:border-red-400 hover:text-red-500 hover:bg-red-50 active:scale-[0.99] transition-all disabled:opacity-50"
      >
        Equivalent / not sure
      </button>
    </div>
  )
}

function LikertPanel({ evaluator }: { evaluator: string }) {
  const [items, setItems] = useState<EvalItinerary[]>([])
  const [idx, setIdx] = useState(0)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [scores, setScores] = useState({ realism: 3, completeness: 3, profile_fit: 3, overall: 3 })

  useEffect(() => {
    void (async () => {
      try { setItems(await getEvalItineraries(evaluator)) } finally { setLoading(false) }
    })()
  }, [evaluator])

  const current = items[idx]
  const dims: { key: keyof typeof scores; label: string }[] = [
    { key: 'realism', label: 'Realism (is the day feasible?)' },
    { key: 'completeness', label: 'Completeness (are the days full enough?)' },
    { key: 'profile_fit', label: 'Profile fit' },
    { key: 'overall', label: 'Overall satisfaction' },
  ]

  const submit = async () => {
    if (!current) return
    setSubmitting(true)
    try {
      await postLikert({ itinerary_id: current.itinerary_id, evaluator_id: evaluator, ...scores })
      setScores({ realism: 3, completeness: 3, profile_fit: 3, overall: 3 })
      setIdx((i) => i + 1)
    } finally { setSubmitting(false) }
  }

  if (loading) return <Centered><Loader2 className="animate-spin text-indigo-500" /></Centered>
  if (!current) return <Centered><Done count={items.length} label="itineraries" /></Centered>

  return (
    <div>
      <Progress done={idx} total={items.length} />
      <ProfileCard profile={current.profile} />
      <p className="text-xs text-gray-400 font-medium mb-2">{current.city} · {current.num_days} days</p>

      {/* Route map — needed to judge whether the day is geographically feasible */}
      <div className="mb-4">
        <ItineraryMap days={current.payload.days as unknown as ItineraryDay[]} />
      </div>

      <div className="space-y-3 mb-5">
        {current.payload.days.map((d) => (
          <div key={d.day_number} className="bg-white rounded-2xl border border-gray-100 shadow-sm p-3">
            <p className="text-xs font-bold text-indigo-600 mb-2">Day {d.day_number}</p>
            <ul className="space-y-1">
              {d.stops.map((s, i) => (
                <li key={s.position}>
                  {/* Travel leg from the previous stop — the realism signal */}
                  {i > 0 && s.transport_from_previous != null && s.travel_minutes_from_previous != null && (
                    <div className="flex items-center gap-1.5 text-[11px] text-gray-400 pl-[88px] py-0.5">
                      <span>{transportLabel(s.transport_from_previous)}</span>
                      <span>{Math.round(s.travel_minutes_from_previous)} min</span>
                    </div>
                  )}
                  <div className="flex items-baseline gap-2 text-sm">
                    <span className="text-[11px] text-gray-400 w-20 shrink-0">
                      {s.arrival_time}–{s.departure_time}
                    </span>
                    <span className={s.is_food ? 'text-amber-600' : 'text-gray-700'}>{s.name}</span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ))}
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
                      ? 'border-indigo-500 bg-indigo-50 text-indigo-600'
                      : 'border-gray-100 bg-white text-gray-400'
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
        {submitting ? 'Saving…' : 'Submit and continue'}
      </button>
    </div>
  )
}

function Centered({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-col items-center justify-center py-24">{children}</div>
}
function Done({ count, label }: { count: number; label: string }) {
  return (
    <div className="bg-white rounded-3xl border border-gray-100 shadow-sm px-7 py-8 flex flex-col items-center gap-3 text-center">
      <div className="w-14 h-14 rounded-2xl bg-emerald-50 flex items-center justify-center">
        <Check size={26} className="text-emerald-500" />
      </div>
      <p className="font-bold text-gray-800">You completed all {label}.</p>
      <p className="text-sm text-gray-400">Thanks for helping! ({count} rated)</p>
    </div>
  )
}
function Progress({ done, total }: { done: number; total: number }) {
  return (
    <div className="mb-4">
      <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-indigo-500 to-violet-500 transition-all"
          style={{ width: `${total ? (done / total) * 100 : 0}%` }}
        />
      </div>
      <p className="text-[11px] text-gray-400 mt-1 text-right">{done}/{total}</p>
    </div>
  )
}

export default function Evaluation() {
  const [params, setParams] = useSearchParams()
  const evaluator = params.get('evaluator') ?? ''
  const [tab, setTab] = useState<Tab>('pairs')
  const [nameInput, setNameInput] = useState('')

  const headerTabs = useMemo(
    () => [
      { key: 'pairs' as Tab, label: 'Comparisons' },
      { key: 'likert' as Tab, label: 'Itineraries' },
    ],
    [],
  )

  if (!evaluator) {
    const start = () => nameInput.trim() && setParams({ evaluator: nameInput.trim() })
    return (
      <div className="max-w-md mx-auto min-h-screen flex flex-col items-center justify-center bg-gradient-to-b from-indigo-50 via-gray-50 to-gray-50 px-6">
        <div className="w-full bg-white rounded-3xl border border-gray-100 shadow-sm px-7 py-8">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 flex items-center justify-center mb-5 shadow-md shadow-indigo-200">
            <Sparkles size={24} className="text-white" />
          </div>
          <h1 className="text-2xl font-extrabold text-gray-900 tracking-tight mb-1.5">Itinerary evaluation</h1>
          <p className="text-sm text-gray-500 mb-6">Enter a name or code to begin rating.</p>
          <input
            value={nameInput}
            onChange={(e) => setNameInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && start()}
            placeholder="e.g. evaluator-01"
            className="w-full border border-gray-200 rounded-xl px-4 py-3 mb-3 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent"
          />
          <button
            disabled={!nameInput.trim()}
            onClick={start}
            className="w-full bg-gradient-to-r from-indigo-600 to-violet-600 text-white font-semibold rounded-xl py-3 shadow-md shadow-indigo-200 disabled:opacity-50 active:scale-[0.98] transition-transform"
          >
            Start
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-md mx-auto min-h-screen flex flex-col bg-gradient-to-b from-indigo-50 via-gray-50 to-gray-50 pb-20">
      {/* Header */}
      <div className="bg-gradient-to-br from-indigo-600 via-violet-600 to-fuchsia-500 px-6 pt-14 pb-20">
        <p className="text-indigo-200 text-sm font-medium mb-1.5">Evaluation · {evaluator}</p>
        <h1 className="text-2xl font-extrabold text-white tracking-tight">Help us rate itineraries</h1>
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
        {tab === 'pairs' ? <PairwisePanel evaluator={evaluator} /> : <LikertPanel evaluator={evaluator} />}
      </div>
    </div>
  )
}
