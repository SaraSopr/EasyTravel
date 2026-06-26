import { create } from 'zustand'
import type { User } from '@/types'

const DEV_MODE = import.meta.env.VITE_DEV_MODE === 'true'
const DEV_USER_EMAIL = import.meta.env.VITE_DEV_USER_EMAIL || 'test@test.it'

const DEV_USER: User = {
  id: 'dev',
  email: DEV_USER_EMAIL,
  home_city: '',
  age_range: '',
  travel_with_children: false,
  preferences: { nature: 0, culture: 0.5, food: 0.5, adventure: 0, nightlife: 0, relax: 0, family_friendly: 0 },
}

interface AuthState {
  user: User | null
  token: string | null
  setAuth: (user: User, token: string) => void
  logout: () => void
}

function getStoredUser(): User | null {
  if (DEV_MODE) return DEV_USER
  const raw = localStorage.getItem('auth_user')
  if (!raw) return null

  try {
    return JSON.parse(raw) as User
  } catch {
    localStorage.removeItem('auth_user')
    return null
  }
}

if (DEV_MODE) {
  localStorage.setItem('auth_token', 'dev')
  localStorage.setItem('auth_user', JSON.stringify(DEV_USER))
}

const useAuthStore = create<AuthState>((set) => ({
  user: getStoredUser(),
  token: DEV_MODE ? 'dev' : localStorage.getItem('auth_token'),
  setAuth: (user, token) => {
    localStorage.setItem('auth_token', token)
    localStorage.setItem('auth_user', JSON.stringify(user))
    set({ user, token })
  },
  logout: () => {
    localStorage.removeItem('auth_token')
    localStorage.removeItem('auth_user')
    set({ user: null, token: null })
  },
}))

export default useAuthStore
