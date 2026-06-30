import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Loader2, Mail, Lock, AlertCircle } from 'lucide-react'
import axios from 'axios'
import { login } from '@/api/endpoints'
import useAuthStore from '@/store/useAuthStore'

export default function Login() {
  const navigate = useNavigate()
  const setAuth = useAuthStore((s) => s.setAuth)

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [rateLimitError, setRateLimitError] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setRateLimitError(false)
    setLoading(true)
    try {
      const { access_token, user } = await login({ email, password })
      setAuth(user, access_token)
      navigate('/home')
    } catch (err) {
      if (axios.isAxiosError(err)) {
        if (err.response?.status === 429) {
          setRateLimitError(true)
          setError('Too many login attempts. Please try again later.')
        } else if (err.response?.status === 403) {
          setError('Please verify your email first. Check your inbox for a verification code.')
        } else {
          setError('Invalid email or password. Please try again.')
        }
      } else {
        setError('Invalid email or password. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative max-w-md mx-auto min-h-screen flex flex-col overflow-hidden bg-gradient-to-b from-indigo-50 via-violet-50 to-gray-50">
      <div
        aria-hidden="true"
        className="absolute left-[-4rem] top-[20rem] h-48 w-48 rounded-full bg-indigo-300/35 blur-3xl"
      />
      <div
        aria-hidden="true"
        className="absolute right-[-5rem] top-[28rem] h-56 w-56 rounded-full bg-fuchsia-300/25 blur-3xl"
      />

      {/* Hero */}
      <div className="relative bg-gradient-to-br from-indigo-600 via-violet-600 to-fuchsia-500 px-6 pt-16 pb-20 flex flex-col items-center text-center">
        <div className="glass-dark glass-specular w-14 h-14 rounded-2xl flex items-center justify-center mb-4">
          <span className="text-3xl" aria-hidden="true">✈️</span>
        </div>
        <h1 className="text-3xl font-extrabold text-white tracking-tight">EasyTravel</h1>
        <p className="text-indigo-200 text-sm mt-1.5 font-medium">Your AI travel planner</p>
      </div>

      {/* Card */}
      <div className="relative flex-1 -mt-6 rounded-t-3xl bg-gradient-to-b from-indigo-50/95 via-violet-50 to-gray-50 px-6 pt-6 pb-10">
        <div className="glass glass-specular rounded-3xl px-6 py-7">
          <h2 className="text-xl font-bold text-gray-900 mb-1">Welcome back</h2>
          <p className="text-gray-500 text-sm mb-6">Sign in to continue</p>

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-semibold text-gray-700" htmlFor="email">Email</label>
              <div className="relative">
                <Mail size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  id="email"
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full border border-white/60 rounded-xl pl-10 pr-4 py-3 text-sm bg-white/55 shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:bg-white/85 transition-colors disabled:opacity-50"
                  placeholder="you@example.com"
                  disabled={rateLimitError}
                />
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-semibold text-gray-700" htmlFor="password">Password</label>
              <div className="relative">
                <Lock size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  id="password"
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full border border-white/60 rounded-xl pl-10 pr-4 py-3 text-sm bg-white/55 shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:bg-white/85 transition-colors disabled:opacity-50"
                  placeholder="••••••••"
                  disabled={rateLimitError}
                />
              </div>
            </div>

            {error && (
              <div
                className={`flex items-start gap-2.5 text-sm rounded-xl px-4 py-3 border backdrop-blur-md ${
                  error.includes('verify your email')
                    ? 'bg-amber-50/80 border-amber-100/80 text-amber-700'
                    : 'bg-red-50/80 border-red-100/80 text-red-600'
                }`}
              >
                <AlertCircle size={16} className="flex-shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={loading || rateLimitError}
              className="flex items-center justify-center gap-2 bg-gradient-to-r from-indigo-600 to-violet-600 text-white font-semibold rounded-xl py-3.5 mt-1 disabled:opacity-60 shadow-md shadow-indigo-200/70 active:scale-[0.98] transition-transform"
            >
              {loading && <Loader2 size={18} className="animate-spin" />}
              {loading ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          <p className="text-sm text-center text-gray-500 mt-6">
            Don't have an account?{' '}
            <Link to="/register" className="text-indigo-600 font-semibold">Register</Link>
          </p>
        </div>
      </div>
    </div>
  )
}
