"""Creator maths (v2 task 1.2): numbers and patterns from a fetched CreatorReport. Pure: no network, no LLM.

reports.py calls these by name (interfaces pinned in docs/implementation-plan-v2.md):
    analyse(report, today)      sync, in place: caption fields, 7-day window, median, ratios,
                                engagement, cadence, window_note, patterns
    fill_caption_fields(reel)   sync, in place: the caption part for one Reel (also the pasted
                                Reel of a Reel report)

The 7-day window is highlighted, not used alone: most creators post 2-5 Reels a week, too few
for patterns. So patterns compare all recent Reels (up to 12, pinned ones left out), each Reel
says whether it is in the window, and window_note says which dates the patterns cover.
"Working" = a Reel's views against this creator's own median (outliers.creator_median); a
pattern row is the median ratio of the Reels that share a value, and how many of them sit in
the creator's top and bottom third.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date

from backend import caption_analysis, outliers
from backend.report_models import CreatorReport, NichePulse, PatternRow, ReelStat

MIN_SHARED = 2  # a hashtag, keyword or weekday used once isn't a pattern
DIMENSION_ORDER = ("hook_type", "audio", "caption_length", "hashtag", "keyword", "weekday", "cover_text")


def fill_caption_fields(reel: ReelStat) -> None:
    """Hook type, hashtags, keywords, caption length and CTA from the Reel's caption. A Reel whose
    page didn't load keeps them empty; its null_reasons already say why."""
    if reel.caption is None:
        return
    reel.hook_type = caption_analysis.hook_type(reel.hook_line)
    reel.hashtags = caption_analysis.hashtags(reel.caption)
    reel.keywords = caption_analysis.keywords(reel.caption)
    reel.caption_chars = caption_analysis.caption_chars(reel.caption)
    reel.has_cta = caption_analysis.has_cta(reel.caption)
    for f in ("hook_type", "caption_chars", "has_cta"):
        reel.null_reasons.pop(f, None)


def caption_bucket(chars: int) -> str:
    return "short (< 60)" if chars < 60 else "medium (60-200)" if chars <= 200 else "long (200+)"


def _window_note(report: CreatorReport, today: date) -> str:
    p = report.profile
    dated = [r.posted_date for r in report.reels if r.posted_date]
    span = f" (back to {min(dated):%d %b})" if dated else ""
    base = f"patterns compare all {len(report.reels)} recent Reels{span}"
    if p.reels_in_window == 0:
        newest = f" (newest: {max(dated):%d %b})" if dated else ""
        return f"No Reels in the last {p.window_days} days{newest}; {base}"
    return f"{p.reels_in_window} Reel{'s' if p.reels_in_window != 1 else ''} in the last {p.window_days} days; {base}"


def patterns(reels: list[ReelStat]) -> list[PatternRow]:
    """One row per value per dimension, over Reels whose page loaded."""
    readable = [r for r in reels if r.access_status == "accessible"]
    ranked = sorted((r for r in reels if r.ratio_vs_median is not None), key=lambda r: -r.ratio_vs_median)
    third = len(ranked) // 3
    top = {r.id for r in ranked[:third]}
    bottom = {r.id for r in ranked[-third:]} if third else set()

    groups: dict[tuple[str, str], list[ReelStat]] = defaultdict(list)
    for r in readable:
        if r.hook_type:
            groups[("hook_type", r.hook_type)].append(r)
        if r.original_audio is not None:
            groups[("audio", "original" if r.original_audio else "named track")].append(r)
        if r.caption_chars is not None:
            groups[("caption_length", caption_bucket(r.caption_chars))].append(r)
        for tag in r.hashtags:
            groups[("hashtag", tag)].append(r)
        for word in r.keywords:
            groups[("keyword", word)].append(r)
        if r.posted_date:
            groups[("weekday", r.posted_date.strftime("%A"))].append(r)
        if r.cover_notes is not None:
            groups[("cover_text", "text on cover" if r.cover_notes.text_on_cover else "no text on cover")].append(r)

    rows = []
    for (dimension, value), members in groups.items():
        if dimension in ("hashtag", "keyword", "weekday") and len(members) < MIN_SHARED:
            continue
        ratios = [m.ratio_vs_median for m in members if m.ratio_vs_median is not None]
        ids = [m.id for m in members]
        rows.append(PatternRow(
            dimension=dimension, value=value, reel_ids=ids,
            median_ratio=round(statistics.median(ratios), 2) if ratios else None,
            in_top=len(top.intersection(ids)), in_bottom=len(bottom.intersection(ids)),
        ))
    return sorted(rows, key=lambda p: (DIMENSION_ORDER.index(p.dimension), -(p.median_ratio or 0), p.value))


def analyse(report: CreatorReport, today: date) -> None:
    """Fill every computed field of a fetched creator report, in place."""
    p = report.profile
    for r in report.reels:
        fill_caption_fields(r)
        r.in_window = r.posted_date is not None and (today - r.posted_date).days <= p.window_days

    # Views come from the grid, so a Reel whose page failed still counts in the median.
    p.median_views = outliers.creator_median([r.views for r in report.reels])
    if p.median_views is None:
        report.null_reasons["median_views"] = f"Fewer than {outliers.MIN_KNOWN_VIEWS} Reels show a view count, so there's no fair baseline"
    for r in report.reels:
        r.ratio_vs_median = round(r.views / p.median_views, 2) if p.median_views and r.views else None
        if r.ratio_vs_median is None:
            r.null_reasons.setdefault("ratio_vs_median", report.null_reasons.get("median_views") or r.null_reasons.get("views", "No view count on the grid"))

    p.reels_in_window = sum(1 for r in report.reels if r.in_window)
    dated = [r.posted_date for r in report.reels if r.posted_date]
    # Up to today, not the newest post: a creator who stopped posting shows a falling rate.
    p.posts_per_week = round(len(dated) * 7 / max(1, (today - min(dated)).days), 1) if dated else None
    engagement = [(r.likes + r.comments) / r.views for r in report.reels
                  if r.views and r.likes is not None and r.comments is not None]
    p.median_engagement = round(statistics.median(engagement), 4) if engagement else None
    p.window_note = _window_note(report, today) if report.reels else None
    report.patterns = patterns(report.reels)


def analyse_pulse(pulse: NichePulse, previous: NichePulse | None) -> None:
    """Fill caption patterns and the day-over-day change list for a Pulse snapshot."""
    for reel in pulse.reels:
        fill_caption_fields(reel)
        reel.in_window = reel.posted_date is not None and 0 <= (pulse.run_date - reel.posted_date).days <= 7
    pulse.patterns = patterns(pulse.reels)
    pulse.previous_run_date = previous.run_date if previous else None
    pulse.since_last_run = []
    if previous is None:
        return

    def values(report: NichePulse) -> dict[str, set[str]]:
        found: dict[str, set[str]] = {"hashtag": set(), "audio": set(), "hook": set()}
        for reel in report.reels:
            found["hashtag"].update(reel.hashtags)
            if reel.audio_label:
                found["audio"].add(reel.audio_label)
            if reel.hook_type:
                found["hook"].add(reel.hook_type)
        return found

    old, current = values(previous), values(pulse)
    labels = {"hashtag": "hashtag", "audio": "audio", "hook": "hook type"}
    for dimension in ("hashtag", "audio", "hook"):
        for value in sorted(current[dimension] - old[dimension]):
            shown = value if dimension != "hashtag" or value.startswith("#") else f"#{value}"
            pulse.since_last_run.append(f"New {labels[dimension]} in outliers: {shown}")
