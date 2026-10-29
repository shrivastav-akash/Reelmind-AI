"""The grounded recommendation. BUILT ON FRIDAY (tasks N3, N4).

Called by jobs.py once both streams finish. One Gemini call turns our
measurements + the accessible outlier examples into 1-3 suggestions; then
validate.py decides what may be shown:

    LLM answer --validate--> shown (source="llm")
        | nothing passed
        v
    regenerate once with the reasons --validate--> shown (source="llm_retry")
        | nothing passed (or Gemini down)
        v
    template_suggestion() (source="template")
        | no accessible examples at all
        v
    insufficient_evidence: no card, just the breakdown and statuses

Prompt drafts: docs/prompts.md §2-§4. "Done" is defined by tests/test_recommend.py.
"""

from __future__ import annotations

from backend.models import Example, Recommendation, Suggestion, VideoMeasurements


def build_prompt(video: VideoMeasurements, examples: list[Example], topic: str, retry_reasons: list[str] | None = None) -> str:
    """docs/prompts.md §2 (plus §3 when retry_reasons is given).

    MEASUREMENTS: one line per video.citable() key, estimated ones marked
    "(estimated: <payoff_reason>)". EXAMPLES: accessible ones only, e.g.
    'ex1: @handle · 3.1x their median (412000 views vs 133000) · posted 2026-10-24 · audio: Original audio'
    followed by the hook line and caption length.
    """
    raise NotImplementedError("N3: built on Friday")


def template_suggestion(video: VideoMeasurements, examples: list[Example]) -> Suggestion | None:
    """docs/prompts.md §4: deterministic fallback, no LLM. Cites real keys and the top
    accessible examples by ratio (max 3). None when there is no accessible example.
    Must itself pass validate.validate().
    """
    raise NotImplementedError("N4: built on Friday")


async def recommend(video: VideoMeasurements, examples: list[Example], topic: str) -> Recommendation:
    """The ladder in the module docstring. Calls Gemini through the module
    (`llm_client.generate_json(..., SuggestionSet)`) so tests can swap it; never raises.
    """
    raise NotImplementedError("N3: built on Friday")
