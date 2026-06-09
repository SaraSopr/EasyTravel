import { Link, useLocation } from 'react-router-dom'
import { Home, Map, UserCircle } from 'lucide-react'
import useTripStore from '@/store/useTripStore'

export default function BottomNav() {
  const { pathname } = useLocation()
  const itineraryId = useTripStore((s) => s.itinerary?.itinerary_id)

  const navItems = [
    { to: '/home', icon: Home, label: 'Home' },
    { to: itineraryId ? `/itinerary/${itineraryId}` : null, icon: Map, label: 'Trip' },
    { to: '/profile', icon: UserCircle, label: 'Profile' },
  ]

  const isVisible =
    pathname === '/home' ||
    pathname === '/profile' ||
    pathname.startsWith('/itinerary/')

  if (!isVisible) return null

  return (
    <nav className="fixed bottom-0 left-1/2 -translate-x-1/2 w-full max-w-md bg-white/80 backdrop-blur-md border-t border-gray-100 flex shadow-lg">
      {navItems.map(({ to, icon: Icon, label }) => {
        const active = to
          ? pathname === to || (label === 'Trip' && pathname.startsWith('/itinerary/'))
          : false
        const inner = (
          <>
            <div
              className={`flex items-center justify-center w-10 h-7 rounded-full transition-all ${
                active ? 'bg-indigo-100' : ''
              }`}
            >
              <Icon size={20} className={active ? 'text-indigo-600' : 'text-gray-400'} />
            </div>
            <span className={`text-[10px] font-semibold ${active ? 'text-indigo-600' : 'text-gray-400'}`}>
              {label}
            </span>
          </>
        )
        return to ? (
          <Link
            key={label}
            to={to}
            className="flex-1 flex flex-col items-center pt-2.5 pb-4 gap-1 transition-colors"
          >
            {inner}
          </Link>
        ) : (
          <div
            key={label}
            className="flex-1 flex flex-col items-center pt-2.5 pb-4 gap-1 opacity-30"
          >
            {inner}
          </div>
        )
      })}
    </nav>
  )
}
