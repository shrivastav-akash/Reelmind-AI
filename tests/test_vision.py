"""Defines "done" for vision.py (Fri task N1). Fails with NotImplementedError until built."""


import pytest

from backend import llm_client, vision
from backend.models import VisionResult
from backend.video import Frame, Word

# Built on Friday: run with `pytest -m friday`. Delete this line once the file passes.
pytestmark = pytest.mark.friday


@pytest.fixture
def frames(tmp_path) -> list[Frame]:
    out = []
    for t in (0.0, 0.5, 1.0, 3.0, 16.2):
        p = tmp_path / f"f{t}.jpg"
        p.write_bytes(b"\xff\xd8fakejpeg")
        out.append(Frame(t=t, path=p))
    return out


WORDS = [Word("Today", 0.6, 0.9), Word("we", 1.0, 1.1)]


def fake_llm(monkeypatch, answer=None, error=None):
    calls = []

    async def generate_json(prompt, schema, *, images=None, temperature=0.2):
        calls.append({"prompt": prompt, "schema": schema, "images": images})
        if error:
            raise error
        return answer

    monkeypatch.setattr(llm_client, "generate_json", generate_json)
    return calls


async def test_fills_vision_fields(monkeypatch, done_job, frames):
    video = done_job.video.model_copy(update={"payoff_at_s": None, "text_overlay_first_3s": None})
    answer = VisionResult(text_overlay_first_3s="2-Minute Dahi Curry", opening_description="A title card.",
                          payoff_at_s=16.2, payoff_reason="Frame t=16.2s shows the finished curry.")
    calls = fake_llm(monkeypatch, answer)
    out = await vision.analyse_opening(video, frames, WORDS, "cooking")
    assert out.payoff_at_s == 16.2 and out.text_overlay_first_3s == "2-Minute Dahi Curry"
    assert calls[0]["schema"] is VisionResult
    assert [label for label, _ in calls[0]["images"]] == [f.label for f in frames]


async def test_payoff_time_must_match_a_frame(monkeypatch, done_job, frames):
    answer = VisionResult(text_overlay_first_3s=None, opening_description="x", payoff_at_s=9.0, payoff_reason="guess")
    fake_llm(monkeypatch, answer)
    out = await vision.analyse_opening(done_job.video, frames, WORDS, "cooking")
    assert out.payoff_at_s is None and "payoff_at_s" in out.null_reasons


async def test_gemini_failure_never_raises(monkeypatch, done_job, frames):
    fake_llm(monkeypatch, error=llm_client.LLMError("Gemini unavailable"))
    video = done_job.video.model_copy(update={"payoff_at_s": None})
    out = await vision.analyse_opening(video, frames, WORDS, "cooking")
    assert out.payoff_at_s is None and "Gemini unavailable" in out.null_reasons["payoff_at_s"]
    assert out.cut_times_s == video.cut_times_s  # measured fields untouched
