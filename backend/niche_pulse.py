"""Niche Pulse research (v2 task 5.1): what's working today for 1-3 keywords or hashtags.

    keywords -> parse_keywords (normalise_topic each, dedupe, 1-3)
             -> per keyword, at the same time:
                  niche_scout.run_niche_scout(topic, use_agent=False)   topic page -> creators -> outliers
                  tinyfish_client.search x2 (SEARCH_QUERIES) -> WebSignals that name the keyword
             -> one markdown Fetch of all outlier pages for their audio names
             -> NichePulse: outlier Reels (r1 = highest ratio) with handle + topic, web signals

"Working" here means the v1 rule: a Reel at 2x or more of its own creator's median views
(outliers.MIN_RATIO). That's evidence of what is working now, never a prediction (decision D4).
Patterns, the day-over-day diff and insights come later (5.2); reports.run_niche_report runs it all.
Network only through tinyfish_client, called through the module so tests can swap in fakes.
"""

from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timezone

from backend import instagram_parse as ig
from backend import niche_scout, tinyfish_client
from backend.creator_profiler import _audio_from
from backend.models import Example
from backend.niche_scout import Emit, _say
from backend.report_models import NichePulse, ReelStat, WebSignal

MAX_KEYWORDS = 3
SEARCH_HITS = 5  # per keyword
# Checked live on 30 Oct (dal, cooking, skincare): the unquoted "<topic> instagram reels trend this
# week" drifted to generic "Reels trends" pages for a narrow keyword; these two stay on topic. Each
# returns only 3-5 hits, so both run (search is free) and their hits are merged.
SEARCH_QUERIES = ('"{topic}" reels trending this week', "#{topic} instagram reels")
_REEL_FIELDS = set(ReelStat.model_fields)


class KeywordsRejected(ValueError):
    """Shown to the user as is (400)."""


def parse_keywords(raw: list[str] | None) -> list[str]:
    """['#Cooking', 'dal recipes', 'cooking'] -> ['cooking', 'dalrecipes']. TopicRejected (from
    normalise_topic) or KeywordsRejected carry a message for the user."""
    topics: list[str] = []
    for k in raw or []:
        if not (k or "").strip():
            continue
        topic = ig.normalise_topic(k)
        if topic not in topics:
            topics.append(topic)
    if not 1 <= len(topics) <= MAX_KEYWORDS:
        raise KeywordsRejected(f"Add 1 to {MAX_KEYWORDS} keywords or hashtags, like cooking or #dal.")
    return topics


def _for_topic(emit: Emit, topic: str) -> Emit:
    """Prefix every line with its keyword: three keywords run at once and their lines interleave."""
    def emit_topic(source, kind, message, data=None):
        return emit(source, kind, f"#{topic}: {message}", data)
    return emit_topic


def mentions(hit: tinyfish_client.SearchHit, topic: str) -> bool:
    """The keyword as a whole word in the title, snippet or URL: "dal" matches "/dal-chivda-reels"
    and "Dal is life", not "medal" or "Daleng"."""
    text = f"{hit.title} {hit.snippet} {hit.url}".lower()
    return re.search(rf"(?<!\w){re.escape(topic)}(?!\w)", text) is not None


async def _web(topic: str, emit: Emit) -> list[WebSignal]:
    batches = await asyncio.gather(*(tinyfish_client.search(q.format(topic=topic)) for q in SEARCH_QUERIES))
    now = datetime.now(timezone.utc)
    signals: list[WebSignal] = []
    for h in (h for batch in batches for h in batch):
        if h.url and h.title and mentions(h, topic) and all(s.url != h.url for s in signals):
            signals.append(WebSignal(title=h.title, url=h.url, snippet=h.snippet or None, retrieved_at=now))
    signals = signals[:SEARCH_HITS]
    await _say(emit, "progress", f"{len(signals)} web results" if signals else f"No web results mention #{topic}")
    return signals


async def _one(topic: str, emit: Emit) -> tuple[list, list[Example], list[WebSignal]]:
    tagged = _for_topic(emit, topic)
    (creators, examples), web = await asyncio.gather(
        niche_scout.run_niche_scout(topic, tagged, use_agent=False), _web(topic, tagged)
    )
    return creators, examples, web


def _reel(ex: Example, topic: str) -> ReelStat:
    fields = ex.model_dump(include=_REEL_FIELDS - {"id"})
    reel = ReelStat(id="", topic=topic, ratio_vs_median=ex.outlier_ratio, **fields)
    reel.null_reasons = {f: r for f, r in ex.null_reasons.items() if f in _REEL_FIELDS and getattr(reel, f) is None}
    return reel


async def run_pulse(keywords: list[str], emit: Emit, today: date) -> NichePulse:
    """Research every keyword at once. Returns a NichePulse with reels (outliers, best first) and
    web signals; patterns / since_last_run / insights are left for 5.2. Never raises for Instagram
    problems (a walled keyword just has no outliers); TinyFishAccountError propagates."""
    results = await asyncio.gather(*(_one(topic, emit) for topic in keywords))

    reels: list[ReelStat] = []
    web: list[WebSignal] = []
    creators: set[str] = set()
    for topic, (found, examples, signals) in zip(keywords, results):
        creators |= {c.handle for c in found if c.access_status == "accessible" and c.median_views is not None}
        reels += [_reel(ex, topic) for ex in examples]
        web += [s for s in signals if all(s.url != w.url for w in web)]

    # One Reel can be an outlier under two keywords: keep it once. Best ratio first, then number them.
    unique = {}
    for r in sorted(reels, key=lambda r: -(r.ratio_vs_median or 0)):
        unique.setdefault(r.source_url, r)
    reels = list(unique.values())
    for n, r in enumerate(reels, start=1):
        r.id = f"r{n}"

    readable = [r for r in reels if r.access_status == "accessible"]
    if readable:
        # v1 outlier pages are html only, which never carries the audio name (decision: html + markdown).
        pages = await tinyfish_client.fetch_pages([r.source_url for r in readable], purpose="Read a Reel's audio name",
                                                  redact=ig.redact_reel_page)
        for r, page in zip(readable, pages):
            r.audio_label = _audio_from(page)
            if r.audio_label:
                r.original_audio = r.audio_label.startswith("Original audio")
                r.null_reasons.pop("audio_label", None)
            else:
                r.null_reasons.setdefault("audio_label", "Audio name isn't shown on the public page")
                r.null_reasons["original_audio"] = r.null_reasons["audio_label"]

    pulse = NichePulse(keywords=keywords, run_date=today, creators_read=len(creators), reels=reels, web=web)
    if not reels:
        pulse.null_reasons["reels"] = "No Reel beat its creator's usual views by 2x on these topic pages today"
    await _say(emit, "progress", f"{len(reels)} outliers from {len(creators)} creators; {len(web)} web results")
    return pulse
