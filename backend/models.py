"""Pydantic models: the single contract between backend and frontend.

GET /jobs/{id} returns `Job` as JSON. The frontend (useJob.js) and the mock
jobs in samples/job.*.json follow this shape exactly. To change it: edit this
file first, then the mock jobs, then the UI. tests/test_models.py fails if the
mocks drift from this file.

Also here: the shapes we ask external services for (`AgentGrid` from the
TinyFish Agent, `VisionResult` and `SuggestionSet` from Gemini), so every
external payload is validated before we trust it.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

AccessStatus = Literal["accessible", "login_wall", "blocked", "not_found", "timeout"]
Method = Literal["fetch", "agent"]
StageStatus = Literal["pending", "running", "done", "failed", "skipped"]
JobStatus = Literal["queued", "running", "done", "failed"]


# ---------------------------------------------------------------- job state


class StageState(BaseModel):
    status: StageStatus = "pending"
    reason: str | None = None  # shown in the UI when failed or skipped


class Stages(BaseModel):
    video: StageState = Field(default_factory=StageState)
    scout: StageState = Field(default_factory=StageState)
    recommend: StageState = Field(default_factory=StageState)


class Event(BaseModel):
    """One line in the live panel. `message` is shown verbatim, so write it for humans."""

    t: float  # seconds since the job started
    source: Literal["video", "scout", "llm", "system"]
    kind: Literal["progress", "streaming_url", "creator", "outlier", "error", "info"]
    message: str
    data: dict[str, Any] | None = None  # e.g. {"handle": "...", "url": "..."}


# ---------------------------------------------------------------- video stream


class VideoMeasurements(BaseModel):
    """What we measured in the draft. The LLM cites these as `m.<field>`."""

    duration_s: float
    cut_times_s: list[float]
    cuts_first_3s: int
    avg_shot_length_s: float
    transcript: str
    first_word_at_s: float | None  # None when there is no speech
    words_first_3s: str
    # Filled by vision.py (Gemini): judgements, not measurements. The UI labels them "estimated".
    text_overlay_first_3s: str | None = None
    opening_description: str | None = None
    payoff_at_s: float | None = None
    payoff_reason: str | None = None
    null_reasons: dict[str, str] = Field(default_factory=dict)

    def citable(self) -> dict[str, Any]:
        """Keys the LLM may cite (`m.duration_s`, ...), only for values we actually have."""
        skip = {"null_reasons", "payoff_reason"}
        return {f"m.{k}": v for k, v in self.model_dump().items() if k not in skip and v not in (None, "", [])}


# Keys whose values come from the vision model, so the UI must say "estimated".
ESTIMATED_KEYS = frozenset({"m.text_overlay_first_3s", "m.opening_description", "m.payoff_at_s"})


class VisionResult(BaseModel):
    """Gemini response_schema for vision.py."""

    text_overlay_first_3s: str | None
    opening_description: str
    payoff_at_s: float | None
    payoff_reason: str


# ---------------------------------------------------------------- niche scout


class Creator(BaseModel):
    """One creator Niche Scout looked at. Drives the per-creator rows in the live panel."""

    handle: str
    reels_url: str
    status: Literal["pending", "running", "done"] = "pending"
    access_status: AccessStatus | None = None
    status_reason: str | None = None
    method: Method | None = None
    streaming_url: str | None = None  # live browser view of the Agent run, if any
    reels_read: int = 0
    median_views: int | None = None


class Example(BaseModel):
    """One outlier Reel. `id` (ex1..exN) is what the LLM must cite as evidence."""

    id: str
    source_url: str
    retrieved_at: datetime
    method: Method
    access_status: AccessStatus
    status_reason: str | None = None
    handle: str
    caption: str | None = None
    hook_line: str | None = None  # first line of the caption: the written hook
    audio_label: str | None = None
    posted_date: date | None = None
    likes: int | None = None
    comments: int | None = None
    views: int | None = None
    creator_median_views: int | None = None
    outlier_ratio: float | None = None
    cover_url: str | None = None
    null_reasons: dict[str, str] = Field(default_factory=dict)  # field -> why it is None


class GridReel(BaseModel):
    """One tile as the Agent reports it. Counts stay strings ("18.5K") until instagram_parse.to_int."""

    reel_url: str
    views: str | None = None
    likes: str | None = None
    comments: str | None = None


class AgentGrid(BaseModel):
    """Validated result of the Agent's grid-reading run (matches GRID_SCHEMA in niche_scout.py)."""

    handle: str
    blocked: bool
    blocked_reason: str | None = None
    reels: list[GridReel] = Field(default_factory=list)


# ---------------------------------------------------------------- recommendation


class Experiment(BaseModel):
    cut_a: str
    cut_b: str
    measure: str


class Suggestion(BaseModel):
    observation: str
    measurement_keys: list[str]
    evidence_ids: list[str]
    evidence_summary: str
    hypothesis: str
    experiment: Experiment


class SuggestionSet(BaseModel):
    """Gemini response_schema for recommend.py."""

    suggestions: list[Suggestion]


class ValidatorNote(BaseModel):
    suggestion_index: int
    dropped: bool
    reasons: list[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    suggestions: list[Suggestion] = Field(default_factory=list)
    source: Literal["llm", "llm_retry", "template", "insufficient_evidence"]
    validator_report: list[ValidatorNote] = Field(default_factory=list)


# ---------------------------------------------------------------- the job


class Job(BaseModel):
    id: str
    status: JobStatus = "queued"
    created_at: datetime
    topic: str
    replay: bool = False
    replay_recorded_at: datetime | None = None
    stages: Stages = Field(default_factory=Stages)
    events: list[Event] = Field(default_factory=list)
    video: VideoMeasurements | None = None
    creators: list[Creator] = Field(default_factory=list)
    examples: list[Example] = Field(default_factory=list)
    recommendation: Recommendation | None = None
    error: str | None = None  # job-level failure, e.g. "TinyFish key or credits problem"
