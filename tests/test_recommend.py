"""Defines "done" for recommend.py (Fri tasks N3, N4). Fails with NotImplementedError until built."""

import pytest

from backend import llm_client, recommend, validate
from backend.models import Experiment, Suggestion, SuggestionSet

# Built on Friday: run with `pytest -m friday`. Delete this line once the file passes.
pytestmark = pytest.mark.friday


def suggestion(evidence=("ex1",), keys=("m.payoff_at_s",)):
    return Suggestion(
        observation="The payoff arrives at ~6.2 s (m.payoff_at_s).",
        measurement_keys=list(keys),
        evidence_ids=list(evidence),
        evidence_summary="Pattern in 1 example: ex1 (3.1x).",
        hypothesis="Opening on the dish may hold viewers.",
        experiment=Experiment(cut_a="As is", cut_b="Start on the dish", measure="3-second hold"),
    )


def scripted_llm(monkeypatch, *answers):
    """Each call returns the next answer; an Exception instance is raised instead."""
    prompts = []
    queue = list(answers)

    async def generate_json(prompt, schema, *, images=None, temperature=0.2):
        prompts.append(prompt)
        nxt = queue.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    monkeypatch.setattr(llm_client, "generate_json", generate_json)
    return prompts


async def test_good_answer_is_shown(monkeypatch, done_job):
    scripted_llm(monkeypatch, SuggestionSet(suggestions=[suggestion()]))
    rec = await recommend.recommend(done_job.video, done_job.examples, "cooking")
    assert rec.source == "llm" and len(rec.suggestions) == 1


async def test_rejected_answer_is_regenerated_once_with_reasons(monkeypatch, done_job):
    prompts = scripted_llm(monkeypatch, SuggestionSet(suggestions=[suggestion(evidence=["ex9"])]),
                           SuggestionSet(suggestions=[suggestion()]))
    rec = await recommend.recommend(done_job.video, done_job.examples, "cooking")
    assert rec.source == "llm_retry" and len(prompts) == 2
    assert "evidence id ex9 does not exist" in prompts[1]


async def test_two_bad_answers_fall_back_to_the_template(monkeypatch, done_job):
    bad = SuggestionSet(suggestions=[suggestion(keys=["m.invented"])])
    scripted_llm(monkeypatch, bad, bad)
    rec = await recommend.recommend(done_job.video, done_job.examples, "cooking")
    assert rec.source == "template" and len(rec.suggestions) == 1
    kept, _ = validate.validate(SuggestionSet(suggestions=rec.suggestions), done_job.video, done_job.examples)
    assert kept == rec.suggestions


async def test_gemini_down_falls_back_to_the_template(monkeypatch, done_job):
    scripted_llm(monkeypatch, llm_client.LLMError("down"), llm_client.LLMError("down"))
    rec = await recommend.recommend(done_job.video, done_job.examples, "cooking")
    assert rec.source == "template"


async def test_no_accessible_examples_means_no_card_and_no_llm_call(monkeypatch, done_job):
    prompts = scripted_llm(monkeypatch)
    for e in done_job.examples:
        e.access_status = "login_wall"
    rec = await recommend.recommend(done_job.video, done_job.examples, "cooking")
    assert rec.source == "insufficient_evidence" and rec.suggestions == [] and prompts == []


def test_template_follows_prompts_md_rule_1(done_job):
    s = recommend.template_suggestion(done_job.video, done_job.examples)  # payoff at 6.2 s >= 3 s
    assert "m.payoff_at_s" in s.measurement_keys and s.evidence_ids[0] == "ex1"


def test_prompt_lists_measurements_and_accessible_examples(done_job):
    done_job.examples[2].access_status = "blocked"
    prompt = recommend.build_prompt(done_job.video, done_job.examples, "cooking")
    assert "m.payoff_at_s = 6.2 (estimated" in prompt
    assert "ex1: @mock_kitchen_a" in prompt and "3.1x" in prompt
    assert "ex3" not in prompt
    for word in ("viral", "guarantee", "algorithm"):
        assert word in prompt.lower()  # the rules name the banned words
