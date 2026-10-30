"""Vision step: Gemini looks at the sampled frames. BUILT ON FRIDAY (task N1).

Called by jobs.py after video.measure(). Fills the judgement fields of
VideoMeasurements (text_overlay_first_3s, opening_description, payoff_at_s,
payoff_reason); these are labelled "estimated" in the UI. The prompt draft is
docs/prompts.md §1. "Done" is defined by tests/test_vision.py.
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel

from backend import llm_client
from backend.models import VideoMeasurements, VisionResult
from backend.report_models import CoverNotes, CreatorReport, ReelStat
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

COVER_TIMEOUT_S = 5.0
COVER_MAX_BYTES = 4 * 1024 * 1024
COVER_TYPES = {"image/jpeg", "image/png", "image/webp"}
COVER_HOSTS = ("cdninstagram.com", "fbcdn.net")


class CoverReading(BaseModel):
    reel_id: str
    notes: CoverNotes


class CoverReadings(BaseModel):
    covers: list[CoverReading]


COVER_PROMPT = """Describe only visible details in each public Instagram Reel cover image.
For every image, return its exact Reel id with:
- text_on_cover: visible words copied exactly, or null if there is no readable text
- face: true only when a person's face is visible, false when no face is visible, null if unclear
- setting: a short literal description of the visible setting
- style: a short description of the visible framing, colour, or presentation
Do not infer performance, audience, recipe quality, or anything outside the image. These are visual estimates.
Return one item per image, using the ids shown in the labels."""


def _cover_url_reason(url: str) -> str | None:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        valid_host = any(host == suffix or host.endswith(f".{suffix}") for suffix in COVER_HOSTS)
        if parsed.scheme != "https" or not valid_host or parsed.username or parsed.password or parsed.port not in (None, 443):
            return "Cover URL is not a public Instagram image URL"
    except ValueError:
        return "Cover URL is not a valid public Instagram image URL"
    return None


async def _download_cover(url: str) -> tuple[str, bytes]:
    """Read bounded image bytes from Instagram's CDN only; never follow redirects off-domain."""
    reason = _cover_url_reason(url)
    if reason:
        raise ValueError(reason)
    async with httpx.AsyncClient(timeout=COVER_TIMEOUT_S, follow_redirects=False) as client:
        async with client.stream("GET", url) as response:
            if response.status_code < 200 or response.status_code >= 300:
                raise ValueError(f"Cover image request returned HTTP {response.status_code}")
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type not in COVER_TYPES:
                raise ValueError("Public page did not return a supported image")
            length = response.headers.get("content-length")
            if length and int(length) > COVER_MAX_BYTES:
                raise ValueError("Cover image is over 4 MB")
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > COVER_MAX_BYTES:
                    raise ValueError("Cover image is over 4 MB")
    return content_type, bytes(data)


def _covers_to_analyse(report: CreatorReport, also: list[ReelStat]) -> list[ReelStat]:
    """Choose top and bottom performers by measured ratio; explicit Reel-report covers always join."""
    ranked = [r for r in report.reels if r.access_status == "accessible" and r.cover_url and r.ratio_vs_median is not None]
    ranked.sort(key=lambda r: (r.ratio_vs_median, r.id))
    chosen_ids = {r.id for r in ranked[:3] + ranked[-3:]}
    chosen_ids.update(r.id for r in also if r.access_status == "accessible" and r.cover_url)
    for reel in report.reels:
        if reel.id in chosen_ids:
            reel.null_reasons.pop("cover_notes", None)
        elif reel.cover_url and reel.access_status == "accessible":
            reel.cover_notes = None
            reel.null_reasons["cover_notes"] = (
                "A creator median is needed to rank covers" if reel.ratio_vs_median is None
                else "Only the three highest and lowest ratio covers are analysed"
            )
    return [r for r in [*report.reels, *also] if r.id in chosen_ids]


async def analyse_covers(report: CreatorReport, also: list[ReelStat] = ()) -> None:
    """Fill estimated cover notes on top/bottom creator Reels and explicitly requested Reels.

    Direct downloads are limited to the public Instagram image CDNs and bounded by size/time;
    cover failures remain local to the Reel so the rest of the report can finish.
    """
    selected = _covers_to_analyse(report, list(also))
    if not selected:
        return

    semaphore = asyncio.Semaphore(3)

    async def load(reel: ReelStat) -> tuple[ReelStat, tuple[str, bytes] | None]:
        async with semaphore:
            try:
                mime, image = await _download_cover(reel.cover_url or "")
                return reel, (mime, image)
            except (httpx.HTTPError, ValueError) as exc:
                reel.cover_notes = None
                reel.null_reasons["cover_notes"] = f"Cover couldn't be analysed: {exc}"
                return reel, None

    loaded = await asyncio.gather(*(load(reel) for reel in selected))
    images = [(f"Reel {reel.id}", data[1], data[0]) for reel, data in loaded if data]
    if not images:
        return
    ids = {label.removeprefix("Reel ") for label, _, _ in images}
    prompt = COVER_PROMPT
    try:
        answer = await llm_client.generate_json(prompt, CoverReadings, images=images)
    except Exception as exc:  # Cover notes are optional; preserve the rest of the report on Gemini failures.
        for reel, data in loaded:
            if data:
                reel.cover_notes = None
                reel.null_reasons["cover_notes"] = f"Cover analysis failed: {exc}"
        return

    by_id = {r.id: r for r, data in loaded if data}
    seen: set[str] = set()
    for item in answer.covers:
        reel = by_id.get(item.reel_id)
        if reel is None or item.reel_id in seen:
            continue
        reel.cover_notes = item.notes
        reel.null_reasons.pop("cover_notes", None)
        seen.add(item.reel_id)
    for reel_id in ids - seen:
        by_id[reel_id].cover_notes = None
        by_id[reel_id].null_reasons["cover_notes"] = "Gemini did not return notes for this cover"


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
