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

from pathlib import Path

from backend.config import settings  # noqa: F401  (data_dir, replay_dir; tests swap this)
from backend.models import Job


JOB_ID = r"^[0-9a-f]{12}$"  # get_job() refuses anything else, so an id can never be a path


class ReplayUnavailable(Exception):
    """REPLAY=1 but no recording exists. main.py answers 503 "No recorded run ..."."""


def save_job(job: Job) -> None:
    """Write data/jobs/{id}.json atomically (temp file + rename) so a poll never reads half a file."""
    raise NotImplementedError("A4: built on Friday")


def get_job(job_id: str) -> Job | None:
    """Read data/jobs/{id}.json; None if the id doesn't match JOB_ID or the file doesn't exist."""
    raise NotImplementedError("A4: built on Friday")


async def create_job(upload: Path, filename: str, topic: str) -> Job:
    """instagram_parse.normalise_topic() and video.guard() first (TopicRejected / VideoRejected
    propagate; main.py turns them into 400s with their message), then copy the upload to
    data/uploads/{id}{suffix} (the user's file name is never used as a path), create and save
    a queued Job with a 12-char hex id and the normalised topic."""
    raise NotImplementedError("A4: built on Friday")


async def run_job(job_id: str) -> Job:
    """Run both streams in parallel, then recommend. Returns the final Job (also saved).

    - Video stream: video.measure in a thread, then vision.analyse_opening. Any exception ->
      stages.video failed with the message; the job carries on.
    - Scout stream: niche_scout.run_niche_scout(topic, emit). TinyFishAccountError -> job failed
      with its message (the video stream still finishes and is kept).
    - Recommend: only if video measurements exist; otherwise stages.recommend skipped with a reason.
    - Events get t = seconds since the job started, so they are always in time order.
    """
    raise NotImplementedError("A4: built on Friday")


async def start_replay(topic: str, speed: float = 1.0) -> Job:
    """A6. Newest settings.replay_dir/*.json -> a new Job with replay=True and
    replay_recorded_at = the recording's created_at. Returns the new Job at once;
    a background task re-emits the recorded events on their original timing
    (divided by `speed`; tests pass a big number) and fills the results as they come.
    Never calls TinyFish or Gemini. No recording -> ReplayUnavailable("No recorded run ...")."""
    raise NotImplementedError("A6: built on Friday")
