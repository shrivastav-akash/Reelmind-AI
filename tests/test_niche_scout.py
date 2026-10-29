"""Defines "done" for niche_scout.py (Fri tasks A1-A3). IDs refer to docs/test-cases.md.

A fake TinyFish replays the REAL logged-out pages fetched on 29 Oct (samples/instagram/):
the #cooking topic page, 11 creators' Reels grids, and the Agent's real picks. Each test
switches on one thing that goes wrong for real users: a walled topic page, an Agent that
times out or invents a handle, a walled or deleted creator, a Reel page that won't load.
"""

import asyncio
import json
from datetime import datetime, timezone

import pytest

from backend import instagram_parse as ig
from backend import niche_scout, tinyfish_client
from backend.outliers import ReelCounts, pick_outliers, score_creator
from backend.tinyfish_client import AgentEvent, AgentOutcome, FetchedPage, TinyFishAccountError

from .conftest import SAMPLES

# Built on Friday: run with `pytest -m friday`. Delete this line once the file passes.
pytestmark = pytest.mark.friday

IG = SAMPLES / "instagram"
NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")
TOPIC = FetchedPage(**json.loads((IG / "topic_cooking.json").read_text()))
GRIDS = {p.stem.removeprefix("grid_"): FetchedPage(**json.loads(p.read_text())) for p in IG.glob("grid_*.json")}
AGENT_PICKS = json.loads((IG / "agent_topic_cooking.json").read_text())["result"]["creators"]
TILES = {}  # canonical reel url -> (handle, GridTile)
for _h, _p in GRIDS.items():
    for _t in ig.parse_grid(_p.text, _p.links, _p.description, _h).tiles:
        TILES[_t.reel_url] = (_h, _t)


def rounded(n: int) -> str:
    """How og:description rounds counts ("1M" for 1.3M), so tests can tell grid and og numbers apart."""
    return f"{n // 1_000_000}M" if n >= 1_000_000 else f"{n // 1000}K" if n >= 1000 else str(n)


def grid_tiles(handle):
    p = GRIDS[handle]
    return ig.parse_grid(p.text, p.links, p.description, handle).tiles


def expected_outliers(handles):
    cands = []
    for h in handles:
        _, cs = score_creator(h, [ReelCounts(t.reel_url, t.views, t.likes, t.comments, t.pinned) for t in grid_tiles(h)])
        cands += cs
    return pick_outliers(cands)


class World:
    """What the fake internet does in one test."""

    def __init__(self):
        self.agent = "ok"  # ok | wall | timeout | custom
        self.agent_picks = AGENT_PICKS
        self.topic = "ok"  # ok | walled | empty
        self.walled_grids, self.missing_grids, self.thin_grids, self.failing_reels = set(), set(), set(), set()
        self.account_error = False
        self.fetch_calls, self.order = [], []

    async def fetch_pages(self, urls, *, fmt="markdown", html_head=False, purpose=None, redact=None, fallback_to_cache=True):
        self.fetch_calls.append({"urls": list(urls), "fmt": fmt, "html_head": html_head, "redact": redact})
        if self.account_error:
            raise TinyFishAccountError("TinyFish wallet can't cover this (402). Top up or switch to the spare key.")
        out = []
        for url in urls:
            page = self._page(url, fmt)
            out.append(redact(page) if (redact and page.ok) else page)
        return out

    def _page(self, url, fmt):
        if "/explore/tags/" in url:
            self.order.append("fetch_topic")
            if self.topic == "walled":
                return FetchedPage(url=url, retrieved_at=NOW, final_url="https://www.instagram.com/accounts/login/?next=/explore/",
                                   text="Log in", links=["https://www.instagram.com/accounts/login/"])
            if self.topic == "empty":
                return FetchedPage(url=url, retrieved_at=NOW, final_url="https://www.instagram.com/popular/zzqxvw/",
                                   text="", links=["https://www.instagram.com/"])
            return TOPIC
        if url.rstrip("/").endswith("/reels"):
            handle = url.split("/")[3]
            if handle in self.missing_grids or handle not in GRIDS:
                return FetchedPage(url=url, retrieved_at=NOW, error="404 Not Found")
            if handle in self.walled_grids:
                return FetchedPage(url=url, retrieved_at=NOW, final_url=url, links=[],
                                   text="Instagram\nLog In\nSign Up\nThis account is private\nFollow to see their photos and videos.")
            if handle in self.thin_grids:
                g = GRIDS[handle]
                return FetchedPage(url=url, retrieved_at=NOW, description=g.description, links=g.links[:40],
                                   text="Tagged\n10\n1\nView Count Icon\n900\n12\n0\nView Count Icon\n1,100\n5\n0\nView Count Icon\n\nClose")
            return GRIDS[handle]
        canonical = ig.canonical_reel_url(url)
        if canonical:
            code = ig.reel_shortcode(url)
            if code in self.failing_reels or canonical not in TILES:
                return FetchedPage(url=url, retrieved_at=NOW, error="Fetch failed: page timed out")
            handle, tile = TILES[canonical]
            head = f'<meta content="https://cdn.example/v/t51.2885-15/{code}.jpg" property="og:image"/>' if fmt == "html" else ""
            return FetchedPage(
                url=url, retrieved_at=NOW, published_date="2026-10-20T10:00:00.000Z", text=head,
                description=f'{rounded(tile.likes)} likes, {tile.comments:,} comments - {handle} on October 20, 2026: "Hook for {code}\\n#cooking"',
                links=[f"https://www.instagram.com/{handle}/"], image_links=[],
            )
        return FetchedPage(url=url, retrieved_at=NOW, error="unexpected URL in test")

    async def run_agent(self, url, goal, schema, *, on_event=None, max_seconds=90, stealth=False):
        assert "/explore/tags/" in url, "the Agent is only used on the topic page (grids give it a login wall)"
        assert "Do not include any numbers" in goal and max_seconds <= 75
        self.order.append("agent_start")
        await tinyfish_client._emit(on_event, AgentEvent("streaming_url", "Live browser view ready", "r1", "https://live.example/r1"))
        await tinyfish_client._emit(on_event, AgentEvent("progress", "Extract reel creator details", "r1"))
        await asyncio.sleep(0.05)
        self.order.append("agent_end")
        base = dict(url=url, profile="lite", status="COMPLETED", steps=3, duration_s=50.0, streaming_url="https://live.example/r1")
        if self.agent == "wall":
            return AgentOutcome(**base, access_status="login_wall", status_reason="Login wall: public view not available",
                                result={"topic": "cooking", "blocked": True, "blocked_reason": "Log in to continue", "creators": []})
        if self.agent == "timeout":
            return AgentOutcome(**{**base, "status": None}, access_status="timeout", status_reason="Run did not finish before our deadline",
                                error_code="TIMEOUT")
        return AgentOutcome(**base, access_status="accessible", status_reason=None,
                            result={"topic": "cooking", "blocked": False, "creators": self.agent_picks})


@pytest.fixture
def world(monkeypatch):
    w = World()
    monkeypatch.setattr(tinyfish_client, "fetch_pages", w.fetch_pages)
    monkeypatch.setattr(tinyfish_client, "run_agent", w.run_agent)
    monkeypatch.setattr(tinyfish_client, "run_agent_with_stealth_retry", w.run_agent)
    return w


@pytest.fixture
def events():
    return []


@pytest.fixture
def emit(events):
    def _emit(source, kind, message, data=None):
        events.append({"source": source, "kind": kind, "message": message, "data": data})

    return _emit


def handles(creators):
    return [c.handle for c in creators]


# ---------------------------------------------------------------- the normal run (D1)


async def test_real_cooking_run(world, emit, events):  # D1, G5
    creators, examples = await niche_scout.run_niche_scout("cooking", emit)

    agent_first_four = [p["handle"] for p in AGENT_PICKS][:4]
    assert handles(creators) == agent_first_four
    for c in creators:
        assert c.picked_by == "agent" and c.access_status == "accessible" and c.method == "fetch"
        assert c.followers and c.median_views and c.reels_read == 12
        assert c.pick_reason is None or not any(ch.isdigit() for ch in c.pick_reason)
        assert c.pinned_skipped == sum(t.pinned for t in grid_tiles(c.handle))

    want = expected_outliers(agent_first_four)
    assert [e.id for e in examples] == [f"ex{i}" for i in range(1, len(want) + 1)]
    assert [(e.handle, e.outlier_ratio) for e in examples] == [(c.handle, c.outlier_ratio) for c in want]
    assert 3 <= len(examples) <= 5
    for e, c in zip(examples, want):
        assert e.access_status == "accessible" and e.method == "fetch" and e.retrieved_at
        assert e.source_url == ig.canonical_reel_url(c.reel_url)
        assert e.views == c.views and e.creator_median_views == c.creator_median_views
        assert e.likes == TILES[e.source_url][1].likes  # the grid's precise count, not og's rounded one
        assert e.hook_line.startswith("Hook for") and e.cover_url.startswith("https://cdn.example/")
        for field, value in e.model_dump(exclude={"status_reason"}).items():  # status_reason is empty when all is well
            if value is None:
                assert field in e.null_reasons, f"{e.id}.{field} is None without a reason"

    kinds = [ev["kind"] for ev in events]
    assert {"data": {"url": "https://live.example/r1"}}.items() <= next(ev for ev in events if ev["kind"] == "streaming_url").items()
    assert any(ev["kind"] == "creator" and "Agent picked" in ev["message"] for ev in events)
    outlier_lines = [ev["message"] for ev in events if ev["kind"] == "outlier"]
    assert len(outlier_lines) == len(examples)
    assert f"x @{examples[0].handle}'s median" in outlier_lines[0]
    assert kinds.index("streaming_url") < kinds.index("creator") < kinds.index("outlier")


async def test_agent_and_fetch_run_at_the_same_time(world, emit):
    await niche_scout.run_niche_scout("cooking", emit)
    assert world.order.index("fetch_topic") < world.order.index("agent_end")


async def test_reel_pages_fetched_once_as_html_and_redacted(world, emit):  # G1
    _, examples = await niche_scout.run_niche_scout("cooking", emit)
    reel_calls = [c for c in world.fetch_calls if any(ig.reel_shortcode(u) for u in c["urls"])]
    assert len(reel_calls) == 1
    call = reel_calls[0]
    assert call["fmt"] == "html" and call["html_head"] and call["redact"] is ig.redact_reel_page
    assert len(call["urls"]) == len(examples)


async def test_pinned_reels_never_become_examples(world, emit):  # D11
    _, examples = await niche_scout.run_niche_scout("cooking", emit)
    assert not any(TILES[e.source_url][1].pinned for e in examples)


async def test_topic_word_is_normalised(world, emit):  # B2
    await niche_scout.run_niche_scout("#Cooking ", emit)
    assert any(u == "https://www.instagram.com/explore/tags/cooking/" for c in world.fetch_calls for u in c["urls"])


# ---------------------------------------------------------------- when the Agent struggles (D2-D6)


CODE_PICKS = ["pov__gil", "eylems_kitchen", "baiba.tropina", "hkncook"]  # smallest first among the prefetched grids


async def test_agent_wall_falls_back_to_code_picks(world, emit, events):  # D2
    world.agent = "wall"
    creators, examples = await niche_scout.run_niche_scout("cooking", emit)
    assert handles(creators) == CODE_PICKS and all(c.picked_by == "code" for c in creators)
    assert examples and all(e.access_status == "accessible" for e in examples)
    assert any("login wall" in ev["message"].lower() for ev in events)


async def test_agent_timeout_falls_back(world, emit, events):  # D3
    world.agent = "timeout"
    creators, _ = await niche_scout.run_niche_scout("cooking", emit)
    assert handles(creators) == CODE_PICKS
    assert any("time" in ev["message"].lower() for ev in events if ev["source"] == "scout")


async def test_invented_handles_are_dropped(world, emit):  # D4
    world.agent_picks = [{"handle": "pov__gil"}, {"handle": "made_up_cook"}, {"handle": "eylems_kitchen"}, {"handle": "hkncook"}]
    creators, _ = await niche_scout.run_niche_scout("cooking", emit)
    assert "made_up_cook" not in handles(creators)
    assert handles(creators)[:3] == ["pov__gil", "eylems_kitchen", "hkncook"]


async def test_agent_picks_are_cleaned(world, emit):  # D5, D6
    world.agent_picks = [
        {"handle": "POV__GIL", "reason": "Small creator (~34.4M followers) with ASMR recipes"},
        {"handle": "pov__gil", "reason": "duplicate"},
        {"handle": "tasty", "reason": "Huge brand"},
        {"handle": "eylems_kitchen", "reason": "Home cook; 99K followers"},
        {"handle": "hkncook", "reason": "Fast recipes"},
        {"handle": "baiba.tropina", "reason": "Easy meals"},
        {"handle": "zap_eat", "reason": "Fifth pick, over the cap"},
    ]
    creators, _ = await niche_scout.run_niche_scout("cooking", emit)
    assert handles(creators) == ["pov__gil", "eylems_kitchen", "hkncook", "baiba.tropina"]
    assert creators[0].pick_reason == "Small creator with ASMR recipes"
    assert creators[1].pick_reason == "Home cook"


async def test_too_few_valid_agent_picks_are_topped_up_by_code(world, emit):
    world.agent_picks = [{"handle": "baiba.tropina"}, {"handle": "ghost_one"}, {"handle": "ghost_two"}]
    creators, _ = await niche_scout.run_niche_scout("cooking", emit)
    assert creators[0].handle == "baiba.tropina" and creators[0].picked_by == "agent"
    assert len(creators) >= niche_scout.MIN_CREATORS and all(c.picked_by == "code" for c in creators[1:])


# ---------------------------------------------------------------- when Instagram walls things (D7-D10, D14)


async def test_everything_walled_uses_saved_list(world, emit, events):  # D7
    world.topic, world.agent = "walled", "wall"
    creators, examples = await niche_scout.run_niche_scout("cooking", emit)
    saved = [c["handle"] for c in json.loads((SAMPLES / "demo_creators.json").read_text())["creators"]][:4]
    assert handles(creators) == saved and all(c.picked_by == "saved_list" for c in creators)
    assert examples
    assert any("saved" in ev["message"].lower() for ev in events)


async def test_topic_with_no_creators(world, emit, events):  # B13, D7
    world.topic, world.agent_picks = "empty", []
    creators, examples = await niche_scout.run_niche_scout("zzqxvw", emit)
    assert creators == [] and examples == []
    assert any(ev["kind"] == "error" and "No creators" in ev["message"] for ev in events)


async def test_one_walled_grid(world, emit):  # D8
    world.walled_grids = {"shifhaneen"}
    creators, examples = await niche_scout.run_niche_scout("cooking", emit)
    walled = next(c for c in creators if c.handle == "shifhaneen")
    assert walled.access_status == "login_wall" and walled.status_reason and walled.median_views is None
    assert all(e.handle != "shifhaneen" for e in examples)
    assert sum(c.access_status == "accessible" for c in creators) == 3


async def test_not_found_grid(world, emit):  # D9
    world.missing_grids = {"shifhaneen"}
    world.agent_picks = AGENT_PICKS  # the Agent saw @shifhaneen on the page, but the account is gone
    creators, _ = await niche_scout.run_niche_scout("cooking", emit)
    gone = next((c for c in creators if c.handle == "shifhaneen"), None)
    assert gone is None or gone.access_status == "not_found"


async def test_creator_with_too_few_views(world, emit):  # D10
    world.thin_grids = {"shifhaneen"}
    creators, examples = await niche_scout.run_niche_scout("cooking", emit)
    thin = next(c for c in creators if c.handle == "shifhaneen")
    assert thin.median_views is None and thin.status_reason == "Too few Reels with views"
    assert all(e.handle != "shifhaneen" for e in examples)


async def test_failed_reel_page_is_not_citable(world, emit):  # D14
    first = expected_outliers([p["handle"] for p in AGENT_PICKS][:4])[0]
    world.failing_reels = {ig.reel_shortcode(first.reel_url)}
    _, examples = await niche_scout.run_niche_scout("cooking", emit)
    broken = next(e for e in examples if e.source_url == ig.canonical_reel_url(first.reel_url))
    assert broken.access_status != "accessible" and broken.status_reason
    assert broken.views == first.views and broken.outlier_ratio == first.outlier_ratio
    assert broken.caption is None and "caption" in broken.null_reasons


async def test_no_credits_stops_the_scout(world, emit):  # D16
    world.account_error = True
    with pytest.raises(TinyFishAccountError, match="402"):
        await niche_scout.run_niche_scout("cooking", emit)
