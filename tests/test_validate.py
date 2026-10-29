import pytest

from backend import validate
from backend.models import Experiment, Suggestion, SuggestionSet


def suggestion(**over) -> Suggestion:
    base = dict(
        observation="The payoff arrives at ~6.2 s (m.payoff_at_s).",
        measurement_keys=["m.payoff_at_s"],
        evidence_ids=["ex1"],
        evidence_summary="Pattern in 1 example: ex1 (3.1x) names the dish first.",
        hypothesis="Opening on the dish may hold viewers.",
        experiment=Experiment(cut_a="As is", cut_b="Start on the dish", measure="3-second hold"),
    )
    return Suggestion(**(base | over))


def run(done_job, *suggestions):
    return validate.validate(SuggestionSet(suggestions=list(suggestions)), done_job.video, done_job.examples)


def test_grounded_suggestion_is_kept(done_job):
    kept, notes = run(done_job, suggestion())
    assert len(kept) == 1 and notes[0].dropped is False


@pytest.mark.parametrize(
    "over, reason",
    [
        ({"measurement_keys": []}, "cites no measurement key"),
        ({"measurement_keys": ["m.made_up"]}, "measurement m.made_up does not exist"),
        ({"evidence_ids": []}, "cites no example"),
        ({"evidence_ids": ["ex9"]}, "evidence id ex9 does not exist"),
        ({"observation": "Your opening is slow."}, "observation quotes no measured number"),
        ({"hypothesis": "This will go viral."}, "uses banned words: viral"),
        ({"evidence_summary": "The Algorithm loves it"}, "uses banned words: algorithm"),
        ({"hypothesis": "You will get more views, guaranteed"}, "uses banned words: guaranteed, will get"),
    ],
)
def test_each_rule_drops_the_suggestion(done_job, over, reason):
    kept, notes = run(done_job, suggestion(**over))
    assert kept == []
    assert reason in notes[0].reasons


def test_inaccessible_example_cannot_be_cited(done_job):
    done_job.examples[0].access_status = "login_wall"
    kept, notes = run(done_job, suggestion())
    assert kept == [] and "evidence ex1 was not accessible (login_wall)" in notes[0].reasons


def test_observation_may_quote_a_text_measurement_by_key(done_job):
    s = suggestion(observation="Your first words are a list of steps (m.words_first_3s).", measurement_keys=["m.words_first_3s"])
    assert run(done_job, s)[0] == [s]


def test_mixed_answer_keeps_only_good_ones(done_job):
    kept, notes = run(done_job, suggestion(evidence_ids=["ex7"]), suggestion())
    assert len(kept) == 1 and [n.dropped for n in notes] == [True, False]
    assert validate.retry_reasons(notes) == ["suggestion 1: evidence id ex7 does not exist"]


def test_has_citable_evidence(done_job):
    assert validate.has_citable_evidence(done_job.examples)
    for e in done_job.examples:
        e.access_status = "blocked"
    assert not validate.has_citable_evidence(done_job.examples)


def test_banned_words_are_whole_words():
    assert validate.banned_words("Virality and algorithms") == ["virality", "algorithms"]
    assert validate.banned_words("A secretly great curry") == ["secretly"]
    assert validate.banned_words("Survival guide") == []
