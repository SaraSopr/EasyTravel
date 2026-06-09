import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import ProtectedRoute from '@/components/ProtectedRoute'
import BottomNav from '@/components/BottomNav'
import Login from '@/pages/Login'
import Register from '@/pages/Register'
import Onboarding from '@/pages/Onboarding'
import Home from '@/pages/Home'
import Recommendations from '@/pages/Recommendations'
import Itinerary from '@/pages/Itinerary'
import Profile from '@/pages/Profile'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/login" replace />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />

        <Route element={<ProtectedRoute />}>
          <Route path="/onboarding" element={<Onboarding />} />
          <Route
            path="/home"
            element={
              <>
                <Home />
                <BottomNav />
              </>
            }
          />
          <Route
            path="/recommendations"
            element={
              <>
                <Recommendations />
                <BottomNav />
              </>
            }
          />
          <Route
            path="/itinerary/:id"
            element={
              <>
                <Itinerary />
                <BottomNav />
              </>
            }
          />
          <Route
            path="/profile"
            element={
              <>
                <Profile />
                <BottomNav />
              </>
            }
          />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
