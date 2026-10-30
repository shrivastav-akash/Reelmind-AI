"""Defines "done" for creator_report.py (v2 task 1.4): Gemini's insights are only shown when every
key and Reel they cite exists; otherwise one retry, then the rule-based template, then nothing.
Gemini is faked; the report comes from the real creator maths on hand-built Reels."""

import pytest

from backend import creator_metrics, creator_report, llm_client, reports, validate
from backend.llm_client import LLMError
from backend.report_models import InsightDraft, InsightSet

from .test_creator_metrics import TODAY, normal, reel, report


def analysed():
    r = normal()
    r.reels.append(reel(7, 40_000, 2, "Why is my biryani dry?", access="timeout"))  # page didn't load: not citable
    creator_metrics.analyse(r, TODAY)
    return r


GOOD = InsightDraft(kind="working", claim="Your 2 question hooks reached a median of 4.07x your usual views.",
                    keys=["pat.hook_type.question", "p.median_views"], reel_ids=["r1", "r3"])
TEST = InsightDraft(kind="try_next", claim="Open your next recipe with a question.", keys=["pat.hook_type.question"],
                    reel_ids=["r1"])


class Gemini:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    async def generate_json(self, prompt, schema, *, images=None, temperature=0.2):
        assert schema is InsightSet
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return InsightSet(insights=answer)


@pytest.fixture
def gemini(monkeypatch):
    def use(*answers):
        g = Gemini(*answers)
        monkeypatch.setattr(llm_client, "generate_json", g.generate_json)
        return g
    return use


async def test_good_answer_is_shown(gemini):
    g = gemini([GOOD, TEST])
    r = analysed()
    await creator_report.write_insights(r)
    assert r.insights_source == "llm" and [i.kind for i in r.insights] == ["working", "try_next"]
    assert len(g.prompts) == 1


def test_prompt_has_the_numbers_and_only_readable_reels():
    r = analysed()
    q = next(p for p in r.patterns if p.key == "pat.hook_type.question")
    prompt = creator_report.build_prompt(r)
    assert f"p.median_views = {r.profile.median_views}" in prompt
    assert f"pat.hook_type.question = {q.median_ratio:g}x · 2 Reels (r1, r3) · 2 top / 0 bottom" in prompt
    assert f"r1: 2026-10-29 (last 7 days) · 50000 views ({r.reels[0].ratio_vs_median:g}x) · hook type question" in prompt
    assert "r7:" not in prompt  # its page didn't load (its grid views still count in the median)
    assert "4 Reels in the last 7 days" in prompt and "Never claim anything about pacing" in prompt


@pytest.mark.parametrize(
    "bad, reason",
    [
        (InsightDraft(kind="working", claim="Up 3x", keys=["pat.hook_type.dance"], reel_ids=["r1"]), "key pat.hook_type.dance does not exist"),
        (InsightDraft(kind="working", claim="Up 3x", keys=["p.median_views"], reel_ids=["r99"]), "Reel r99 does not exist"),
        (InsightDraft(kind="working", claim="Up 3x", keys=["p.median_views"], reel_ids=["r7"]), "Reel r7 does not exist or its page wasn't readable"),
        (InsightDraft(kind="working", claim="Up 3x", keys=[], reel_ids=["r1"]), "cites no key"),
        (InsightDraft(kind="working", claim="Up 3x", keys=["p.median_views"], reel_ids=[]), "cites no Reel"),
        (InsightDraft(kind="working", claim="Questions do better.", keys=["p.median_views"], reel_ids=["r1"]), "quotes no number"),
        (InsightDraft(kind="working", claim="This 4x hook went viral", keys=["p.median_views"], reel_ids=["r1"]), "banned words: viral"),
        (InsightDraft(kind="trend", claim="Up 3x", keys=["p.median_views"], reel_ids=["r1"]), "kind 'trend' must be one of"),
    ],
)
async def test_a_bad_insight_is_dropped_and_the_good_one_kept(gemini, bad, reason):
    gemini([bad, GOOD])
    r = analysed()
    await creator_report.write_insights(r)
    assert r.insights_source == "llm" and [i.claim for i in r.insights] == [GOOD.claim]
    _, reasons = validate.validate_insights(InsightSet(insights=[bad]), set(r.citable()),
                                            {x.id for x in r.reels if x.access_status == "accessible"})
    assert any(reason in x for x in reasons), reasons


async def test_a_try_next_may_skip_the_number(gemini):
    gemini([TEST])
    r = analysed()
    await creator_report.write_insights(r)
    assert r.insights_source == "llm" and r.insights[0].kind == "try_next"


async def test_rejected_answer_gets_one_retry_with_the_reasons(gemini):
    bad = InsightDraft(kind="working", claim="Up 3x", keys=["pat.made.up"], reel_ids=["r1"])
    g = gemini([bad], [GOOD])
    r = analysed()
    await creator_report.write_insights(r)
    assert r.insights_source == "llm_retry" and r.insights[0].claim == GOOD.claim
    assert "Your previous answer was rejected" in g.prompts[1] and "insight 1: key pat.made.up does not exist" in g.prompts[1]


async def test_both_rejected_falls_back_to_the_template(gemini):
    bad = InsightDraft(kind="working", claim="Up 3x", keys=["pat.made.up"], reel_ids=["r1"])
    g = gemini([bad], [])
    r = analysed()
    await creator_report.write_insights(r)
    assert r.insights_source == "template" and len(g.prompts) == 2
    assert [i.kind for i in r.insights] == ["working", "not_working", "try_next"]


async def test_gemini_down_goes_straight_to_the_template(gemini):
    g = gemini(LLMError("Gemini unavailable (timeout)"))
    r = analysed()
    await creator_report.write_insights(r)
    assert r.insights_source == "template" and len(g.prompts) == 1  # no second long wait


def test_template_says_what_the_patterns_say():
    r = analysed()
    q = next(p for p in r.patterns if p.key == "pat.hook_type.question")
    working, not_working, try_next = creator_report.template_insights(r)
    assert working.keys == ["pat.hook_type.question", "p.median_views"] and working.reel_ids == ["r1", "r3"]
    assert working.claim == f"Question hooks reached a median of {q.median_ratio:g}x your usual views (2 Reels, 2 in your top third)."
    assert not_working.claim.startswith(("Plain-statement hooks", "Named-track Reels", "Reels tagged #dinner"))
    assert try_next.claim == (f"Test it: make your next Reel like these (question hooks), "
                              f"then compare its views with your median of {r.profile.median_views:,}.")


@pytest.mark.parametrize("value, label", [("pov", "POV hooks"), ("how_to", "How-to hooks"), ("question", "Question hooks")])
def test_hook_labels_read_well(value, label):
    from backend.report_models import PatternRow

    p = PatternRow(dimension="hook_type", value=value, reel_ids=["r1"], median_ratio=2.0, in_top=1, in_bottom=0)
    assert creator_report._label(p) == label
    assert creator_report._mid_sentence(label) == ("POV hooks" if value == "pov" else label[0].lower() + label[1:])


def test_template_always_passes_the_validator():
    r = analysed()
    drafts = [InsightDraft(**i.model_dump()) for i in creator_report.template_insights(r)]
    kept, reasons = validate.validate_insights(InsightSet(insights=drafts), set(r.citable()),
                                               {x.id for x in r.reels if x.access_status == "accessible"})
    assert len(kept) == 3 and reasons == []


def test_template_without_anything_below_1x():
    r = report(reel(1, 10_000, 1, "Why x?"), reel(2, 10_000, 2, "Why y?"), reel(3, 10_000, 3, "Why z?"))
    creator_metrics.analyse(r, TODAY)
    kinds = [i.kind for i in creator_report.template_insights(r)]
    assert "not_working" not in kinds


async def test_no_median_means_no_insights_and_no_gemini_call(gemini):
    g = gemini()
    r = report(reel(1, 5_000, 1), reel(2, None, 2), reel(3, None, 3))
    creator_metrics.analyse(r, TODAY)
    await creator_report.write_insights(r)
    assert r.insights == [] and r.insights_source == "insufficient_evidence" and g.prompts == []


async def test_no_readable_reel_means_no_insights(gemini):
    g = gemini()
    r = report(*(reel(n, 10_000 * n, n, access="timeout") for n in range(1, 4)))
    creator_metrics.analyse(r, TODAY)
    await creator_report.write_insights(r)
    assert r.insights_source == "insufficient_evidence" and g.prompts == []


async def test_at_most_six_insights(gemini):
    many = [GOOD.model_copy(update={"kind": k, "reel_ids": [f"r{n}"]}) for k in ("working", "not_working", "try_next")
            for n in range(1, 4)]
    gemini(many)
    r = analysed()
    await creator_report.write_insights(r)
    assert len(r.insights) == creator_report.MAX_INSIGHTS


async def test_the_same_reels_under_another_word_are_one_insight(gemini):
    # live 30 Oct: "breakfast" (r3, r7, r8) and "kahvaltı" (r7, r8) came back as two working insights
    broad = GOOD.model_copy(update={"reel_ids": ["r1", "r2", "r3"]})
    narrow = GOOD.model_copy(update={"claim": "Your 2 question hooks: 4.07x.", "reel_ids": ["r1", "r3"]})
    other = GOOD.model_copy(update={"kind": "try_next", "reel_ids": ["r1", "r3"]})  # another kind: kept
    gemini([broad, narrow, other])
    r = analysed()
    await creator_report.write_insights(r)
    assert [(i.kind, i.reel_ids) for i in r.insights] == [("working", ["r1", "r2", "r3"]), ("try_next", ["r1", "r3"])]


def test_the_runner_now_finds_the_writer():
    assert reports._stage_fn("creator_report", "write_insights") is creator_report.write_insights
