"""The frontend mocks are the UI's copy of the contract: they must stay valid Jobs."""

import pytest

from backend import validate
from backend.models import ESTIMATED_KEYS, SuggestionSet

from .conftest import load_mock


@pytest.mark.parametrize("name", ["done", "running", "failed"])
def test_mock_jobs_match_the_contract(name):
    job = load_mock(name)
    assert job.status == name
    assert job.events[0].message.startswith("MOCK DATA")  # never mistaken for a real run


def test_mock_recommendation_passes_the_real_validator(done_job):
    kept, notes = validate.validate(
        SuggestionSet(suggestions=done_job.recommendation.suggestions), done_job.video, done_job.examples
    )
    assert len(kept) == 1 and not notes[0].reasons


def test_citable_skips_empty_values_and_reasons(done_job):
    keys = done_job.video.citable()
    assert keys["m.payoff_at_s"] == 6.2
    assert "m.payoff_reason" not in keys and "m.null_reasons" not in keys
    assert ESTIMATED_KEYS <= set(keys)


def test_example_ids_are_unique(done_job):
    ids = [e.id for e in done_job.examples]
    assert len(ids) == len(set(ids))
