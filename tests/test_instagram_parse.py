"""instagram_parse on the real logged-out pages fetched through TinyFish on 29 Oct (samples/instagram/),
plus the odd inputs real users and real pages throw at it. IDs refer to docs/test-cases.md."""

import json
from datetime import date

import pytest

from backend import instagram_parse as ig
from backend.tinyfish_client import FetchedPage

from .conftest import SAMPLES

IG = SAMPLES / "instagram"
CREATORS = ["_kiran_ki_rasoi_", "baiba.tropina", "burnt_pellet_bbq", "cookwithprincia", "eylems_kitchen",
            "hkncook", "pov__gil", "shifhaneen", "silent_gourmet__asmr", "theflavrqueen", "zap_eat"]


def page(name: str) -> FetchedPage:
    return FetchedPage(**json.loads((IG / f"{name}.json").read_text()))


# ---------------------------------------------------------------- counts


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("18.5K", 18_500), ("1.9M", 1_900_000), ("1M", 1_000_000), ("2B", 2_000_000_000),
        ("8,340", 8340), ("1,222", 1222), ("0", 0), ("  95.2K ", 95_200), ("1.2k", 1200),
        (None, None), ("", None), ("—", None), ("N/A", None), ("1.2.3K", None), (512, 512),
    ],
)
def test_to_int(raw, expected):
    assert ig.to_int(raw) == expected


# ---------------------------------------------------------------- og:description


def test_og_real_reel():
    og = ig.parse_og_description(page("reel1_markdown").description)
    assert (og.likes, og.comments, og.handle, og.posted_date) == (1_000_000, 4859, "cookwithprincia", date(2026, 3, 7))
    assert og.caption.startswith("Hot Coffee ☕")


def test_og_hidden_likes():  # D13
    og = ig.parse_og_description('12 comments - some.cook on October 2, 2026: "Chai time"')
    assert og.likes is None and og.comments == 12


def test_og_singular_and_quotes_inside_caption():
    og = ig.parse_og_description('1 like, 1 comment - a_b on May 1, 2026: "She said "wow" \\n#chai".')
    assert og.likes == 1 and og.comments == 1 and og.caption == 'She said "wow" \n#chai'


@pytest.mark.parametrize("text", [None, "", "Watch short videos about cooking", "1M likes - missing parts"])
def test_og_unrecognised_returns_none(text):
    assert ig.parse_og_description(text) is None


@pytest.mark.parametrize(
    "caption, hook",
    [
        ("Hot Coffee ☕ \n\n#explorepage #cooking", "Hot Coffee ☕"),
        ("\n\n  First real line\nsecond", "First real line"),
        ("#food #cooking", None),
        ("", None),
        (None, None),
        ("Egg Flower Omelette 🍳\\n\\nRecipe", "Egg Flower Omelette 🍳"),
    ],
)
def test_hook_line(caption, hook):
    assert ig.hook_line(caption) == hook


# ---------------------------------------------------------------- URLs


@pytest.mark.parametrize(
    "url, canonical",
    [
        ("https://www.instagram.com/reel/DVgF8OrE3WU/?utm_source=popular_topic_grid", "https://www.instagram.com/reel/DVgF8OrE3WU/"),
        ("https://www.instagram.com/pov__gil/reel/DefePjGgbz2/", "https://www.instagram.com/reel/DefePjGgbz2/"),
        ("/reels/DWBj-4FE-Mt/", "https://www.instagram.com/reel/DWBj-4FE-Mt/"),
        ("https://www.instagram.com/pov__gil/", None),
        ("https://www.instagram.com/p/ABCDEFG/c/1234567/", None),
    ],
)
def test_canonical_reel_url(url, canonical):
    assert ig.canonical_reel_url(url) == canonical


@pytest.mark.parametrize(
    "url, handle",
    [
        ("https://www.instagram.com/cookwithprincia/", "cookwithprincia"),
        ("https://www.instagram.com/cookwithprincia", "cookwithprincia"),
        ("https://www.instagram.com/baiba.tropina/reels/", "baiba.tropina"),
        ("https://instagram.com/_kiran_ki_rasoi_/", "_kiran_ki_rasoi_"),
        ("https://about.instagram.com/blog/", None),  # real false positive from 29 Oct
        ("https://www.instagram.com/explore/tags/cooking/", None),
        ("https://www.instagram.com/accounts/login/?next=x", None),
        ("https://www.instagram.com/popular/cooking/", None),
        ("https://www.instagram.com/legal/privacy/", None),
        ("https://www.facebook.com/someone/", None),
        ("https://www.instagram.com/", None),
    ],
)
def test_handle_from_url(url, handle):
    assert ig.handle_from_url(url) == handle


# ---------------------------------------------------------------- the user's topic (B1-B12)


@pytest.mark.parametrize(
    "typed, tag",
    [
        ("cooking", "cooking"),
        ("#Cooking ", "cooking"),
        ("  COOKING", "cooking"),
        ("study tips", "studytips"),
        ("Mom's cooking!", "momscooking"),
        ("street_food", "street_food"),
        ("खाना", "खाना"),
        ("https://www.instagram.com/explore/tags/cooking/", "cooking"),
        ("https://www.instagram.com/popular/cooking/?utm_source=explore_tag", "cooking"),
        ("vegan2026", "vegan2026"),
    ],
)
def test_normalise_topic(typed, tag):
    assert ig.normalise_topic(typed) == tag


@pytest.mark.parametrize(
    "typed, message",
    [
        ("", "Type a topic word"),
        ("    ", "Type a topic word"),
        (None, "Type a topic word"),
        ("🍛🔥", "Type a topic word"),
        ("#", "Type a topic word"),
        ("#cooking #food", "one topic at a time"),
        ("2026", "at least one letter"),
        ("x" * 41, "under 40 characters"),
        ("https://www.instagram.com/cookwithprincia/", "Type a topic word"),
    ],
)
def test_topic_rejections(typed, message):
    with pytest.raises(ig.TopicRejected, match=message):
        ig.normalise_topic(typed)


@pytest.mark.parametrize("typed", ["<script>alert(1)</script>", "../../etc/passwd", 'cook"ing', "cook ing/?x=1#y"])
def test_topic_cannot_escape_the_url(typed):  # B12
    url = ig.topic_url(typed)
    assert url.startswith("https://www.instagram.com/explore/tags/") and url.endswith("/")
    tag = url.removeprefix("https://www.instagram.com/explore/tags/").rstrip("/")
    assert tag.replace("_", "").isalnum()


def test_topic_url_encodes_unicode():  # B5
    assert ig.topic_url("खाना") == "https://www.instagram.com/explore/tags/%E0%A4%96%E0%A4%BE%E0%A4%A8%E0%A4%BE/"


# ---------------------------------------------------------------- profile + grid pages


@pytest.mark.parametrize(
    "desc, followers",
    [
        ("204K Followers, 8 Following, 184 Posts - See Instagram photos", 204_000),
        ("9,067 Followers, 41 Following, 236 Posts - See Instagram photos", 9067),
        ("1M Followers, 0 Following, 386 Posts - See", 1_000_000),
        ("1 Follower, 2 Following, 1 Post - See", 1),
        ("Watch short videos about cooking", None),
        (None, None),
    ],
)
def test_parse_followers(desc, followers):
    assert ig.parse_followers(desc) == followers


@pytest.mark.parametrize(
    "desc, counts",
    [
        ("875K Followers, 1,027 Following, 1,712 Posts - See Instagram photos", (875_000, 1027, 1712)),
        ("9,067 Followers, 41 Following, 236 Posts - See", (9067, 41, 236)),
        ("1 Follower, 0 Following, 1 Post - See", (1, 0, 1)),
        ("Watch short videos about cooking", (None, None, None)),
        (None, (None, None, None)),
    ],
)
def test_parse_profile_counts(desc, counts):
    c = ig.parse_profile_counts(desc)
    assert (c.followers, c.following, c.posts) == counts


@pytest.mark.parametrize("handle", CREATORS)
def test_parse_grid_real_pages(handle):  # D11
    p = page(f"grid_{handle}")
    g = ig.parse_grid(p.text, p.links, p.description, handle)
    assert len(g.tiles) == 12 and g.problems == []
    assert all(t.views is not None and t.likes is not None and t.comments is not None for t in g.tiles)
    assert all(t.reel_url.startswith("https://www.instagram.com/reel/") for t in g.tiles)
    assert len({t.reel_url for t in g.tiles}) == 12
    assert g.followers and g.followers > 0


def test_parse_grid_reads_tiles_in_link_order_and_flags_pinned():
    p = page("grid_cookwithprincia")
    g = ig.parse_grid(p.text, p.links, p.description, "cookwithprincia")
    first = g.tiles[0]
    # Cross-checked against the Reel's own page: 4,859 comments (og says "1M likes", the grid says 1.3M).
    assert first.reel_url == "https://www.instagram.com/reel/DVlSnL5k_pn/"
    assert (first.likes, first.comments, first.views, first.pinned) == (1_300_000, 4859, 58_600_000, True)
    assert [t.pinned for t in g.tiles].count(True) == 3


def test_parse_grid_small_creator_numbers():
    p = page("grid_pov__gil")
    g = ig.parse_grid(p.text, p.links, p.description, "pov__gil")
    assert g.followers == 23_000
    assert max(t.views for t in g.tiles) == 26_400 and not any(t.pinned for t in g.tiles)


def test_parse_grid_login_wall_page():  # D8
    text = "Instagram\nLog In\nSign Up\nThis account is private\nFollow to see their photos and videos."
    g = ig.parse_grid(text, [], None, "private.cook")
    assert g.tiles == [] and g.problems == ["No Reel tiles visible on the public page"]


def test_parse_grid_tile_with_one_count_and_missing_views():
    text = "Tagged\n120\n4\nView Count Icon\n9,000\n7\nView Count Icon\n5\n1\nView Count Icon\nClose"
    links = [f"https://www.instagram.com/x/reel/CODE{i}AAA/" for i in range(3)]
    g = ig.parse_grid(text, links, None, "x")
    assert (g.tiles[0].likes, g.tiles[0].comments, g.tiles[0].views) == (120, 4, 9000)
    assert g.tiles[1].likes is None and g.tiles[1].comments is None
    assert g.tiles[2].views is None
    assert "Tile 2: likes/comments not shown" in g.problems and "Tile 3: views not shown" in g.problems


def test_parse_grid_more_tiles_than_links():
    text = "Tagged\n1\n2\nView Count Icon\n100\n3\n4\nView Count Icon\n200\nClose"
    g = ig.parse_grid(text, ["https://www.instagram.com/x/reel/ONLYONE1/"], None, "x")
    assert len(g.tiles) == 1 and "2 tiles but 1 Reel links" in g.problems[0]


def test_parse_grid_without_tabs_ignores_header_numbers():
    text = "203K\nfollowers\n8\nfollowing\n10\n2\nView Count Icon\n5,000\nClose"
    g = ig.parse_grid(text, ["https://www.instagram.com/x/reel/ABCDE12/"], None, "x")
    assert (g.tiles[0].likes, g.tiles[0].comments, g.tiles[0].views) == (10, 2, 5000)


# ---------------------------------------------------------------- topic page


def test_parse_topic_page_real():
    p = page("topic_cooking")
    t = ig.parse_topic_page(p.final_url, p.links)
    assert not t.walled
    assert t.handles == CREATORS[3:4] + ["hkncook", "zap_eat", "pov__gil", "eylems_kitchen", "burnt_pellet_bbq",
                                         "theflavrqueen", "silent_gourmet__asmr", "baiba.tropina", "shifhaneen",
                                         "_kiran_ki_rasoi_"]
    assert "blog" not in t.handles
    assert len(t.entries) == 12
    assert t.entries[0].handle == "cookwithprincia"
    assert sum(e.handle is None for e in t.entries) == 1  # one Reel is shown without its creator
    assert "korean-cooking-challenge-ideas" in t.related_topics


def test_parse_topic_page_redirected_to_login():  # D7
    t = ig.parse_topic_page("https://www.instagram.com/accounts/login/?next=/explore/tags/cooking/", [])
    assert t.walled and t.handles == [] and t.entries == []


def test_parse_topic_page_with_no_reels():  # B13
    t = ig.parse_topic_page("https://www.instagram.com/popular/zzqxvw/", ["https://www.instagram.com/", "https://about.instagram.com/blog/"])
    assert not t.walled and t.handles == [] and t.entries == []


# ---------------------------------------------------------------- Reel pages


@pytest.mark.parametrize("name", ["reel1_markdown", "reel2_markdown", "reel3_markdown", "reel1_html", "reel2_html", "reel3_html"])
def test_parse_reel_page_real(name):  # G5
    r = ig.parse_reel_page(page(name))
    assert r.handle == "cookwithprincia" and r.likes and r.comments and r.posted_date
    assert r.hook_line and not r.hook_line.startswith("#")
    if name == "reel3_markdown":  # page layout B shows the audio under the author
        assert r.audio_label == "Thaman S, Silambarasan TR, Roshini JKV · Mangalyam"
    else:  # layout A and html heads don't
        assert r.audio_label is None and "audio_label" in r.null_reasons
    if name.endswith("html"):
        assert r.cover_url.startswith("https://") and "cdninstagram.com" in r.cover_url and "&amp;" not in r.cover_url
    else:
        assert r.cover_url is None and "cover_url" in r.null_reasons
    for field, value in vars(r).items():
        if value is None:
            assert field in r.null_reasons, f"{field} is None without a reason"


def test_parse_reel_page_without_summary_uses_published_date():
    p = FetchedPage(url="u", retrieved_at="t", description=None, published_date="2026-10-01T09:00:00.000Z", text="nothing useful")
    r = ig.parse_reel_page(p)
    assert r.likes is None and r.null_reasons["likes"] == "Page didn't include the post summary"
    assert r.posted_date == date(2026, 10, 1)


def test_parse_reel_page_hidden_likes_reason():  # D13
    p = FetchedPage(url="u", retrieved_at="t", description='40 comments - a.cook on June 3, 2026: "Dal tadka"')
    r = ig.parse_reel_page(p)
    assert r.likes is None and r.null_reasons["likes"] == "Likes hidden by the creator" and r.comments == 40


def test_parse_reel_page_reads_original_audio_when_shown():
    p = FetchedPage(url="u", retrieved_at="t", description='1 comment - a on June 3, 2026: "x"', text="a\n\nOriginal audio\n\n")
    assert ig.parse_reel_page(p).audio_label == "Original audio"


# ---------------------------------------------------------------- Agent output (D6, G6)


@pytest.mark.parametrize(
    "reason, cleaned",
    [
        ("Individual creator with ~24.5M followers; posts approachable recipes like garlic bread with English translations, feels like a personal home-cooking account",
         "Posts approachable recipes like garlic bread with English translations, feels like a personal home-cooking account"),
        ("Individual creator (~42.9M followers) sharing quick easy recipes", "Individual creator sharing quick easy recipes"),
        ("Has 2M views", None),
        ("", None),
        (None, None),
        ("home cook, short recipes", "Home cook, short recipes"),
    ],
)
def test_clean_agent_reason_real_cases(reason, cleaned):
    assert ig.clean_agent_reason(reason) == cleaned


def test_clean_agent_reason_is_capped():
    out = ig.clean_agent_reason("a" * 400)
    assert len(out) == 140 and out.endswith("…")


def test_saved_agent_sample_has_no_numbers_in_reasons():
    picks = json.loads((IG / "agent_topic_cooking.json").read_text())["result"]["creators"]
    assert picks and all(p["reason"] is None or not any(ch.isdigit() for ch in p["reason"]) for p in picks)
