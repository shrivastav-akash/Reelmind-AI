"""Defines "done" for jobs.py + the /analyze and /jobs routes (Fri tasks A4, A5, A6).
Fails until built. Every stream is faked: no ffmpeg, TinyFish or Gemini."""

import json

import pytest
from fastapi.testclient import TestClient

from backend import jobs, niche_scout, recommend, video, vision
from backend.models import Job
from backend.tinyfish_client import TinyFishAccountError

from .conftest import SAMPLES

# Built on Friday: run with `pytest -m friday`. Delete this line once the file passes.
pytestmark = pytest.mark.friday


@pytest.fixture
def job_env(isolated, monkeypatch, done_job):
    monkeypatch.setattr(jobs, "settings", isolated, raising=False)

    def measure(path, work_dir, **kw):
        return done_job.video.model_copy(update={"payoff_at_s": None}), [], []

    async def analyse_opening(v, frames, words, topic):
        return v.model_copy(update={"payoff_at_s": 6.2})

    async def run_niche_scout(topic, emit):
        emit("scout", "outlier", "3.1x @mock_kitchen_a's median", None)
        return done_job.creators, done_job.examples

    async def fake_recommend(v, examples, topic):
        return done_job.recommendation

    monkeypatch.setattr(video, "measure", measure)
    monkeypatch.setattr(vision, "analyse_opening", analyse_opening)
    monkeypatch.setattr(niche_scout, "run_niche_scout", run_niche_scout)
    monkeypatch.setattr(recommend, "recommend", fake_recommend)
    return isolated


async def test_full_job_runs_both_streams_then_recommends(job_env):
    job = await jobs.create_job(SAMPLES / "synthetic_clip.mp4", "synthetic_clip.mp4", "cooking")
    assert job.status == "queued" and len(job.id) == 12
    final = await jobs.run_job(job.id)
    assert final.status == "done"
    assert all(getattr(final.stages, s).status == "done" for s in ("video", "scout", "recommend"))
    assert final.video.payoff_at_s == 6.2 and len(final.examples) == 3 and final.recommendation.suggestions
    assert any(e.kind == "outlier" for e in final.events)
    saved = Job.model_validate(json.loads((job_env.data_dir / "jobs" / f"{job.id}.json").read_text()))
    assert saved == final and jobs.get_job(job.id) == final


async def test_bad_upload_is_rejected_before_a_job_exists(job_env, tmp_path):
    f = tmp_path / "clip.avi"
    f.write_bytes(b"x")
    with pytest.raises(video.VideoRejected):
        await jobs.create_job(f, "clip.avi", "cooking")


async def test_no_credits_fails_the_job_with_a_plain_message(job_env, monkeypatch):
    async def broke(topic, emit):
        raise TinyFishAccountError("TinyFish wallet can't cover this (402).")

    monkeypatch.setattr(niche_scout, "run_niche_scout", broke)
    job = await jobs.create_job(SAMPLES / "synthetic_clip.mp4", "synthetic_clip.mp4", "cooking")
    final = await jobs.run_job(job.id)
    assert final.status == "failed" and "402" in final.error
    assert final.video is not None  # the other stream still finished


async def test_replay_is_always_labelled(job_env, done_job):
    job_env.replay_dir.mkdir(parents=True)
    (job_env.replay_dir / "run.json").write_text(done_job.model_dump_json())
    replay = await jobs.start_replay("cooking", speed=1000)
    assert replay.replay is True and replay.replay_recorded_at is not None


def test_routes(job_env):
    from backend.main import app

    client = TestClient(app)
    bad = client.post("/analyze", files={"file": ("clip.avi", b"x")}, data={"topic": "cooking"})
    assert bad.status_code == 400 and ".mp4 or .mov" in bad.json()["detail"]
    with open(SAMPLES / "synthetic_clip.mp4", "rb") as fh:
        ok = client.post("/analyze", files={"file": ("clip.mp4", fh)}, data={"topic": "cooking"})
    assert ok.status_code == 202
    job_id = ok.json()["job_id"]
    assert client.get(f"/jobs/{job_id}").status_code == 200
    assert client.get("/jobs/doesnotexist").status_code == 404
