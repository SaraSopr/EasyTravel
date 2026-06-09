# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
npm run dev      # start dev server (localhost:5173), proxies /api → http://localhost:8000
npm run build    # tsc + vite build (must exit 0)
npm run preview  # preview production build
```

## Architecture

**Stack:** React 18 + TypeScript strict · Vite · TailwindCSS v3 · react-router-dom v6 · axios · zustand · lucide-react

**Layout constraint:** Every page root uses `max-w-md mx-auto min-h-screen`. No inline styles — Tailwind only (exception: dynamic `style={{ width }}` for score bars where arbitrary percentages can't be expressed statically).

### Key directories

| Path | Purpose |
|---|---|
| `src/types/index.ts` | All shared TypeScript interfaces (User, Place, Itinerary, etc.) |
| `src/api/client.ts` | Axios instance with auth interceptor (Bearer token from `auth_token` localStorage key) and 401 redirect |
| `src/api/endpoints.ts` | One typed async function per backend route |
| `src/store/useAuthStore.ts` | Zustand: `user`, `token`; `setAuth` writes to localStorage, `logout` clears it |
| `src/store/useTripStore.ts` | Zustand: `city`, `numDays`, `recommendations`, `selectedPlaceIds`, `itinerary` |
| `src/utils/categoryColors.ts` | Shared Tailwind class map for place/experience category badges |
| `src/components/` | ProtectedRoute, BottomNav, ExperienceCard, PlaceCard, ItineraryTimeline, LoadingSkeleton |
| `src/pages/` | Login, Register, Onboarding, Home, Recommendations, Itinerary |

### Auth flow
1. `POST /api/auth/register` → token saved to localStorage + zustand → `/onboarding`
2. `POST /api/auth/login` → token saved → `/home`
3. `ProtectedRoute` wraps all routes except `/login` and `/register`; redirects to `/login` if no token
4. 401 from any API call → clears localStorage token + hard redirect to `/login`

### Trip flow
`Home` → fetch recommendations → `useTripStore.setRecommendations` → `/recommendations` → select places → `generateItinerary` → `/itinerary/:id` → fetch + render `ItineraryTimeline`

### Lucide icon dynamic lookup (ExperienceCard)
`experience.icon` is used as a key into `* as LucideIcons`; falls back to `MapPin` if the key doesn't exist.

### BottomNav
Rendered inline in `App.tsx` alongside each protected page route (Home, Recommendations, Itinerary). Uses `useLocation` to determine the active tab.
