"""Defines "done" for reports.py + the /reports routes (v2 task 1.5).

The fetch stage is faked with the creator mock (no TinyFish); the intelligence-lane stages
(1.2-1.4) are faked through reports._stage_fn, including "not built yet", so these tests
don't change when those modules land on main.
"""

import asyncio
import json
import secrets
from dataclasses import replace
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend import creator_profiler, jobs, outliers, reports
from backend.report_models import STAGES, CoverNotes, CreatorReport, Insight, ReportJob
from backend.tinyfish_client import TinyFishAccountError

from .conftest import MOCKS

MOCK = ReportJob.model_validate(json.loads((MOCKS / "report.creator.json").read_text()))


def skeleton(handle="mock_kitchen_a") -> CreatorReport:
    """What fetch_creator returns: profile + reels, nothing computed."""
    r = MOCK.result.model_copy(deep=True)
    r.profile.handle, r.profile.median_views, r.profile.reels_in_window = handle, None, 0
    r.patterns, r.insights, r.insights_source = [], [], "insufficient_evidence"
    for reel in r.reels:
        reel.ratio_vs_median, reel.in_window, reel.cover_notes = None, False, None
    return r


class Lane:
    """The intelligence lane's stage functions, as they will look once built."""

    def __init__(self):
        self.built = {"analyse", "visuals", "insights"}
        self.fail = set()
        self.calls = []

    def stage_fn(self, module, name):
        stage = {"analyse": "analyse", "analyse_covers": "visuals", "write_insights": "insights"}[name]
        return getattr(self, stage) if stage in self.built else None

    def analyse(self, report, today):
        self.calls.append(("analyse", today))
        if "analyse" in self.fail:
            raise RuntimeError("bad numbers")
        report.profile.median_views = MOCK.result.profile.median_views
        report.profile.reels_in_window = 4
        report.patterns = MOCK.result.patterns

    async def visuals(self, report):
        self.calls.append(("visuals",))
        if "visuals" in self.fail:
            raise RuntimeError("Gemini timed out")
        report.reels[0].cover_notes = CoverNotes(text_on_cover=None, face=True, setting="kitchen", style="bright")

    async def insights(self, report):
        self.calls.append(("insights",))
        report.insights = [Insight(kind="working", claim="Question hooks work", keys=["pat.hook_type.question"], reel_ids=["r3"])]
        report.insights_source = "llm"


@pytest.fixture
def env(isolated, monkeypatch):
    monkeypatch.setattr(reports, "settings", isolated, raising=False)
    lane = Lane()
    world = {"fetch": "ok", "fetched": []}

    async def fetch_creator(handle, emit):
        world["fetched"].append(handle)
        emit("scout", "progress", f"Reading @{handle}'s Reels grid")
        if world["fetch"] == "account_error":
            raise TinyFishAccountError("TinyFish wallet can't cover this (402).")
        report = skeleton(handle)
        if world["fetch"] == "private":
            report.profile.access_status = "login_wall"
            report.profile.status_reason = "Login wall: this account's Reels aren't public"
            report.reels = []
        return report

    monkeypatch.setattr(creator_profiler, "fetch_creator", fetch_creator)
    monkeypatch.setattr(reports, "_stage_fn", lane.stage_fn)
    return isolated, lane, world


async def new_and_run(handle="mock_kitchen_a"):
    job = reports.create_report("creator", {"handle_or_url": f"@{handle}", "handle": handle})
    return await reports.run_creator_report(job.id, today=date(2026, 10, 30))


# ---------------------------------------------------------------- the runner


def test_create_report_saves_a_queued_job(env):
    job = reports.create_report("creator", {"handle": "pov__gil"})
    saved = reports.get_report(job.id)
    assert saved.status == "queued" and saved.kind == "creator"
    assert list(saved.stages) == list(STAGES["creator"]) and all(s.status == "pending" for s in saved.stages.values())


async def test_runs_every_stage_in_order(env):
    _, lane, world = env
    job = await new_and_run()
    assert job.status == "done" and job.error is None
    assert {n: s.status for n, s in job.stages.items()} == dict.fromkeys(STAGES["creator"], "done")
    assert [c[0] for c in lane.calls] == ["analyse", "visuals", "insights"]
    assert lane.calls[0][1] == date(2026, 10, 30)
    assert job.result.insights_source == "llm" and job.result.reels[0].cover_notes is not None
    assert reports.get_report(job.id) == job  # what GET returns is the final state
    times = [e.t for e in job.events]
    assert times == sorted(times)
    messages = [e.message for e in job.events]
    assert "4 Reels in the last 7 days; median views 12.8K" in messages
    assert "1 insight(s) passed every grounding check" in messages


async def test_stages_not_built_yet_are_skipped_and_the_report_still_finishes(env):
    _, lane, _ = env
    lane.built = set()
    job = await new_and_run()
    assert job.status == "done" and job.stages["fetch"].status == "done"
    for name, task in (("analyse", "1.2"), ("visuals", "1.3"), ("insights", "1.4")):
        assert job.stages[name].status == "skipped" and job.stages[name].reason == f"Not built yet (task {task})"
    assert job.result.reels  # the fetched numbers still reach the UI


async def test_insights_wait_for_the_analysis(env):
    _, lane, _ = env
    lane.built = {"visuals", "insights"}
    job = await new_and_run()
    assert job.stages["insights"].status == "skipped" and "analysis" in job.stages["insights"].reason
    assert ("insights",) not in lane.calls


async def test_a_failing_stage_is_reported_and_the_rest_carry_on(env):
    _, lane, _ = env
    lane.fail = {"visuals"}
    job = await new_and_run()
    assert job.status == "done"
    assert job.stages["visuals"].status == "failed" and "Gemini timed out" in job.stages["visuals"].reason
    assert job.stages["insights"].status == "done"
    assert any(e.kind == "error" and "Gemini timed out" in e.message for e in job.events)


async def test_a_private_account_fails_the_report_but_keeps_the_profile(env):
    _, lane, world = env
    world["fetch"] = "private"
    job = await new_and_run("private_one")
    assert job.status == "failed" and job.error == "@private_one: Login wall: this account's Reels aren't public"
    assert job.stages["fetch"].status == "failed"
    assert all(job.stages[n].status == "skipped" for n in ("analyse", "visuals", "insights"))
    assert job.result.profile.access_status == "login_wall" and lane.calls == []


async def test_a_tinyfish_account_problem_fails_the_report_in_plain_words(env):
    _, _, world = env
    world["fetch"] = "account_error"
    job = await new_and_run()
    assert job.status == "failed" and "402" in job.error and job.result is None
    assert job.stages["fetch"].status == "failed"


def test_get_report_rejects_ids_that_are_not_ours(env):
    assert reports.get_report("../../etc/passwd") is None and reports.get_report("") is None
    assert reports.get_report("abcdefabcdef") is None  # well formed, but no such file


def test_stage_fn_finds_built_modules_only():
    assert reports._stage_fn.__module__ == "backend.reports"
    assert reports._stage_fn("outliers", "creator_median") is outliers.creator_median
    assert reports._stage_fn("outliers", "no_such_function") is None
    assert reports._stage_fn("no_such_module_xyz", "anything") is None


# ---------------------------------------------------------------- the HTTP routes


@pytest.fixture
def client(env):
    from backend.main import app

    return TestClient(app)


def test_route_accepts_a_handle_and_runs_the_report(client, env):
    _, _, world = env
    r = client.post("/reports/creator", json={"handle_or_url": "https://www.instagram.com/pov__gil/"})
    assert r.status_code == 202
    report_id = r.json()["report_id"]
    body = client.get(f"/reports/{report_id}").json()  # the background task has run by now
    assert body["status"] == "done" and body["kind"] == "creator"
    assert body["input"]["handle"] == "pov__gil" and world["fetched"] == ["pov__gil"]
    assert body["result"]["kind"] == "creator" and body["result"]["insights"]


@pytest.mark.parametrize("raw", ["", "https://www.tiktok.com/@someone", "has space"])
def test_route_rejects_handles_we_cannot_read(client, env, raw):
    r = client.post("/reports/creator", json={"handle_or_url": raw})
    assert r.status_code == 400 and "Instagram handle" in r.json()["detail"]
    assert env[2]["fetched"] == []


def test_route_needs_a_body(client):
    assert client.post("/reports/creator", json={}).status_code == 422


def test_unknown_report_is_404(client):
    r = client.get("/reports/abcdefabcdef")
    assert r.status_code == 404 and r.json()["detail"] == "We couldn't find that report."


# ---------------------------------------------------------------- replay (demo safety)


async def test_record_and_replay_a_report(env):
    isolated, _, _ = env
    live = await new_and_run()
    path = reports.record(live)
    assert path.parent == isolated.replay_dir / "reports" and path.name.startswith("creator_")
    replay = await reports.start_replay("creator", speed=1000)
    assert replay.replay and replay.replay_recorded_at == live.created_at and replay.status == "running"
    await asyncio.gather(*reports._replays)
    done = reports.get_report(replay.id)
    assert done.status == "done" and done.replay and done.id != live.id
    assert done.result == live.result and [e.message for e in done.events] == [e.message for e in live.events]


@pytest.mark.parametrize("kind", ["creator", "reel", "niche"])
async def test_every_v2_report_kind_can_replay_offline(env, kind):
    """The demo fallback must preserve the full result for every V2 report kind."""
    _, _, _ = env
    recorded = ReportJob.model_validate_json((MOCKS / f"report.{kind}.json").read_text())
    recorded.id = secrets.token_hex(6)
    recorded.created_at = datetime.now(timezone.utc)
    recorded.status = "done"
    path = reports.record(recorded)
    assert path.name.startswith(f"{kind}_")
    replay = await reports.start_replay(kind, speed=1000)
    assert replay.replay and replay.kind == kind and replay.status == "running"
    await asyncio.gather(*reports._replays)
    done = reports.get_report(replay.id)
    assert done.status == "done" and done.replay and done.result == recorded.result


@pytest.mark.parametrize(
    ("kind", "path", "body"),
    [
        ("creator", "/reports/creator", {"handle_or_url": "@mock_kitchen_a"}),
        ("reel", "/reports/reel", {"url": "https://www.instagram.com/reel/MOCK0000001/"}),
        ("niche", "/reports/niche", {"keywords": ["cooking", "dal"]}),
    ],
)
def test_replay_mode_routes_to_the_recording_without_live_work(client, env, monkeypatch, kind, path, body):
    """REPLAY=1 must select a completed report and bypass its live research runner."""
    import backend.main as main

    isolated, _, _ = env
    recorded = ReportJob.model_validate_json((MOCKS / f"report.{kind}.json").read_text())
    recorded.id = secrets.token_hex(6)
    recorded.created_at = datetime.now(timezone.utc)
    reports.record(recorded)
    monkeypatch.setattr(main, "settings", replace(isolated, replay=True), raising=False)
    start = reports.start_replay

    async def fast_replay(report_kind, **kwargs):
        return await start(report_kind, speed=1000, **kwargs)

    monkeypatch.setattr(reports, "start_replay", fast_replay)
    response = client.post(path, json=body)
    assert response.status_code == 202
    replay = reports.get_report(response.json()["report_id"])
    assert replay is not None and replay.replay and replay.kind == kind
    assert replay.input == recorded.input


async def test_only_finished_live_reports_can_be_recorded(env):
    _, _, world = env
    world["fetch"] = "private"
    failed = await new_and_run()
    with pytest.raises(ValueError, match="failed"):
        reports.record(failed)


async def test_replay_without_a_recording(env):
    with pytest.raises(jobs.ReplayUnavailable, match="No recorded creator report"):
        await reports.start_replay("creator")


async def test_report_recordings_never_reach_the_v1_replay(env, monkeypatch):
    isolated, _, _ = env
    monkeypatch.setattr(jobs, "settings", isolated, raising=False)
    reports.record(await new_and_run())
    with pytest.raises(jobs.ReplayUnavailable):  # v1 globs replay_dir/*.json only
        await jobs.start_replay("cooking")


def test_replay_route(client, env, monkeypatch):
    import backend.main as main

    isolated, _, _ = env
    monkeypatch.setattr(main, "settings", replace(isolated, replay=True), raising=False)
    r = client.post("/reports/creator", json={"handle_or_url": "@pov__gil"})
    assert r.status_code == 503 and "No recorded creator report" in r.json()["detail"]
