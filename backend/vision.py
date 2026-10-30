"""Vision step: Gemini looks at the sampled frames. BUILT ON FRIDAY (task N1).

Called by jobs.py after video.measure(). Fills the judgement fields of
VideoMeasurements (text_overlay_first_3s, opening_description, payoff_at_s,
payoff_reason); these are labelled "estimated" in the UI. The prompt draft is
docs/prompts.md §1. "Done" is defined by tests/test_vision.py.
"""

from __future__ import annotations

from backend import llm_client
from backend.models import VideoMeasurements, VisionResult
from backend.video import Frame, Word

# A payoff time must sit on (or within this many seconds of) a frame we actually sent.
FRAME_TOLERANCE_S = 0.3
VISION_FIELDS = ("text_overlay_first_3s", "opening_description", "payoff_at_s", "payoff_reason")

# docs/prompts.md §1.
PROMPT = """You are measuring the opening of a short vertical video: an unposted Instagram Reel draft.
You get frames with their timestamps, and the transcript with each word's start time.
Return JSON matching the schema.

- text_overlay_first_3s: the on-screen text visible in frames from 0 to 3 s, copied exactly. null if there is none.
- opening_description: one sentence describing what a viewer sees in the first 2 seconds. Describe; don't judge.
- payoff_at_s: the timestamp of the first frame that shows the result or payoff (e.g. the finished dish, the final look, the answer). Use only the timestamps given. null if no frame shows a payoff.
- payoff_reason: one sentence naming the frame and what in it is the payoff, or why none was found.

Rules: only describe what is in the frames and transcript. Don't guess about moments you have no frame for. Don't give advice.

Topic: {topic}
Transcript (word: start time): {word_list}"""


def build_prompt(words: list[Word], topic: str) -> str:
    word_list = ", ".join(f"{w.text}: {w.start:g}" for w in words) if words else "(no speech in the draft)"
    return PROMPT.format(topic=topic, word_list=word_list)


async def analyse_opening(
    video: VideoMeasurements, frames: list[Frame], words: list[Word], topic: str
) -> VideoMeasurements:
    """Return a copy of `video` with the four vision fields filled.

    - Send the prompt plus each frame as (frame.label, jpeg bytes) through
      llm_client.generate_json(..., VisionResult). Call it through the module
      (`llm_client.generate_json`) so tests can swap it.
    - If payoff_at_s isn't within FRAME_TOLERANCE_S of a frame we sent, set it to
      None with null_reasons["payoff_at_s"] = "Model named a time we sent no frame for".
    - On LLMError: leave the fields None, put the reason in null_reasons, never raise.
    """
    reasons = {k: v for k, v in video.null_reasons.items() if k not in VISION_FIELDS}
    if not frames:
        reasons["payoff_at_s"] = "No frames to look at"
        return video.model_copy(update={**dict.fromkeys(VISION_FIELDS), "null_reasons": reasons})

    images = [(f.label, f.path.read_bytes()) for f in frames]
    try:
        answer = await llm_client.generate_json(build_prompt(words, topic), VisionResult, images=images)
    except llm_client.LLMError as exc:
        for field in ("text_overlay_first_3s", "opening_description", "payoff_at_s"):
            reasons[field] = f"Vision step failed: {exc}"
        return video.model_copy(update={**dict.fromkeys(VISION_FIELDS), "null_reasons": reasons})

    payoff, payoff_reason = answer.payoff_at_s, answer.payoff_reason
    if payoff is not None and not any(abs(payoff - f.t) <= FRAME_TOLERANCE_S for f in frames):
        payoff, payoff_reason = None, None
        reasons["payoff_at_s"] = "Model named a time we sent no frame for"
    elif payoff is None:
        reasons["payoff_at_s"] = answer.payoff_reason or "No frame shows a payoff"
    if not answer.text_overlay_first_3s:
        reasons["text_overlay_first_3s"] = "No on-screen text seen in the first 3 s"
    return video.model_copy(update={
        "text_overlay_first_3s": answer.text_overlay_first_3s or None,
        "opening_description": answer.opening_description or None,
        "payoff_at_s": payoff,
        "payoff_reason": payoff_reason,
        "null_reasons": reasons,
    })
