import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { LogOut, MapPin, Users, Calendar, Pencil, X, Check, Lock, Trash2, Loader2, ChevronDown } from 'lucide-react'
import axios from 'axios'
import { logoutApi, updateProfile, changePassword, deleteAccount, getPreferences } from '@/api/endpoints'
import useAuthStore from '@/store/useAuthStore'
import { useAgeRanges } from '@/hooks/useAgeRanges'
import { validatePassword, isPasswordValid } from '@/utils/passwordValidator'
import type { PreferenceVector } from '@/types'

const PREFERENCE_META: Record<keyof PreferenceVector, { label: string; emoji: string }> = {
  culture:         { label: 'Culture',   emoji: '🎭' },
  food:            { label: 'Food',      emoji: '🍝' },
  nature:          { label: 'Nature',    emoji: '🌿' },
  adventure:       { label: 'Adventure', emoji: '🏔️' },
  relax:           { label: 'Relax',     emoji: '☀️' },
  nightlife:       { label: 'Nightlife', emoji: '🌙' },
  family_friendly: { label: 'Family',    emoji: '👨‍👩‍👧' },
}

function getInitials(email: string) {
  return email.split('@')[0].slice(0, 2).toUpperCase()
}

function getFirstName(email: string) {
  const name = email.split('@')[0]
  return name.charAt(0).toUpperCase() + name.slice(1)
}

export default function Profile() {
  const navigate = useNavigate()
  const { user, setAuth, logout } = useAuthStore()
  const AGE_RANGES = useAgeRanges()

  const [editing, setEditing] = useState(false)
  const [homeCity, setHomeCity] = useState(user?.home_city ?? '')
  const [ageRange, setAgeRange] = useState(user?.age_range ?? '18-25')
  const [travelWithChildren, setTravelWithChildren] = useState(user?.travel_with_children ?? false)
  const [saving, setSaving] = useState(false)
  const [editError, setEditError] = useState('')

  const [showPassword, setShowPassword] = useState(false)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [changingPassword, setChangingPassword] = useState(false)
  const [passwordError, setPasswordError] = useState('')
  const [passwordSuccess, setPasswordSuccess] = useState(false)

  const [preferences, setPreferences] = useState<PreferenceVector | null>(user?.preferences ?? null)
  useEffect(() => {
    getPreferences().then(setPreferences).catch(() => {/* fallback to store data */})
  }, [])

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')

  const passwordReq = validatePassword(newPassword)

  if (!user) return null

  const handleLogout = async () => {
    try { await logoutApi() } catch { /* ignore */ }
    logout()
    navigate('/login', { replace: true })
  }

  const handleSaveProfile = async () => {
    setEditError('')
    setSaving(true)
    try {
      const updated = await updateProfile({ home_city: homeCity, age_range: ageRange, travel_with_children: travelWithChildren })
      setAuth(updated, useAuthStore.getState().token!)
      setEditing(false)
    } catch {
      setEditError('Failed to update profile. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const handleCancelEdit = () => {
    setHomeCity(user.home_city)
    setAgeRange(user.age_range)
    setTravelWithChildren(user.travel_with_children)
    setEditError('')
    setEditing(false)
  }

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault()
    setPasswordError('')
    setPasswordSuccess(false)
    if (!isPasswordValid(newPassword)) {
      setPasswordError('New password does not meet all requirements.')
      return
    }
    setChangingPassword(true)
    try {
      await changePassword({ current_password: currentPassword, new_password: newPassword })
      setPasswordSuccess(true)
      setCurrentPassword('')
      setNewPassword('')
      setShowPassword(false)
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 401) {
        setPasswordError('Current password is incorrect.')
      } else {
        setPasswordError('Failed to change password. Please try again.')
      }
    } finally {
      setChangingPassword(false)
    }
  }

  const handleDeleteAccount = async () => {
    setDeleteError('')
    setDeleting(true)
    try {
      await deleteAccount()
      logout()
      navigate('/login', { replace: true })
    } catch {
      setDeleteError('Failed to delete account. Please try again.')
      setDeleting(false)
    }
  }

  const inputClass = 'w-full border border-white/60 rounded-xl px-4 py-3 text-sm bg-white/55 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:bg-white/85 transition-colors'

  return (
    <div className="max-w-md mx-auto min-h-screen flex flex-col bg-gradient-to-b from-indigo-50 via-gray-50 to-gray-50 pb-28">
      {/* Header */}
      <div className="bg-gradient-to-br from-indigo-600 via-violet-600 to-fuchsia-500 px-6 pt-14 pb-20">
        <div className="flex flex-col items-center gap-3">
          <div className="w-16 h-16 rounded-full glass-dark glass-specular flex items-center justify-center">
            <span className="text-xl font-extrabold text-white">{getInitials(user.email)}</span>
          </div>
          <div className="text-center">
            <h1 className="text-2xl font-extrabold text-white tracking-tight">{getFirstName(user.email)}</h1>
            <p className="text-indigo-200 text-sm mt-1">{user.email}</p>
          </div>
        </div>
      </div>

      <div className="flex-1 bg-gray-50 rounded-t-3xl -mt-6 px-6 pt-6 flex flex-col gap-4">

        {/* Profile info card */}
        <div className="glass glass-specular rounded-3xl p-5 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <span className="text-sm font-bold text-gray-800">Profile info</span>
            {!editing ? (
              <button onClick={() => setEditing(true)} className="flex items-center gap-1 text-indigo-500 text-sm font-semibold">
                <Pencil size={14} /> Edit
              </button>
            ) : (
              <div className="flex gap-3">
                <button onClick={handleCancelEdit} className="flex items-center gap-1 text-gray-400 text-sm font-medium">
                  <X size={14} /> Cancel
                </button>
                <button onClick={handleSaveProfile} disabled={saving} className="flex items-center gap-1 text-indigo-500 text-sm font-semibold disabled:opacity-50">
                  {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />} Save
                </button>
              </div>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="flex items-center gap-1.5 text-xs text-gray-400 font-medium">
              <MapPin size={13} /> Home city
            </label>
            {editing ? (
              <input value={homeCity} onChange={(e) => setHomeCity(e.target.value)} className={inputClass} placeholder="e.g. Rome" />
            ) : (
              <p className="text-sm font-semibold text-gray-800">{user.home_city}</p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="flex items-center gap-1.5 text-xs text-gray-400 font-medium">
              <Calendar size={13} /> Age range
            </label>
            {editing ? (
              <div className="relative">
                <select value={ageRange} onChange={(e) => setAgeRange(e.target.value)} className="w-full appearance-none border border-white/60 rounded-xl px-4 py-3 pr-9 text-sm bg-white/55 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:bg-white/85 transition-colors">
                  {AGE_RANGES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
                <ChevronDown size={15} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
              </div>
            ) : (
              <p className="text-sm font-semibold text-gray-800">{user.age_range}</p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="flex items-center gap-1.5 text-xs text-gray-400 font-medium">
              <Users size={13} /> Travelling with children
            </label>
            {editing ? (
              <button
                type="button"
                onClick={() => setTravelWithChildren((v) => !v)}
                className={`flex items-center justify-between border rounded-xl px-4 py-3 transition-colors ${
                  travelWithChildren ? 'border-indigo-300 bg-white/80 shadow-sm' : 'border-white/60 bg-white/45'
                }`}
              >
                <span className={`text-sm font-medium ${travelWithChildren ? 'text-indigo-700' : 'text-gray-400'}`}>
                  {travelWithChildren ? 'Yes' : 'No'}
                </span>
                <div className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${travelWithChildren ? 'bg-indigo-600' : 'bg-gray-300'}`}>
                  <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${travelWithChildren ? 'translate-x-[18px]' : 'translate-x-[3px]'}`} />
                </div>
              </button>
            ) : (
              <p className="text-sm font-semibold text-gray-800">{user.travel_with_children ? 'Yes' : 'No'}</p>
            )}
          </div>

          {editError && <p className="text-sm text-red-500">{editError}</p>}
        </div>

        {/* Travel preferences */}
        <div className="glass glass-specular rounded-3xl p-5 flex flex-col gap-4">
          <span className="text-sm font-bold text-gray-800">Travel preferences</span>
          <div className="flex flex-col gap-3">
            {preferences && (Object.entries(preferences) as [keyof PreferenceVector, number][])
              .sort(([, a], [, b]) => b - a)
              .map(([key, value]) => {
                const { label, emoji } = PREFERENCE_META[key]
                const pct = Math.round(value * 100)
                return (
                  <div key={key} className="flex items-center gap-3">
                    <span className="text-base w-5 shrink-0">{emoji}</span>
                    <span className="text-xs font-medium text-gray-600 w-20 shrink-0">{label}</span>
                    <div className="flex-1 bg-white/55 rounded-full h-1.5 overflow-hidden">
                      <div
                        className="bg-gradient-to-r from-indigo-500 to-violet-500 h-2 rounded-full transition-all"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="text-xs font-semibold text-gray-500 w-8 text-right shrink-0">{pct}%</span>
                  </div>
                )
              })}
          </div>
        </div>

        {/* Change password */}
        <div className="glass glass-specular rounded-3xl overflow-hidden">
          <button
            onClick={() => { setShowPassword((v) => !v); setPasswordError(''); setPasswordSuccess(false) }}
            className="w-full flex items-center justify-between px-5 py-4"
          >
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-xl bg-white/60 border border-white/60 flex items-center justify-center">
                <Lock size={16} className="text-indigo-500" />
              </div>
              <span className="text-sm font-semibold text-gray-800">Change password</span>
            </div>
            <ChevronDown size={16} className={`text-gray-400 transition-transform ${showPassword ? 'rotate-180' : ''}`} />
          </button>

          {showPassword && (
            <form onSubmit={handleChangePassword} className="px-5 pb-5 flex flex-col gap-3 border-t border-white/45 pt-4">
              <input
                type="password"
                placeholder="Current password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                className={inputClass}
                required
              />
              <div className="flex flex-col gap-1.5">
                <input
                  type="password"
                  placeholder="New password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className={inputClass}
                  required
                />
                {newPassword && (
                  <div className="grid grid-cols-2 gap-1.5 text-xs mt-0.5">
                    {[
                      { key: 'minLength',      label: '8+ characters'  },
                      { key: 'hasUppercase',   label: 'Uppercase'      },
                      { key: 'hasLowercase',   label: 'Lowercase'      },
                      { key: 'hasDigit',       label: 'Number'         },
                      { key: 'hasSpecialChar', label: 'Special char'   },
                    ].map(({ key, label }) => (
                      <div key={key} className={`flex items-center gap-1 ${passwordReq[key as keyof typeof passwordReq] ? 'text-green-700' : 'text-gray-400'}`}>
                        <Check size={10} className={passwordReq[key as keyof typeof passwordReq] ? 'opacity-100' : 'opacity-0'} />
                        {label}
                      </div>
                    ))}
                  </div>
                )}
              </div>
              {passwordError && <p className="text-sm text-red-500">{passwordError}</p>}
              {passwordSuccess && <p className="text-sm text-green-600 font-medium">Password changed successfully.</p>}
              <button
                type="submit"
                disabled={changingPassword}
                className="flex items-center justify-center gap-2 bg-gradient-to-r from-indigo-600 to-violet-600 text-white font-semibold rounded-xl py-3 disabled:opacity-50 active:scale-[0.98] transition-all"
              >
                {changingPassword && <Loader2 size={16} className="animate-spin" />}
                {changingPassword ? 'Saving…' : 'Update password'}
              </button>
            </form>
          )}
        </div>

        {/* Logout */}
        <button
          onClick={handleLogout}
          className="glass glass-specular flex items-center justify-center gap-2 w-full text-gray-600 font-semibold rounded-3xl py-4 active:scale-[0.98] transition-transform"
        >
          <LogOut size={18} />
          Log out
        </button>

        {/* Delete account */}
        {!showDeleteConfirm ? (
          <button
            onClick={() => setShowDeleteConfirm(true)}
            className="flex items-center justify-center gap-2 w-full bg-red-50/80 backdrop-blur border border-red-100/80 text-red-500 font-semibold rounded-3xl py-4 active:scale-[0.98] transition-transform"
          >
            <Trash2 size={18} />
            Delete account
          </button>
        ) : (
          <div className="bg-red-50/85 backdrop-blur border border-red-100/80 rounded-3xl p-5 flex flex-col gap-3">
            <p className="text-sm font-semibold text-red-700">Are you sure? This cannot be undone.</p>
            {deleteError && <p className="text-sm text-red-500">{deleteError}</p>}
            <div className="flex gap-3">
              <button
                onClick={() => { setShowDeleteConfirm(false); setDeleteError('') }}
                className="flex-1 py-3 rounded-xl border border-white/70 bg-white/75 text-gray-600 text-sm font-semibold"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteAccount}
                disabled={deleting}
                className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl bg-red-500 text-white text-sm font-semibold disabled:opacity-50"
              >
                {deleting && <Loader2 size={15} className="animate-spin" />}
                {deleting ? 'Deleting…' : 'Yes, delete'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
