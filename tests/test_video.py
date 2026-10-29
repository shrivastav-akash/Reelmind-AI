"""video.py on the synthetic clip (cards cut at 4/8/12/16 s, voice starts ~1 s)."""

import subprocess

import pytest

from backend import video

from .conftest import SAMPLES

CLIP = SAMPLES / "synthetic_clip.mp4"


def test_frame_times_cover_hook_window_and_cuts():
    assert video.frame_times(20.0, [4.0, 8.0]) == [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.2, 8.2]


def test_frame_times_dedupe_clamp_and_cap():
    times = video.frame_times(3.1, [0.1, 2.9, *range(3, 20)])
    assert max(times) <= 3.05 and len(times) <= video.MAX_FRAMES
    assert all(b - a >= 0.25 for a, b in zip(times, times[1:]))


def test_guard_rejects_wrong_type(tmp_path):
    f = tmp_path / "clip.avi"
    f.write_bytes(b"x")
    with pytest.raises(video.VideoRejected, match=".mp4 or .mov"):
        video.guard(f)


def test_guard_rejects_non_video(tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"not a video")
    with pytest.raises(video.VideoRejected):
        video.guard(f)


@pytest.mark.slow
def test_guard_rejects_long_video(tmp_path):
    f = tmp_path / "long.mp4"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=62:r=5", "-c:v", "libx264", str(f)],
        check=True,
    )
    with pytest.raises(video.VideoRejected, match="62 s"):
        video.guard(f)


@pytest.mark.slow
def test_guard_accepts_the_sample():
    info = video.guard(CLIP)
    assert info["has_audio"] and 19.5 < info["duration_s"] < 20.5


@pytest.mark.slow
def test_measure_synthetic_clip(tmp_path):
    m, frames, words = video.measure(CLIP, tmp_path)
    assert m.cut_times_s == [4.0, 8.0, 12.0, 16.0]
    assert m.cuts_first_3s == 0 and m.avg_shot_length_s == 4.0
    assert 0.3 <= m.first_word_at_s <= 1.5  # voice is delayed 1 s; whisper/VAD timing is approximate
    assert "curry" in m.transcript.lower() and m.words_first_3s
    assert [f.label for f in frames][:6] == ["t=0.0s", "t=0.5s", "t=1.0s", "t=1.5s", "t=2.0s", "t=3.0s"]
    assert all(f.path.exists() for f in frames)
    assert isinstance(words[0].start, float)
