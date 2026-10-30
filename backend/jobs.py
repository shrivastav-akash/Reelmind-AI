"""Job runner. BUILT ON FRIDAY (tasks A4, A6).

Called by main.py. One job = one analysis:

    create_job()  save upload, guard it, write a queued Job to data/jobs/{id}.json
    run_job()     video stream and Niche Scout at the same time (asyncio.gather),
                  then recommend; every change appends an Event and rewrites the
                  job file, which GET /jobs/{id} returns
    start_replay() REPLAY=1: re-emit a recorded job's events on their original
                  timing, with replay=true so the UI shows the banner

Failure rules: a failed stream marks its stage failed with a reason and the
job carries on; TinyFishAccountError (bad key / no credits) fails the whole
job with a plain message. "Done" is defined by tests/test_jobs.py.

Call other modules through the module (`video.measure`, `vision.analyse_opening`,
`niche_scout.run_niche_scout`, `recommend.recommend`) so tests can swap them.
"""

from __future__ import annotations

import asyncio
import re
import secrets
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend import instagram_parse, niche_scout, recommend, video, vision
from backend.config import settings
from backend.models import Event, Job, StageState
from backend.tinyfish_client import TinyFishAccountError

JOB_ID = r"^[0-9a-f]{12}$"  # get_job() refuses anything else, so an id can never be a path
_JOB_ID_RE = re.compile(JOB_ID)
# Background replay tasks: asyncio only keeps weak references, so hold them until they finish.
_replays: set[asyncio.Task] = set()


class ReplayUnavailable(Exception):
    """REPLAY=1 but no recording exists. main.py answers 503 "No recorded run ..."."""


def _jobs_dir() -> Path:
    return settings.data_dir / "jobs"


def _upload_path(job_id: str) -> Path | None:
    return next(iter(sorted((settings.data_dir / "uploads").glob(f"{job_id}.*"))), None)


def save_job(job: Job) -> None:
    """Write data/jobs/{id}.json atomically (temp file + rename) so a poll never reads half a file."""
    folder = _jobs_dir()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{job.id}.{uuid.uuid4().hex}.tmp"
    tmp.write_text(job.model_dump_json())
    tmp.replace(folder / f"{job.id}.json")


def get_job(job_id: str) -> Job | None:
    """Read data/jobs/{id}.json; None if the id doesn't match JOB_ID or the file doesn't exist."""
    if not isinstance(job_id, str) or not _JOB_ID_RE.fullmatch(job_id):
        return None
    try:
        return Job.model_validate_json((_jobs_dir() / f"{job_id}.json").read_text())
    except (OSError, ValueError):
        return None


async def create_job(upload: Path, filename: str, topic: str) -> Job:
    """instagram_parse.normalise_topic() and video.guard() first (TopicRejected / VideoRejected
    propagate; main.py turns them into 400s with their message), then copy the upload to
    data/uploads/{id}{suffix} (the user's file name is never used as a path), create and save
    a queued Job with a 12-char hex id and the normalised topic."""
    tag = instagram_parse.normalise_topic(topic)
    await asyncio.to_thread(video.guard, upload, filename)  # ffprobe blocks
    job = Job(id=secrets.token_hex(6), created_at=datetime.now(timezone.utc), topic=tag)
    uploads = settings.data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    # Only the suffix comes from the user's name, and guard() has already limited it to .mp4/.mov.
    shutil.copyfile(upload, uploads / f"{job.id}{Path(filename).suffix.lower()}")
    save_job(job)
    return job


def _fail(stage: StageState, reason: str) -> None:
    stage.status, stage.reason = "failed", reason


async def run_job(job_id: str) -> Job:
    """Run both streams in parallel, then recommend. Returns the final Job (also saved).

    - Video stream: video.measure in a thread, then vision.analyse_opening. Any exception ->
      stages.video failed with the message; the job carries on.
    - Scout stream: niche_scout.run_niche_scout(topic, emit). TinyFishAccountError -> job failed
      with its message (the video stream still finishes and is kept).
    - Recommend: only if video measurements exist; otherwise stages.recommend skipped with a reason.
    - Events get t = seconds since the job started, so they are always in time order.
    """
    job = get_job(job_id)
    if job is None:
        raise ValueError(f"No job {job_id!r}")
    started = time.monotonic()

    def emit(source: str, kind: str, message: str, data: dict[str, Any] | None = None) -> None:
        # Sync on purpose: every caller runs on the event loop, so events land in call order.
        job.events.append(Event(t=round(time.monotonic() - started, 2), source=source, kind=kind, message=message, data=data))
        if kind == "streaming_url" and data and data.get("url"):
            job.live_view_url = data["url"]
        save_job(job)

    async def video_stream() -> None:
        job.stages.video.status = "running"
        emit("video", "progress", "Measuring your draft: cuts, speech and frames")
        try:
            upload = _upload_path(job.id)
            if upload is None:
                raise FileNotFoundError("the uploaded video is missing")
            m, frames, words = await asyncio.to_thread(video.measure, upload, settings.data_dir / "work" / job.id)
            job.video = m
            first = f"first word at {m.first_word_at_s:g} s" if m.first_word_at_s is not None else "no speech found"
            emit("video", "progress", f"Found {len(m.cut_times_s)} cuts, {m.cuts_first_3s} in the first 3 s; {first}")
            emit("video", "progress", "Gemini is looking at the opening frames")
            job.video = await vision.analyse_opening(m, frames, words, job.topic)
            if job.video.payoff_at_s is not None:
                emit("video", "progress", f"Payoff estimated at ~{job.video.payoff_at_s:g} s")
            job.stages.video.status = "done"
        except Exception as exc:
            _fail(job.stages.video, f"Couldn't measure the video: {exc}")
            emit("video", "error", job.stages.video.reason)
        save_job(job)  # results reach the UI now, not at the other stream's next event

    async def scout_stream() -> None:
        job.stages.scout.status = "running"
        try:
            job.creators, job.examples = await niche_scout.run_niche_scout(job.topic, emit)
            job.stages.scout.status = "done"
            if not any(e.access_status == "accessible" for e in job.examples):
                job.stages.scout.reason = "No public outlier Reels could be read for this topic"
        except TinyFishAccountError as exc:  # key or credits: not Instagram's fault, fail the job
            _fail(job.stages.scout, str(exc))
            job.error = str(exc)
            emit("scout", "error", str(exc))
        except Exception as exc:
            _fail(job.stages.scout, f"Niche Scout stopped: {exc}")
            emit("scout", "error", job.stages.scout.reason)
        save_job(job)  # creators and examples show while the video step may still be running

    try:
        job.status = "running"
        save_job(job)
        await asyncio.gather(video_stream(), scout_stream())

        if job.video is None:
            job.stages.recommend = StageState(status="skipped", reason="No video measurements to compare against")
        elif job.error:
            job.stages.recommend = StageState(status="skipped", reason="The research step failed")
        else:
            job.stages.recommend.status = "running"
            emit("llm", "progress", "Writing a grounded suggestion")
            job.recommendation = await recommend.recommend(job.video, job.examples, job.topic)
            job.stages.recommend.status = "done"
            n = len(job.recommendation.suggestions)
            emit("llm", "info", {
                "llm": f"{n} suggestion(s) passed every grounding check",
                "llm_retry": f"{n} suggestion(s) passed the grounding checks on the second try",
                "template": "Gemini's answers didn't pass the grounding checks, so this is a rule-based suggestion",
                "insufficient_evidence": "Not enough public examples to back a suggestion; showing the measurements only",
            }[job.recommendation.source])
        job.status = "failed" if job.error else "done"
    except Exception as exc:  # last resort: the UI must always get a final state
        job.status, job.error = "failed", f"Something went wrong: {exc}"
    save_job(job)
    return job


async def start_replay(topic: str, speed: float = 1.0) -> Job:
    """A6. Newest settings.replay_dir/*.json -> a new Job with replay=True and
    replay_recorded_at = the recording's created_at. Returns the new Job at once;
    a background task re-emits the recorded events on their original timing
    (divided by `speed`; tests pass a big number) and fills the results as they come.
    Never calls TinyFish or Gemini. No recording -> ReplayUnavailable("No recorded run ...")."""
    recordings = sorted(settings.replay_dir.glob("*.json"), key=lambda p: p.stat().st_mtime) if settings.replay_dir.exists() else []
    if not recordings:
        raise ReplayUnavailable("No recorded run to replay yet. Record one with scripts/record_replay.py, or set REPLAY=0.")
    recorded = Job.model_validate_json(recordings[-1].read_text())
    # The replay shows the recorded topic, whatever was typed: it's a recording, not a new run.
    job = Job(id=secrets.token_hex(6), created_at=datetime.now(timezone.utc), topic=recorded.topic, status="running",
              replay=True, replay_recorded_at=recorded.created_at)
    save_job(job)
    task = asyncio.create_task(_replay(job, recorded, speed))
    _replays.add(task)
    task.add_done_callback(_replays.discard)
    return job


async def _replay(job: Job, recorded: Job, speed: float) -> None:
    started = time.monotonic()
    last_video_t = max((e.t for e in recorded.events if e.source == "video"), default=None)
    outliers_seen = 0
    try:
        for ev in recorded.events:
            await asyncio.sleep(max(0.0, ev.t / speed - (time.monotonic() - started)))
            if ev.kind == "streaming_url":
                # That live view ended when the run did; never show it as if it were live.
                ev = ev.model_copy(update={"kind": "info", "data": None,
                                           "message": "The Agent's live browser view was shown here during the recorded run"})
            job.events.append(ev)
            if ev.kind == "creator":
                job.creators = recorded.creators
            elif ev.kind == "outlier":
                outliers_seen += 1
                job.examples = recorded.examples[:outliers_seen]
            if ev.source == "video" and ev.t == last_video_t:
                job.video, job.stages.video = recorded.video, recorded.stages.video
            save_job(job)
    finally:
        job.video, job.creators, job.examples = recorded.video, recorded.creators, recorded.examples
        job.recommendation, job.stages, job.error = recorded.recommendation, recorded.stages, recorded.error
        job.status = recorded.status if recorded.status in ("done", "failed") else "done"
        save_job(job)
