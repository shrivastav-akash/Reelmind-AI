"""Parsers for public Instagram pages fetched through TinyFish. Pure functions.

Called by niche_scout.py (Fri) on tinyfish_client.FetchedPage objects; outputs
plain values for models.Example / models.Creator. Formats were checked against
logged-out TinyFish fetches (brief §6, 25 Oct; samples/ refreshed 29 Oct).

Privacy: nothing here returns comment text or commenter usernames, and
strip_comments() removes them before pages are cached or saved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import urlparse

# "711K likes, 1,838 comments - cookwithprincia on March 5, 2026: "caption"."
# Likes can be hidden, so that part is optional. DOTALL: captions span lines.
OG_DESCRIPTION = re.compile(
    r'^(?:(?P<likes>[\d.,]+[KMB]?) likes?, )?(?P<comments>[\d.,]+[KMB]?) comments? - '
    r'(?P<handle>[\w.]+) on (?P<date>[A-Z][a-z]+ \d{1,2}, \d{4}): "(?P<caption>.*)"\.?\s*$',
    re.S,
)
REEL_PATH = re.compile(r"/(?:[\w.]+/)?reels?/([A-Za-z0-9_-]{5,})")
HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
# First path segments that are Instagram pages, not creator handles.
RESERVED_PATHS = {
    "explore", "popular", "reel", "reels", "p", "accounts", "about", "legal", "direct", "stories",
    "tv", "developer", "web", "challenge", "privacy", "terms", "session", "emails", "download", "locations",
    "topics", "directory", "lite", "api", "static",
}


@dataclass
class OgParts:
    likes: int | None
    comments: int | None
    handle: str
    posted_date: date | None
    caption: str


@dataclass
class ReelPage:
    """What one public Reel page tells us. Missing values come with a reason."""

    handle: str | None = None
    likes: int | None = None
    comments: int | None = None
    posted_date: date | None = None
    caption: str | None = None
    hook_line: str | None = None
    audio_label: str | None = None
    cover_url: str | None = None
    null_reasons: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------- numbers + text


def to_int(s: str | int | None) -> int | None:
    """'18.5K' -> 18500, '1.9M' -> 1900000, '8,340' -> 8340. None/blank/unparseable -> None (never a guess)."""
    if s is None:
        return None
    if isinstance(s, int):
        return s
    s = s.replace(",", "").strip().upper()
    if not s:
        return None
    mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(s[-1], 1)
    num = s[:-1] if mult > 1 else s
    try:
        return int(round(float(num) * mult))
    except ValueError:
        return None


def parse_og_description(text: str | None) -> OgParts | None:
    if not text:
        return None
    m = OG_DESCRIPTION.match(text.strip())
    if not m:
        return None
    try:
        posted = datetime.strptime(m["date"], "%B %d, %Y").date()
    except ValueError:
        posted = None
    return OgParts(
        likes=to_int(m["likes"]),
        comments=to_int(m["comments"]),
        handle=m["handle"],
        posted_date=posted,
        caption=m["caption"].replace("\\n", "\n").strip(),
    )


def hook_line(caption: str | None) -> str | None:
    """The caption's first line: the written hook. None if the first line is only hashtags."""
    if not caption:
        return None
    for line in caption.replace("\\n", "\n").splitlines():
        line = line.strip()
        if line:
            words = line.split()
            return None if all(w.startswith("#") for w in words) else line
    return None


# ---------------------------------------------------------------- URLs


def reel_shortcode(url: str) -> str | None:
    m = REEL_PATH.search(urlparse(url).path)
    return m.group(1) if m else None


def canonical_reel_url(url: str) -> str | None:
    """Every Reel link form (/reel/X/, /handle/reel/X/?utm=...) -> https://www.instagram.com/reel/X/."""
    code = reel_shortcode(url)
    return f"https://www.instagram.com/reel/{code}/" if code else None


def handle_from_url(url: str) -> str | None:
    """'https://www.instagram.com/cookwithx/' or '/cookwithx/reels/' -> 'cookwithx'. Instagram's own pages -> None."""
    parsed = urlparse(url)
    if parsed.netloc and "instagram.com" not in parsed.netloc:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None
    first = parts[0]
    if first.lower() in RESERVED_PATHS or not HANDLE_RE.match(first):
        return None
    if len(parts) > 1 and parts[1] not in ("reels", "reel", "p", "tagged"):
        return None
    return first


def reels_url(handle: str) -> str:
    return f"https://www.instagram.com/{handle}/reels/"


def topic_url(topic: str) -> str:
    return f"https://www.instagram.com/explore/tags/{topic.strip().lstrip('#').lower()}/"
