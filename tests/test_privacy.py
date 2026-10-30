"""G1: nothing we save holds comments, commenter usernames, their profile links or avatars.

Checks the committed samples and redact_reel_page itself. Structural checks
(comment permalinks, profile pictures, "Reply" lines) so they hold on any page,
not just the names we happened to see on 29 Oct.
"""

import json
import re

import pytest

from backend import instagram_parse as ig
from backend.tinyfish_client import FetchedPage

from .conftest import SAMPLES

REEL_SAMPLES = sorted((SAMPLES / "instagram").glob("reel*.json"))


def load(path) -> FetchedPage:
    return FetchedPage(**json.loads(path.read_text()))


@pytest.mark.parametrize("path", REEL_SAMPLES, ids=lambda p: p.stem)
def test_reel_samples_hold_no_comments(path):
    p = load(path)
    text = p.text or ""
    assert "Reply" not in text and "Load more comments" not in text
    assert not any(re.search(r"/p/[^/]+/c/\d+", u) for u in p.links), "comment permalink kept"
    assert not any("-19/" in u for u in p.image_links), "profile picture kept"
    og = ig.parse_og_description(p.description)
    allowed = {og.handle} | set(re.findall(r"@([\w.]+)", og.caption))
    profiles = {h for h in (ig.handle_from_url(u) for u in p.links) if h}
    assert profiles <= allowed, f"profile links of non-authors kept: {profiles - allowed}"
    caption_tags = {t.casefold() for t in re.findall(r"#(\w+)", og.caption)}
    for u in p.links:
        if m := re.search(r"/explore/tags/([^/?#]+)", u):
            assert m.group(1).casefold() in caption_tags, f"hashtag from a comment kept: {m.group(1)}"


def test_markdown_samples_keep_the_caption_and_counts():
    p = load(SAMPLES / "instagram" / "reel2_markdown.json")
    assert "Egg Flower Omelette" in p.text and "[comments removed]" in p.text and "3.2M8.6K" in p.text


@pytest.mark.parametrize("name", ["reel1_html", "reel2_html", "reel3_html"])
def test_html_samples_keep_only_meta_tags(name):
    p = load(SAMPLES / "instagram" / f"{name}.json")
    outside_tags = re.sub(r"<meta\b[^>]*>", "", p.text, flags=re.S).strip()
    assert outside_tags == "" and 'property="og:image"' in p.text


def test_layout_b_page_is_redacted():
    p = load(SAMPLES / "instagram" / "reel3_markdown.json")
    assert "Load more comments" not in p.text and "[comments removed]" in p.text
    assert "Spicy Mango" in p.text and "2.1M" in p.text


def test_redaction_on_a_synthetic_page_with_tricky_comments():
    text = (
        "---\n\nauthor_x\n\n 3d\n\nMy dal recipe @friend_y #dal\n\n"
        "commenter_one\n\n 2d\n\nlooks viral! #fake\n\n1 like\n\nReply\n\n"
        "commenter\\_two\n\n 5h\n\nhttps://www.instagram.com/reel/AAAAAAA/\n\nReply\n\n"
        "12K340\n\nOctober 2\n\nLog in to like or comment.\n\n---\n"
    )
    page = FetchedPage(
        url="https://www.instagram.com/reel/ZZZZZZZ/", retrieved_at="t",
        description='12K likes, 340 comments - author_x on October 2, 2026: "My dal recipe @friend_y #dal"',
        text=text,
        links=["https://www.instagram.com/author_x/", "https://www.instagram.com/friend_y/",
               "https://www.instagram.com/explore/tags/dal/", "https://www.instagram.com/commenter_one/",
               "https://www.instagram.com/p/ZZZZZZZ/c/1234567/", "https://www.instagram.com/explore/tags/fake/",
               "https://www.instagram.com/commenter_two/", "https://www.instagram.com/author_x/reel/BBBBBBB/"],
        image_links=["https://cdn/v/t51.2885-19/avatar.jpg", "https://cdn/v/t51.71878-15/post.jpg"],
    )
    out = ig.redact_reel_page(page)
    assert "commenter" not in out.text and "viral" not in out.text and "My dal recipe" in out.text
    assert out.links == ["https://www.instagram.com/author_x/", "https://www.instagram.com/friend_y/",
                         "https://www.instagram.com/explore/tags/dal/", "https://www.instagram.com/author_x/reel/BBBBBBB/"]
    assert out.image_links == ["https://cdn/v/t51.71878-15/post.jpg"]
    assert page.text == text  # the original object isn't modified


def test_redaction_keeps_a_page_without_comments_whole():
    text = "---\n\nauthor_x\n\n 3d\n\nNo comments yet\n\n0\n\nOctober 2\n"
    page = FetchedPage(url="u", retrieved_at="t", text=text, description='0 comments - author_x on October 2, 2026: "No comments yet"')
    assert ig.redact_reel_page(page).text == text


def test_no_raw_pages_are_committed():
    import subprocess

    tracked = subprocess.run(["git", "ls-files", "samples"], capture_output=True, text=True, cwd=SAMPLES.parent).stdout
    assert "samples/raw/" not in tracked
