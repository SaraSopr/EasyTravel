# EasyTravel — Frontend

Mobile-first AI travel planner SPA built with React 18 + TypeScript.

## Stack

- **React 18** + **TypeScript** (strict)
- **Vite** — dev server + build
- **TailwindCSS v3** — styling
- **react-router-dom v6** — routing
- **axios** — HTTP client with auth interceptors
- **zustand** — global state (auth + trip)
- **lucide-react** — icons

## Commands

```bash
npm install       # install dependencies
npm run dev       # dev server at localhost:5173
npm run build     # type-check + production build
npm run preview   # preview production build
```

## Architecture

### Auth flow
1. `/register` → email verification (OTP) → `/onboarding`
2. `/login` → `/home`
3. All routes except `/login` and `/register` are protected — redirect to `/login` if no token
4. 401 from any API call → clears token + hard redirect to `/login`
5. `POST /api/auth/logout` is called on logout to invalidate the token server-side

### Trip flow
`/home` → enter city + days → fetch recommendations → `/recommendations` → select places → generate itinerary → `/itinerary/:id`

### Pages

| Route | Page | Description |
|---|---|---|
| `/login` | Login | Email + password sign in |
| `/register` | Register | Sign up with OTP email verification |
| `/onboarding` | Onboarding | Pick travel experience preferences |
| `/home` | Home | Enter destination + trip duration |
| `/recommendations` | Recommendations | Browse and select places |
| `/itinerary/:id` | Itinerary | AI-generated day-by-day timeline |
| `/profile` | Profile | Edit profile, change password, delete account |

### Key files

| Path | Purpose |
|---|---|
| `src/types/index.ts` | Shared TypeScript interfaces |
| `src/api/client.ts` | Axios instance — Bearer token injection, 401 redirect |
| `src/api/endpoints.ts` | One typed function per backend route |
| `src/store/useAuthStore.ts` | Auth state — user, token, persisted in localStorage |
| `src/store/useTripStore.ts` | Trip state — city, days, recommendations, itinerary |
| `src/components/ProtectedRoute.tsx` | Guards auth-required routes |
| `src/components/BottomNav.tsx` | Fixed bottom navigation (Home / Explore / Trip / Profile) |

## Deployment

Deployed on **Vercel**, backend proxied from **Railway**.

`vercel.json` rewrites:
- `/api/*` → Railway backend
- `/*` → `index.html` (SPA fallback)
