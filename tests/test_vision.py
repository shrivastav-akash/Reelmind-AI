"""Defines "done" for vision.py (Fri task N1). Fails with NotImplementedError until built."""


from datetime import datetime, timezone

import pytest

from backend import llm_client, vision
from backend.models import VisionResult
from backend.report_models import CoverNotes, CreatorReport, ProfileStats, ReelStat
from backend.video import Frame, Word



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


async def test_no_frames_means_no_call(monkeypatch, done_job):
    calls = fake_llm(monkeypatch, None)
    video = done_job.video.model_copy(update={"payoff_at_s": None})
    out = await vision.analyse_opening(video, [], WORDS, "cooking")
    assert calls == [] and out.payoff_at_s is None and out.null_reasons["payoff_at_s"] == "No frames to look at"


async def test_payoff_within_tolerance_of_a_frame_is_kept(monkeypatch, done_job, frames):
    answer = VisionResult(text_overlay_first_3s=None, opening_description="x", payoff_at_s=16.0, payoff_reason="near the 16.2 s frame")
    fake_llm(monkeypatch, answer)
    out = await vision.analyse_opening(done_job.video, frames, WORDS, "cooking")
    assert out.payoff_at_s == 16.0


async def test_prompt_has_topic_and_word_timings(monkeypatch, done_job, frames):
    answer = VisionResult(text_overlay_first_3s=None, opening_description="x", payoff_at_s=None, payoff_reason="no payoff frame")
    calls = fake_llm(monkeypatch, answer)
    out = await vision.analyse_opening(done_job.video, frames, WORDS, "cooking")
    assert "cooking" in calls[0]["prompt"] and "Today" in calls[0]["prompt"] and "0.6" in calls[0]["prompt"]
    assert out.payoff_at_s is None and out.payoff_reason == "no payoff frame"


async def test_draft_without_speech_still_works(monkeypatch, done_job, frames):  # A13, A14
    answer = VisionResult(text_overlay_first_3s="2-Minute Dahi Curry", opening_description="x", payoff_at_s=3.0, payoff_reason="r")
    calls = fake_llm(monkeypatch, answer)
    out = await vision.analyse_opening(done_job.video, frames, [], "cooking")
    assert out.payoff_at_s == 3.0 and "no speech" in calls[0]["prompt"].lower()


def cover_report(count=8):
    now = datetime.now(timezone.utc)
    return CreatorReport(
        profile=ProfileStats(handle="test_creator", profile_url="https://www.instagram.com/test_creator/"),
        reels=[ReelStat(
            id=f"r{n}", source_url=f"https://www.instagram.com/reel/{n:011d}/", retrieved_at=now,
            access_status="accessible", ratio_vs_median=float(n),
            cover_url=f"https://scontent.cdninstagram.com/{n}.jpg",
        ) for n in range(1, count + 1)],
    )


async def test_cover_analysis_selects_top_bottom_and_explicit_reel(monkeypatch):
    report = cover_report()
    extra = ReelStat(id="r0", source_url="https://www.instagram.com/reel/00000000000/",
                     retrieved_at=datetime.now(timezone.utc), access_status="accessible", cover_url="https://scontent.cdninstagram.com/0.jpg")

    async def download(url):
        return "image/jpeg", url.encode()

    monkeypatch.setattr(vision, "_download_cover", download)
    calls = []

    async def generate(prompt, schema, *, images=None, temperature=0.2):
        calls.append((prompt, schema, images))
        return schema(covers=[vision.CoverReading(reel_id=label.removeprefix("Reel "), notes=CoverNotes(
            text_on_cover="Recipe", face=False, setting="kitchen", style="bright")) for label, _, _ in images])

    monkeypatch.setattr(llm_client, "generate_json", generate)
    await vision.analyse_covers(report, also=[extra])

    assert calls[0][1] is vision.CoverReadings
    assert {label for label, _, _ in calls[0][2]} == {"Reel r1", "Reel r2", "Reel r3", "Reel r6", "Reel r7", "Reel r8", "Reel r0"}
    assert extra.cover_notes.text_on_cover == "Recipe"
    assert report.reels[0].cover_notes.text_on_cover == "Recipe"
    assert "Only the three highest and lowest ratio covers" in report.reels[3].null_reasons["cover_notes"]


async def test_cover_analysis_keeps_reason_when_download_fails(monkeypatch):
    report = cover_report(1)

    async def download(_url):
        raise ValueError("Public page did not return a supported image")

    monkeypatch.setattr(vision, "_download_cover", download)

    async def should_not_run(*_args, **_kwargs):
        pytest.fail("Gemini should not run without a downloaded image")

    monkeypatch.setattr(llm_client, "generate_json", should_not_run)
    await vision.analyse_covers(report)
    assert report.reels[0].cover_notes is None
    assert "supported image" in report.reels[0].null_reasons["cover_notes"]


def test_cover_download_only_allows_https_instagram_cdns():
    assert vision._cover_url_reason("http://scontent.cdninstagram.com/a.jpg")
    assert vision._cover_url_reason("https://example.com/a.jpg")
    assert vision._cover_url_reason("https://scontent.cdninstagram.com/a.jpg") is None
