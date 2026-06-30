import * as LucideIcons from 'lucide-react'
import { CheckCircle2 } from 'lucide-react'
import type { Experience } from '@/types'

interface ExperienceCardProps {
  experience: Experience
  selected: boolean
  onOpen: () => void
}

type LucideIcon = React.ComponentType<{ size?: number; className?: string }>

export default function ExperienceCard({ experience, selected, onOpen }: ExperienceCardProps) {
  const iconKey = experience.icon as keyof typeof LucideIcons
  const IconComponent =
    (LucideIcons[iconKey] as LucideIcon | undefined) ?? LucideIcons.MapPin

  return (
    <button
      onClick={onOpen}
      className={`glass glass-specular relative flex flex-col items-start gap-2.5 p-4 rounded-2xl border-2 text-left w-full transition-all active:scale-[0.97] ${
        selected
          ? 'border-indigo-400 bg-gradient-to-br from-indigo-50/90 to-violet-50/90 shadow-md shadow-indigo-100'
          : 'border-white/60'
      }`}
    >
      {selected && (
        <CheckCircle2 size={16} className="absolute top-3 right-3 text-indigo-500" />
      )}
      <div className={`p-2 rounded-xl border border-white/60 ${selected ? 'bg-indigo-100/80' : 'bg-white/55'}`}>
        <IconComponent
          size={22}
          className={selected ? 'text-indigo-600' : 'text-gray-500'}
        />
      </div>
      <span className="font-bold text-gray-900 text-sm leading-tight">
        {experience.name}
      </span>
      <span className="text-xs text-gray-400 leading-snug line-clamp-2">
        {experience.description}
      </span>
    </button>
  )
}
