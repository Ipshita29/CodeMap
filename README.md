# CodeMap

CodeMap is an AI-powered repository intelligence platform. Paste a public GitHub URL and it clones,
scans, and parses the repository, then lets you explore it through an interactive dependency graph,
execution-flow tracing, change-impact analysis, Git history, a heuristic health score, AI-generated
summaries and Q&A, and exportable reports — all in a single-page app, without needing to read the
code yourself first.

## What it does

- **Repository scanning** — file/folder structure, languages, frameworks, and basic statistics
- **Code intelligence** — Tree-sitter-based parsing of Python/JavaScript/TypeScript into functions,
  classes, imports, exports, call relationships, and detected API routes
- **AI understanding** — beginner and developer repository summaries, and grounded Q&A over the
  actual codebase (no hallucinated files or functions — answers cite real source)
- **Interactive graph** — an architecture/dependency view of the repository built with React Flow,
  with search, filtering, and automatic layout
- **Execution flow tracing** — follows a feature from a starting file through resolved function
  calls, detected frontend API calls, and matched backend routes, with an explicit confidence level
  (high/medium/low/unknown) on every step — never presented as fact when it isn't verified
- **Change impact analysis** — direct/indirect dependents of a file, related API routes, and a
  heuristic structural risk score, with an AI explanation grounded only in that structural evidence
- **Git intelligence** — latest commit, commit history/timeline, per-file history, and repository
  activity stats (contributors, recent commit volume, most-changed files)
- **Repository health** — a deterministic 0–100 score across structure, dependencies, complexity,
  architecture, documentation, and testing, with concrete findings and recommendations
- **Export** — Markdown, JSON, and PDF reports assembled from what's already been analyzed in the
  session, plus copy-to-clipboard sharing

## Tech stack

- **Backend**: FastAPI (Python), Tree-sitter, GitPython, fpdf2
- **Frontend**: React 19, Vite, TanStack Query, React Flow, Dagre

## Run it

**Backend** (from `backend/`):

```bash
source venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

First time only:

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in OPENAI_API_KEY etc.
```

**Frontend** (from `frontend/`):

```bash
npm run dev
```

First time only:

```bash
cd frontend
npm install
cp .env.example .env   # only needed if the backend isn't on localhost:8000
```

- Backend: http://127.0.0.1:8000
- Frontend: http://localhost:5173
- Both need to be running at the same time.

## Configuration

**Backend** (`backend/.env`):

| Variable | Purpose |
| --- | --- |
| `CORS_ORIGINS` | JSON list of allowed frontend origins |
| `OPENAI_API_KEY` | Required for AI summaries/chat/impact explanations. Works with OpenAI or any OpenAI-compatible provider (e.g. Groq's free tier) |
| `OPENAI_BASE_URL` | Leave blank for OpenAI directly, or point at a compatible provider |
| `OPENAI_MODEL` | Model name for the configured provider |

**Frontend** (`frontend/.env`):

| Variable | Purpose |
| --- | --- |
| `VITE_API_BASE_URL` | Backend URL. Defaults to `http://localhost:8000` if unset |

AI features degrade gracefully without a key configured — structural analysis (graph, flow, impact,
Git, health) all work independently of the AI provider.

## Project structure

```
backend/app/
  analyzer/     # file scanning, folder tree, Tree-sitter parsing (Day 2-3)
  ai/           # context building + prompts for summaries/chat (Day 4)
  graph/        # architecture/dependency graph builder (Day 5)
  flow/         # execution-flow tracing (Day 6)
  impact/       # change-impact analysis (Day 6)
  git/          # Git history/activity (Day 7)
  health/       # repository health scoring (Day 7)
  export/       # PDF rendering (Day 7)
  api/          # FastAPI routers
  services/     # cloning, storage, orchestration

frontend/src/
  pages/        # landing, analysis (all feature tabs), repository insights
  components/   # RepositoryGraph (React Flow), FileDetailsPanel
  lib/          # export report builders
  api.js        # backend client
```
