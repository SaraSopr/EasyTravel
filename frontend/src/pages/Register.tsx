import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Loader2, Mail, Lock, MapPin, ChevronDown, Check } from 'lucide-react'
import axios from 'axios'
import { register, verifyEmail } from '@/api/endpoints'
import useAuthStore from '@/store/useAuthStore'
import { useAgeRanges } from '@/hooks/useAgeRanges'
import { validatePassword, isPasswordValid } from '@/utils/passwordValidator'

export default function Register() {
  const navigate = useNavigate()
  const setAuth = useAuthStore((s) => s.setAuth)
  const AGE_RANGES = useAgeRanges()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [homeCity, setHomeCity] = useState('')
  const [ageRange, setAgeRange] = useState('18-25')
  const [travelWithChildren, setTravelWithChildren] = useState(false)
  const [verificationCode, setVerificationCode] = useState('')
  const [stage, setStage] = useState<'form' | 'otp'>('form')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [rateLimitError, setRateLimitError] = useState(false)

  const passwordReq = validatePassword(password)
  const formValid =
    email &&
    isPasswordValid(password) &&
    homeCity &&
    ageRange &&
    !rateLimitError

  const inputClass =
    'w-full border border-white/60 rounded-xl pl-10 pr-4 py-3 text-sm bg-white/55 shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:bg-white/85 transition-colors disabled:opacity-50'

  const handleRegisterSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setRateLimitError(false)
    if (!isPasswordValid(password)) {
      setError('Password does not meet all requirements.')
      return
    }
    setLoading(true)
    try {
      const result = await register({
        email,
        password,
        home_city: homeCity,
        age_range: ageRange,
        travel_with_children: travelWithChildren,
      })
      if ('access_token' in result) {
        setAuth(result.user, result.access_token)
        navigate('/onboarding')
      } else {
        setStage('otp')
        setError('')
      }
    } catch (err) {
      if (axios.isAxiosError(err)) {
        if (err.response?.status === 429) {
          setRateLimitError(true)
          setError('Too many registration attempts. Please try again later.')
        } else if (err.response?.status === 409) {
          setError('This email is already registered. Try signing in instead.')
        } else if (err.response?.status === 422) {
          const detail = (err.response.data as { detail: { msg: string }[] }).detail
          setError(detail.map((d) => d.msg).join(' '))
        } else {
          setError('Registration failed. Please check your details and try again.')
        }
      } else {
        setError('Registration failed. Please check your details and try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleVerifySubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setRateLimitError(false)
    if (!verificationCode.trim()) {
      setError('Please enter the verification code.')
      return
    }
    setLoading(true)
    try {
      const { access_token, user } = await verifyEmail({ email, code: verificationCode })
      setAuth(user, access_token)
      navigate('/onboarding')
    } catch (err) {
      if (axios.isAxiosError(err)) {
        if (err.response?.status === 429) {
          setRateLimitError(true)
          setError('Too many verification attempts. Please try again later.')
        } else if (err.response?.status === 400) {
          setError('Invalid or expired verification code. Please try again.')
        } else if (err.response?.status === 404) {
          setError('Email not found. Please register again.')
        } else {
          setError('Verification failed. Please try again.')
        }
      } else {
        setError('Verification failed. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  if (stage === 'otp') {
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

        <div className="relative bg-gradient-to-br from-indigo-600 via-violet-600 to-fuchsia-500 px-6 pt-16 pb-20 flex flex-col items-center text-center">
          <div className="glass-dark glass-specular w-14 h-14 rounded-2xl flex items-center justify-center mb-4">
            <Mail size={26} className="text-white" />
          </div>
          <h1 className="text-2xl font-extrabold text-white tracking-tight">Verify your email</h1>
          <p className="text-indigo-200 text-sm mt-1.5 font-medium">Code sent to {email}</p>
        </div>

        <div className="relative flex-1 -mt-6 rounded-t-3xl bg-gradient-to-b from-indigo-50/95 via-violet-50 to-gray-50 px-6 pt-6 pb-10">
          <div className="glass glass-specular rounded-3xl px-6 py-7">
            <form onSubmit={handleVerifySubmit} className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <label className="text-sm font-semibold text-gray-700" htmlFor="code">
                  Verification code
                </label>
                <input
                  id="code"
                  type="text"
                  required
                  value={verificationCode}
                  onChange={(e) => setVerificationCode(e.target.value.toUpperCase())}
                  className="w-full border border-white/60 rounded-xl px-4 py-3 text-sm bg-white/55 shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:bg-white/85 transition-colors disabled:opacity-50"
                  placeholder="Enter 6-digit code"
                  maxLength={6}
                  disabled={rateLimitError}
                />
              </div>

              {error && (
                <div className="text-sm text-red-600 bg-red-50/80 backdrop-blur-md border border-red-100/80 rounded-xl px-4 py-3">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={loading || rateLimitError}
                className="flex items-center justify-center gap-2 bg-gradient-to-r from-indigo-600 to-violet-600 text-white font-semibold rounded-xl py-3.5 mt-1 disabled:opacity-60 shadow-md shadow-indigo-200/70 active:scale-[0.98] transition-all"
              >
                {loading && <Loader2 size={18} className="animate-spin" />}
                {loading ? 'Verifying…' : 'Verify email'}
              </button>

              <button
                type="button"
                onClick={() => setStage('form')}
                className="text-sm text-center text-gray-500 mt-2"
              >
                Back to registration
              </button>
            </form>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="relative max-w-md mx-auto min-h-screen flex flex-col overflow-hidden bg-gradient-to-b from-indigo-50 via-violet-50 to-gray-50">
      <div
        aria-hidden="true"
        className="absolute left-[-4rem] top-[20rem] h-48 w-48 rounded-full bg-indigo-300/35 blur-3xl"
      />
      <div
        aria-hidden="true"
        className="absolute right-[-5rem] top-[34rem] h-56 w-56 rounded-full bg-fuchsia-300/25 blur-3xl"
      />

      <div className="relative bg-gradient-to-br from-indigo-600 via-violet-600 to-fuchsia-500 px-6 pt-16 pb-20 flex flex-col items-center text-center">
        <div className="glass-dark glass-specular w-14 h-14 rounded-2xl flex items-center justify-center mb-4">
          <span className="text-3xl" aria-hidden="true">✈️</span>
        </div>
        <h1 className="text-3xl font-extrabold text-white tracking-tight">EasyTravel</h1>
        <p className="text-indigo-200 text-sm mt-1.5 font-medium">Start planning your next trip</p>
      </div>

      <div className="relative flex-1 -mt-6 rounded-t-3xl bg-gradient-to-b from-indigo-50/95 via-violet-50 to-gray-50 px-6 pt-6 pb-10">
        <div className="glass glass-specular rounded-3xl px-6 py-7">
          <h2 className="text-xl font-bold text-gray-900 mb-1">Create your account</h2>
          <p className="text-gray-500 text-sm mb-6">Takes about 60 seconds</p>

          <form onSubmit={handleRegisterSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-semibold text-gray-700" htmlFor="reg-email">Email</label>
            <div className="relative">
              <Mail size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                id="reg-email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={inputClass}
                placeholder="you@example.com"
                disabled={rateLimitError}
              />
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-semibold text-gray-700" htmlFor="reg-password">Password</label>
            <div className="relative">
              <Lock size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                id="reg-password"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={inputClass}
                placeholder="Min. 8 characters"
                disabled={rateLimitError}
              />
            </div>
            {password && (
              <div className="grid grid-cols-2 gap-2 text-xs mt-1">
                {([
                  { key: 'minLength',      label: '8+ characters'     },
                  { key: 'hasUppercase',   label: 'Uppercase letter'  },
                  { key: 'hasLowercase',   label: 'Lowercase letter'  },
                  { key: 'hasDigit',       label: 'Number (0–9)'      },
                  { key: 'hasSpecialChar', label: 'Special char'      },
                ] as const).map(({ key, label }) => (
                  <div key={key} className={`flex items-center gap-1.5 ${passwordReq[key] ? 'text-green-700' : 'text-gray-400'}`}>
                    <div className={`w-3.5 h-3.5 rounded border flex items-center justify-center shrink-0 ${passwordReq[key] ? 'bg-green-50/80 border-green-400' : 'border-white/70 bg-white/35'}`}>
                      {passwordReq[key] && <Check size={10} className="text-green-700" />}
                    </div>
                    <span>{label}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-semibold text-gray-700" htmlFor="home-city">Home city</label>
            <div className="relative">
              <MapPin size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                id="home-city"
                type="text"
                required
                value={homeCity}
                onChange={(e) => setHomeCity(e.target.value)}
                className={inputClass}
                placeholder="e.g. Rome"
                disabled={rateLimitError}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-semibold text-gray-700" htmlFor="age-range">Age range</label>
              <div className="relative">
                <select
                  id="age-range"
                  value={ageRange}
                  onChange={(e) => setAgeRange(e.target.value)}
                  disabled={rateLimitError}
                  className="w-full appearance-none border border-white/60 rounded-xl px-4 py-3 pr-9 text-sm bg-white/55 shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:bg-white/85 transition-colors disabled:opacity-50"
                >
                  {AGE_RANGES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
                <ChevronDown size={15} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-semibold text-gray-700">With children?</span>
              <button
                type="button"
                onClick={() => setTravelWithChildren((v) => !v)}
                disabled={rateLimitError}
                className={`flex items-center justify-between border rounded-xl px-4 py-3 transition-colors disabled:opacity-50 ${
                  travelWithChildren
                    ? 'border-indigo-300 bg-white/80 shadow-sm'
                    : 'border-white/60 bg-white/45 shadow-[inset_0_1px_0_rgba(255,255,255,0.65)]'
                }`}
              >
                <span className={`text-sm font-medium ${travelWithChildren ? 'text-indigo-700' : 'text-gray-400'}`}>
                  {travelWithChildren ? 'Yes' : 'No'}
                </span>
                <div className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${travelWithChildren ? 'bg-indigo-600' : 'bg-gray-300'}`}>
                  <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${travelWithChildren ? 'translate-x-[18px]' : 'translate-x-[3px]'}`} />
                </div>
              </button>
            </div>
          </div>

          {error && (
            <div className="text-sm text-red-600 bg-red-50/80 backdrop-blur-md border border-red-100/80 rounded-xl px-4 py-3">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || rateLimitError || !formValid}
            className="flex items-center justify-center gap-2 bg-gradient-to-r from-indigo-600 to-violet-600 text-white font-semibold rounded-xl py-3.5 mt-1 disabled:opacity-60 shadow-md shadow-indigo-200/70 active:scale-[0.98] transition-all"
          >
            {loading && <Loader2 size={18} className="animate-spin" />}
            {loading ? 'Creating account…' : 'Create account'}
          </button>
          </form>

          <p className="text-sm text-center text-gray-500 mt-6">
            Already have an account?{' '}
            <Link to="/login" className="text-indigo-600 font-semibold">Sign in</Link>
          </p>
        </div>
      </div>
    </div>
  )
}
