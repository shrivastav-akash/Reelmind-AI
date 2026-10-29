"""Defines "done" for niche_scout.py (Fri tasks A1-A3). Fails with NotImplementedError until built.

A fake TinyFish stands in for the network:
- topic page links to @cook_a, @cook_b, @cook_c, a mega account (@natgeo) and Instagram's own pages
- @cook_a: 12 Reels, median 10K, two outliers (50K = 5.0x, 35K = 3.5x)
- @cook_b: login wall
- @cook_c: 6 Reels, median 20K, one outlier (45K = 2.25x)
"""

from datetime import datetime, timezone

import pytest

from backend import niche_scout, tinyfish_client
from backend.tinyfish_client import AgentOutcome, FetchedPage

# Built on Friday: run with `pytest -m friday`. Delete this line once the file passes.
pytestmark = pytest.mark.friday

NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")
TOPIC_LINKS = [
    "https://www.instagram.com/cook_a/",
    "https://www.instagram.com/explore/tags/food/",
    "https://www.instagram.com/cook_b/",
    "https://www.instagram.com/natgeo/",
    "https://www.instagram.com/reel/AAA111/?utm_source=popular_topic_grid",
    "https://www.instagram.com/cook_c/",
]
VIEWS = {
    "cook_a": ["10K"] * 10 + ["50K", "35K"],
    "cook_c": ["20K"] * 5 + ["45K"],
}


def reel_url(handle, i):
    return f"https://www.instagram.com/{handle}/reel/{handle.upper()}{i:03d}/"


@pytest.fixture
def events():
    return []


@pytest.fixture
def emit(events):
    def _emit(source, kind, message, data=None):
        events.append((source, kind, message, data))

    return _emit


@pytest.fixture
def fake_tinyfish(monkeypatch):
    calls = {"agent": [], "fetch": []}

    async def fetch_pages(urls, **kw):
        calls["fetch"].append(list(urls))
        pages = []
        for u in urls:
            if "/explore/tags/" in u:
                pages.append(FetchedPage(url=u, retrieved_at=NOW, final_url="https://www.instagram.com/popular/cooking/",
                                         title="Cooking • 362M reels on Instagram", text="Top reels", links=TOPIC_LINKS))
            elif "/reel/" in u:
                code = u.rstrip("/").split("/")[-1]
                handle = "cook_c" if code.startswith("COOK_C") else "cook_a"
                pages.append(FetchedPage(
                    url=u, retrieved_at=NOW,
                    description=f'1.2K likes, 30 comments - {handle} on October 20, 2026: "Hook for {code}\\n#cooking"',
                    text="Original audio", image_links=[f"https://cdn.example/{code}.jpg"],
                ))
            else:
                pages.append(FetchedPage(url=u, retrieved_at=NOW, error="404"))
        return pages

    async def run_agent(url, goal, schema, *, on_event=None, max_seconds=90, stealth=False):
        handle = url.split("/")[3]
        calls["agent"].append(handle)
        if handle == "cook_b":
            result = {"handle": handle, "blocked": True, "blocked_reason": "Log in to see more"}
            status = ("login_wall", "Login wall: public view not available")
        else:
            result = {"handle": handle, "blocked": False,
                      "reels": [{"reel_url": reel_url(handle, i), "views": v, "likes": "100", "comments": "5"}
                                for i, v in enumerate(VIEWS[handle])]}
            status = ("accessible", None)
        if on_event:
            on_event(tinyfish_client.AgentEvent("streaming_url", "Live browser view ready", "r", f"https://live/{handle}"))
        return AgentOutcome(url=url, profile="lite", access_status=status[0], status_reason=status[1],
                            status="COMPLETED", result=result, steps=6, duration_s=21.0,
                            streaming_url=f"https://live/{handle}")

    monkeypatch.setattr(tinyfish_client, "fetch_pages", fetch_pages)
    monkeypatch.setattr(tinyfish_client, "run_agent", run_agent)
    monkeypatch.setattr(tinyfish_client, "run_agent_with_stealth_retry", run_agent)
    return calls


async def test_discover_skips_mega_accounts_and_instagram_pages(fake_tinyfish, emit, events):
    handles = await niche_scout.discover_creators("cooking", emit)
    assert handles == ["cook_a", "cook_b", "cook_c"]
    assert any(src == "scout" for src, *_ in events)


async def test_read_grid_accessible_creator(fake_tinyfish, emit):
    creator, candidates = await niche_scout.read_grid("cook_a", emit)
    assert creator.access_status == "accessible" and creator.method == "agent"
    assert creator.reels_read == 12 and creator.median_views == 10_000
    assert creator.streaming_url == "https://live/cook_a"
    assert sorted(c.outlier_ratio for c in candidates)[-2:] == [3.5, 5.0]


async def test_read_grid_login_wall_is_reported_not_bypassed(fake_tinyfish, emit):
    creator, candidates = await niche_scout.read_grid("cook_b", emit)
    assert creator.access_status == "login_wall" and candidates == []
    assert fake_tinyfish["agent"] == ["cook_b"]  # no second attempt of any kind


async def test_run_niche_scout_end_to_end(fake_tinyfish, emit, events):
    creators, examples = await niche_scout.run_niche_scout("cooking", emit)
    assert [c.handle for c in creators] == ["cook_a", "cook_b", "cook_c"]
    assert [e.id for e in examples] == ["ex1", "ex2", "ex3"]
    assert [e.outlier_ratio for e in examples] == [5.0, 3.5, 2.25]
    first = examples[0]
    assert first.access_status == "accessible" and first.views == 50_000 and first.creator_median_views == 10_000
    assert first.source_url.startswith("https://www.instagram.com/") and first.retrieved_at
    assert first.likes == 1200 and first.hook_line.startswith("Hook for") and first.audio_label == "Original audio"
    outlier_lines = [m for _, kind, m, _ in events if kind == "outlier"]
    assert len(outlier_lines) == 3 and "5.0x @cook_a" in outlier_lines[0]
