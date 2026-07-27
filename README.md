# AnangAI — AI Concierge & Local Business Portal for Kingston, ON

AnangAI (internally named **KingstonAssist**) is a full-stack web app that helps residents and visitors discover restaurants, cafés, shops, attractions, and events in Kingston, Ontario through a conversational AI assistant — and helps local businesses get discovered through a guided "Get Featured" onboarding pipeline tied to real City of Kingston licensing steps.

It combines a custom retrieval pipeline over curated local business/event data with an LLM, a bilingual (English/French) React frontend, and an admin-reviewed partner program with a sustainability rating system ("Green Plate Certification").

> 🏆 Built at **QHacks**, Queen's University's annual hackathon in Kingston, ON.

## ✨ Features

**AI Assistant**
- Conversational chat interface that answers natural-language questions like *"where can I get vegan food downtown?"* or *"what's happening this weekend?"*
- Custom retrieval pipeline: intent detection + fuzzy keyword matching (handles typos) pulls relevant entries from local data before generating an answer — no vector database required.
- Date-aware event filtering (e.g. resolves "this weekend" or a specific month to real calendar dates).
- Responses generated via an LLM through the OpenRouter API.

**Discovery Page**
- Browse categorized local listings (restaurants, bakeries, cafés, breweries & pubs, ice cream/gelato, shops, places to visit, events) without needing to chat.
- Categories and entries are driven dynamically by the data files on the backend.

**Green Plate Certification (sustainability rating)**
- Food businesses can carry a Gold / Silver / Bronze / uncertified rating based on local sourcing and vegetarian/vegan options.
- The assistant and discovery listings surface higher-certified businesses first.

**Get Featured — Business Onboarding**
- Local businesses apply to be listed via a category-specific form (food businesses vs. shops have different fields).
- Applications go through an **admin review queue** (approve/reject) before a business account is finalized.
- Approved businesses get a login and a **dashboard** that tracks their progress through a 7-step civic licensing journey (provincial registration, zoning, HST/CRA setup, fire & health clearances, final city license) — including real City of Kingston contacts and links.

**Admin Portal**
- Token-based admin login separate from regular user auth.
- Dashboard to review pending applications, approve/reject businesses, and manage uploaded licensing documents.

**Bilingual UI**
- Full English/French translation support via a language-context hook (`src/locales/en.json`, `fr.json`).

## 🏗️ Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19, Vite 7, React Router 7, Tailwind CSS 4, Framer Motion, Lucide icons |
| Backend | FastAPI (Python), Pydantic, httpx |
| AI / LLM | OpenRouter API (`openai/gpt-4o-mini`) |
| Data layer | Structured `.txt` files per category (custom parser, no database yet) |
| Auth | Custom hashed-password auth (SHA-256) + token-based admin auth |
| Deployment | Vercel — static frontend (`@vercel/static-build`) + Python serverless functions (`@vercel/python`) via a Mangum-compatible bridge |

## 🧠 How the Assistant Answers a Question

```
User question
     │
     ▼
Normalize + expand keywords (typo-tolerant, fuzzy match)
     │
     ▼
Classify intent → food / places / events (+ sub-category)
     │
     ▼
Retrieve matching entries from Food/ Places/ Events data files
     │
     ▼
Sort food results by Green Plate Certification (Gold > Silver > Bronze)
     │
     ▼
Format retrieved entries as context
     │
     ▼
Send question + context to OpenRouter (gpt-4o-mini)
     │
     ▼
Return generated answer to the chat UI
```

## 📁 Project Structure

```
AnangAI/
├── src/                      # React frontend
│   ├── pages/                # HomePage, DiscoveryPage, GetFeaturedPage,
│   │                          # PartnerPage, DashboardPage, AdminDashboardPage, ...
│   ├── components/           # ChatInterface, DiscoveryCard, CertificationLeaves, ...
│   ├── context/               # Auth, AdminAuth, Language, App contexts
│   ├── hooks/                 # useTranslation, useGemini (chat API hook)
│   └── locales/               # en.json, fr.json
├── backend/
│   ├── main.py                # FastAPI app, all HTTP routes
│   ├── router.py              # Retrieval logic + OpenRouter call (`ask`)
│   ├── extractallevent.py     # Event data extraction helper
│   ├── webScraper/            # Raw scraped source data
│   └── Food/ Places/ Events/  # Structured local business & event data
├── api/[...path].py           # Vercel serverless entrypoint (imports FastAPI app)
├── vercel.json                # Routes both frontend + Python backend on one Vercel project
└── requirements.txt / package.json
```

## 🚀 Getting Started

### Prerequisites
- Node.js 18+
- Python 3.9+
- An [OpenRouter](https://openrouter.ai/keys) API key

### 1. Frontend
```bash
npm install
npm run dev
```
Runs on `http://localhost:5173` and proxies `/api/*` to `http://127.0.0.1:8000`.

### 2. Backend
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
```

Create `backend/.env`:
```
OPENROUTER_API_KEY=your_key_here
```

Then start the API:
```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

### 3. Verify
```bash
curl http://127.0.0.1:8000/api/health
```

## ⚙️ Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | Powers all AI chat responses. Get one at openrouter.ai/keys. |
| `FRONTEND_ORIGIN` | Production only | Your deployed frontend origin, for CORS. |
| `ENV` | Recommended | Set to `production` on deploy. |
| `VITE_API_URL` | Production only | Base API URL for the frontend when not using the Vite proxy. |

## 📡 Key API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/chat` | Ask the AI assistant a question |
| `GET` | `/api/discovery/categories` | List browsable categories |
| `GET` | `/api/discovery/data` | Get entries for a category |
| `POST` | `/api/submit-application` | Business "Get Featured" application |
| `POST` | `/api/admin/login` | Admin authentication |
| `GET` | `/api/admin/applications` | List pending applications (admin) |
| `POST` | `/api/admin/applications/approve` / `/reject` | Review an application |
| `POST` | `/api/register` / `/api/login` | Business account auth |
| `GET` | `/api/dashboard-data/{email}` | Business licensing-journey progress |
| `GET` | `/api/health` | Health check |

*(Full list in `backend/main.py`.)*

## ☁️ Deployment (Vercel)

This repo deploys as a **single Vercel project** serving both the static frontend and the Python backend:
1. Import the repo in the Vercel dashboard (framework auto-detected).
2. Set the environment variables above in **Project Settings → Environment Variables**.
3. `vercel.json` routes `/api/*` to the FastAPI app (via `api/[...path].py`) and everything else to the built frontend.
4. Every push to the connected branch triggers a new deployment.

## 🧪 Useful Checks

```bash
npm run lint
npm run build
python -m compileall api backend
```



## 👤 Author

Built by [Saurav Yadav](https://github.com/Sauravyadav15).
