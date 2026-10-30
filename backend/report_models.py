"""Pydantic models for the v2 reports: the contract between backend and frontend.

GET /reports/{id} returns `ReportJob` as JSON; its `result` is a `CreatorReport`,
`ReelReport` or `NichePulse` (told apart by `kind`). GET /me returns `UserPublic`.
The mocks in frontend/src/mocks/report.*.json and me.json follow these shapes and are
built by scripts/make_report_mocks.py; tests/test_report_models.py fails if they drift.

`Job` in models.py (the v1 draft analyser) is frozen, so v2 lives here and only
imports shared pieces from it. To change a shape: edit this file, rerun the mock
script, then update the UI.

Citations: every Insight cites keys from `CreatorReport.citable()` (`p.median_views`,
`pat.hook_type.question`, ...) and Reel ids (`r1..rN`; `r0` is the Reel being analysed
in a ReelReport). The validator drops any insight that cites something that isn't there.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field

from .models import AccessStatus, Event, JobStatus, StageState

ReportKind = Literal["creator", "reel", "niche"]
HookType = Literal["question", "number_list", "pov", "how_to", "warning", "story", "statement", "none"]
Dimension = Literal["hook_type", "audio", "hashtag", "keyword", "caption_length", "weekday", "cover_text"]
InsightsSource = Literal["llm", "llm_retry", "template", "insufficient_evidence"]

# Stage names per report kind, in run order. The runner sets them; the UI shows them in this order.
STAGES: dict[str, tuple[str, ...]] = {
    "creator": ("fetch", "analyse", "visuals", "insights"),
    "reel": ("reel", "creator", "visuals", "insights"),
    "niche": ("research", "patterns", "insights"),
}

WINDOW_DAYS = 7  # "the last 7 days"; the grid has no dates, so they come from each Reel page


# ---------------------------------------------------------------- one Reel


class CoverNotes(BaseModel):
    """Gemini's reading of a cover image: judgements, so the UI labels them "estimated"."""

    text_on_cover: str | None
    face: bool | None
    setting: str
    style: str


class ReelStat(BaseModel):
    """One public Reel. Grid numbers win over the page's rounded ones (see instagram_parse)."""

    id: str  # r1..rN in a creator report, r0 for the Reel under analysis
    source_url: str
    retrieved_at: datetime
    access_status: AccessStatus
    status_reason: str | None = None  # why the Reel page couldn't be read; such a Reel can't be cited
    handle: str | None = None  # set in Niche Pulse, where Reels come from many creators
    pinned: bool = False
    posted_date: date | None = None
    in_window: bool = False  # posted in the last WINDOW_DAYS days
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    ratio_vs_median: float | None = None  # views / the creator's median views
    caption: str | None = None
    hook_line: str | None = None  # the caption's first line: the written hook
    hook_type: HookType | None = None
    hashtags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    caption_chars: int | None = None
    has_cta: bool | None = None
    audio_label: str | None = None
    original_audio: bool | None = None
    cover_url: str | None = None
    cover_notes: CoverNotes | None = None
    null_reasons: dict[str, str] = Field(default_factory=dict)  # field -> why it is None


# ---------------------------------------------------------------- what's working


class PatternRow(BaseModel):
    """One row of a "what's working" table, e.g. hook_type = question in 3 Reels, median 4.1x."""

    dimension: Dimension
    value: str
    reel_ids: list[str]
    median_ratio: float | None  # median views/median of these Reels; None when views are missing
    in_top: int  # how many of these Reels are in the creator's top third by ratio
    in_bottom: int

    @property
    def key(self) -> str:
        return f"pat.{self.dimension}.{self.value}"


class Insight(BaseModel):
    kind: Literal["working", "not_working", "try_next"]
    claim: str
    keys: list[str]  # from CreatorReport.citable()
    reel_ids: list[str]


class ComparisonRow(BaseModel):
    """Reel report: this Reel next to its creator's usual, e.g. "Hook type: question vs statement"."""

    label: str
    this_reel: str | None
    creator_usual: str | None
    keys: list[str] = Field(default_factory=list)
    note: str | None = None


# ---------------------------------------------------------------- reports


class ProfileStats(BaseModel):
    handle: str
    profile_url: str
    followers: int | None = None
    following: int | None = None
    posts: int | None = None
    reels_read: int = 0
    pinned_skipped: int = 0  # pinned Reels are old hits, left out of the median
    median_views: int | None = None
    reels_in_window: int = 0
    posts_per_week: float | None = None
    median_engagement: float | None = None  # median of (likes + comments) / views
    window_days: int = WINDOW_DAYS
    window_note: str | None = None  # e.g. "2 Reels in the last 7 days; the baseline uses all 12"
    access_status: AccessStatus = "accessible"
    status_reason: str | None = None


class CreatorReport(BaseModel):
    kind: Literal["creator"] = "creator"
    profile: ProfileStats
    reels: list[ReelStat] = Field(default_factory=list)
    patterns: list[PatternRow] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    insights_source: InsightsSource = "insufficient_evidence"
    null_reasons: dict[str, str] = Field(default_factory=dict)  # e.g. "video_length": "not on public pages"

    def citable(self) -> dict[str, Any]:
        """Keys an insight may cite, only for values we actually have."""
        skip = {"handle", "profile_url", "window_note", "access_status", "status_reason", "window_days"}
        keys = {f"p.{k}": v for k, v in self.profile.model_dump().items() if k not in skip and v is not None}
        keys.update({p.key: p.median_ratio for p in self.patterns})
        return keys

    def reel_ids(self) -> set[str]:
        return {r.id for r in self.reels}


class ReelReport(BaseModel):
    kind: Literal["reel"] = "reel"
    reel: ReelStat  # id "r0"; left out of the creator's median
    creator: CreatorReport
    comparison: list[ComparisonRow] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    insights_source: InsightsSource = "insufficient_evidence"


class WebSignal(BaseModel):
    """A TinyFish Search hit about the niche: context, never a number we quote as ours."""

    title: str
    url: str
    snippet: str | None = None
    retrieved_at: datetime


class NichePulse(BaseModel):
    kind: Literal["niche"] = "niche"
    keywords: list[str]
    run_date: date
    creators_read: int = 0
    reels: list[ReelStat] = Field(default_factory=list)  # the outliers, each with `handle`
    patterns: list[PatternRow] = Field(default_factory=list)
    web: list[WebSignal] = Field(default_factory=list)
    previous_run_date: date | None = None
    since_last_run: list[str] = Field(default_factory=list)  # empty on a first run
    insights: list[Insight] = Field(default_factory=list)
    insights_source: InsightsSource = "insufficient_evidence"
    null_reasons: dict[str, str] = Field(default_factory=dict)

    def citable(self) -> dict[str, Any]:
        return {p.key: p.median_ratio for p in self.patterns}

    def reel_ids(self) -> set[str]:
        return {r.id for r in self.reels}


ReportResult = Annotated[Union[CreatorReport, ReelReport, NichePulse], Field(discriminator="kind")]


class ReportJob(BaseModel):
    id: str
    kind: ReportKind
    status: JobStatus = "queued"
    created_at: datetime
    input: dict[str, Any]  # {"handle_or_url": ...} | {"url": ...} | {"keywords": [...]}
    owner_id: int | None = None  # set when a signed-in user's own report
    replay: bool = False
    replay_recorded_at: datetime | None = None
    stages: dict[str, StageState] = Field(default_factory=dict)  # names from STAGES[kind]
    events: list[Event] = Field(default_factory=list)
    result: ReportResult | None = None
    error: str | None = None


# ---------------------------------------------------------------- request bodies


class CreatorReportRequest(BaseModel):
    handle_or_url: str


class ReelReportRequest(BaseModel):
    url: str


class NicheReportRequest(BaseModel):
    keywords: list[str]  # 1-3; each goes through instagram_parse.normalise_topic


# ---------------------------------------------------------------- accounts + assistant


class SignupRequest(BaseModel):
    email: str
    password: str  # at least 8 characters; never logged or returned
    instagram_url: str  # profile URL or @handle -> instagram_parse.handle_from_url


class LoginRequest(BaseModel):
    email: str
    password: str


class UserPublic(BaseModel):
    """GET /me. Never includes the password hash or session tokens."""

    id: int
    email: str
    ig_handle: str
    profile_url: str
    created_at: datetime
    latest_report_id: str | None = None


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str


class AssistantRequest(BaseModel):
    message: str
    history: list[ChatTurn] = Field(default_factory=list)  # the last 6 turns at most


class AssistantReply(BaseModel):
    """Gemini response_schema for assistant.py, and what POST /assistant returns."""

    answer: str
    keys: list[str]  # from the user's CreatorReport.citable()
    reel_ids: list[str]
    follow_ups: list[str]
