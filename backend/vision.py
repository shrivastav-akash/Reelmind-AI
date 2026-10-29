"""Vision step: Gemini looks at the sampled frames. BUILT ON FRIDAY (task N1).

Called by jobs.py after video.measure(). Fills the judgement fields of
VideoMeasurements (text_overlay_first_3s, opening_description, payoff_at_s,
payoff_reason); these are labelled "estimated" in the UI. The prompt draft is
docs/prompts.md §1. "Done" is defined by tests/test_vision.py.
"""

from __future__ import annotations

from backend.models import VideoMeasurements
from backend.video import Frame, Word

# A payoff time must sit on (or within this many seconds of) a frame we actually sent.
FRAME_TOLERANCE_S = 0.3


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
    raise NotImplementedError("N1: built on Friday")
