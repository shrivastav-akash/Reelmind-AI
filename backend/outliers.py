"""Outlier maths for Niche Scout: which Reels beat their own creator's normal.

Raw views mislead (a mega-account's average Reel beats a small creator's best),
so each Reel is compared with the median views of the same creator's visible
Reels: outlier_ratio = views / creator median. Pure functions, called by
niche_scout.py (Fri) after the Agent has read each creator's grid.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import median

MIN_RATIO = 2.0  # brief: keep Reels at 2x their creator's median or more
MIN_KNOWN_VIEWS = 3  # with fewer known view counts, a median says little
TOP_N = 5
MAX_PER_CREATOR = 2  # keep the evidence from more than one creator


@dataclass
class ReelCounts:
    reel_url: str
    views: int | None
    likes: int | None = None
    comments: int | None = None
    # Pinned Reels are a creator's chosen old hits (one had 281M views on 29 Oct). They are
    # neither "recent" nor "normal", so they count towards neither the median nor the outliers.
    pinned: bool = False


@dataclass
class Candidate:
    handle: str
    reel_url: str
    views: int
    likes: int | None
    comments: int | None
    creator_median_views: int
    outlier_ratio: float


def creator_median(views: list[int | None]) -> int | None:
    known = [v for v in views if v is not None and v > 0]
    if len(known) < MIN_KNOWN_VIEWS:
        return None
    return int(median(known))


def score_creator(handle: str, reels: list[ReelCounts]) -> tuple[int | None, list[Candidate]]:
    """Median for this creator and every Reel's ratio against it. (None, []) if too few views are visible.
    Pinned Reels are left out of both."""
    recent = [r for r in reels if not r.pinned]
    med = creator_median([r.views for r in recent])
    if not med:
        return None, []
    seen: set[str] = set()
    out = []
    for r in recent:
        if not r.views or r.reel_url in seen:
            continue
        seen.add(r.reel_url)
        out.append(Candidate(handle, r.reel_url, r.views, r.likes, r.comments, med, round(r.views / med, 2)))
    return med, out


def pick_outliers(
    candidates: list[Candidate],
    *,
    min_ratio: float = MIN_RATIO,
    top_n: int = TOP_N,
    max_per_creator: int = MAX_PER_CREATOR,
) -> list[Candidate]:
    """Highest ratios first, at least `min_ratio`, at most `max_per_creator` from one creator."""
    eligible = sorted((c for c in candidates if c.outlier_ratio >= min_ratio), key=lambda c: -c.outlier_ratio)
    per_creator: Counter[str] = Counter()
    picked: list[Candidate] = []
    picked_urls: set[str] = set()  # a collab Reel shows on both creators' grids: count it once
    for c in eligible:
        if per_creator[c.handle] >= max_per_creator or c.reel_url in picked_urls:
            continue
        picked.append(c)
        picked_urls.add(c.reel_url)
        per_creator[c.handle] += 1
        if len(picked) == top_n:
            break
    return picked
