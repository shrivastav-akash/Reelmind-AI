"""Parsers for public Instagram pages fetched through TinyFish. Pure functions.

Called by niche_scout.py (Fri) on tinyfish_client.FetchedPage objects; outputs
plain values for models.Example / models.Creator. Formats were checked against
logged-out TinyFish fetches (brief §6, 25 Oct; samples/ refreshed 29 Oct).

Privacy: nothing here returns comment text or commenter usernames, and
redact_reel_page() removes them (plus commenter links and avatars) before
pages are cached, logged or saved.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from urllib.parse import quote, unquote, urlparse

# "711K likes, 1,838 comments - cookwithprincia on March 5, 2026: "caption"."
# Likes can be hidden, so that part is optional. DOTALL: captions span lines.
OG_DESCRIPTION = re.compile(
    r'^(?:(?P<likes>[\d.,]+[KMB]?) likes?, )?(?P<comments>[\d.,]+[KMB]?) comments? - '
    r'(?P<handle>[\w.]+) on (?P<date>[A-Z][a-z]+ \d{1,2}, \d{4}): "(?P<caption>.*)"\.?\s*$',
    re.S,
)
# Not /reels/audio/<id>/: every Reel page links its sound there, and it isn't a Reel.
REEL_PATH = re.compile(r"/(?:[\w.]+/)?reels?/(?!audio/)([A-Za-z0-9_-]{5,})")
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
    # Exact hosts only: about.instagram.com/blog/ is not a creator called "blog".
    if parsed.netloc and parsed.netloc.lower() not in ("instagram.com", "www.instagram.com"):
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
    """URL of the public topic page. Pass a topic through normalise_topic() first."""
    return f"https://www.instagram.com/explore/tags/{quote(normalise_topic(topic))}/"


# ---------------------------------------------------------------- the user's topic


class TopicRejected(ValueError):
    """The topic box can't become a hashtag. The message is shown to the user as-is (400)."""


MAX_TOPIC_CHARS = 40


def normalise_topic(raw: str | None) -> str:
    """What the user typed -> one Instagram hashtag, the way Instagram would read it.

    '#Cooking ' -> 'cooking'; 'study tips' -> 'studytips'; "Mom's food" -> 'momsfood';
    'खाना' stays 'खाना'; a pasted tag URL -> its tag. Rejects empty, emoji-only,
    digits-only, several hashtags at once, and anything over 40 characters.
    """
    text = (raw or "").strip()
    if "instagram.com" in text.lower():  # someone pasted a tag or topic page URL (phones capitalise it)
        m = re.search(r"/(?:explore/tags|popular)/([^/?#]+)", text, re.I)
        text = unquote(m.group(1)) if m else ""
    if len(re.findall(r"#\s*\w", text)) > 1:
        raise TopicRejected("Use one topic at a time, e.g. cooking.")
    # Letters, marks and numbers in any script: Hindi vowel signs (e.g. "ा" in खाना) are
    # combining marks, which str.isalnum() would wrongly drop.
    tag = "".join(ch for ch in text.lstrip("#") if ch == "_" or unicodedata.category(ch)[0] in "LMN").casefold()
    if not tag:
        raise TopicRejected("Type a topic word, e.g. cooking.")
    if not any(ch.isalpha() for ch in tag):
        raise TopicRejected("A topic needs at least one letter, e.g. cooking.")
    if len(tag) > MAX_TOPIC_CHARS:
        raise TopicRejected(f"Keep the topic under {MAX_TOPIC_CHARS} characters.")
    return tag


# ---------------------------------------------------------------- profile + grid pages

PROFILE_DESCRIPTION = re.compile(
    r"^(?P<followers>[\d.,]+[KMB]?) Followers?, (?P<following>[\d.,]+[KMB]?) Following, (?P<posts>[\d.,]+[KMB]?) Posts?"
)
COUNT_LINE = re.compile(r"^[\d.,]+[KMB]?$")


def parse_followers(description: str | None) -> int | None:
    """'204K Followers, 8 Following, 184 Posts - See Instagram photos...' -> 204000."""
    m = PROFILE_DESCRIPTION.match((description or "").strip())
    return to_int(m["followers"]) if m else None


@dataclass
class ProfileCounts:
    followers: int | None
    following: int | None
    posts: int | None


def parse_profile_counts(description: str | None) -> ProfileCounts:
    """The same line as parse_followers, all three counts: '204K Followers, 8 Following, 184 Posts' ->
    (204000, 8, 184). Rounded like the page shows them ("204K"); None when the line isn't there."""
    m = PROFILE_DESCRIPTION.match((description or "").strip())
    if not m:
        return ProfileCounts(None, None, None)
    return ProfileCounts(to_int(m["followers"]), to_int(m["following"]), to_int(m["posts"]))


@dataclass
class GridTile:
    reel_url: str
    likes: int | None
    comments: int | None
    views: int | None
    pinned: bool = False


@dataclass
class GridPage:
    handle: str | None
    followers: int | None
    tiles: list[GridTile]
    problems: list[str] = field(default_factory=list)  # why some numbers are missing, in plain words
    # Whether the page could be read at all. parse_grid only sees text, so niche_scout sets these
    # from the fetch result (failed fetch, login wall, private account).
    access_status: str = "accessible"
    status_reason: str | None = None


def parse_grid(text: str | None, links: list[str], description: str | None = None, handle: str | None = None) -> GridPage:
    """A creator's /reels/ page as Fetch returns it (markdown), checked on 11 creators on 29 Oct.

    After the "Posts / Reels / Tagged" tabs, each tile is:
        <likes> <comments> [Pinned post icon] View Count Icon <views>
    Tiles map to the page's Reel links in order. Pinned tiles are flagged, because
    they are the creator's old hits, not recent Reels.
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    start = lines.index("Tagged") + 1 if "Tagged" in lines else 0
    raw: list[tuple[list[str], bool, str | None]] = []
    buf: list[str] = []
    pinned = False
    i = start
    while i < len(lines):
        ln = lines[i]
        if ln == "Close":
            break
        if ln == "Pinned post icon":
            pinned = True
        elif ln == "View Count Icon":
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            views = nxt if COUNT_LINE.match(nxt) else None
            raw.append((buf[-2:], pinned, views))
            buf, pinned = [], False
            if views:
                i += 1
        elif COUNT_LINE.match(ln):
            buf.append(ln)
        i += 1

    reels = list(dict.fromkeys(c for c in (canonical_reel_url(u) for u in links) if c))
    problems: list[str] = []
    if not raw:
        problems.append("No Reel tiles visible on the public page")
    if raw and len(raw) != len(reels):
        problems.append(f"{len(raw)} tiles but {len(reels)} Reel links; only the first {min(len(raw), len(reels))} are used")

    tiles = []
    for n, ((counts, is_pinned, views), url) in enumerate(zip(raw, reels), start=1):
        if len(counts) == 2:
            likes, comments = to_int(counts[0]), to_int(counts[1])
        else:
            likes = comments = None
            problems.append(f"Tile {n}: likes/comments not shown")
        if views is None:
            problems.append(f"Tile {n}: views not shown")
        tiles.append(GridTile(reel_url=url, likes=likes, comments=comments, views=to_int(views), pinned=is_pinned))
    return GridPage(handle=handle, followers=parse_followers(description), tiles=tiles, problems=problems)


# ---------------------------------------------------------------- topic page


@dataclass
class TopicEntry:
    reel_url: str
    handle: str | None  # None when the page shows the Reel without its creator


@dataclass
class TopicPage:
    walled: bool
    entries: list[TopicEntry]
    handles: list[str]  # creators in page order, deduped
    related_topics: list[str]


def parse_topic_page(final_url: str | None, links: list[str]) -> TopicPage:
    """/explore/tags/<topic>/ redirects to /popular/<topic>/. Its links list each Reel,
    then the creator's profile link. A redirect to /accounts/login/ means a wall."""
    walled = "/accounts/login" in (final_url or "")
    entries: list[TopicEntry] = []
    handles: list[str] = []
    related: list[str] = []
    for url in links:
        if reel := canonical_reel_url(url):
            if all(e.reel_url != reel for e in entries):
                entries.append(TopicEntry(reel_url=reel, handle=None))
        elif h := handle_from_url(url):
            if entries and entries[-1].handle is None:
                entries[-1].handle = h
            if h not in handles:
                handles.append(h)
        elif "/popular/" in url and "topic_pill" in url:
            slug = unquote(urlparse(url).path.strip("/").split("/")[-1])
            if slug and slug not in related:
                related.append(slug)
    return TopicPage(walled=walled, entries=entries, handles=handles, related_topics=related)


# ---------------------------------------------------------------- Reel pages

AGE_LINE = re.compile(r"^\d+[smhdw]$")  # "33w", "2d", "5h"
JAMMED_COUNTS = re.compile(r"^[\d.,]+[KMB]?[\d.,]+[KMB]?$")  # "1.3M4.9K": likes+comments run together
COMMENT_LINK = re.compile(r"/p/[^/]+/c/\d+")
META_TAG = re.compile(r'<meta\b[^>]*\b(?:property|name)=["\'](?:og:[^"\']+|description)["\'][^>]*>', re.S)
OG_IMAGE = re.compile(r'<meta\b[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']', re.S)
# The og:description content is single-quoted because the caption inside it is in double
# quotes, so each quote style must run to its own closing quote.
OG_DESCRIPTION_META = re.compile(r'content=(?:"([^"]*)"|\'([^\']*)\')[^>]*og:description', re.S)


def redact_reel_page(page):
    """Remove comments, commenter usernames, their profile links and avatars from a
    fetched Reel page (tinyfish_client.FetchedPage) before it is cached, logged or saved.

    Markdown: keep the post header + caption and the counts/date lines; drop comment blocks.
    HTML: keep only the og:/description <meta> tags from <head>.
    Links: drop comment permalinks, and keep a profile link only for the Reel's author or an
    account the author @-mentions in the caption (a commenter's profile link sits just
    before their comment, so cutting by position isn't enough).
    Images: keep post media only (Instagram CDN "-15/" paths), never profile pictures ("-19/").
    """
    text = page.text or ""
    if "<head" in text or "<meta" in text:
        text = "\n".join(m.group(0) for m in META_TAG.finditer(text))
    else:
        text = _strip_comment_blocks(text)
    og = parse_og_description(page.description)
    allowed = {og.handle.lower()} if og else set()
    allowed |= {m.lower() for m in re.findall(r"@([\w.]+)", og.caption if og else "")}
    caption_tags = {t.casefold() for t in re.findall(r"#(\w+)", og.caption if og else "")}
    links = []
    for u in page.links:
        if COMMENT_LINK.search(u):
            continue
        h = handle_from_url(u)
        if h is not None and h.lower() not in allowed:
            continue
        tag = re.search(r"/explore/tags/([^/?#]+)", u)
        # A hashtag someone used in a comment. Without the caption we can't tell, so drop them all.
        if tag and (og is None or unquote(tag.group(1)).casefold() not in caption_tags):
            continue
        links.append(u)
    images = [u for u in page.image_links if "-15/" in u]
    return replace(page, text=text, links=links, image_links=images)


def _strip_comment_blocks(text: str) -> str:
    """Two Reel page layouts seen on 29 Oct:
    A: "---" sections, blank lines, counts jammed as "1.3M4.9K".
    B: one line per item, "Load more comments", counts as "Like / 2.1M / Comment / 4.6K".
    In both, each comment is <username> <age> <text> ... "Reply", and the post itself
    is <author> <age> <caption> just before the first comment.
    """
    lines = text.splitlines()
    ages = [i for i, ln in enumerate(lines) if AGE_LINE.match(ln.strip())]
    if len(ages) < 2:
        return text  # no comments shown
    # ages[0] is the post's own age line; ages[1] belongs to the first comment, whose
    # username is the last non-empty line before it.
    first_comment = ages[1] - 1
    while first_comment > ages[0] and not lines[first_comment].strip():
        first_comment -= 1
    if first_comment > ages[0] and lines[first_comment - 1].strip() == "Load more comments":
        first_comment -= 1
    end = len(lines)
    nonblank = [i for i in range(first_comment, len(lines)) if lines[i].strip()]
    # Every comment ends with "Reply", so the post's counts come after the last one. Without this,
    # a comment that is just a number ("100") would pass for the counts line and end the cut early.
    last_reply = max((i for i in nonblank if lines[i].strip() == "Reply"), default=-1)
    for n, i in enumerate(nonblank):
        if i < last_reply:
            continue
        ln = lines[i].strip()
        nxt = lines[nonblank[n + 1]].strip() if n + 1 < len(nonblank) else ""
        if JAMMED_COUNTS.match(ln) or (ln == "Like" and COUNT_LINE.match(nxt)) or ln.startswith("Log in to like"):
            end = i
            break
    return "\n".join(lines[:first_comment] + ["[comments removed]", ""] + lines[end:])


def _audio_label(text: str) -> str | None:
    """Layout B shows the audio under the author: "Follow / <artists> / • / <song>".
    Either layout may show "Original audio". Layout A shows neither."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if ln.startswith("Original audio"):
            return ln
        if ln == "Follow" and i + 3 < len(lines) and lines[i + 2] == "•":
            return f"{lines[i + 1]} · {lines[i + 3]}"
    return None


def parse_reel_page(page) -> ReelPage:
    """One public Reel page (markdown or html, ideally already redacted) -> ReelPage.

    Counts and caption come from og:description (the page's jammed "1.3M4.9K" line is
    ambiguous). Likes there are rounded ("1M" for 1.3M), so prefer grid counts when you have them.
    """
    out = ReelPage()
    og = parse_og_description(page.description)
    if og is None and page.text:
        m = OG_DESCRIPTION_META.search(page.text)
        og = parse_og_description(html.unescape(m.group(1) if m.group(1) is not None else m.group(2))) if m else None
    if og:
        out.handle, out.likes, out.comments, out.posted_date = og.handle, og.likes, og.comments, og.posted_date
        out.caption, out.hook_line = og.caption, hook_line(og.caption)
        if og.likes is None:
            out.null_reasons["likes"] = "Likes hidden by the creator"
        if out.hook_line is None:
            out.null_reasons["hook_line"] = "Caption's first line is empty or only hashtags"
    else:
        for f in ("likes", "comments", "caption", "hook_line"):
            out.null_reasons[f] = "Page didn't include the post summary"
    if out.posted_date is None and page.published_date:
        try:
            out.posted_date = datetime.fromisoformat(page.published_date.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    if out.posted_date is None:
        out.null_reasons["posted_date"] = "No post date on the page"

    out.audio_label = _audio_label(page.text or "")
    if out.audio_label is None:
        out.null_reasons["audio_label"] = "Audio name isn't shown on the public page"

    if m := OG_IMAGE.search(page.text or ""):
        out.cover_url = html.unescape(m.group(1))
    else:
        out.null_reasons["cover_url"] = "Cover needs the page's HTML head (fetch with format=html)"
    return out


# ---------------------------------------------------------------- Agent output


def clean_agent_reason(reason: str | None, max_chars: int = 140) -> str | None:
    """Keep the Agent's words about *why* it picked a creator, minus any numbers.

    On 29 Oct it called a 99K-follower account "~24.5M followers": numbers on screen
    must come from our own parsing, never from the Agent's prose.
    """
    if not reason:
        return None
    text = re.sub(r"\s*\([^)]*\d[^)]*\)", "", reason)  # "(~42.9M followers)"
    parts = [p.strip() for p in re.split(r"[;,]", text) if p.strip() and not re.search(r"\d", p)]
    if not parts:
        return None
    out = ", ".join(parts)
    out = out[0].upper() + out[1:]
    return out if len(out) <= max_chars else out[: max_chars - 1].rstrip() + "…"
