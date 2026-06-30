import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { prefetchCities } from '@/api/endpoints'
import ProtectedRoute from '@/components/ProtectedRoute'
import BottomNav from '@/components/BottomNav'
import Login from '@/pages/Login'
import Register from '@/pages/Register'
import Onboarding from '@/pages/Onboarding'
import Home from '@/pages/Home'
import Recommendations from '@/pages/Recommendations'
import Itinerary from '@/pages/Itinerary'
import Itineraries from '@/pages/Itineraries'
import Profile from '@/pages/Profile'
import Evaluation from '@/pages/Evaluation'

export default function App() {
  // Warm the (effectively static) city list as soon as the app boots, so the
  // Home form's dropdown is ready before the user navigates there.
  useEffect(() => {
    prefetchCities()
  }, [])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/login" replace />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/eval" element={<Evaluation />} />

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
            path="/itineraries"
            element={
              <>
                <Itineraries />
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
