# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# EasyTravel — Monorepo

This repo contains both the backend (FastAPI) and frontend (React/Vite) for EasyTravel.

```
EasyTravel/
├── backend/   # FastAPI + PostgreSQL (deployed on Railway)
└── frontend/  # React + Vite (deployed on Vercel)
```

For backend-specific instructions see [backend/CLAUDE.md](backend/CLAUDE.md).
For frontend-specific instructions see [frontend/CLAUDE.md](frontend/CLAUDE.md).

## Quick start

```bash
# Backend
cd backend
source .venv/bin/activate
python -m uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

## Deployment

- **Frontend**: Vercel — set Root Directory to `frontend`
- **Backend + DB**: Railway — set Root Directory to `backend`


