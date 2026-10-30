"""Save a finished live run as the replay recording (task A6). Free: no network.

    .venv/bin/python scripts/record_replay.py <job_id>

Copies data/jobs/<job_id>.json to backend/cache/replay/ (gitignored). With REPLAY=1,
POST /analyze replays the newest recording there, always labelled as a replay.
Only a finished live run can be recorded: never a failed run, and never a replay of a replay.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import jobs  # noqa: E402
from backend.config import settings  # noqa: E402


def main(job_id: str) -> None:
    job = jobs.get_job(job_id)
    if job is None:
        sys.exit(f"No job {job_id!r} in {settings.data_dir / 'jobs'}")
    if job.replay or job.status != "done":
        sys.exit(f"Job {job_id} is {'a replay' if job.replay else job.status}: record a finished live run instead.")
    settings.replay_dir.mkdir(parents=True, exist_ok=True)
    dst = settings.replay_dir / f"{job.created_at:%Y%m%d-%H%M%S}-{job.id}.json"
    dst.write_text(job.model_dump_json(indent=1))
    print(f"Recorded {len(job.events)} events, {len(job.examples)} examples -> {dst.relative_to(ROOT)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
