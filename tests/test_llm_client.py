"""llm_client.generate_json when Gemini misbehaves: every failure becomes an LLMError
the callers can fall back on (vision: empty fields; recommend: template card)."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from backend import llm_client
from backend.models import VisionResult

ANSWER = '{"text_overlay_first_3s": null, "opening_description": "x", "payoff_at_s": null, "payoff_reason": "y"}'


def fake_gemini(monkeypatch, *behaviours):
    """Each call takes the next behaviour: a JSON string to answer, an exception, or "hang"."""
    calls = []
    queue = list(behaviours)

    async def generate_content(model, contents, config):
        calls.append(model)
        nxt = queue.pop(0)
        if nxt == "hang":
            await asyncio.sleep(60)
        if isinstance(nxt, Exception):
            raise nxt
        return SimpleNamespace(text=nxt)

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    monkeypatch.setattr(llm_client.genai, "Client", lambda api_key: client)
    return calls


async def test_a_hung_call_times_out_and_tries_the_fallback(isolated, monkeypatch):
    monkeypatch.setattr(llm_client, "settings", replace(isolated, llm_timeout_s=0.05))
    calls = fake_gemini(monkeypatch, "hang", ANSWER)
    out = await llm_client.generate_json("p", VisionResult)
    assert out.opening_description == "x" and len(calls) == 2


async def test_both_models_hanging_is_an_llm_error(isolated, monkeypatch):
    monkeypatch.setattr(llm_client, "settings", replace(isolated, llm_timeout_s=0.05))
    fake_gemini(monkeypatch, "hang", "hang")
    with pytest.raises(llm_client.LLMError, match="no answer within"):
        await llm_client.generate_json("p", VisionResult)


async def test_wifi_drop_is_an_llm_error_not_a_crash(isolated, monkeypatch):
    fake_gemini(monkeypatch, httpx.ConnectError("no route"), httpx.ReadTimeout("slow"))
    with pytest.raises(llm_client.LLMError, match="network error"):
        await llm_client.generate_json("p", VisionResult)
