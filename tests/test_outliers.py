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
