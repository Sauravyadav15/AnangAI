# AnangAI (Vite + React + FastAPI)

This repository contains:
- **Frontend**: React + Vite app (root `src/`)
- **Backend**: FastAPI app (`backend/main.py`)
- **Vercel serverless bridge**: `api/[...path].py`

## Local development

### 1) Frontend
```bash
npm install
npm run dev
```
Frontend runs on `http://localhost:5173` and proxies `/api/*` to `http://127.0.0.1:8000`.

### 2) Backend
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

## Deploy to Vercel (frontend + backend together)

This repo is configured so one Vercel project serves both static frontend and Python backend.

### 1) Import the repo
- Go to **Vercel Dashboard → Add New Project**
- Import this Git repository
- Framework preset can remain auto-detected

### 2) Build/runtime configuration
`vercel.json` already handles both runtimes:
- `@vercel/static-build` for Vite frontend (`dist`)
- `@vercel/python` for `/api/*` routes via `api/[...path].py`

### 3) Environment variables
Set these in **Project Settings → Environment Variables** as needed:
- `OPENROUTER_API_KEY` (required for AI-powered backend routes)
- `FRONTEND_ORIGIN` (optional, e.g. your production domain)
- `ENV=production` (recommended)

### 4) Deploy
Every push to your connected branch triggers deployment.

## Useful checks

```bash
npm run lint
npm run build
python -m compileall api backend
```

## Notes
- Data is currently persisted in text files under `backend/` (`database.txt`, `applications.txt`, etc.). On serverless platforms this storage is ephemeral.
- For production persistence, migrate to a managed database/storage service.
