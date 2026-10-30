"""Authenticated assistant answers use only the signed-in creator's citable report data."""

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend import assistant, auth, llm_client, reports
from backend.report_models import AssistantReply, NichePulse, ReportJob

from .conftest import MOCKS

CREATOR_JOB = ReportJob.model_validate(json.loads((MOCKS / "report.creator.json").read_text()))
PULSE_JOB = ReportJob.model_validate(json.loads((MOCKS / "report.niche.json").read_text()))


@pytest.fixture
def env(isolated, monkeypatch):
    from backend import main

    monkeypatch.setattr(auth, "settings", isolated, raising=False)
    monkeypatch.setattr(reports, "settings", isolated, raising=False)
    monkeypatch.setattr(main, "settings", isolated, raising=False)

    async def no_pulse(report_id):
        return None

    monkeypatch.setattr(reports, "run_niche_report", no_pulse)
    user, token = auth.signup("creator@example.com", "correct horse battery", "@mock_kitchen_a")
    creator = CREATOR_JOB.model_copy(deep=True, update={"id": "abcdef123456", "owner_id": user.id,
                                                      "created_at": datetime.now(timezone.utc)})
    reports.save_report(creator)
    auth.set_latest_report(user.id, creator.id)
    user = user.model_copy(update={"latest_report_id": creator.id})
    return isolated, user, token, monkeypatch, main


@pytest.fixture
def client(env):
    from backend.main import app

    return TestClient(app)


def fake_reply(monkeypatch, reply=None, error=None):
    calls = []

    async def generate(prompt, schema, *, images=None, temperature=0.2):
        calls.append((prompt, schema))
        if error:
            raise error
        assert schema is AssistantReply
        return reply

    monkeypatch.setattr(llm_client, "generate_json", generate)
    return calls


GOOD = AssistantReply(answer="Question hooks reached 4.45x the usual views across two Reels.",
                      keys=["pat.hook_type.question"], reel_ids=["r1", "r3"],
                      follow_ups=["Which question hook should I test next?"])


async def test_good_answer_is_returned_with_existing_citations(env):
    _, user, _, monkeypatch, _ = env
    calls = fake_reply(monkeypatch, GOOD)
    result = await assistant.answer(user, assistant.AssistantRequest(message="What is working for me?"))
    assert result == GOOD
    assert calls[0][1] is AssistantReply
    assert "p.median_views" in calls[0][0] and "r1" in calls[0][0]


@pytest.mark.parametrize("reply", [
    AssistantReply(answer="This secret will get views.", keys=["pat.hook_type.question"], reel_ids=["r1"], follow_ups=[]),
    AssistantReply(answer="Question hooks reached 4x.", keys=["made.up"], reel_ids=["r1"], follow_ups=[]),
    AssistantReply(answer="Question hooks reached 4x.", keys=["pat.hook_type.question"], reel_ids=["r99"], follow_ups=[]),
    AssistantReply(answer="", keys=["pat.hook_type.question"], reel_ids=["r1"], follow_ups=[]),
])
async def test_invalid_or_hyped_answers_fall_back_without_citations(env, reply):
    _, user, _, monkeypatch, _ = env
    fake_reply(monkeypatch, reply)
    result = await assistant.answer(user, assistant.AssistantRequest(message="What should I do?"))
    assert result.answer == assistant.FALLBACK and result.keys == result.reel_ids == []


async def test_gemini_failure_has_a_clear_fallback(env):
    _, user, _, monkeypatch, _ = env
    fake_reply(monkeypatch, error=llm_client.LLMError("Gemini unavailable"))
    result = await assistant.answer(user, assistant.AssistantRequest(message="Suggest a hook"))
    assert result.answer == assistant.FALLBACK


async def test_latest_pulse_is_scoped_to_the_account(env):
    _, user, _, monkeypatch, _ = env
    pulse = PULSE_JOB.model_copy(deep=True, update={"id": "fedcba123456", "owner_id": user.id,
                                                    "created_at": datetime.now(timezone.utc)})
    reports.save_report(pulse)
    calls = fake_reply(monkeypatch, GOOD)
    await assistant.answer(user, assistant.AssistantRequest(message="What is changing?"))
    assert "since_last_run" in calls[0][0] and "cooking" in calls[0][0]


async def test_another_users_latest_report_is_not_used(env):
    _, user, _, monkeypatch, _ = env
    other = user.model_copy(update={"id": user.id + 1})
    with pytest.raises(assistant.AssistantError, match="not ready") as exc:
        await assistant.answer(other, assistant.AssistantRequest(message="What is working?"))
    assert exc.value.status == 409
    async def should_not_call(*_args, **_kwargs):
        pytest.fail("Gemini must not run with another account's report")
    monkeypatch.setattr(llm_client, "generate_json", should_not_call)


@pytest.mark.parametrize("body, message", [
    (assistant.AssistantRequest(message=" "), "Write a question first"),
    (assistant.AssistantRequest(message="x" * (assistant.MAX_MESSAGE_CHARS + 1)), "under 1200 characters"),
    (assistant.AssistantRequest(message="help", history=[{"role": "user", "text": "x"}] * 7), "at most 6"),
])
async def test_request_size_and_empty_message_are_rejected(env, body, message):
    _, user, _, _, _ = env
    with pytest.raises(assistant.AssistantError, match=message):
        await assistant.answer(user, body)


def test_route_requires_auth_and_returns_grounded_answer(client, env):
    _, user, token, monkeypatch, _ = env
    fake_reply(monkeypatch, GOOD)
    body = {"message": "What is working?", "history": []}
    assert client.post("/assistant", json=body).status_code == 401
    response = client.post("/assistant", headers={"Authorization": f"Bearer {token}"}, json=body)
    assert response.status_code == 200
    assert response.json()["reel_ids"] == ["r1", "r3"]


def test_signed_in_niche_reports_are_owned_by_the_user(client, env):
    _, user, token, _, _ = env
    response = client.post("/reports/niche", headers={"Authorization": f"Bearer {token}"},
                           json={"keywords": ["cooking"]})
    assert response.status_code == 202
    job = reports.get_report(response.json()["report_id"])
    assert job.owner_id == user.id

