import { useEffect } from 'react'
import * as LucideIcons from 'lucide-react'
import { X, CheckCircle2, Circle } from 'lucide-react'
import type { Experience } from '@/types'

interface ExperienceDetailSheetProps {
  experience: Experience | null
  selected: boolean
  onToggle: () => void
  onClose: () => void
}

type LucideIcon = React.ComponentType<{ size?: number; className?: string }>

export default function ExperienceDetailSheet({
  experience,
  selected,
  onToggle,
  onClose,
}: ExperienceDetailSheetProps) {
  const open = experience !== null

  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => { document.body.style.overflow = '' }
  }, [open])

  const iconKey = experience?.icon as keyof typeof LucideIcons | undefined
  const IconComponent =
    (iconKey ? LucideIcons[iconKey] as LucideIcon | undefined : undefined) ??
    LucideIcons.MapPin

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        className={`fixed inset-0 bg-black/40 backdrop-blur-sm z-40 transition-opacity duration-300 ${
          open ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
        }`}
      />

      {/* Modal */}
      <div
        className={`fixed inset-0 z-50 flex items-center justify-center px-6 transition-all duration-300 ${
          open ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
        }`}
      >
        <div
          className={`glass glass-specular relative w-full max-w-sm rounded-3xl transition-transform duration-300 ease-out ${
            open ? 'scale-100' : 'scale-90'
          }`}
        >
          <button
            onClick={onClose}
            className="absolute top-4 right-4 w-8 h-8 flex items-center justify-center rounded-full bg-white/70 border border-white/70 text-gray-500 shadow-sm z-10"
          >
            <X size={16} />
          </button>

          {experience && (
            <div className="px-6 pt-6 pb-6">
              <div className="w-full h-44 rounded-2xl overflow-hidden mb-5">
                {experience.photo_url ? (
                  <img
                    src={experience.photo_url}
                    alt={experience.name}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <div className="w-full h-full bg-gradient-to-br from-indigo-100 to-violet-100 flex items-center justify-center">
                    <IconComponent size={56} className="text-indigo-400" />
                  </div>
                )}
              </div>

              <h2 className="text-xl font-bold text-gray-900 mb-2">
                {experience.name}
              </h2>
              <p className="text-gray-500 text-sm leading-relaxed">
                {experience.description}
              </p>

              <button
                onClick={() => { onToggle(); onClose() }}
                className={`mt-6 flex items-center justify-center gap-2 w-full font-semibold rounded-xl py-3.5 transition-all active:scale-[0.98] ${
                  selected
                    ? 'bg-white/70 border-2 border-indigo-400 text-indigo-600'
                    : 'bg-gradient-to-r from-indigo-600 to-violet-600 text-white shadow-md shadow-indigo-200'
                }`}
              >
                {selected ? (
                  <>
                    <CheckCircle2 size={18} />
                    Selected
                  </>
                ) : (
                  <>
                    <Circle size={18} />
                    Select this experience
                  </>
                )}
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
