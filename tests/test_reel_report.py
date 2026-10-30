"""Defines "done" for reel_report.py, reports.run_reel_report and POST /reports/reel (v2 task 3.1).

fetch_reel runs against the fake TinyFish from test_creator_profiler (real 29 Oct grids). The
runner tests fake the two fetches with the Reel mock and fake the intelligence lane through
reports._stage_fn, including "not built yet", so they don't change when 1.2-1.4 land.
"""

import json
from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend import creator_profiler, reel_report, reports
from backend import instagram_parse as ig
from backend.report_models import STAGES, Insight, ReportJob

from .conftest import MOCKS
from .test_creator_profiler import World, tiles

MOCK = ReportJob.model_validate(json.loads((MOCKS / "report.reel.json").read_text())).result


def creator_skeleton():
    c = MOCK.creator.model_copy(deep=True)
    c.profile.median_views, c.patterns, c.insights = None, [], []
    for r in c.reels:
        r.ratio_vs_median = None
    return c


def pasted_reel(source_url=None):
    r = MOCK.reel.model_copy(deep=True)
    r.views = r.ratio_vs_median = None
    r.hook_type, r.hashtags = None, []
    if source_url:
        r.source_url = source_url
    return r


# ---------------------------------------------------------------- what users paste


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.instagram.com/reel/DVlSnL5k_pn/",
        "instagram.com/reel/DVlSnL5k_pn",
        "https://www.instagram.com/reels/DVlSnL5k_pn/?igsh=MWx0Z2",
        "https://www.instagram.com/cookwithprincia/reel/DVlSnL5k_pn/",
        "  www.instagram.com/reel/DVlSnL5k_pn/  ",
    ],
)
def test_parse_reel_url_accepts_what_people_paste(raw):
    assert reel_report.parse_reel_url(raw) == "https://www.instagram.com/reel/DVlSnL5k_pn/"


@pytest.mark.parametrize(
    "raw",
    ["", None, "https://www.instagram.com/cookwithprincia/", "https://www.instagram.com/p/DVlSnL5k_pn/",
     "https://evil.example/reel/DVlSnL5k_pn/", "https://www.tiktok.com/@x/video/123", "cookwithprincia"],
)
def test_parse_reel_url_rejects_the_rest(raw):
    with pytest.raises(reel_report.ReelUrlRejected):
        reel_report.parse_reel_url(raw)


# ---------------------------------------------------------------- fetch_reel (fake TinyFish)


@pytest.fixture
def world(monkeypatch):
    from backend import tinyfish_client

    w = World()
    monkeypatch.setattr(tinyfish_client, "fetch_pages", w.fetch_pages)
    return w


async def test_fetch_reel_reads_the_page_and_its_author(world):
    url = tiles("pov__gil")[0].reel_url
    world.original_audio.add(ig.reel_shortcode(url))
    reel, handle = await reel_report.fetch_reel(url, lambda *a, **k: None)
    assert handle == "pov__gil" and reel.handle == "pov__gil"
    assert reel.id == "r0" and reel.access_status == "accessible" and reel.views is None
    assert reel.hook_line.startswith("Hook for") and reel.original_audio is True and reel.cover_url
    assert sorted(c["fmt"] for c in world.calls) == ["html", "markdown"]
    assert all(c["redact"] is ig.redact_reel_page for c in world.calls)


async def test_fetch_reel_that_fails(world):
    url = tiles("pov__gil")[0].reel_url
    world.failing_reels.add(ig.reel_shortcode(url))
    reel, handle = await reel_report.fetch_reel(url, lambda *a, **k: None)
    assert handle is None and reel.access_status == "timeout" and reel.status_reason


# ---------------------------------------------------------------- grid match + comparison (pure)


def test_take_from_grid_copies_exact_numbers_and_leaves_the_median():
    creator = MOCK.creator.model_copy(deep=True)
    target = creator.reels[2]
    reel = pasted_reel(target.source_url)
    assert reel_report.take_from_grid(reel, creator) is True
    assert (reel.views, reel.likes, reel.comments) == (target.views, target.likes, target.comments)
    assert "views" not in reel.null_reasons
    assert target.source_url not in {r.source_url for r in creator.reels}
    assert [r.id for r in creator.reels] == [f"r{n}" for n in range(1, 12)] and creator.profile.reels_read == 11


def test_take_from_grid_when_the_reel_is_older_than_the_grid():
    creator = MOCK.creator.model_copy(deep=True)
    reel = pasted_reel("https://www.instagram.com/reel/OLDREEL0001/")
    assert reel_report.take_from_grid(reel, creator) is False
    assert reel.views is None and reel.null_reasons["views"] == reel_report.NOT_IN_GRID
    assert len(creator.reels) == 12


def test_compare_cites_only_what_the_creator_report_has():
    rows = reel_report.compare(MOCK.reel, MOCK.creator)
    labels = [r.label for r in rows]
    assert labels[0] == "Views vs @mock_kitchen_a's median"
    assert {"Hook type", "Audio", "Hashtags", "Caption length", "Posted on", "Call to action"} <= set(labels)
    keys = MOCK.creator.citable()
    for row in rows:
        assert set(row.keys) <= set(keys), row.label
    views = rows[0]
    assert views.this_reel == "39K (3.06x)" and views.keys == ["p.median_views"]
    hook = next(r for r in rows if r.label == "Hook type")
    assert hook.this_reel == "question" and "statement" in hook.creator_usual and "question" in hook.note


def test_compare_without_views_says_why():
    reel = MOCK.reel.model_copy(update={"views": None, "ratio_vs_median": None, "null_reasons": {"views": reel_report.NOT_IN_GRID}})
    row = reel_report.compare(reel, MOCK.creator)[0]
    assert row.this_reel is None and row.note == reel_report.NOT_IN_GRID and row.keys == []


def test_compare_before_the_analysis_exists():
    rows = reel_report.compare(pasted_reel(), creator_skeleton())
    assert len(rows) >= 1 and all(r.keys == [] for r in rows)  # nothing to cite yet, nothing invented


# ---------------------------------------------------------------- the runner


class Lane:
    def __init__(self):
        self.built = {"analyse", "fill_caption_fields", "analyse_covers", "write_reel_insights"}
        self.fail = set()
        self.calls = []

    def stage_fn(self, module, name):
        return getattr(self, name) if name in self.built else None

    def analyse(self, report, today):
        self.calls.append("analyse")
        if "analyse" in self.fail:
            raise RuntimeError("bad numbers")
        report.profile.median_views, report.patterns = MOCK.creator.profile.median_views, MOCK.creator.patterns

    def fill_caption_fields(self, reel):
        self.calls.append("fill")
        reel.hook_type, reel.hashtags = MOCK.reel.hook_type, MOCK.reel.hashtags

    async def analyse_covers(self, report, also=()):
        self.calls.append(("covers", [r.id for r in also]))

    async def write_reel_insights(self, report):
        self.calls.append("insights")
        report.insights = [Insight(kind="working", claim="Question hook", keys=["pat.hook_type.question"], reel_ids=["r0"])]
        report.insights_source = "llm"


@pytest.fixture
def env(isolated, monkeypatch):
    monkeypatch.setattr(reports, "settings", isolated, raising=False)
    lane = Lane()
    w = {"reel": "ok", "creator": "ok", "in_grid": True, "fetched": []}

    async def fetch_reel(url, emit):
        w["fetched"].append(url)
        reel = pasted_reel(url)
        if w["reel"] == "fails":
            reel.access_status, reel.status_reason = "timeout", "The page took too long to load"
            return reel, None
        return reel, "mock_kitchen_a"

    async def fetch_creator(handle, emit):
        c = creator_skeleton()
        if w["creator"] == "private":
            c.profile.access_status, c.profile.status_reason, c.reels = "login_wall", "Login wall: this account's Reels aren't public", []
        if w["in_grid"] and c.reels:
            c.reels[0].source_url = w["fetched"][-1]
        return c

    monkeypatch.setattr(reel_report, "fetch_reel", fetch_reel)
    monkeypatch.setattr(creator_profiler, "fetch_creator", fetch_creator)
    monkeypatch.setattr(reports, "_stage_fn", lane.stage_fn)
    return isolated, lane, w


URL = "https://www.instagram.com/reel/MOCKPASTE01/"


async def new_and_run():
    job = reports.create_report("reel", {"url": URL, "reel_url": URL})
    return await reports.run_reel_report(job.id, today=date(2026, 10, 30))


async def test_reel_report_runs_every_stage(env):
    _, lane, _ = env
    job = await new_and_run()
    assert job.status == "done" and job.error is None
    assert {n: s.status for n, s in job.stages.items()} == dict.fromkeys(STAGES["reel"], "done")
    r = job.result
    assert r.kind == "reel" and r.reel.views is not None and r.reel.ratio_vs_median is not None
    assert URL not in {x.source_url for x in r.creator.reels}  # left out of the creator's median
    assert r.comparison and r.insights_source == "llm"
    assert lane.calls == ["analyse", "fill", ("covers", ["r0"]), "insights"]  # the pasted Reel's cover is always described
    assert reports.get_report(job.id) == job


async def test_reel_report_before_the_intelligence_lane_lands(env):
    _, lane, _ = env
    lane.built = set()
    job = await new_and_run()
    assert job.status == "done"
    assert job.stages["creator"].status == "done" and "raw numbers only" in job.stages["creator"].reason
    assert job.stages["visuals"].reason == "Not built yet (task 1.3)"
    assert job.stages["insights"].status == "skipped"
    assert job.result.comparison  # raw numbers still compared


async def test_older_reel_has_no_views_and_says_why(env):
    _, _, w = env
    w["in_grid"] = False
    job = await new_and_run()
    reel = job.result.reel
    assert reel.views is None and reel.ratio_vs_median is None and reel.null_reasons["views"] == reel_report.NOT_IN_GRID
    assert any("isn't among @mock_kitchen_a's recent Reels" in e.message for e in job.events)


async def test_unreadable_reel_fails_the_report(env):
    _, lane, w = env
    w["reel"] = "fails"
    job = await new_and_run()
    assert job.status == "failed" and job.error == "Couldn't read this Reel: The page took too long to load"
    assert all(job.stages[n].status == "skipped" for n in ("creator", "visuals", "insights")) and lane.calls == []


async def test_private_creator_keeps_the_reel(env):
    _, lane, w = env
    w["creator"] = "private"
    job = await new_and_run()
    assert job.status == "done" and job.result.reel.source_url == URL
    assert job.stages["creator"].status == "failed" and "Login wall" in job.stages["creator"].reason
    assert job.stages["insights"].status == "skipped" and lane.calls == []


async def test_analysis_failure_skips_insights_but_keeps_the_comparison(env):
    _, lane, _ = env
    lane.fail = {"analyse"}
    job = await new_and_run()
    assert job.status == "done" and job.stages["creator"].status == "failed"
    assert job.stages["insights"].status == "skipped" and "insights" not in lane.calls
    assert job.result.comparison


# ---------------------------------------------------------------- the HTTP route


@pytest.fixture
def client(env):
    from backend.main import app

    return TestClient(app)


def test_route_accepts_a_reel_link(client, env):
    r = client.post("/reports/reel", json={"url": "instagram.com/reel/MOCKPASTE01?igsh=abc"})
    assert r.status_code == 202
    body = client.get(f"/reports/{r.json()['report_id']}").json()
    assert body["status"] == "done" and body["kind"] == "reel"
    assert body["input"]["reel_url"] == URL and body["result"]["kind"] == "reel"


@pytest.mark.parametrize("raw", ["", "https://www.instagram.com/mock_kitchen_a/", "https://www.instagram.com/p/ABCDEF1/"])
def test_route_rejects_links_that_are_not_reels(client, env, raw):
    r = client.post("/reports/reel", json={"url": raw})
    assert r.status_code == 400 and "Reel link" in r.json()["detail"]
    assert env[2]["fetched"] == []


def test_reel_replay_route_without_a_recording(client, env, monkeypatch):
    import backend.main as main

    monkeypatch.setattr(main, "settings", replace(env[0], replay=True), raising=False)
    r = client.post("/reports/reel", json={"url": URL})
    assert r.status_code == 503 and "No recorded reel report" in r.json()["detail"]
