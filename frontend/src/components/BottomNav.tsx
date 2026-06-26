import { Link, useLocation } from 'react-router-dom'
import { Home, Map, UserCircle } from 'lucide-react'

export default function BottomNav() {
  const { pathname } = useLocation()

  const navItems = [
    { to: '/home',         icon: Home,       label: 'Home'    },
    { to: '/itineraries',  icon: Map,        label: 'Trip'    },
    { to: '/profile',      icon: UserCircle, label: 'Profile' },
  ]

  const isVisible =
    pathname === '/home' ||
    pathname === '/profile' ||
    pathname === '/itineraries' ||
    pathname.startsWith('/itinerary/')

  if (!isVisible) return null

  return (
    <nav className="fixed bottom-4 left-1/2 -translate-x-1/2 w-[calc(100%-2rem)] max-w-[26rem] glass glass-specular rounded-[1.75rem] flex shadow-xl z-30">
      {navItems.map(({ to, icon: Icon, label }) => {
        const active = pathname === to || (label === 'Trip' && pathname.startsWith('/itinerary/'))
        return (
          <Link
            key={label}
            to={to}
            className="flex-1 flex flex-col items-center pt-2.5 pb-2.5 gap-1 transition-colors"
          >
            <div
              className={`flex items-center justify-center w-10 h-7 rounded-full transition-all ${
                active ? 'bg-indigo-600/15' : ''
              }`}
            >
              <Icon size={20} className={active ? 'text-indigo-600' : 'text-gray-500'} />
            </div>
            <span className={`text-[10px] font-semibold ${active ? 'text-indigo-600' : 'text-gray-500'}`}>
              {label}
            </span>
          </Link>
        )
      })}
    </nav>
  )
}
