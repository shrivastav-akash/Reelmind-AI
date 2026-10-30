"""Niche Scout: the TinyFish centrepiece. BUILT ON FRIDAY (tasks A1-A3 in docs/implementation-plan.md).

Design after the 29 Oct live tests (docs/decisions.md):
- The TinyFish **Agent** gets a login wall on creators' /reels/ tabs, but reads the public
  topic page fine. So the Agent does the judgement step: it *picks* individual creators on
  the topic page while judges watch its live browser.
- TinyFish **Fetch** (free, fast) reads everything else: the topic page (in parallel, as
  the fallback), each creator's Reels grid, and the outlier Reel pages.

    topic --+-- Agent: pick <=4 creators on the topic page (live view, 75 s cap) --+
            +-- Fetch: topic page -> handles -> prefetch their grids --------------+
                                                                                   v
           creators (Agent's picks, else code's) -> grids -> outliers -> Reel pages (Fetch)

Network only through tinyfish_client, called through the module
(`tinyfish_client.fetch_pages`, `tinyfish_client.run_agent`) so tests can swap in fakes.
Parsing and maths: instagram_parse + outliers (built and tested). "Done" is defined by
tests/test_niche_scout.py, which replays the real 29 Oct #cooking pages.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from backend import instagram_parse as ig
from backend import outliers, tinyfish_client
from backend.instagram_parse import GridPage
from backend.models import AgentTopicPicks, Creator, Example

# emit(source, kind, message, data=None) appends an Event to the job (jobs.py).
Emit = Callable[..., Awaitable[None] | None]

MAX_CREATORS = 4
MIN_CREATORS = 3
PREFETCH_GRIDS = 10  # grids fetched in parallel with the Agent, so the code fallback is instant
AGENT_MAX_SECONDS = 75
MAX_FOLLOWERS_FOR_CODE_PICK = 1_000_000  # code prefers individual creators, like the Agent is asked to
MIN_TILES_WITH_VIEWS = 6
# Big brands skew "outliers" and their advice doesn't transfer to small creators.
MEGA_ACCOUNTS = {
    "natgeo", "tasty", "buzzfeedtasty", "gordongram", "gordonramsay", "foodnetwork", "bonappetitmag",
    "nytcooking", "instagram", "creators", "zomato", "swiggyindia", "delish", "jamieoliver",
}
SAVED_CREATORS = Path(__file__).resolve().parent.parent / "samples" / "demo_creators.json"

TOPIC_GOAL = (
    "You are on Instagram's public topic page for #{topic}. Do not log in, do not click "
    '"Log in" or "Sign up", do not submit anything. Look at the Reels shown without logging in. '
    "Pick up to 4 creators whose Reels appear here, preferring individual creators over brands, "
    "media companies or very large accounts. For each, return the handle exactly as shown, the "
    "Reel URL you saw for them, and one short reason about their content style. Do not include "
    "any numbers (followers, views or likes) in the reason. If a login wall or captcha blocks "
    "the page, return blocked=true with blocked_reason. Stop after reading the visible Reels."
)

TOPIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "topic": {"type": "string"},
        "blocked": {"type": "boolean"},
        "blocked_reason": {"type": "string"},
        "creators": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "handle": {"type": "string"},
                    "reel_url": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["handle"],
            },
        },
    },
    "required": ["topic", "blocked"],
}


# ---------------------------------------------------------------- small helpers


async def _say(emit: Emit, kind: str, message: str, data: dict | None = None) -> None:
    """Send one scout line to the live panel. jobs.py's emit may be sync or async."""
    out = emit("scout", kind, message, data)
    if inspect.isawaitable(out):
        await out


def _short(n: int | None) -> str:
    """26400 -> '26.4K', 1300000 -> '1.3M', for the live panel lines."""
    if n is None:
        return "?"
    for size, suffix in ((1_000_000, "M"), (1_000, "K")):
        if n >= size:
            return f"{n / size:.1f}".rstrip("0").rstrip(".") + suffix
    return str(n)


def _status_from_error(error: str | None, what: str) -> tuple[str, str]:
    """A failed fetch in plain words. `what` is "Account" or "Reel"."""
    text = (error or "").lower()
    if "404" in text or "not found" in text:
        return "not_found", f"{what} not found (it may be deleted or renamed)"
    if "timed out" in text or "timeout" in text:
        return "timeout", "The page took too long to load"
    return "blocked", f"Couldn't load the page ({error or 'no reason given'})"


def _looks_walled(page: tinyfish_client.FetchedPage) -> bool:
    text = (page.text or "").lower()
    return "/accounts/login" in (page.final_url or "") or "this account is private" in text or "log in" in text


def _grid_from_page(handle: str, page: tinyfish_client.FetchedPage) -> GridPage:
    """Parse one fetched /reels/ page, and record whether it could be read at all."""
    if not page.ok:
        status, reason = _status_from_error(page.error, "Account")
        return GridPage(handle=handle, followers=None, tiles=[], problems=[reason], access_status=status, status_reason=reason)
    grid = ig.parse_grid(page.text, page.links, page.description, handle)
    if not grid.tiles and _looks_walled(page):
        # Only checked when no tiles were read: every logged-out page shows "Log In" in its header.
        grid.access_status, grid.status_reason = "login_wall", "Login wall: this account's Reels aren't public"
    elif not grid.tiles:
        grid.status_reason = "No Reels visible on the public page"
    return grid


def _saved_handles(topic: str) -> list[str]:
    """samples/demo_creators.json, used only when the topic page and the Agent both fail."""
    try:
        saved = json.loads(SAVED_CREATORS.read_text())
    except (OSError, ValueError):
        return []
    return [c["handle"] for c in saved.get("creators", [])] if saved.get("topic") == topic else []


# ---------------------------------------------------------------- A1: who to look at


async def agent_pick_creators(topic: str, emit: Emit) -> list[tuple[str, str | None]] | None:
    """A1 (Agent half). tinyfish_client.run_agent(topic_url, TOPIC_GOAL, TOPIC_SCHEMA,
    max_seconds=AGENT_MAX_SECONDS, on_event=...): forward the streaming URL as a
    kind="streaming_url" event with data={"url": ...} and each progress step as
    "Agent: <purpose>". Validate with models.AgentTopicPicks. Return [(handle, clean
    reason)] with instagram_parse.clean_agent_reason, deduped case-insensitively, MEGA_ACCOUNTS
    removed (choose_creators caps them at MAX_CREATORS after dropping invented handles).
    Return None (and emit why) on a wall, block, timeout or no picks.
    Never raises for Instagram problems; TinyFishAccountError propagates.
    """

    async def on_event(ev: tinyfish_client.AgentEvent) -> None:
        if ev.kind == "streaming_url" and ev.streaming_url:
            await _say(emit, "streaming_url", "Live view: the TinyFish Agent is reading the topic page", {"url": ev.streaming_url})
        elif ev.kind == "progress" and ev.message:
            await _say(emit, "progress", f"Agent: {ev.message}")

    await _say(emit, "progress", f"TinyFish Agent is choosing creators on #{topic} (live browser)")
    # No stealth retry here: it would double the wait on stage, and Fetch covers this step anyway.
    out = await tinyfish_client.run_agent(
        ig.topic_url(topic), TOPIC_GOAL.format(topic=topic), TOPIC_SCHEMA,
        on_event=on_event, max_seconds=AGENT_MAX_SECONDS,
    )
    fallback = "picking creators from the page copy instead"
    if out.access_status != "accessible":
        why = {
            "login_wall": "hit a login wall",
            "timeout": "ran out of time",
            "not_found": "found no topic page",
        }.get(out.access_status, f"was blocked ({out.status_reason or 'no reason given'})")
        await _say(emit, "info", f"The Agent {why} on the topic page; {fallback}.")
        return None
    try:
        result = AgentTopicPicks.model_validate(out.result or {})
    except ValidationError:
        await _say(emit, "info", f"The Agent's answer wasn't in the expected shape; {fallback}.")
        return None

    picks: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for p in result.creators:
        handle = p.handle.strip().lstrip("@").lower()
        if not ig.HANDLE_RE.match(handle) or handle in seen or handle in MEGA_ACCOUNTS:
            continue
        seen.add(handle)
        picks.append((handle, ig.clean_agent_reason(p.reason)))
    if not picks:
        await _say(emit, "info", f"The Agent didn't pick any creators; {fallback}.")
        return None
    return picks


async def fetch_topic_and_grids(topic: str, emit: Emit) -> tuple[list[str], dict[str, GridPage]]:
    """A1 (Fetch half). Fetch the topic page, instagram_parse.parse_topic_page, drop
    MEGA_ACCOUNTS, then fetch up to PREFETCH_GRIDS creators' /reels/ pages in one call and
    parse each with instagram_parse.parse_grid. Returns (handles in page order, grids by handle).
    A walled or failed topic page returns ([], {}) and emits why.
    """
    [page] = await tinyfish_client.fetch_pages([ig.topic_url(topic)], purpose="Find creators posting Reels on this topic")
    if not page.ok:
        await _say(emit, "info", f"Couldn't read the #{topic} page with Fetch ({page.error}).")
        return [], {}
    parsed = ig.parse_topic_page(page.final_url, page.links)
    if parsed.walled:
        await _say(emit, "info", f"Instagram showed a login wall instead of the #{topic} page.")
        return [], {}
    handles = [h for h in (h.lower() for h in parsed.handles) if h not in MEGA_ACCOUNTS]
    if not handles:
        return [], {}
    note = " (an older saved copy)" if page.from_cache else ""
    await _say(emit, "progress", f"Fetch read the #{topic} page{note}: {len(handles)} creators. Reading their Reels…")

    prefetch = handles[:PREFETCH_GRIDS]
    pages = await tinyfish_client.fetch_pages([ig.reels_url(h) for h in prefetch], purpose="Read a creator's Reels grid")
    return handles, {h: _grid_from_page(h, p) for h, p in zip(prefetch, pages)}


def choose_creators(
    agent_picks: list[tuple[str, str | None]] | None,
    page_handles: list[str],
    grids: dict[str, GridPage],
    topic: str,
) -> list[Creator]:
    """A1 (decision). Agent's picks first: keep only handles that are on the Fetch copy of the
    topic page or have a readable grid (drops invented handles); picked_by="agent".
    If fewer than MIN_CREATORS survive (or the Agent failed), fill from page_handles whose grid has
    >= MIN_TILES_WITH_VIEWS tiles with views, followers <= MAX_FOLLOWERS_FOR_CODE_PICK, smallest
    first; picked_by="code". Still short and samples/demo_creators.json lists this topic: fill
    from it, picked_by="saved_list". At most MAX_CREATORS.
    """
    on_page = set(page_handles)
    chosen: list[Creator] = []

    def add(handle: str, picked_by: str, reason: str | None = None) -> None:
        if len(chosen) < MAX_CREATORS and all(c.handle != handle for c in chosen):
            grid = grids.get(handle)
            chosen.append(Creator(handle=handle, reels_url=ig.reels_url(handle), picked_by=picked_by,
                                  pick_reason=reason, followers=grid.followers if grid else None))

    for handle, reason in agent_picks or []:
        grid = grids.get(handle)
        if handle in on_page or (grid and grid.tiles):
            add(handle, "agent", reason)

    if len(chosen) < MIN_CREATORS:
        # Code's pick: individual creators with enough readable numbers, smallest first.
        def views_known(g: GridPage) -> int:
            return sum(1 for t in g.tiles if t.views is not None and not t.pinned)

        ok = [h for h in page_handles if (g := grids.get(h)) and views_known(g) >= MIN_TILES_WITH_VIEWS
              and g.followers is not None and g.followers <= MAX_FOLLOWERS_FOR_CODE_PICK]
        for handle in sorted(ok, key=lambda h: grids[h].followers):
            add(handle, "code")

    if len(chosen) < MIN_CREATORS:
        for handle in _saved_handles(topic):
            add(handle, "saved_list")
    return chosen


# ---------------------------------------------------------------- A2: read their grids


async def read_grids(creators: list[Creator], grids: dict[str, GridPage], emit: Emit) -> list[outliers.Candidate]:
    """A2. Fetch any grid not prefetched; fill each Creator row honestly (followers, method="fetch",
    reels_read, pinned_skipped, median_views, access_status: accessible / login_wall / not_found /
    blocked with a plain status_reason, e.g. "Too few Reels with views" when no median).
    Return outliers.score_creator candidates for every accessible creator.
    """
    missing = [c.handle for c in creators if c.handle not in grids]
    if missing:
        pages = await tinyfish_client.fetch_pages([ig.reels_url(h) for h in missing], purpose="Read a creator's Reels grid")
        grids = {**grids, **{h: _grid_from_page(h, p) for h, p in zip(missing, pages)}}

    candidates: list[outliers.Candidate] = []
    for c in creators:
        grid = grids[c.handle]
        c.method, c.status = "fetch", "done"
        c.access_status, c.status_reason = grid.access_status, grid.status_reason
        c.followers = grid.followers if grid.followers is not None else c.followers
        c.reels_read = len(grid.tiles)
        c.pinned_skipped = sum(1 for t in grid.tiles if t.pinned)
        if grid.access_status != "accessible":
            await _say(emit, "progress", f"@{c.handle}: {grid.status_reason}")
            continue
        median, cands = outliers.score_creator(
            c.handle, [outliers.ReelCounts(t.reel_url, t.views, t.likes, t.comments, t.pinned) for t in grid.tiles]
        )
        c.median_views = median
        if median is None:
            c.status_reason = grid.status_reason or "Too few Reels with views"
            await _say(emit, "progress", f"@{c.handle}: {c.status_reason}")
            continue
        candidates += cands
        pinned = f", {c.pinned_skipped} pinned left out" if c.pinned_skipped else ""
        await _say(emit, "progress", f"@{c.handle}: {c.reels_read} Reels read{pinned}, median {_short(median)} views")
    return candidates


# ---------------------------------------------------------------- A3: the outlier Reels


async def fetch_outlier_pages(candidates: list[outliers.Candidate], emit: Emit) -> list[Example]:
    """A3 (part). One Fetch call for the picked outliers' Reel pages, format="html",
    html_head=True, redact=instagram_parse.redact_reel_page; instagram_parse.parse_reel_page;
    Examples ex1..exN with views / median / ratio from the grid and likes / comments from the grid
    when known (og likes are rounded). A page that fails keeps its grid numbers but gets that
    failure's access_status, so it can't be cited. Every None field has a null_reasons entry.
    """
    if not candidates:
        return []
    urls = [ig.canonical_reel_url(c.reel_url) or c.reel_url for c in candidates]
    pages = await tinyfish_client.fetch_pages(
        urls, fmt="html", html_head=True, purpose="Read one public Reel", redact=ig.redact_reel_page
    )
    examples: list[Example] = []
    for n, (c, url, page) in enumerate(zip(candidates, urls, pages), start=1):
        fields: dict[str, Any] = {}
        reasons: dict[str, str] = {}
        if not page.ok:
            status, status_reason = _status_from_error(page.error, "Reel")
            for f in ("caption", "hook_line", "audio_label", "posted_date", "cover_url"):
                reasons[f] = f"Reel page didn't load: {status_reason}"
        elif "/accounts/login" in (page.final_url or ""):
            status, status_reason = "login_wall", "Login wall on this Reel's page"
            for f in ("caption", "hook_line", "audio_label", "posted_date", "cover_url"):
                reasons[f] = status_reason
        else:
            status, status_reason = "accessible", None
            reel = ig.parse_reel_page(page)
            fields = {"caption": reel.caption, "hook_line": reel.hook_line, "audio_label": reel.audio_label,
                      "posted_date": reel.posted_date, "cover_url": reel.cover_url}
            fields["likes"], fields["comments"] = reel.likes, reel.comments  # grid numbers win below
            reasons.update(reel.null_reasons)
        if c.likes is not None:
            fields["likes"] = c.likes
        if c.comments is not None:
            fields["comments"] = c.comments
        ex = Example(
            id=f"ex{n}", source_url=url, retrieved_at=page.retrieved_at, method="fetch",
            access_status=status, status_reason=status_reason, handle=c.handle,
            views=c.views, creator_median_views=c.creator_median_views, outlier_ratio=c.outlier_ratio,
            **fields,
        )
        for f, value in ex.model_dump(exclude={"status_reason", "null_reasons"}).items():
            if value is None:
                reasons.setdefault(f, "Not shown on the public grid or Reel page")
        ex.null_reasons = {f: r for f, r in reasons.items() if getattr(ex, f, None) is None}
        examples.append(ex)
    return examples


async def run_niche_scout(topic: str, emit: Emit) -> tuple[list[Creator], list[Example]]:
    """A3. normalise_topic -> agent_pick_creators and fetch_topic_and_grids together
    (asyncio.gather) -> choose_creators -> read_grids -> outliers.pick_outliers ->
    fetch_outlier_pages. Emit one "creator" event naming who picked whom, and one "outlier"
    event per Example, e.g. "4.7x @pov__gil's median (26.4K vs 5.6K)".
    """
    topic = ig.normalise_topic(topic)
    agent_picks, (page_handles, grids) = await asyncio.gather(
        agent_pick_creators(topic, emit), fetch_topic_and_grids(topic, emit)
    )
    creators = choose_creators(agent_picks, page_handles, grids, topic)
    if not creators:
        await _say(emit, "error", f"No creators found for #{topic} on public pages. Try a broader topic, e.g. cooking.")
        return [], []

    by = {who: [f"@{c.handle}" for c in creators if c.picked_by == who] for who in ("agent", "code", "saved_list")}
    parts = []
    if by["agent"]:
        parts.append("Agent picked " + ", ".join(by["agent"]))
    if by["code"]:
        parts.append(("code added " if parts else "Code picked ") + ", ".join(by["code"]) + " (smallest creators on the page)")
    if by["saved_list"]:
        parts.append(("then the saved list: " if parts else f"Topic page unreadable, using the saved list of #{topic} creators: ")
                     + ", ".join(by["saved_list"]))
    await _say(emit, "creator", "; ".join(parts), {"creators": [c.handle for c in creators]})

    candidates = await read_grids(creators, grids, emit)
    picked = outliers.pick_outliers(candidates)
    if not picked:
        await _say(emit, "error", f"No Reel beat its creator's usual views by {outliers.MIN_RATIO:g}x, so there are no examples to learn from.")
        return creators, []

    examples = await fetch_outlier_pages(picked, emit)
    for ex in examples:
        line = f"{ex.outlier_ratio:g}x @{ex.handle}'s median ({_short(ex.views)} vs {_short(ex.creator_median_views)})"
        if ex.access_status != "accessible":
            line += f", but its page didn't load ({ex.status_reason}), so it won't be cited"
        await _say(emit, "outlier", line, {"id": ex.id, "url": ex.source_url})
    return creators, examples
