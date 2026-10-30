"""FastAPI entry point. Run from the repo root:

    uvicorn backend.main:app --reload --port 8000

Routes:
- GET /health: is the server up, is replay on, are the keys loaded (booleans only).
- POST /analyze: video + topic -> 202 {job_id}; the job runs in the background (jobs.run_job).
  A bad file or topic is a 400 whose detail the UI shows as-is. With REPLAY=1 it starts a
  replay of the newest recording instead (503 if there is none).
- GET /jobs/{job_id}: the Job (backend/models.py) for the UI to poll; 404 if unknown.
"""

import os
import tempfile
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from backend import jobs, video
from backend.config import settings
from backend.instagram_parse import TopicRejected, normalise_topic
from backend.video import VideoRejected

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


@app.post("/analyze", status_code=202)
async def analyze(
    background: BackgroundTasks,
    file: UploadFile | None = File(None),
    topic: str | None = Form(None),
) -> dict:
    if file is None or not file.filename:
        raise HTTPException(400, "Choose a video to upload (.mp4 or .mov, up to 60 s).")
    if settings.replay:
        try:
            replay = await jobs.start_replay(normalise_topic(topic))
        except TopicRejected as exc:
            raise HTTPException(400, str(exc)) from exc
        except jobs.ReplayUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        return {"job_id": replay.id}

    # The upload goes to a temp file first; create_job() checks it and copies it under the job's
    # own id. The user's file name is only used for its suffix, never as a path.
    fd, tmp = tempfile.mkstemp(prefix="reelmind-", suffix=".upload")
    try:
        with os.fdopen(fd, "wb") as out:
            size = 0
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > video.MAX_BYTES:
                    raise VideoRejected(f"Video is over {video.MAX_BYTES // 1024 // 1024} MB; the limit is 50 MB.")
                out.write(chunk)
        job = await jobs.create_job(Path(tmp), file.filename, topic or "")
    except (TopicRejected, VideoRejected) as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        Path(tmp).unlink(missing_ok=True)
    background.add_task(jobs.run_job, job.id)
    return {"job_id": job.id}


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, "We couldn't find that analysis.")
    return job.model_dump(mode="json")
