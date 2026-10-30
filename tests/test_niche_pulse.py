"""Defines "done" for niche_pulse.py, reports.run_niche_report and POST /reports/niche (v2 task 5.1).

Niche Scout, TinyFish Search and Fetch are faked with the v1 mock job's creators and outliers;
the intelligence-lane steps (5.2) are faked through reports._stage_fn, including "not built yet".
"""

import re
from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend import niche_pulse, niche_scout, reports, tinyfish_client
from backend.instagram_parse import TopicRejected
from backend.report_models import STAGES, Insight, PatternRow
from backend.tinyfish_client import FetchedPage, SearchHit, TinyFishAccountError

from .conftest import load_mock

DONE = load_mock("done")
TODAY = date(2026, 10, 30)


# ---------------------------------------------------------------- what users type


@pytest.mark.parametrize(
    "raw, topics",
    [
        (["cooking"], ["cooking"]),
        (["#Cooking", "dal recipes", "cooking"], ["cooking", "dalrecipes"]),
        (["cooking", "", "  ", "#dal"], ["cooking", "dal"]),
    ],
)
def test_parse_keywords(raw, topics):
    assert niche_pulse.parse_keywords(raw) == topics


@pytest.mark.parametrize("raw", [[], None, ["  "], ["a", "b", "c", "d"]])
def test_parse_keywords_needs_one_to_three(raw):
    with pytest.raises(niche_pulse.KeywordsRejected, match="1 to 3"):
        niche_pulse.parse_keywords(raw)


def test_a_bad_keyword_says_why():
    with pytest.raises(TopicRejected):
        niche_pulse.parse_keywords(["x" * 60])


# ---------------------------------------------------------------- research (fakes)


class Internet:
    def __init__(self):
        self.outliers = {"cooking": [0, 1], "dal": [1, 2]}  # indexes into DONE.examples; ex2 is under both
        self.account_error = self.no_relevant_web = False
        self.scouted, self.searched, self.fetched = [], [], []

    async def run_niche_scout(self, topic, emit, *, use_agent=True):
        assert use_agent is False, "Niche Pulse never uses the Agent"
        self.scouted.append(topic)
        if self.account_error:
            raise TinyFishAccountError("TinyFish wallet can't cover this (402).")
        emit("scout", "progress", "Code picked @mock_kitchen_a, @mock_kitchen_c")
        return DONE.creators, [DONE.examples[i].model_copy(deep=True) for i in self.outliers.get(topic, [])]

    async def search(self, query):
        self.searched.append(query)
        topic = re.search(r'[#"](\w+)', query).group(1)
        if self.no_relevant_web:
            return [SearchHit(title="Olympic medal reels", url="https://example.com/medal", snippet="")]
        if query.startswith('"'):
            return [
                SearchHit(title="Shared cooking and dal post", url="https://example.com/shared", snippet=""),  # both keywords find it
                SearchHit(title="Olympic medal reels", url="https://example.com/medal", snippet="sport highlights"),
                *(SearchHit(title=f"{topic} trend {n}", url=f"https://example.com/{topic}/t{n}", snippet="s") for n in range(3)),
            ]
        return [SearchHit(title=f"{topic} pick {n}", url=f"https://example.com/{topic}/p{n}", snippet="s") for n in range(5)]

    async def fetch_pages(self, urls, *, fmt="markdown", html_head=False, purpose=None, redact=None, fallback_to_cache=True):
        assert fmt == "markdown" and redact is not None
        self.fetched.append(list(urls))
        out = []
        for u in urls:
            text = "\nmock_kitchen_a\nFollow\nOriginal audio - mock_kitchen_a\n" if u.endswith("MOCK0000001/") else "no audio here"
            out.append(FetchedPage(url=u, retrieved_at="2026-10-30T06:00:00+00:00", text=text, description=None))
        return out


@pytest.fixture
def net(monkeypatch):
    n = Internet()
    monkeypatch.setattr(niche_scout, "run_niche_scout", n.run_niche_scout)
    monkeypatch.setattr(tinyfish_client, "search", n.search)
    monkeypatch.setattr(tinyfish_client, "fetch_pages", n.fetch_pages)
    return n


def collect(events):
    return lambda source, kind, message, data=None: events.append(message)


async def test_run_pulse_gathers_outliers_and_web_signals(net):
    events = []
    pulse = await niche_pulse.run_pulse(["cooking", "dal"], collect(events), TODAY)
    assert net.scouted == ["cooking", "dal"] and sorted(net.searched) == [
        '"cooking" reels trending this week', '"dal" reels trending this week', "#cooking instagram reels", "#dal instagram reels"]
    # ex2 was an outlier under both keywords: kept once; best ratio first; numbered after sorting
    assert [r.source_url[-12:] for r in pulse.reels] == ["MOCK0000001/", "MOCK0000002/", "MOCK0000003/"]
    assert [r.id for r in pulse.reels] == ["r1", "r2", "r3"] and [r.ratio_vs_median for r in pulse.reels] == [3.1, 2.4, 2.1]
    assert [r.topic for r in pulse.reels] == ["cooking", "cooking", "dal"]
    assert all(r.handle for r in pulse.reels)
    assert pulse.creators_read == 2  # the walled creator doesn't count
    assert pulse.run_date == TODAY and pulse.keywords == ["cooking", "dal"]


async def test_web_signals_capped_and_deduplicated(net):
    pulse = await niche_pulse.run_pulse(["cooking", "dal"], collect([]), TODAY)
    urls = [w.url for w in pulse.web]
    assert len(urls) == len(set(urls)) == 9  # 5 per keyword, and the hit both keywords found is kept once
    assert urls.count("https://example.com/shared") == 1 and "https://example.com/medal" not in urls
    assert urls[:5] == ["https://example.com/shared", *(f"https://example.com/cooking/t{n}" for n in range(3)),
                        "https://example.com/cooking/p0"]  # the quoted query's hits first, then the hashtag query's
    assert all(w.retrieved_at for w in pulse.web)
    assert pulse.web[0].snippet is None  # an empty snippet isn't shown as ""


async def test_web_results_that_dont_name_the_keyword_are_dropped(net):
    net.no_relevant_web = True
    events = []
    pulse = await niche_pulse.run_pulse(["dal"], collect(events), TODAY)
    assert pulse.web == [] and "#dal: No web results mention #dal" in events


@pytest.mark.parametrize(
    "title, url, topic, expected",
    [
        ("Dal is life", "https://x.example/a", "dal", True),
        ("Dal Chivda Reels", "https://www.instagram.com/popular/dal-chivda-reels", "dal", True),
        ("x", "https://www.instagram.com/explore/tags/dal/", "dal", True),
        ("Trending Reels Daleng", "https://x.example/b", "dal", False),
        ("Olympic medal reels", "https://x.example/medal", "dal", False),
        ("Instagram Reels Trends This Week", "https://www.instagram.com/popular/reel-trends", "dal", False),
        ("#cooking | TikTok", "https://www.tiktok.com/tag/cooking", "cooking", True),
    ],
)
def test_mentions_needs_the_whole_word(title, url, topic, expected):
    assert niche_pulse.mentions(SearchHit(title=title, url=url, snippet=""), topic) is expected


async def test_audio_comes_from_one_markdown_fetch(net):
    pulse = await niche_pulse.run_pulse(["cooking", "dal"], collect([]), TODAY)
    assert len(net.fetched) == 1 and len(net.fetched[0]) == 3
    first, second = pulse.reels[0], pulse.reels[1]
    assert first.audio_label.startswith("Original audio") and first.original_audio is True
    assert second.audio_label is None and "audio_label" in second.null_reasons and "original_audio" in second.null_reasons


async def test_lines_say_which_keyword_they_are_about(net):
    events = []
    await niche_pulse.run_pulse(["cooking", "dal"], collect(events), TODAY)
    assert "#cooking: Code picked @mock_kitchen_a, @mock_kitchen_c" in events
    assert "#dal: 5 web results" in events
    assert events[-1] == "3 outliers from 2 creators; 9 web results"


async def test_no_outliers_says_why(net):
    net.outliers = {}
    pulse = await niche_pulse.run_pulse(["cooking"], collect([]), TODAY)
    assert pulse.reels == [] and "2x" in pulse.null_reasons["reels"] and pulse.web
    assert net.fetched == []


async def test_account_problem_propagates(net):
    net.account_error = True
    with pytest.raises(TinyFishAccountError):
        await niche_pulse.run_pulse(["cooking"], collect([]), TODAY)


# ---------------------------------------------------------------- the runner + daily snapshots


class Lane:
    def __init__(self):
        self.built = {"analyse_pulse", "write_pulse_insights"}
        self.previous = []

    def stage_fn(self, module, name):
        return getattr(self, name) if name in self.built else None

    def analyse_pulse(self, pulse, previous):
        self.previous.append(previous.run_date if previous else None)
        pulse.patterns = [PatternRow(dimension="hook_type", value="question", reel_ids=["r1"], median_ratio=3.1, in_top=1, in_bottom=0)]
        pulse.since_last_run = ["New hook type: question"] if previous else []
        pulse.previous_run_date = previous.run_date if previous else None

    async def write_pulse_insights(self, pulse):
        pulse.insights = [Insight(kind="working", claim="Questions lead", keys=["pat.hook_type.question"], reel_ids=["r1"])]
        pulse.insights_source = "llm"


@pytest.fixture
def env(isolated, monkeypatch, net):
    monkeypatch.setattr(reports, "settings", isolated, raising=False)
    lane = Lane()
    monkeypatch.setattr(reports, "_stage_fn", lane.stage_fn)
    return isolated, lane, net


async def run(keywords=("cooking", "dal"), today=TODAY):
    job = reports.create_report("niche", {"keywords": list(keywords)})
    return await reports.run_niche_report(job.id, today=today)


async def test_niche_report_runs_every_stage_and_saves_the_day(env):
    isolated, lane, _ = env
    job = await run()
    assert job.status == "done" and {n: s.status for n, s in job.stages.items()} == dict.fromkeys(STAGES["niche"], "done")
    assert job.result.kind == "niche" and job.result.insights_source == "llm" and job.result.patterns
    saved = isolated.data_dir / "pulse" / "cooking+dal" / "2026-10-30.json"
    assert saved.exists() and "pat" not in saved.name
    assert lane.previous == [None]
    assert any("first run for these keywords" in e.message for e in job.events)


async def test_the_next_day_compares_with_the_previous_run(env):
    _, lane, _ = env
    await run(today=date(2026, 10, 29))
    job = await run(keywords=("dal", "cooking"), today=TODAY)  # same keywords, any order
    assert lane.previous == [None, date(2026, 10, 29)]
    assert job.result.since_last_run == ["New hook type: question"] and job.result.previous_run_date == date(2026, 10, 29)
    assert any("since 29 Oct: 1 change(s)" in e.message for e in job.events)


async def test_a_rerun_the_same_day_still_compares_with_yesterday(env):
    _, lane, _ = env
    await run(today=date(2026, 10, 29))
    await run(today=TODAY)
    await run(today=TODAY)
    assert lane.previous == [None, date(2026, 10, 29), date(2026, 10, 29)]


async def test_before_5_2_lands_the_report_still_finishes_and_saves(env):
    isolated, lane, _ = env
    lane.built = set()
    job = await run()
    assert job.status == "done" and job.stages["research"].status == "done"
    assert job.stages["patterns"].reason == "Not built yet (task 5.2)" and job.stages["insights"].status == "skipped"
    assert (isolated.data_dir / "pulse" / "cooking+dal" / "2026-10-30.json").exists()


async def test_a_day_without_outliers(env):
    _, _, net = env
    net.outliers = {}
    job = await run()
    assert job.status == "done" and job.result.web
    assert job.stages["patterns"].status == job.stages["insights"].status == "skipped"
    assert "2x" in job.stages["research"].reason


async def test_account_problem_fails_the_report(env):
    _, _, net = env
    net.account_error = True
    job = await run()
    assert job.status == "failed" and "402" in job.error and job.stages["research"].status == "failed"


# ---------------------------------------------------------------- the HTTP route


@pytest.fixture
def client(env):
    from backend.main import app

    return TestClient(app)


def test_route_runs_a_pulse(client, env):
    r = client.post("/reports/niche", json={"keywords": ["#Cooking", "dal"]})
    assert r.status_code == 202
    body = client.get(f"/reports/{r.json()['report_id']}").json()
    assert body["status"] == "done" and body["kind"] == "niche" and body["input"]["keywords"] == ["cooking", "dal"]


@pytest.mark.parametrize(
    "keywords, message",
    [([], "1 to 3"), (["a1", "b1", "c1", "d1"], "1 to 3"), (["x" * 60], "under 40 characters")],
)
def test_route_rejects_bad_keywords(client, env, keywords, message):
    r = client.post("/reports/niche", json={"keywords": keywords})
    assert r.status_code == 400 and message in r.json()["detail"]
    assert env[2].scouted == []


def test_niche_replay_route_without_a_recording(client, env, monkeypatch):
    import backend.main as main

    monkeypatch.setattr(main, "settings", replace(env[0], replay=True), raising=False)
    r = client.post("/reports/niche", json={"keywords": ["cooking"]})
    assert r.status_code == 503 and "No recorded niche report" in r.json()["detail"]
