"""Defines "done" for creator_report.write_reel_insights (v2 task 3.2): insights about one pasted
Reel against its creator, in the third person, citing r0 plus the creator's own Reels and keys.
Gemini is faked; the report is built with the real maths and comparison."""

import pytest

from backend import creator_metrics, creator_report, reel_report, reports, validate
from backend.llm_client import LLMError
from backend.report_models import InsightDraft, InsightSet, ReelReport

from .test_creator_metrics import TODAY, normal, reel, report
from .test_creator_report import Gemini


def reel_report_for(views=39_000):
    creator = normal()
    creator.reels.append(reel(7, 40_000, 2, "Why is my biryani dry?", access="timeout"))  # not citable
    creator_metrics.analyse(creator, TODAY)
    r0 = reel(0, views, 2, "Why is my biryani always dry?\nSave this\n#biryani #cooking", "Original audio")
    creator_metrics.fill_caption_fields(r0)
    if views is not None:
        r0.ratio_vs_median = round(views / creator.profile.median_views, 2)
    else:
        r0.null_reasons["views"] = reel_report.NOT_IN_GRID
    rep = ReelReport(reel=r0, creator=creator)
    rep.comparison = reel_report.compare(r0, creator)
    return rep


def ids(rep):
    return {r.id for r in rep.creator.reels if r.access_status == "accessible"} | {"r0"}


GOOD = InsightDraft(kind="working", claim="This Reel opens with a question, and @test_cook's 2 question hooks average 3.67x their median.",
                    keys=["pat.hook_type.question"], reel_ids=["r0", "r1", "r3"])


@pytest.fixture
def gemini(monkeypatch):
    from backend import llm_client

    def use(*answers):
        g = Gemini(*answers)
        monkeypatch.setattr(llm_client, "generate_json", g.generate_json)
        return g
    return use


async def test_good_answer_is_shown(gemini):
    g = gemini([GOOD])
    rep = reel_report_for()
    await creator_report.write_reel_insights(rep)
    assert rep.insights_source == "llm" and rep.insights[0].reel_ids == ["r0", "r1", "r3"]
    assert len(g.prompts) == 1


def test_prompt_is_about_this_reel_in_the_third_person():
    rep = reel_report_for()
    prompt = creator_report.build_reel_prompt(rep)
    assert 'write about "this Reel" and "@test_cook", never "you" or "your"' in prompt
    assert f"r0: @test_cook · posted 2026-10-28 · 39000 ({rep.reel.ratio_vs_median:g}x their median) · hook type question" in prompt
    assert f"This Reel got 39000 views, {rep.reel.ratio_vs_median:g}x @test_cook's median of {rep.creator.profile.median_views}." in prompt
    best = next(p for p in rep.creator.patterns if p.key == "pat.hook_type.question").median_ratio
    assert f"Hook type: question | question (2 of 6 Reels) | Their best-performing hook type: question ({best:g}x their median)" in prompt
    assert "r7:" not in prompt


def test_prompt_when_the_views_are_not_public():
    prompt = creator_report.build_reel_prompt(reel_report_for(views=None))
    assert "view count isn't public" in prompt and "Say nothing about how many views it got" in prompt
    assert "views not public" in prompt


@pytest.mark.parametrize(
    "bad, reason",
    [
        (InsightDraft(kind="working", claim="3x", keys=["p.median_views"], reel_ids=["r7"]), "Reel r7 does not exist or its page wasn't readable"),
        (InsightDraft(kind="working", claim="3x", keys=["pat.hook_type.dance"], reel_ids=["r0"]), "key pat.hook_type.dance does not exist"),
        (InsightDraft(kind="working", claim="This went viral at 3x", keys=["p.median_views"], reel_ids=["r0"]), "banned words: viral"),
    ],
)
async def test_bad_reel_insights_are_dropped(gemini, bad, reason):
    gemini([bad, GOOD])
    rep = reel_report_for()
    await creator_report.write_reel_insights(rep)
    assert [i.claim for i in rep.insights] == [GOOD.claim]
    _, reasons = validate.validate_insights(InsightSet(insights=[bad]), set(rep.creator.citable()), ids(rep))
    assert any(reason in r for r in reasons), reasons


async def test_gemini_down_uses_the_reel_template(gemini):
    g = gemini(LLMError("Gemini unavailable"))
    rep = reel_report_for()
    await creator_report.write_reel_insights(rep)
    assert rep.insights_source == "template" and len(g.prompts) == 1
    first, hook, borrow = rep.insights
    m = rep.creator.profile.median_views
    assert first.claim == f"This Reel reached {rep.reel.ratio_vs_median:g}x @test_cook's median views (39,000 vs {m:,})."
    assert first.kind == "working" and first.reel_ids == ["r0"]
    assert hook.claim.startswith("This Reel opens with a question hook; @test_cook's question hooks average")
    assert borrow.kind == "try_next" and borrow.claim.startswith("Worth borrowing from @test_cook: ")
    assert "your" not in borrow.claim


def test_reel_template_passes_the_validator():
    for views in (39_000, 5_000, None):
        rep = reel_report_for(views)
        drafts = [InsightDraft(**i.model_dump()) for i in creator_report.template_reel_insights(rep)]
        kept, reasons = validate.validate_insights(InsightSet(insights=drafts), set(rep.creator.citable()), ids(rep))
        assert drafts and len(kept) == len(drafts) and reasons == [], views


def test_reel_template_below_the_median_and_without_views():
    low = creator_report.template_reel_insights(reel_report_for(5_000))
    assert low[0].kind == "not_working"
    hidden = creator_report.template_reel_insights(reel_report_for(None))
    assert not any("median views (" in i.claim for i in hidden)  # nothing about its reach


async def test_creator_without_a_median_means_no_insights(gemini):
    g = gemini()
    creator = report(reel(1, 5_000, 1), reel(2, None, 2), reel(3, None, 3))
    creator_metrics.analyse(creator, TODAY)
    rep = ReelReport(reel=reel(0, None, 1), creator=creator)
    await creator_report.write_reel_insights(rep)
    assert rep.insights_source == "insufficient_evidence" and g.prompts == []


def test_the_runner_now_finds_the_reel_writer():
    assert reports._stage_fn("creator_report", "write_reel_insights") is creator_report.write_reel_insights
