"""Defines "done" for creator_metrics.py (v2 task 1.2): the numbers and patterns in a creator report.
Hand-built Reels for the rules, plus the real 29 Oct grids through the real profiler."""

from datetime import date, datetime, timedelta, timezone

import pytest

from backend import creator_metrics, creator_profiler, outliers, reports
from backend.report_models import CoverNotes, CreatorReport, ProfileStats, ReelStat

from .test_creator_profiler import World, emit_into, tiles

TODAY = date(2026, 10, 30)
NOW = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)


def reel(n, views, days_ago, caption="Plain dinner tonight\n#dinner", audio=None, likes=100, comments=5, access="accessible"):
    return ReelStat(
        id=f"r{n}", source_url=f"https://www.instagram.com/reel/TEST{n:07d}/", retrieved_at=NOW, access_status=access,
        posted_date=TODAY - timedelta(days=days_ago) if days_ago is not None else None, views=views, likes=likes,
        comments=comments, caption=caption if access == "accessible" else None,
        hook_line=caption.split("\n")[0] if caption and access == "accessible" else None,
        audio_label=audio, original_audio=None if audio is None else audio.startswith("Original audio"),
    )


def report(*reels):
    return CreatorReport(profile=ProfileStats(handle="test_cook", profile_url="https://www.instagram.com/test_cook/"),
                         reels=list(reels))


def normal():
    return report(
        reel(1, 50_000, 1, "Why does restaurant dal taste better?\nSave this\n#dal #cooking", "Original audio"),
        reel(2, 9_000, 3, "Aaj kuch naya\n#dinner #cooking", "Artist · Song"),
        reel(3, 60_000, 7, "Is ghee healthy?\n#ghee #cooking", "Original audio"),
        reel(4, 12_000, 8, "My mom's rajma\n#rajma", "Artist · Song"),
        reel(5, 15_000, 10, "How to make soft rotis\n#roti #cooking", "Original audio"),
        reel(6, 7_000, 14, "Lunch box idea\n#lunchbox #dinner", "Artist · Song"),
    )


def row(r, key):
    return next(p for p in r.patterns if p.key == key)


# ---------------------------------------------------------------- numbers


def test_median_ratios_and_window():
    r = normal()
    creator_metrics.analyse(r, TODAY)
    p = r.profile
    assert p.median_views == 13_500  # median of 50K, 9K, 60K, 12K, 15K, 7K
    assert [x.ratio_vs_median for x in r.reels] == [3.7, 0.67, 4.44, 0.89, 1.11, 0.52]
    assert [x.in_window for x in r.reels] == [True, True, True, False, False, False]  # 7 days ago is in, 8 is out
    assert p.reels_in_window == 3
    assert p.window_note == "3 Reels in the last 7 days; patterns compare all 6 recent Reels (back to 16 Oct)"


def test_cadence_counts_up_to_today():
    r = normal()
    creator_metrics.analyse(r, TODAY)
    assert r.profile.posts_per_week == 3.0  # 6 Reels over the 14 days since the oldest


def test_median_engagement():
    r = normal()
    creator_metrics.analyse(r, TODAY)
    # every Reel has 100 likes + 5 comments: the middle two views are 12K and 15K
    assert r.profile.median_engagement == round((105 / 12_000 + 105 / 15_000) / 2, 4)


def test_no_reels_in_the_window_says_so():
    r = report(reel(1, 5_000, 16), reel(2, 6_000, 19), reel(3, 7_000, 22))
    creator_metrics.analyse(r, TODAY)
    assert r.profile.reels_in_window == 0
    assert r.profile.window_note == "No Reels in the last 7 days (newest: 14 Oct); patterns compare all 3 recent Reels (back to 08 Oct)"


def test_one_reel_in_the_window_is_singular():
    r = report(reel(1, 5_000, 2), reel(2, 6_000, 19), reel(3, 7_000, 22))
    creator_metrics.analyse(r, TODAY)
    assert r.profile.window_note.startswith("1 Reel in the last 7 days;")


def test_too_few_views_means_no_ratios_and_says_why():
    r = report(reel(1, 5_000, 1), reel(2, None, 2), reel(3, None, 3))
    creator_metrics.analyse(r, TODAY)
    assert r.profile.median_views is None and "Fewer than 3" in r.null_reasons["median_views"]
    assert all(x.ratio_vs_median is None and x.null_reasons["ratio_vs_median"] for x in r.reels)
    assert all(p.median_ratio is None and p.in_top == p.in_bottom == 0 for p in r.patterns)


def test_no_reels_at_all_does_not_crash():
    r = report()
    creator_metrics.analyse(r, TODAY)
    assert r.profile.median_views is None and r.profile.posts_per_week is None
    assert r.profile.window_note is None and r.patterns == []


def test_unreadable_reels_count_in_the_median_but_not_in_patterns():
    r = report(reel(1, 10_000, 1, "Why x?"), reel(2, 20_000, 2, "Why y?"), reel(3, 30_000, 3, access="timeout"))
    creator_metrics.analyse(r, TODAY)
    assert r.profile.median_views == 20_000
    assert row(r, "pat.hook_type.question").reel_ids == ["r1", "r2"]
    assert r.reels[2].hook_type is None


# ---------------------------------------------------------------- patterns


def test_patterns_name_what_works_for_this_creator():
    r = normal()
    creator_metrics.analyse(r, TODAY)
    q = row(r, "pat.hook_type.question")
    assert (q.reel_ids, q.median_ratio, q.in_top, q.in_bottom) == (["r1", "r3"], 4.07, 2, 0)
    s = row(r, "pat.hook_type.statement")
    assert s.reel_ids == ["r2", "r6"] and s.in_bottom == 2
    assert row(r, "pat.audio.original").median_ratio == 3.7 and row(r, "pat.audio.named track").median_ratio == 0.67
    assert row(r, "pat.hashtag.#cooking").reel_ids == ["r1", "r2", "r3", "r5"]


def test_one_off_hashtags_keywords_and_days_are_not_patterns():
    r = normal()
    creator_metrics.analyse(r, TODAY)
    keys = {p.key for p in r.patterns}
    assert "pat.hashtag.#rajma" not in keys and "pat.hashtag.#dinner" in keys
    for p in r.patterns:
        if p.dimension in ("hashtag", "keyword", "weekday"):
            assert len(p.reel_ids) >= 2, p.key


def test_patterns_are_ordered_by_dimension_then_strength():
    r = normal()
    creator_metrics.analyse(r, TODAY)
    dims = [p.dimension for p in r.patterns]
    assert dims == sorted(dims, key=creator_metrics.DIMENSION_ORDER.index)
    hooks = [p.median_ratio for p in r.patterns if p.dimension == "hook_type"]
    assert hooks == sorted(hooks, reverse=True)


def test_cover_notes_become_a_pattern_when_present():
    r = normal()
    r.reels[0].cover_notes = CoverNotes(text_on_cover="DAL SECRET", face=True, setting="stove", style="bright")
    r.reels[1].cover_notes = CoverNotes(text_on_cover=None, face=False, setting="table", style="dim")
    creator_metrics.analyse(r, TODAY)
    assert row(r, "pat.cover_text.text on cover").reel_ids == ["r1"]


def test_every_pattern_is_citable():
    r = normal()
    creator_metrics.analyse(r, TODAY)
    keys = r.citable()
    assert {p.key for p in r.patterns} <= set(keys) and keys["p.median_views"] == 13_500


# ---------------------------------------------------------------- caption fields


def test_fill_caption_fields():
    x = reel(1, 1, 1, "3 chutneys in 5 minutes\nComment GREEN for the recipe\n#chutney #quick")
    creator_metrics.fill_caption_fields(x)
    assert x.hook_type == "number_list" and x.hashtags == ["#chutney", "#quick"] and x.has_cta is True
    assert "chutneys" in x.keywords and x.caption_chars == len(x.caption)


def test_fill_caption_fields_leaves_a_missing_caption_alone():
    x = reel(1, 1, 1, access="timeout")
    creator_metrics.fill_caption_fields(x)
    assert x.hook_type is None and x.hashtags == [] and x.has_cta is None


@pytest.mark.parametrize("chars, bucket", [(0, "short (< 60)"), (59, "short (< 60)"), (60, "medium (60-200)"),
                                           (200, "medium (60-200)"), (201, "long (200+)")])
def test_caption_buckets(chars, bucket):
    assert creator_metrics.caption_bucket(chars) == bucket


# ---------------------------------------------------------------- with real pages and the runner


@pytest.fixture
def world(monkeypatch):
    from backend import tinyfish_client

    w = World()
    monkeypatch.setattr(tinyfish_client, "fetch_pages", w.fetch_pages)
    return w


async def test_real_grid_through_profiler_and_maths(world):
    r = await creator_profiler.fetch_creator("eylems_kitchen", emit_into([]))
    creator_metrics.analyse(r, TODAY)
    recent = [t for t in tiles("eylems_kitchen") if not t.pinned]
    assert r.profile.median_views == outliers.creator_median([t.views for t in recent])
    assert all(x.hook_type and x.hashtags == ["#cooking", "#dinner"] for x in r.reels)
    assert row(r, "pat.hashtag.#cooking").reel_ids == [x.id for x in r.reels]


def test_the_runner_now_finds_these_steps():
    assert reports._stage_fn("creator_metrics", "analyse") is creator_metrics.analyse
    assert reports._stage_fn("creator_metrics", "fill_caption_fields") is creator_metrics.fill_caption_fields
