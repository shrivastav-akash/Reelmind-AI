"""Defines "done" for v2 task 4.3: sign-up starts the user's own creator report, GET /me points
at it, POST /me/refresh starts a new one. The fetch is faked with the creator mock; the
intelligence-lane stages count as not built, so reports finish with the fetched numbers.
"""

import asyncio
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from backend import auth, creator_profiler, reports

from .test_reports import skeleton

PASSWORD = "correct horse battery"


@pytest.fixture
def env(isolated, monkeypatch):
    import backend.main as main

    monkeypatch.setattr(auth, "settings", isolated, raising=False)
    monkeypatch.setattr(reports, "settings", isolated, raising=False)
    fetched = []

    async def fetch_creator(handle, emit):
        fetched.append(handle)
        return skeleton(handle)

    monkeypatch.setattr(creator_profiler, "fetch_creator", fetch_creator)
    monkeypatch.setattr(reports, "_stage_fn", lambda module, name: None)
    return isolated, fetched, main, monkeypatch


@pytest.fixture
def client(env):
    from backend.main import app

    return TestClient(app)


def signup(client, instagram_url="https://www.instagram.com/eylems_kitchen/", email="cook@example.com"):
    return client.post("/auth/signup", json={"email": email, "password": PASSWORD, "instagram_url": instagram_url})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_signup_starts_the_users_own_report(client, env):
    _, fetched, _, _ = env
    body = signup(client).json()
    report_id = body["user"]["latest_report_id"]
    report = client.get(f"/reports/{report_id}").json()  # the background task has run
    assert report["status"] == "done" and report["kind"] == "creator"
    assert report["input"]["handle"] == "eylems_kitchen" and report["owner_id"] == body["user"]["id"]
    assert fetched == ["eylems_kitchen"]
    assert client.get("/me", headers=bearer(body["token"])).json()["latest_report_id"] == report_id


def test_a_failed_signup_starts_nothing(client, env):
    isolated, fetched, _, _ = env
    assert signup(client, instagram_url="https://www.tiktok.com/@x").status_code == 400
    assert fetched == [] and not (isolated.data_dir / "reports").exists()


def test_refresh_starts_a_new_report(client, env):
    _, fetched, _, _ = env
    body = signup(client).json()
    r = client.post("/me/refresh", headers=bearer(body["token"]))
    assert r.status_code == 202
    new_id = r.json()["report_id"]
    assert new_id != body["user"]["latest_report_id"] and fetched == ["eylems_kitchen", "eylems_kitchen"]
    assert client.get("/me", headers=bearer(body["token"])).json()["latest_report_id"] == new_id


def test_refresh_while_running_returns_the_same_report(client, env):
    _, fetched, _, _ = env
    body = signup(client).json()
    current = reports.get_report(body["user"]["latest_report_id"])
    current.status = "running"
    reports.save_report(current)
    r = client.post("/me/refresh", headers=bearer(body["token"]))
    assert r.status_code == 202 and r.json()["report_id"] == current.id and len(fetched) == 1


def test_refresh_needs_a_session(client):
    assert client.post("/me/refresh").status_code == 401


def test_each_user_gets_their_own_report(client, env):
    a = signup(client, email="a@example.com").json()
    b = signup(client, instagram_url="@pov__gil", email="b@example.com").json()
    ra, rb = (reports.get_report(x["user"]["latest_report_id"]) for x in (a, b))
    assert (ra.input["handle"], ra.owner_id) == ("eylems_kitchen", a["user"]["id"])
    assert (rb.input["handle"], rb.owner_id) == ("pov__gil", b["user"]["id"])


# ---------------------------------------------------------------- replay mode (demo safety)


async def record_one(handle):
    job = reports.create_report("creator", {"handle": handle})
    return reports.record(await reports.run_creator_report(job.id))


def test_replay_mode_replays_only_a_recording_of_the_users_own_handle(client, env):
    isolated, _, main, monkeypatch = env
    asyncio.run(record_one("eylems_kitchen"))
    asyncio.run(record_one("pov__gil"))  # newer, but someone else's
    monkeypatch.setattr(main, "settings", replace(isolated, replay=True), raising=False)
    body = signup(client).json()
    report = reports.get_report(body["user"]["latest_report_id"])
    assert report.replay and report.input["handle"] == "eylems_kitchen" and report.owner_id == body["user"]["id"]


def test_replay_mode_without_their_recording_starts_nothing(client, env):
    isolated, _, main, monkeypatch = env
    asyncio.run(record_one("pov__gil"))
    monkeypatch.setattr(main, "settings", replace(isolated, replay=True), raising=False)
    body = signup(client).json()
    assert body["user"]["latest_report_id"] is None
    r = client.post("/me/refresh", headers=bearer(body["token"]))
    assert r.status_code == 503 and "@eylems_kitchen" in r.json()["detail"]
