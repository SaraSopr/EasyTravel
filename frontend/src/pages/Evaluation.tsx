import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Loader2, MapPin, Star, Check } from 'lucide-react'
import {
  getPairs, postRating, getEvalItineraries, postLikert,
  type EvalPair, type EvalItinerary,
} from '@/api/evaluation'

type Tab = 'pairs' | 'likert'

function ProfileCard({ profile }: { profile: EvalPair['profile'] }) {
  const interests = Object.entries(profile.interests ?? {})
    .filter(([, v]) => v >= 0.5)
    .sort((a, b) => b[1] - a[1])
    .map(([k]) => k)
  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm px-4 py-3 mb-4">
      <p className="text-xs text-gray-400 font-medium mb-1">Who this trip is for</p>
      <p className="font-bold text-gray-800">{profile.label}</p>
      <div className="flex flex-wrap gap-1.5 mt-2">
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
  option, onPick,
}: { option: EvalPair['options'][number]; onPick: () => void }) {
  return (
    <button
      onClick={onPick}
      className="flex flex-col items-start text-left w-full bg-white rounded-2xl border-2 border-gray-100 hover:border-indigo-400 shadow-sm p-4 active:scale-[0.98] transition-all"
    >
      <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-500 flex items-center justify-center mb-2.5">
        <MapPin size={18} className="text-white" />
      </div>
      <p className="font-bold text-gray-800 leading-snug">{option.name}</p>
      {option.travel_category && (
        <span className="text-[11px] text-gray-400 mt-0.5">{option.travel_category}</span>
      )}
      {option.rating != null && (
        <span className="flex items-center gap-1 text-xs text-amber-500 mt-1.5">
          <Star size={12} className="fill-amber-400 stroke-amber-400" /> {option.rating}
        </span>
      )}
      {option.google_maps_url && (
        <a
          href={option.google_maps_url}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="text-[11px] text-indigo-500 mt-2 underline"
        >
          View on Maps
        </a>
      )}
    </button>
  )
}

function PairwisePanel({ evaluator }: { evaluator: string }) {
  const [pairs, setPairs] = useState<EvalPair[]>([])
  const [idx, setIdx] = useState(0)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    void (async () => {
      try { setPairs(await getPairs(evaluator)) } finally { setLoading(false) }
    })()
  }, [evaluator])

  const current = pairs[idx]

  const choose = async (choice: 'a' | 'b' | 'equal') => {
    if (!current) return
    setSubmitting(true)
    try {
      await postRating(current.pair_id, evaluator, choice)
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
      <p className="text-center text-sm font-semibold text-gray-600 mb-3">
        Which place is better suited for this traveler?
      </p>
      <div className="grid grid-cols-2 gap-3">
        {current.options.map((o) => (
          <PoiOption key={o.slot} option={o} onPick={() => void choose(o.slot)} />
        ))}
      </div>
      <button
        disabled={submitting}
        onClick={() => void choose('equal')}
        className="w-full mt-3 text-sm text-gray-500 font-medium py-2.5 rounded-xl border border-gray-200 bg-white disabled:opacity-50"
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
      <div className="space-y-3 mb-5">
        {current.payload.days.map((d) => (
          <div key={d.day_number} className="bg-white rounded-2xl border border-gray-100 shadow-sm p-3">
            <p className="text-xs font-bold text-indigo-600 mb-2">Day {d.day_number}</p>
            <ul className="space-y-1.5">
              {d.stops.map((s) => (
                <li key={s.position} className="flex items-baseline gap-2 text-sm">
                  <span className="text-[11px] text-gray-400 w-20 shrink-0">
                    {s.arrival_time}–{s.departure_time}
                  </span>
                  <span className={s.is_food ? 'text-amber-600' : 'text-gray-700'}>{s.name}</span>
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
    <div className="flex flex-col items-center gap-3 text-center">
      <div className="w-14 h-14 rounded-full bg-emerald-50 flex items-center justify-center">
        <Check className="text-emerald-500" />
      </div>
      <p className="font-semibold text-gray-700">You completed all {label}.</p>
      <p className="text-sm text-gray-400">Thanks! ({count} rated)</p>
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
    return (
      <div className="max-w-md mx-auto min-h-screen flex flex-col items-center justify-center bg-gray-50 px-6">
        <h1 className="text-xl font-extrabold text-gray-800 mb-2">Itinerary evaluation</h1>
        <p className="text-sm text-gray-500 mb-6 text-center">Enter a name or code to start.</p>
        <input
          value={nameInput}
          onChange={(e) => setNameInput(e.target.value)}
          placeholder="e.g. evaluator-01"
          className="w-full border border-gray-200 rounded-xl px-4 py-3 mb-3"
        />
        <button
          disabled={!nameInput.trim()}
          onClick={() => setParams({ evaluator: nameInput.trim() })}
          className="w-full bg-gradient-to-r from-indigo-600 to-violet-600 text-white font-semibold rounded-xl py-3 disabled:opacity-50"
        >
          Start
        </button>
      </div>
    )
  }

  return (
    <div className="max-w-md mx-auto min-h-screen bg-gray-50">
      <div className="bg-gradient-to-br from-indigo-600 to-violet-600 px-6 pt-12 pb-6">
        <p className="text-indigo-200 text-xs font-medium">Evaluation · {evaluator}</p>
        <h1 className="text-xl font-extrabold text-white mt-1">Help us evaluate itineraries</h1>
        <div className="flex gap-2 mt-4">
          {headerTabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-4 py-1.5 rounded-full text-sm font-semibold transition-all ${
                tab === t.key ? 'bg-white text-indigo-600' : 'bg-white/15 text-white'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>
      <div className="px-6 py-6">
        {tab === 'pairs' ? <PairwisePanel evaluator={evaluator} /> : <LikertPanel evaluator={evaluator} />}
      </div>
    </div>
  )
}
