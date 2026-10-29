"""FastAPI entry point. Run from the repo root:

    uvicorn backend.main:app --reload --port 8000

Routes:
- GET /health: is the server up, is replay on, are the keys loaded (booleans only).
- POST /analyze and GET /jobs/{job_id}: added on the day, backed by jobs.py.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings

app = FastAPI(title="ReelMind AI")

# The Vite dev server runs on 5173 and calls this API directly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "replay": settings.replay,
        "tinyfish_key_loaded": bool(settings.tinyfish_api_key),
        "gemini_key_loaded": bool(settings.gemini_api_key),
    }
