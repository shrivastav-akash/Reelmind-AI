"""video.py: what happens with the files real users actually upload. IDs refer to docs/test-cases.md.

The synthetic sample has cards cut at 4/8/12/16 s and a voice starting ~1 s in. Other
clips are generated per test with ffmpeg's built-in sources (a few hundred ms each).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from backend import video

from .conftest import SAMPLES

CLIP = SAMPLES / "synthetic_clip.mp4"


def make_clip(path: Path, *, seconds: float, size: str = "360x640", fps: int = 30, audio: str | None = "silence",
              video_track: bool = True) -> Path:
    """audio: None (no track), "silence", or "tone". video_track=False makes an audio-only .mp4."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if video_track:
        cmd += ["-f", "lavfi", "-i", f"color=c=0x336699:s={size}:d={seconds}:r={fps}"]
    if audio:
        src = "anullsrc=r=44100:cl=mono" if audio == "silence" else "sine=frequency=440:sample_rate=44100"
        cmd += ["-f", "lavfi", "-i", src]
    cmd += ["-t", str(seconds)]
    if video_track:
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac"]
    subprocess.run([*cmd, str(path)], check=True)
    return path


def stream_info(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)["streams"][0]


# ---------------------------------------------------------------- frame sampling (pure)


def test_frame_times_cover_hook_window_and_cuts():
    assert video.frame_times(20.0, [4.0, 8.0]) == [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.2, 8.2]


def test_frame_times_dedupe_clamp_and_cap():  # A19: lots of fast cuts
    times = video.frame_times(3.1, [0.1, 2.9, *range(3, 20)])
    assert max(times) <= 3.05 and len(times) <= video.MAX_FRAMES
    assert all(b - a >= 0.25 for a, b in zip(times, times[1:]))


def test_frame_times_for_a_one_second_clip_stay_inside_it():  # A15
    times = video.frame_times(1.0, [])
    assert times == [0.0, 0.5, 0.95] and all(t < 1.0 for t in times)


# ---------------------------------------------------------------- guard: what gets in


def test_guard_accepts_the_sample():  # A1
    info = video.guard(CLIP)
    assert info["has_audio"] and 19.5 < info["duration_s"] < 20.5


@pytest.mark.parametrize("name", ["Draft.MOV", "draft.Mp4", "IMG_0042.mov"])
def test_guard_accepts_any_case_extension(tmp_path, name):  # A2
    f = tmp_path / name
    shutil.copy(CLIP, f)
    assert video.guard(f)["duration_s"] > 0


def test_guard_accepts_unicode_names(tmp_path):  # A3
    f = tmp_path / "my reel (final) ✨ खाना.mp4"
    shutil.copy(CLIP, f)
    assert video.guard(f)["duration_s"] > 0


def test_guard_checks_the_uploaded_name_not_the_temp_name(tmp_path):
    f = tmp_path / "upload.tmp"
    shutil.copy(CLIP, f)
    assert video.guard(f, filename="draft.mp4")["duration_s"] > 0
    with pytest.raises(video.VideoRejected, match=".mp4 or .mov"):
        video.guard(f, filename="draft.webm")


@pytest.mark.parametrize("name", ["clip.avi", "clip.mkv", "clip.gif", "clip.jpg", "clip.webm", "clip", "clip.mp4.exe"])
def test_guard_rejects_wrong_types(tmp_path, name):  # A4, A5
    f = tmp_path / name
    shutil.copy(CLIP, f)
    with pytest.raises(video.VideoRejected, match=r"Upload an \.mp4 or \.mov file"):
        video.guard(f)


@pytest.mark.parametrize("content", [b"not a video at all", b"\x89PNG\r\n\x1a\n" + b"\x00" * 200])
def test_guard_rejects_non_video(tmp_path, content):  # A6: a text file or broken image renamed to .mp4
    f = tmp_path / "clip.mp4"
    f.write_bytes(content)
    with pytest.raises(video.VideoRejected, match="isn't a readable video|looks like a photo"):
        video.guard(f)


@pytest.mark.parametrize("ext", ["png", "jpg"])
def test_guard_rejects_a_real_photo_renamed_to_mp4(tmp_path, ext):  # A6
    img = tmp_path / f"photo.{ext}"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1", str(img)], check=True)
    f = tmp_path / "photo.mp4"
    img.rename(f)
    with pytest.raises(video.VideoRejected, match="looks like a photo"):
        video.guard(f)


def test_guard_rejects_a_blink_length_clip(tmp_path):
    f = make_clip(tmp_path / "blink.mp4", seconds=0.2, audio=None)
    with pytest.raises(video.VideoRejected, match="too short"):
        video.guard(f)


def test_guard_rejects_empty_file(tmp_path):  # A7
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"")
    with pytest.raises(video.VideoRejected):
        video.guard(f)


def test_guard_rejects_truncated_video(tmp_path):  # A8: half-downloaded file
    f = tmp_path / "half.mp4"
    data = CLIP.read_bytes()
    f.write_bytes(data[: len(data) // 3])
    with pytest.raises(video.VideoRejected):
        video.guard(f)


def test_guard_rejects_big_file_before_probing(tmp_path):  # A11
    f = tmp_path / "huge.mp4"
    with open(f, "wb") as fh:
        fh.truncate(51 * 1024 * 1024)  # sparse: instant, and not even a real video
    with pytest.raises(video.VideoRejected, match="51 MB; the limit is 50 MB"):
        video.guard(f)


@pytest.mark.slow
def test_guard_rejects_long_video(tmp_path):  # A9
    f = make_clip(tmp_path / "long.mp4", seconds=75, size="64x64", fps=5, audio=None)
    with pytest.raises(video.VideoRejected, match="Video is 75 s; the limit is 60 s."):
        video.guard(f)


@pytest.mark.slow
@pytest.mark.parametrize("seconds, ok", [(60, True), (60.4, True), (61, False)])
def test_guard_accepts_exactly_60_s(tmp_path, seconds, ok):  # A10
    f = make_clip(tmp_path / "edge.mp4", seconds=seconds, size="64x64", fps=5, audio=None)
    if ok:
        assert video.guard(f)
    else:
        with pytest.raises(video.VideoRejected, match="limit is 60 s"):
            video.guard(f)


@pytest.mark.slow
def test_guard_rejects_audio_only(tmp_path):  # A12
    f = make_clip(tmp_path / "voice-note.mp4", seconds=3, audio="tone", video_track=False)
    with pytest.raises(video.VideoRejected, match="no video track"):
        video.guard(f)


# ---------------------------------------------------------------- measuring


@pytest.mark.slow
def test_measure_synthetic_clip(tmp_path):  # A1
    m, frames, words = video.measure(CLIP, tmp_path)
    assert m.cut_times_s == [4.0, 8.0, 12.0, 16.0]
    assert m.cuts_first_3s == 0 and m.avg_shot_length_s == 4.0
    assert 0.3 <= m.first_word_at_s <= 1.5  # voice is delayed 1 s; whisper/VAD timing is approximate
    assert "curry" in m.transcript.lower() and m.words_first_3s
    assert [f.label for f in frames][:6] == ["t=0.0s", "t=0.5s", "t=1.0s", "t=1.5s", "t=2.0s", "t=3.0s"]
    assert all(f.path.exists() for f in frames)
    assert isinstance(words[0].start, float)
    assert m.null_reasons == {}


@pytest.mark.slow
def test_measure_video_without_audio(tmp_path):  # A13
    f = make_clip(tmp_path / "silent-video.mp4", seconds=4, audio=None)
    m, frames, words = video.measure(f, tmp_path / "work")
    assert words == [] and m.transcript == "" and m.words_first_3s == ""
    assert m.first_word_at_s is None and m.null_reasons["first_word_at_s"] == "No audio track"


@pytest.mark.slow
def test_measure_silent_audio(tmp_path):  # A14: music-only / silence, no speech
    f = make_clip(tmp_path / "music-only.mp4", seconds=4, audio="silence")
    m, _, words = video.measure(f, tmp_path / "work")
    assert words == [] and m.first_word_at_s is None
    assert m.null_reasons["first_word_at_s"] == "No speech detected"


@pytest.mark.slow
def test_measure_one_second_clip(tmp_path):  # A15
    f = make_clip(tmp_path / "tiny.mp4", seconds=1, audio=None)
    m, frames, _ = video.measure(f, tmp_path / "work")
    assert 0.9 <= m.duration_s <= 1.1 and frames and all(fr.t < m.duration_s for fr in frames)


@pytest.mark.slow
def test_measure_no_cuts(tmp_path):  # A18: one continuous shot
    f = make_clip(tmp_path / "one-shot.mp4", seconds=5, audio=None)
    m, _, _ = video.measure(f, tmp_path / "work")
    assert m.cut_times_s == [] and m.cuts_first_3s == 0 and m.avg_shot_length_s == m.duration_s


@pytest.mark.slow
@pytest.mark.parametrize("size, expected", [("1920x1080", (1280, 720)), ("1080x1080", (720, 720)), ("2160x3840", (406, 720))])
def test_transcode_keeps_aspect_and_sets_720p_30fps(tmp_path, size, expected):  # A16, A17
    src = make_clip(tmp_path / "in.mp4", seconds=1, size=size, fps=60, audio=None)
    out = video.transcode(src, tmp_path / "out.mp4")
    info = stream_info(out)
    assert (info["width"], info["height"]) == expected and info["r_frame_rate"] == "30/1"
