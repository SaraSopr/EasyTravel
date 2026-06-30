import { Clock, CheckCircle2, Star } from 'lucide-react'
import type { Place } from '@/types'
import { getCategoryColor } from '@/utils/categoryColors'

interface PlaceCardProps {
  place: Place
  selected: boolean
  onToggle: () => void
}

export default function PlaceCard({ place, selected, onToggle }: PlaceCardProps) {
  return (
    <button
      onClick={onToggle}
      className={`glass glass-specular relative w-full text-left p-4 rounded-2xl border-2 transition-all active:scale-[0.98] ${
        selected
          ? 'border-emerald-400 shadow-emerald-100 shadow-md'
          : 'border-white/60'
      }`}
    >
      {selected && (
        <div className="absolute top-3 right-3 bg-emerald-500 rounded-full p-0.5">
          <CheckCircle2 size={14} className="text-white" />
        </div>
      )}

      <div className="flex items-start gap-3 pr-6">
        <div className="flex-1 min-w-0">
          <span
            className={`inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full mb-2 ${getCategoryColor(place.category)}`}
          >
            {place.category}
          </span>
          <p className="font-bold text-gray-900 text-base leading-tight mb-1">
            {place.name}
          </p>
          <p className="text-gray-400 text-sm line-clamp-2 leading-relaxed">
            {place.description}
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3 mt-3 pt-3 border-t border-white/60">
        <span className="flex items-center gap-1.5 text-xs text-gray-400 font-medium">
          <Clock size={12} />
          {place.visit_duration_minutes} min
        </span>
        {place.score !== undefined && (
          <>
            <span className="text-gray-200">·</span>
            <span className="flex items-center gap-1 text-xs text-amber-500 font-medium">
              <Star size={11} className="fill-amber-400 text-amber-400" />
              {(place.score * 5).toFixed(1)}
            </span>
            <div className="flex-1 h-1 bg-white/60 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-indigo-400 to-violet-400 rounded-full"
                style={{ width: `${place.score * 100}%` }}
              />
            </div>
          </>
        )}
      </div>
    </button>
  )
}
