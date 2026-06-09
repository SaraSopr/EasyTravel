import { Navigate, Outlet } from 'react-router-dom'
import useAuthStore from '@/store/useAuthStore'

export default function ProtectedRoute() {
  const token = useAuthStore((s) => s.token)
  const user = useAuthStore((s) => s.user)

  if (!token || !user) {
    return <Navigate to="/login" replace />
  }

  return <Outlet />
}
