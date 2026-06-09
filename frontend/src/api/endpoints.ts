import client from './client'
import type { User, Experience, Place, Itinerary, PreferenceVector } from '@/types'

export const login = async (payload: {
  email: string
  password: string
}): Promise<{ access_token: string; user: User }> => {
  const { data } = await client.post<{ access_token: string; user: User }>(
    '/auth/login',
    payload,
  )
  return data
}

export const register = async (payload: {
  email: string
  password: string
  home_city: string
  age_range: string
  travel_with_children: boolean
}): Promise<{ access_token: string; user: User } | { message: string }> => {
  const { data } = await client.post<
    { access_token: string; user: User } | { message: string }
  >('/auth/register', payload)
  return data
}

export const verifyEmail = async (payload: {
  email: string
  code: string
}): Promise<{ access_token: string; user: User }> => {
  const { data } = await client.post<{ access_token: string; user: User }>(
    '/auth/verify-email',
    payload,
  )
  return data
}

export const logoutApi = async (): Promise<void> => {
  await client.post('/auth/logout')
}

export const updateProfile = async (payload: {
  home_city?: string
  age_range?: string
  travel_with_children?: boolean
}): Promise<User> => {
  const { data } = await client.patch<User>('/users/me', payload)
  return data
}

export const changePassword = async (payload: {
  current_password: string
  new_password: string
}): Promise<void> => {
  await client.put('/users/me/password', payload)
}

export const deleteAccount = async (): Promise<void> => {
  await client.delete('/users/me')
}

export const getExperiences = async (city: string): Promise<Experience[]> => {
  const { data } = await client.get<Experience[]>('/onboarding/experiences', {
    params: { city },
  })
  return data
}

export const submitExperienceChoices = async (
  experience_ids: string[],
): Promise<void> => {
  await client.post('/onboarding/experiences/choices', { experience_ids })
}

export const getRecommendations = async (city: string): Promise<Place[]> => {
  const { data } = await client.post<Place[]>('/recommendations', null, {
    params: { city },
  })
  return data
}

export const generateItinerary = async (payload: {
  city: string
  num_days: number
  travel_mode?: 'solo' | 'couple' | 'friends' | 'family'
}): Promise<Itinerary> => {
  const { data } = await client.post<Itinerary>('/itineraries/generate', payload)
  return data
}

export const getPreferences = async (): Promise<PreferenceVector> => {
  const { data } = await client.get<PreferenceVector>('/users/me/preferences')
  return data
}

export const getItinerary = async (id: string): Promise<Itinerary> => {
  const { data } = await client.get<Itinerary>(`/itineraries/${id}`)
  return data
}

export const markVisited = async (
  itineraryId: string,
  itemId: string,
  visitedAt?: string,
): Promise<{ item_id: string; poi_id: string; poi_name: string; visited_at: string }> => {
  const { data } = await client.post(
    `/itineraries/${itineraryId}/items/${itemId}/visited`,
    { visited_at: visitedAt ?? null },
  )
  return data
}

export const unmarkVisited = async (itineraryId: string, itemId: string): Promise<void> => {
  await client.delete(`/itineraries/${itineraryId}/items/${itemId}/visited`)
}
