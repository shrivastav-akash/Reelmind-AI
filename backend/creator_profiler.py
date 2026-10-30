"""Creator Profiler: one creator's public profile and recent Reels (v2 task 1.1).

The base of every v2 report (creator, Reel, My Studio, Niche Pulse):

    handle -> Fetch /reels/ grid (markdown): followers / following / posts + up to 12 tiles
           -> Fetch the pages of the recent, non-pinned Reels, as html head + markdown (comments redacted)
           -> CreatorReport skeleton: ProfileStats + one ReelStat per Reel (r1 = newest)

Grid numbers win (views, exact likes and comments); each Reel page adds caption, hook line,
post date, audio and cover. Left for later stages: median, ratios, the 7-day window and
patterns (creator_metrics.py, 1.2), caption fields such as hashtags and hook type
(caption_analysis.py, 0.4), cover notes (vision.analyse_covers, 1.3) and insights (1.4).

Network only through tinyfish_client.fetch_pages, called through the module so tests can
swap in a fake. Logged-out pages only: a walled or private account is reported, never bypassed.
"""

from __future__ import annotations

import asyncio
from typing import Any

from backend import instagram_parse as ig
from backend import tinyfish_client
# Shared with Niche Scout so both read grids and word failures the same way.
from backend.niche_scout import Emit, _grid_from_page, _say, _short, _status_from_error
from backend.report_models import CreatorReport, ProfileStats, ReelStat

MAX_REELS = 12  # a logged-out grid shows 12 tiles; pinned ones are left out
PAGE_FIELDS = ("caption", "hook_line", "posted_date", "audio_label", "original_audio", "cover_url")
CHECKED_FIELDS = ("posted_date", "views", "likes", "comments") + PAGE_FIELDS
# Limits of public pages, shown in every creator report rather than hidden.
PUBLIC_PAGE_LIMITS = {
    "video_length": "Video length isn't on public Reel pages",
    "spoken_hook": "Spoken words and cuts need the video file, which public pages don't include",
}


class HandleRejected(ValueError):
    """Shown to the user as is (400)."""


def parse_handle(handle_or_url: str | None) -> str:
    """'@cookwithx', 'cookwithx' or 'https://www.instagram.com/cookwithx/reels/' -> 'cookwithx'."""
    raw = (handle_or_url or "").strip().rstrip("/")
    if "/" in raw or raw.lower().startswith(("http", "www.", "instagram.com")):
        url = raw if raw.lower().startswith("http") else "https://" + raw.lstrip("/")
        handle = ig.handle_from_url(url)
    else:
        handle = raw.lstrip("@")
        handle = handle if ig.HANDLE_RE.match(handle) and handle.lower() not in ig.RESERVED_PATHS else None
    if not handle:
        raise HandleRejected("Enter an Instagram handle like @cookwithx or a profile link like instagram.com/cookwithx.")
    return handle


def _audio_from(page: tinyfish_client.FetchedPage) -> str | None:
    if not page.ok or "/accounts/login" in (page.final_url or ""):
        return None
    return ig.parse_reel_page(page).audio_label


def _reel_from_page(n: int, tile: ig.GridTile, page: tinyfish_client.FetchedPage, md_page: tinyfish_client.FetchedPage) -> ReelStat:
    """One ReelStat: grid numbers, plus the html page's fields when it loaded. The html copy is cut
    to its <meta> tags (cover, caption, date) by redact_reel_page, so the audio name comes from
    the markdown copy of the same page."""
    fields: dict[str, Any] = {}
    reasons: dict[str, str] = {}
    if not page.ok:
        status, status_reason = _status_from_error(page.error, "Reel")
        reasons = {f: f"Reel page didn't load: {status_reason}" for f in PAGE_FIELDS}
    elif "/accounts/login" in (page.final_url or ""):
        status, status_reason = "login_wall", "Login wall on this Reel's page"
        reasons = {f: status_reason for f in PAGE_FIELDS}
    else:
        status, status_reason = "accessible", None
        reel = ig.parse_reel_page(page)
        audio = _audio_from(md_page)
        fields = {"caption": reel.caption, "hook_line": reel.hook_line, "posted_date": reel.posted_date,
                  "audio_label": audio, "cover_url": reel.cover_url,
                  "likes": reel.likes, "comments": reel.comments}  # og counts are rounded: grid wins below
        if audio:
            fields["original_audio"] = audio.startswith("Original audio")
        reasons.update(reel.null_reasons)
        if audio is None and not md_page.ok:
            reasons["audio_label"] = "The page's text copy (where the audio name is) didn't load"
        reasons.setdefault("original_audio", reasons.get("audio_label", "Audio name isn't shown on the public page"))
    if tile.likes is not None:
        fields["likes"] = tile.likes
    if tile.comments is not None:
        fields["comments"] = tile.comments

    stat = ReelStat(
        id=f"r{n}", source_url=tile.reel_url, retrieved_at=page.retrieved_at,
        access_status=status, status_reason=status_reason, views=tile.views, **fields,
    )
    for f in CHECKED_FIELDS:
        if getattr(stat, f) is None:
            reasons.setdefault(f, "Not shown on the public grid or Reel page")
    stat.null_reasons = {f: r for f, r in reasons.items() if getattr(stat, f, None) is None}
    return stat


async def fetch_creator(handle: str, emit: Emit) -> CreatorReport:
    """Read one creator's grid and recent Reel pages. Returns a CreatorReport with `profile` and
    `reels` filled (r1 = newest) and everything computed left empty. Never raises for a missing,
    private or walled account: the profile says so in access_status / status_reason.
    TinyFishAccountError (key or credits) is raised: the whole report can't run.
    """
    profile = ProfileStats(handle=handle, profile_url=f"https://www.instagram.com/{handle}/")
    report = CreatorReport(profile=profile, null_reasons=dict(PUBLIC_PAGE_LIMITS))

    await _say(emit, "progress", f"Reading @{handle}'s Reels grid")
    [page] = await tinyfish_client.fetch_pages([ig.reels_url(handle)], purpose="Read a creator's Reels grid")
    grid = _grid_from_page(handle, page)
    counts = ig.parse_profile_counts(page.description)
    profile.followers, profile.following, profile.posts = counts.followers, counts.following, counts.posts
    profile.access_status, profile.status_reason = grid.access_status, grid.status_reason
    if grid.access_status != "accessible" or not grid.tiles:
        await _say(emit, "error", f"@{handle}: {grid.status_reason}", {"handle": handle})
        return report

    tiles = [t for t in grid.tiles if not t.pinned][:MAX_REELS]
    profile.pinned_skipped = sum(1 for t in grid.tiles if t.pinned)
    pinned = f" ({profile.pinned_skipped} pinned left out)" if profile.pinned_skipped else ""
    await _say(emit, "progress", f"@{handle}: {_short(profile.followers)} followers, {len(tiles)} recent Reels{pinned}",
               {"handle": handle, "url": ig.reels_url(handle)})
    if not tiles:
        profile.status_reason = "Only pinned Reels are visible on the public page"
        return report

    # Fetch costs no credits, so read each page twice at once: html for cover / caption / date,
    # markdown for the audio name. Both are redacted before anything is cached or kept.
    urls = [t.reel_url for t in tiles]
    pages, md_pages = await asyncio.gather(
        tinyfish_client.fetch_pages(urls, fmt="html", html_head=True, purpose="Read one public Reel", redact=ig.redact_reel_page),
        tinyfish_client.fetch_pages(urls, purpose="Read a Reel's audio name", redact=ig.redact_reel_page),
    )
    report.reels = [_reel_from_page(n, *parts) for n, parts in enumerate(zip(tiles, pages, md_pages), start=1)]
    profile.reels_read = len(report.reels)

    readable = [r for r in report.reels if r.access_status == "accessible"]
    dated = sum(1 for r in readable if r.posted_date)
    line = f"Read {len(readable)} of {len(report.reels)} Reel pages: captions, {dated} post dates, audio"
    if len(readable) < len(report.reels):
        line += f"; {len(report.reels) - len(readable)} didn't load, so they can't be cited"
    await _say(emit, "progress", line)
    return report
