"""Defines "done" for jobs.py + the /analyze and /jobs routes (Fri tasks A4, A5, A6).
Every stream is faked: no ffmpeg pipeline, TinyFish or Gemini. IDs refer to docs/test-cases.md."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from backend import jobs, llm_client, niche_scout, recommend, tinyfish_client, video, vision
from backend.models import Job
from backend.tinyfish_client import TinyFishAccountError

from .conftest import SAMPLES

# Built on Friday: run with `pytest -m friday`. Delete this line once the file passes.
pytestmark = pytest.mark.friday

CLIP = SAMPLES / "synthetic_clip.mp4"


@pytest.fixture
def job_env(isolated, monkeypatch, done_job):
    monkeypatch.setattr(jobs, "settings", isolated, raising=False)

    def measure(path, work_dir, **kw):
        return done_job.video.model_copy(update={"payoff_at_s": None}), [], []

    async def analyse_opening(v, frames, words, topic):
        return v.model_copy(update={"payoff_at_s": 6.2})

    async def run_niche_scout(topic, emit):
        await asyncio.sleep(0.01)
        emit("scout", "outlier", f"3.1x @mock_kitchen_a's median ({topic})", None)
        return done_job.creators, done_job.examples

    async def fake_recommend(v, examples, topic):
        return done_job.recommendation

    monkeypatch.setattr(video, "measure", measure)
    monkeypatch.setattr(vision, "analyse_opening", analyse_opening)
    monkeypatch.setattr(niche_scout, "run_niche_scout", run_niche_scout)
    monkeypatch.setattr(recommend, "recommend", fake_recommend)
    return isolated


@pytest.fixture
def client(job_env):
    from backend.main import app

    return TestClient(app)


def upload(client, name="clip.mp4", topic="cooking", content=None):
    data = content if content is not None else CLIP.read_bytes()
    return client.post("/analyze", files={"file": (name, data)}, data={"topic": topic})


# ---------------------------------------------------------------- the job runner


async def test_full_job_runs_both_streams_then_recommends(job_env):
    job = await jobs.create_job(CLIP, "synthetic_clip.mp4", "cooking")
    assert job.status == "queued" and len(job.id) == 12
    final = await jobs.run_job(job.id)
    assert final.status == "done"
    assert all(getattr(final.stages, s).status == "done" for s in ("video", "scout", "recommend"))
    assert final.video.payoff_at_s == 6.2 and len(final.examples) == 3 and final.recommendation.suggestions
    assert any(e.kind == "outlier" for e in final.events)
    saved = Job.model_validate(json.loads((job_env.data_dir / "jobs" / f"{job.id}.json").read_text()))
    assert saved == final and jobs.get_job(job.id) == final


async def test_events_are_in_time_order(job_env):
    job = await jobs.create_job(CLIP, "clip.mp4", "cooking")
    final = await jobs.run_job(job.id)
    ts = [e.t for e in final.events]
    assert ts == sorted(ts) and ts[0] >= 0


async def test_bad_upload_is_rejected_before_a_job_exists(job_env, tmp_path):  # A4
    f = tmp_path / "clip.avi"
    f.write_bytes(b"x")
    with pytest.raises(video.VideoRejected):
        await jobs.create_job(f, "clip.avi", "cooking")
    jobs_dir = job_env.data_dir / "jobs"
    assert not jobs_dir.exists() or not list(jobs_dir.glob("*.json"))


async def test_no_credits_fails_the_job_with_a_plain_message(job_env, monkeypatch):  # D16
    async def broke(topic, emit):
        raise TinyFishAccountError("TinyFish wallet can't cover this (402).")

    monkeypatch.setattr(niche_scout, "run_niche_scout", broke)
    job = await jobs.create_job(CLIP, "synthetic_clip.mp4", "cooking")
    final = await jobs.run_job(job.id)
    assert final.status == "failed" and "402" in final.error
    assert final.video is not None  # the other stream still finished


async def test_a_crashed_video_stream_keeps_the_research(job_env, monkeypatch):
    def broken(path, work_dir, **kw):
        raise RuntimeError("ffmpeg exploded")

    monkeypatch.setattr(video, "measure", broken)
    job = await jobs.create_job(CLIP, "clip.mp4", "cooking")
    final = await jobs.run_job(job.id)
    assert final.status == "done" and final.stages.video.status == "failed" and final.stages.video.reason
    assert final.stages.scout.status == "done" and final.examples
    assert final.stages.recommend.status == "skipped" and final.recommendation is None


async def test_two_jobs_do_not_mix(job_env):  # C8
    a = await jobs.create_job(CLIP, "a.mp4", "cooking")
    b = await jobs.create_job(CLIP, "b.mp4", "baking")
    fa, fb = await asyncio.gather(jobs.run_job(a.id), jobs.run_job(b.id))
    assert fa.id != fb.id and (fa.topic, fb.topic) == ("cooking", "baking")
    assert all("(baking)" not in e.message for e in fa.events)
    assert all("(cooking)" not in e.message for e in fb.events)


# ---------------------------------------------------------------- replay (F1-F3)


async def test_replay_is_always_labelled(job_env, done_job):  # F1
    job_env.replay_dir.mkdir(parents=True)
    (job_env.replay_dir / "run.json").write_text(done_job.model_dump_json())
    replay = await jobs.start_replay("cooking", speed=1000)
    assert replay.replay is True and replay.replay_recorded_at == done_job.created_at


async def test_replay_without_a_recording(job_env):  # F2
    with pytest.raises(jobs.ReplayUnavailable, match="No recorded run"):
        await jobs.start_replay("cooking")


async def test_replay_makes_no_network_calls(job_env, done_job, monkeypatch):  # F3
    def forbidden(*a, **kw):
        raise AssertionError("replay must not call TinyFish or Gemini")

    for mod, name in [(tinyfish_client, "fetch_pages"), (tinyfish_client, "run_agent"), (llm_client, "generate_json"),
                      (niche_scout, "run_niche_scout"), (recommend, "recommend")]:
        monkeypatch.setattr(mod, name, forbidden)
    job_env.replay_dir.mkdir(parents=True)
    (job_env.replay_dir / "run.json").write_text(done_job.model_dump_json())
    replay = await jobs.start_replay("cooking", speed=1000)
    current = replay
    for _ in range(100):
        current = jobs.get_job(replay.id)
        if current.status == "done":
            break
        await asyncio.sleep(0.02)
    assert current.status == "done" and current.replay and len(current.examples) == 3


# ---------------------------------------------------------------- the HTTP routes, as a browser uses them


def test_routes_accept_a_normal_upload(client):  # A1, B2
    ok = upload(client, topic="#Cooking ")
    assert ok.status_code == 202
    job = client.get(f"/jobs/{ok.json()['job_id']}").json()
    assert job["topic"] == "cooking"


def test_routes_need_a_file_and_a_topic(client):  # A20, B7
    no_file = client.post("/analyze", data={"topic": "cooking"})
    assert no_file.status_code == 400 and "Choose a video" in no_file.json()["detail"]
    no_topic = client.post("/analyze", files={"file": ("clip.mp4", CLIP.read_bytes())})
    assert no_topic.status_code == 400 and "Type a topic word" in no_topic.json()["detail"]


@pytest.mark.parametrize("topic, message", [("", "Type a topic word"), ("🍛", "Type a topic word"),
                                             ("#cooking #food", "one topic at a time"), ("2026", "at least one letter")])
def test_routes_reject_bad_topics(client, topic, message):  # B7-B10
    r = upload(client, topic=topic)
    assert r.status_code == 400 and message in r.json()["detail"]


@pytest.mark.parametrize("name, content, message", [("clip.avi", None, ".mp4 or .mov"),
                                                    ("photo.mp4", b"not a video", "isn't a readable video")])
def test_routes_reject_bad_files_with_the_reason(client, name, content, message):  # A4, A6
    r = upload(client, name=name, content=content)
    assert r.status_code == 400 and message in r.json()["detail"]


def test_upload_name_never_becomes_a_path(client, job_env):  # A3
    r = upload(client, name="../../evil ✨.mp4")
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    uploads = list((job_env.data_dir / "uploads").iterdir())
    assert uploads and all(p.name.startswith(job_id) for p in uploads)
    assert not (job_env.data_dir.parent / "evil ✨.mp4").exists()


@pytest.mark.parametrize("job_id", ["doesnotexist", "ABCDEF123456", "..%2F..%2Fetc%2Fpasswd", "%2e%2e", "0" * 64])
def test_unknown_and_malicious_job_ids_are_404(client, job_id):  # C6
    assert client.get(f"/jobs/{job_id}").status_code == 404


def test_get_job_rejects_ids_that_are_not_ours(job_env):
    assert jobs.get_job("../../etc/passwd") is None and jobs.get_job("") is None


def test_replay_route_without_a_recording(client, job_env, monkeypatch):  # F2
    from dataclasses import replace

    import backend.main as main

    monkeypatch.setattr(main, "settings", replace(job_env, replay=True), raising=False)
    r = upload(client)
    assert r.status_code == 503 and "No recorded run" in r.json()["detail"]
