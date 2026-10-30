"""Defines "done" for creator_profiler.py (v2 task 1.1).

A fake TinyFish replays the REAL logged-out Reels grids fetched on 29 Oct (samples/instagram/)
and builds each Reel page from its grid tile, like tests/test_niche_scout.py does. Each test
switches on one thing that goes wrong for real users: a private or deleted account, a Reel
page that won't load or hits a login wall, a grid with only pinned Reels.
"""

import json
from datetime import date, datetime, timezone

import pytest

from backend import creator_profiler, tinyfish_client
from backend import instagram_parse as ig
from backend.tinyfish_client import FetchedPage, TinyFishAccountError

from .conftest import SAMPLES

IG = SAMPLES / "instagram"
NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")
GRIDS = {p.stem.removeprefix("grid_"): FetchedPage(**json.loads(p.read_text())) for p in IG.glob("grid_*.json")}
TILES = {}  # canonical reel url -> (handle, n-th tile, GridTile)
for _h, _p in GRIDS.items():
    for _n, _t in enumerate(ig.parse_grid(_p.text, _p.links, _p.description, _h).tiles):
        TILES[_t.reel_url] = (_h, _n, _t)


def tiles(handle):
    p = GRIDS[handle]
    return ig.parse_grid(p.text, p.links, p.description, handle).tiles


class World:
    def __init__(self):
        self.walled, self.missing, self.only_pinned = set(), set(), set()
        self.failing_reels, self.walled_reels, self.original_audio = set(), set(), set()
        self.account_error = False
        self.calls = []

    async def fetch_pages(self, urls, *, fmt="markdown", html_head=False, purpose=None, redact=None, fallback_to_cache=True):
        self.calls.append({"urls": list(urls), "fmt": fmt, "html_head": html_head, "redact": redact})
        if self.account_error:
            raise TinyFishAccountError("TinyFish wallet can't cover this (402).")
        out = []
        for url in urls:
            page = self._page(url, fmt)
            out.append(redact(page) if (redact and page.ok) else page)
        return out

    def _page(self, url, fmt):
        if url.rstrip("/").endswith("/reels"):
            handle = url.split("/")[3]
            if handle in self.missing or handle not in GRIDS:
                return FetchedPage(url=url, retrieved_at=NOW, error="404 Not Found")
            if handle in self.walled:
                return FetchedPage(url=url, retrieved_at=NOW, final_url=url, links=[], description=GRIDS[handle].description,
                                   text="Instagram\nLog In\nSign Up\nThis account is private\nFollow to see their photos and videos.")
            if handle in self.only_pinned:
                g = GRIDS[handle]
                return FetchedPage(url=url, retrieved_at=NOW, description=g.description, links=g.links,
                                   text="Tagged\n10\n1\nPinned post icon\nView Count Icon\n900\n\nClose")
            return GRIDS[handle]
        code = ig.reel_shortcode(url)
        canonical = ig.canonical_reel_url(url)
        if code in self.failing_reels or canonical not in TILES:
            return FetchedPage(url=url, retrieved_at=NOW, error="Fetch failed: page timed out")
        if code in self.walled_reels:
            return FetchedPage(url=url, retrieved_at=NOW, final_url="https://www.instagram.com/accounts/login/?next=/reel/", text="Log in")
        handle, n, tile = TILES[canonical]
        head = f'<meta content="https://cdn.example/v/{code}.jpg" property="og:image"/>' if fmt == "html" else ""
        audio = f"\n{handle}\nFollow\nOriginal audio - {handle}\n" if code in self.original_audio else ""
        day = 28 - n  # newest tile first, one day apart
        return FetchedPage(
            url=url, retrieved_at=NOW, published_date=f"2026-10-{day:02d}T10:00:00.000Z", text=head + audio,
            description=f'1K likes, {tile.comments or 0:,} comments - {handle} on October {day}, 2026: "Hook for {code}\\n#cooking #dinner"',
            links=[f"https://www.instagram.com/{handle}/"], image_links=[],
        )


@pytest.fixture
def world(monkeypatch):
    w = World()
    monkeypatch.setattr(tinyfish_client, "fetch_pages", w.fetch_pages)
    return w


@pytest.fixture
def events():
    return []


def emit_into(events):
    def emit(source, kind, message, data=None):
        events.append((source, kind, message))
    return emit


async def run(handle, events):
    return await creator_profiler.fetch_creator(handle, emit_into(events))


# ---------------------------------------------------------------- the normal path


async def test_reads_profile_and_recent_reels(world, events):
    report = await run("eylems_kitchen", events)
    p = report.profile
    assert (p.handle, p.followers, p.following, p.posts) == ("eylems_kitchen", 99_000, 16, 172)
    assert p.access_status == "accessible" and p.status_reason is None
    recent = [t for t in tiles("eylems_kitchen") if not t.pinned]
    assert p.pinned_skipped == 3 and p.reels_read == len(recent) == len(report.reels) == 9
    assert [r.id for r in report.reels] == [f"r{n}" for n in range(1, 10)]
    for r, t in zip(report.reels, recent):
        assert r.source_url == t.reel_url and r.access_status == "accessible"
        assert (r.views, r.likes, r.comments) == (t.views, t.likes, t.comments)  # grid numbers, not og's rounded "1K"
        assert r.hook_line == f"Hook for {ig.reel_shortcode(t.reel_url)}" and "#cooking" in r.caption
        assert r.posted_date is not None and r.cover_url.startswith("https://cdn.example/")
    assert report.reels[0].posted_date > report.reels[-1].posted_date  # r1 is the newest
    assert report.reels[0].posted_date == date(2026, 10, 25)  # tile 4 of 12: the first 3 are pinned


async def test_fetches_the_grid_once_then_reel_pages_as_redacted_html_and_markdown(world, events):
    await run("eylems_kitchen", events)
    grid_call, *reel_calls = world.calls
    assert grid_call["urls"] == ["https://www.instagram.com/eylems_kitchen/reels/"] and grid_call["fmt"] == "markdown"
    html = next(c for c in reel_calls if c["fmt"] == "html")
    md = next(c for c in reel_calls if c["fmt"] == "markdown")
    assert len(reel_calls) == 2 and html["html_head"] is True and html["urls"] == md["urls"]
    assert html["redact"] is md["redact"] is ig.redact_reel_page  # no comment text is ever kept
    assert len(html["urls"]) == 9 and not any(TILES[u][2].pinned for u in html["urls"])


async def test_report_starts_with_public_page_limits_and_nothing_computed(world, events):
    report = await run("pov__gil", events)
    assert set(report.null_reasons) == {"video_length", "spoken_hook"}
    assert report.profile.median_views is None and not report.patterns and not report.insights
    assert report.insights_source == "insufficient_evidence"
    assert all(r.ratio_vs_median is None and not r.in_window for r in report.reels)  # 1.2 fills these


async def test_audio_label_sets_original_audio(world, events):
    first = tiles("pov__gil")[0]
    world.original_audio.add(ig.reel_shortcode(first.reel_url))
    report = await run("pov__gil", events)
    assert report.reels[0].original_audio is True and report.reels[0].audio_label.startswith("Original audio")
    second = report.reels[1]
    assert second.audio_label is None and second.original_audio is None
    assert "audio_label" in second.null_reasons and "original_audio" in second.null_reasons


async def test_events_say_what_happened(world, events):
    await run("eylems_kitchen", events)
    messages = [m for _, _, m in events]
    assert messages[0] == "Reading @eylems_kitchen's Reels grid"
    assert "99K followers, 9 recent Reels (3 pinned left out)" in messages[1]
    assert messages[2] == "Read 9 of 9 Reel pages: captions, 9 post dates, audio"
    assert all(src == "scout" for src, _, _ in events)


# ---------------------------------------------------------------- when things go wrong


async def test_private_account_is_reported_not_bypassed(world, events):
    world.walled.add("pov__gil")
    report = await run("pov__gil", events)
    assert report.profile.access_status == "login_wall" and "aren't public" in report.profile.status_reason
    assert report.reels == [] and len(world.calls) == 1  # no Reel pages fetched
    assert report.profile.followers == 23_000  # the description still loads
    assert events[-1][1] == "error"


async def test_unknown_account_is_not_found(world, events):
    world.missing.add("nobody_here_123")
    report = await run("nobody_here_123", events)
    assert report.profile.access_status == "not_found" and report.reels == []


async def test_only_pinned_reels(world, events):
    world.only_pinned.add("pov__gil")
    report = await run("pov__gil", events)
    assert report.reels == [] and report.profile.pinned_skipped == 1
    assert report.profile.status_reason == "Only pinned Reels are visible on the public page"


async def test_a_reel_page_that_fails_keeps_grid_numbers_but_cannot_be_cited(world, events):
    t = tiles("pov__gil")[1]
    world.failing_reels.add(ig.reel_shortcode(t.reel_url))
    report = await run("pov__gil", events)
    r = report.reels[1]
    assert r.access_status == "timeout" and r.status_reason == "The page took too long to load"
    assert r.views == t.views and r.caption is None
    assert r.null_reasons["caption"].startswith("Reel page didn't load")
    assert "1 didn't load, so they can't be cited" in events[-1][2]


async def test_a_walled_reel_page(world, events):
    t = tiles("pov__gil")[0]
    world.walled_reels.add(ig.reel_shortcode(t.reel_url))
    report = await run("pov__gil", events)
    assert report.reels[0].access_status == "login_wall" and report.reels[0].posted_date is None


async def test_every_missing_field_says_why(world, events):
    world.failing_reels.add(ig.reel_shortcode(tiles("pov__gil")[2].reel_url))
    report = await run("pov__gil", events)
    for r in report.reels:
        for f in creator_profiler.CHECKED_FIELDS:
            if getattr(r, f) is None:
                assert r.null_reasons.get(f), (r.id, f)
        assert set(r.null_reasons) <= set(type(r).model_fields)  # reasons only for real fields


async def test_tinyfish_account_problem_stops_the_report(world, events):
    world.account_error = True
    with pytest.raises(TinyFishAccountError):
        await run("pov__gil", events)


# ---------------------------------------------------------------- what users type


@pytest.mark.parametrize(
    "raw, handle",
    [
        ("@eylems_kitchen", "eylems_kitchen"),
        ("eylems_kitchen", "eylems_kitchen"),
        ("  eylems_kitchen/ ", "eylems_kitchen"),
        ("https://www.instagram.com/eylems_kitchen/", "eylems_kitchen"),
        ("https://instagram.com/eylems_kitchen/reels/?igsh=abc123", "eylems_kitchen"),
        ("instagram.com/eylems_kitchen", "eylems_kitchen"),
        ("www.instagram.com/_kiran_ki_rasoi_/", "_kiran_ki_rasoi_"),
    ],
)
def test_parse_handle_accepts_what_people_paste(raw, handle):
    assert creator_profiler.parse_handle(raw) == handle


@pytest.mark.parametrize(
    "raw",
    ["", None, "@", "has space", "https://www.tiktok.com/@eylems_kitchen", "https://www.instagram.com/explore/",
     "https://www.instagram.com/reel/DVlSnL5k_pn/", "a" * 31],
)
def test_parse_handle_rejects_the_rest(raw):
    with pytest.raises(creator_profiler.HandleRejected):
        creator_profiler.parse_handle(raw)
