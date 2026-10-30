"""Reel report pieces (v2 task 3.1): one pasted Reel next to its creator's usual.

    URL -> parse_reel_url -> fetch_reel (html + markdown, redacted) -> ReelStat "r0" + handle
        -> creator_profiler.fetch_creator(handle) -> take_from_grid (exact numbers, and the
           Reel leaves the creator's median) -> compare -> ComparisonRow table

A Reel's own page has no view count: views only show on the creator's grid. So r0 gets views
(and exact likes / comments) only when it is one of the creator's ~12 most recent, non-pinned
Reels; otherwise views stay None with the reason. reports.run_reel_report runs these steps.
Network only through tinyfish_client, called through the module so tests can swap in fakes.
"""

from __future__ import annotations

import asyncio
import statistics
from collections import Counter
from urllib.parse import urlparse

from backend import instagram_parse as ig
from backend import tinyfish_client
from backend.creator_profiler import _reel_from_page
from backend.niche_scout import Emit, _say, _short
from backend.report_models import ComparisonRow, CreatorReport, ReelStat

NOT_IN_GRID = "Views only show on the creator's grid, and this Reel isn't among their recent, non-pinned Reels"


class ReelUrlRejected(ValueError):
    """Shown to the user as is (400)."""


def parse_reel_url(raw: str | None) -> str:
    """Any Reel link people paste -> https://www.instagram.com/reel/<code>/."""
    text = (raw or "").strip()
    url = text if text.lower().startswith("http") else "https://" + text.lstrip("/")
    host = urlparse(url).netloc.lower()
    canonical = ig.canonical_reel_url(url) if host in ("instagram.com", "www.instagram.com") else None
    if not canonical:
        raise ReelUrlRejected("Paste an Instagram Reel link, like instagram.com/reel/ABC123.")
    return canonical


async def fetch_reel(url: str, emit: Emit) -> tuple[ReelStat, str | None]:
    """The Reel page as r0 (no views yet) and its author's handle (None if the page didn't say)."""
    await _say(emit, "progress", "Reading the Reel's public page")
    (page,), (md_page,) = await asyncio.gather(
        tinyfish_client.fetch_pages([url], fmt="html", html_head=True, purpose="Read one public Reel", redact=ig.redact_reel_page),
        tinyfish_client.fetch_pages([url], purpose="Read a Reel's audio name", redact=ig.redact_reel_page),
    )
    reel = _reel_from_page(0, ig.GridTile(reel_url=url, likes=None, comments=None, views=None), page, md_page)
    handle = ig.parse_reel_page(page).handle if reel.access_status == "accessible" else None
    reel.handle = handle
    return reel, handle


def take_from_grid(reel: ReelStat, creator: CreatorReport) -> bool:
    """If the Reel is in the creator's recent grid: copy the grid's exact numbers into r0, take it
    out of the creator's Reels (so it doesn't count in their median) and renumber r1..rN.
    Otherwise mark r0's views as unknown with the reason. True when found."""
    match = next((r for r in creator.reels if r.source_url == reel.source_url), None)
    if match is None:
        reel.null_reasons["views"] = NOT_IN_GRID
        return False
    reel.views, reel.likes, reel.comments = match.views, match.likes, match.comments
    for f in ("views", "likes", "comments"):
        if getattr(reel, f) is not None:
            reel.null_reasons.pop(f, None)
    creator.reels = [r for r in creator.reels if r is not match]
    for n, r in enumerate(creator.reels, start=1):
        r.id = f"r{n}"
    creator.profile.reels_read = len(creator.reels)
    return True


def compare(reel: ReelStat, creator: CreatorReport) -> list[ComparisonRow]:
    """This Reel next to its creator's usual, from numbers only (no LLM). A row cites a key only
    when the creator report has it, so the insight validator accepts every key shown here."""
    p = creator.profile
    keys = creator.citable()
    readable = [r for r in creator.reels if r.access_status == "accessible"]

    def cite(*candidates: str) -> list[str]:
        return [k for k in dict.fromkeys(candidates) if k in keys]

    def best(dimension: str):
        rows = [x for x in creator.patterns if x.dimension == dimension and x.median_ratio is not None]
        return max(rows, key=lambda x: x.median_ratio, default=None)

    rows: list[ComparisonRow] = []
    label = f"Views vs @{p.handle}'s median"
    if reel.views is not None and p.median_views and reel.ratio_vs_median is not None:
        rows.append(ComparisonRow(label=label, this_reel=f"{_short(reel.views)} ({reel.ratio_vs_median:g}x)",
                                  creator_usual=f"{_short(p.median_views)} median", keys=cite("p.median_views")))
    else:
        note = reel.null_reasons.get("views") or "The creator's median isn't available yet"
        rows.append(ComparisonRow(label=label, this_reel=_short(reel.views) if reel.views is not None else None,
                                  creator_usual=f"{_short(p.median_views)} median" if p.median_views else None, note=note))

    types = Counter(r.hook_type for r in readable if r.hook_type)
    if reel.hook_type and types:
        usual, count = types.most_common(1)[0]
        top = best("hook_type")
        rows.append(ComparisonRow(
            label="Hook type", this_reel=reel.hook_type, creator_usual=f"{usual} ({count} of {sum(types.values())} Reels)",
            keys=cite(f"pat.hook_type.{reel.hook_type}", *([f"pat.hook_type.{top.value}"] if top else [])),
            note=f"Their best-performing hook type: {top.value} ({top.median_ratio:g}x their median)" if top else None))

    known = [r for r in readable if r.original_audio is not None]
    if reel.original_audio is not None and known:
        original = sum(1 for r in known if r.original_audio)
        rows.append(ComparisonRow(
            label="Audio", this_reel=reel.audio_label, creator_usual=f"original audio in {original} of {len(known)} Reels",
            keys=cite(*(x.key for x in creator.patterns if x.dimension == "audio"))))

    if reel.hashtags:
        theirs = [x for x in creator.patterns if x.dimension == "hashtag"]
        shared = [t for t in reel.hashtags if any(x.value == t for x in theirs)]
        top_tags = [x.value for x in sorted(theirs, key=lambda x: -(x.median_ratio or 0)) if x.in_top][:5]
        rows.append(ComparisonRow(
            label="Hashtags", this_reel=" ".join(reel.hashtags), creator_usual=" ".join(top_tags) or None,
            keys=cite(*(f"pat.hashtag.{t}" for t in shared)),
            note=f"{len(shared)} of this Reel's {len(reel.hashtags)} hashtags appear in their other Reels"))

    lengths = [r.caption_chars for r in readable if r.caption_chars is not None]
    if reel.caption_chars is not None and lengths:
        rows.append(ComparisonRow(label="Caption length", this_reel=f"{reel.caption_chars} characters",
                                  creator_usual=f"{int(statistics.median(lengths))} characters (median)",
                                  keys=cite(*(x.key for x in creator.patterns if x.dimension == "caption_length"))))

    if reel.posted_date:
        day = reel.posted_date.strftime("%A")
        top = best("weekday")
        rows.append(ComparisonRow(label="Posted on", this_reel=day, creator_usual=f"best day: {top.value}" if top else None,
                                  keys=cite(f"pat.weekday.{day}", *([f"pat.weekday.{top.value}"] if top else []))))

    ctas = [r.has_cta for r in readable if r.has_cta is not None]
    if reel.has_cta is not None and ctas:
        rows.append(ComparisonRow(label="Call to action", this_reel="yes" if reel.has_cta else "no",
                                  creator_usual=f"in {sum(ctas)} of {len(ctas)} Reels"))
    return rows
