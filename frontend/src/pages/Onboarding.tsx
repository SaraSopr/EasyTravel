import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { getExperiences, submitExperienceChoices } from '@/api/endpoints'
import useAuthStore from '@/store/useAuthStore'
import ExperienceCard from '@/components/ExperienceCard'
import ExperienceDetailSheet from '@/components/ExperienceDetailSheet'
import type { Experience } from '@/types'

export default function Onboarding() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)

  const [experiences, setExperiences] = useState<Experience[]>([])
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [activeExperience, setActiveExperience] = useState<Experience | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!user) return
    const fetch = async () => {
      try {
        const data = await getExperiences(user.home_city)
        setExperiences(data)
      } catch {
        setError('Failed to load experiences. Please try again.')
      } finally {
        setLoading(false)
      }
    }
    void fetch()
  }, [user])

  const toggle = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  const handleContinue = async () => {
    setSubmitting(true)
    try {
      await submitExperienceChoices(selectedIds)
      navigate('/home')
    } catch {
      setError('Failed to save your choices. Please try again.')
      setSubmitting(false)
    }
  }

  return (
    <div className="max-w-md mx-auto min-h-screen flex flex-col bg-gradient-to-b from-indigo-50 via-gray-50 to-gray-50 pb-28">
      {/* Header */}
      <div className="bg-gradient-to-br from-indigo-600 via-violet-600 to-fuchsia-500 px-6 pt-14 pb-16">
        <p className="text-indigo-200 text-sm font-medium mb-2">Personalise your experience</p>
        <h1 className="text-2xl font-extrabold text-white tracking-tight leading-snug">
          What kind of traveller are you?
        </h1>
        <p className="text-indigo-200 text-sm mt-2">
          Pick at least one experience you love
        </p>
      </div>

      <div className="flex-1 bg-gray-50 rounded-t-3xl -mt-6 px-6 pt-6">
        {error && (
          <div className="text-sm text-red-600 bg-red-50/85 backdrop-blur border border-red-100/80 rounded-xl px-4 py-3 mb-4">
            {error}
          </div>
        )}

        {loading ? (
          <div className="relative">
            <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-4 pointer-events-none">
              <div className="gradient-ring w-16 h-16 animate-spin" />
              <span className="text-sm font-semibold text-indigo-500 tracking-wide">Finding experiences…</span>
            </div>
            <div className="grid grid-cols-2 gap-3 opacity-30">
              {Array.from({ length: 8 }).map((_, i) => (
                <div
                  key={i}
                  className="flex flex-col items-start gap-2.5 p-4 rounded-2xl border-2 border-gray-100 bg-white shadow-sm animate-pulse"
                >
                  <div className="w-10 h-10 rounded-xl shimmer" />
                  <div className="h-3 w-3/4 rounded-full shimmer" />
                  <div className="h-2.5 w-full rounded-full shimmer" />
                  <div className="h-2.5 w-2/3 rounded-full shimmer" />
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            {experiences.map((exp) => (
              <ExperienceCard
                key={exp.id}
                experience={exp}
                selected={selectedIds.includes(exp.id)}
                onOpen={() =>
                  selectedIds.includes(exp.id)
                    ? toggle(exp.id)
                    : setActiveExperience(exp)
                }
              />
            ))}
          </div>
        )}
      </div>

      <ExperienceDetailSheet
        experience={activeExperience}
        selected={activeExperience ? selectedIds.includes(activeExperience.id) : false}
        onToggle={() => activeExperience && toggle(activeExperience.id)}
        onClose={() => setActiveExperience(null)}
      />

      {/* Sticky bottom */}
      <div className="fixed bottom-0 left-1/2 -translate-x-1/2 z-30 w-full max-w-md glass glass-specular rounded-t-3xl px-6 py-4">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs text-gray-400 font-medium">
            {selectedIds.length === 0
              ? 'Select at least one'
              : `${selectedIds.length} selected`}
          </span>
          <div className="flex gap-1">
            {Array.from({ length: Math.min(selectedIds.length, 6) }).map((_, i) => (
              <div key={i} className="w-1.5 h-1.5 rounded-full bg-indigo-500" />
            ))}
          </div>
        </div>
        <button
          onClick={handleContinue}
          disabled={selectedIds.length === 0 || submitting}
          className="flex items-center justify-center gap-2 w-full bg-gradient-to-r from-indigo-600 to-violet-600 text-white font-semibold rounded-xl py-3.5 disabled:opacity-50 shadow-md shadow-indigo-200 active:scale-[0.98] transition-all"
        >
          {submitting && <Loader2 size={18} className="animate-spin" />}
          Continue
        </button>
      </div>
    </div>
  )
}
