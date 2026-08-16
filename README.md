# CodeMap

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
```

- Backend: http://127.0.0.1:8000
- Frontend: http://localhost:5173
- Both need to be running at the same time.
