from backend.outliers import Candidate, ReelCounts, creator_median, pick_outliers, score_creator


def reels(*views):
    return [ReelCounts(f"https://www.instagram.com/reel/R{i}/", v) for i, v in enumerate(views)]


def test_median_ignores_missing_and_zero_views():
    assert creator_median([100, None, 300, 0, 200]) == 200


def test_median_needs_three_known_views():
    assert creator_median([100, None, 200]) is None


def test_score_creator_ratio_against_own_median():
    med, cands = score_creator("a", reels(100, 100, 100, 400))
    assert med == 100
    assert [c.outlier_ratio for c in cands] == [1.0, 1.0, 1.0, 4.0]


def test_score_creator_skips_duplicates_and_missing_views():
    rs = reels(100, 200, 300) + [ReelCounts("https://www.instagram.com/reel/R0/", 100), ReelCounts("x", None)]
    _, cands = score_creator("a", rs)
    assert len(cands) == 3


def test_score_creator_with_too_few_views_returns_nothing():
    assert score_creator("a", reels(100, None)) == (None, [])


def cand(handle, ratio):
    return Candidate(handle, f"https://www.instagram.com/reel/{handle}{ratio}/", int(ratio * 100), None, None, 100, ratio)


def test_pick_outliers_threshold_order_and_per_creator_cap():
    picked = pick_outliers([cand("a", 1.9), cand("a", 5.0), cand("a", 4.0), cand("a", 3.0), cand("b", 2.0)])
    assert [(c.handle, c.outlier_ratio) for c in picked] == [("a", 5.0), ("a", 4.0), ("b", 2.0)]


def test_pick_outliers_top_n():
    picked = pick_outliers([cand(h, 3.0) for h in "abcdefg"], top_n=5)
    assert len(picked) == 5


# ---------------------------------------------------------------- real-user corner cases


def test_pinned_reels_are_ignored():  # D11: a pinned old hit must not set the bar or be "evidence"
    rs = reels(100, 120, 110, 105) + [ReelCounts("https://www.instagram.com/reel/PINNED/", 281_000_000, pinned=True)]
    med, cands = score_creator("a", rs)
    assert med == 107 and all("PINNED" not in c.reel_url for c in cands)


def test_flat_creator_has_no_outliers():  # D12
    _, cands = score_creator("a", reels(5000, 5100, 4900, 5050, 4980))
    assert pick_outliers(cands) == []


def test_exactly_2x_counts_but_just_under_does_not():
    _, cands = score_creator("a", reels(100, 100, 100, 200, 199))
    assert [c.views for c in pick_outliers(cands)] == [200]


def test_only_pinned_reels_means_no_median():
    rs = [ReelCounts(f"u{i}", 1000, pinned=True) for i in range(5)]
    assert score_creator("a", rs) == (None, [])


def test_pick_outliers_with_nothing():
    assert pick_outliers([]) == []


def test_real_cooking_creators_give_outliers_from_several_creators():
    """The 11 grids TinyFish Fetch read on 29 Oct (samples/instagram/)."""
    import json

    from backend import instagram_parse as ig
    from backend.tinyfish_client import FetchedPage

    from .conftest import SAMPLES

    cands = []
    for path in sorted((SAMPLES / "instagram").glob("grid_*.json")):
        p = FetchedPage(**json.loads(path.read_text()))
        handle = path.stem.removeprefix("grid_")
        g = ig.parse_grid(p.text, p.links, p.description, handle)
        med, cs = score_creator(handle, [ReelCounts(t.reel_url, t.views, t.likes, t.comments, t.pinned) for t in g.tiles])
        assert med is not None
        cands += cs
    picked = pick_outliers(cands)
    assert len(picked) == 5 and all(c.outlier_ratio >= 2.0 for c in picked)
    assert len({c.handle for c in picked}) >= 3
    assert picked == sorted(picked, key=lambda c: -c.outlier_ratio)
