"""Measures the draft video. Everything here is code, not AI.

Called by jobs.py (Fri) as `await asyncio.to_thread(video.measure, path, work_dir)`,
because ffmpeg, PySceneDetect and whisper all block. The one AI step for the
video (payoff time, on-screen text) is vision.py, which runs on the frames
sampled here.

Steps: guard -> transcode to 720p -> cuts -> transcript with word times -> frames.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from backend.models import VideoMeasurements

MAX_SECONDS = 60
MIN_SECONDS = 0.5
MAX_BYTES = 50 * 1024 * 1024
IMAGE_CODECS = {"png", "mjpeg", "jpeg2000", "bmp", "gif", "webp", "tiff", "heif", "hevc_image"}
ALLOWED_SUFFIXES = {".mp4", ".mov"}
FRAME_TIMES = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0)  # the hook window, plus one frame after each cut
MAX_FRAMES = 12
WHISPER_MODEL = "base"  # pre-downloaded by scripts/download_models.py; "small" is more accurate but slower


class VideoRejected(ValueError):
    """The upload breaks a rule. The message is shown to the user as-is (400)."""


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Frame:
    t: float
    path: Path

    @property
    def label(self) -> str:
        return f"t={self.t:.1f}s"


# ---------------------------------------------------------------- guard + transcode


def probe(path: Path) -> dict:
    """Duration and whether there is an audio track, via ffprobe."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise VideoRejected("This file isn't a readable video.")
    data = json.loads(out.stdout or "{}")
    streams = data.get("streams", [])
    kinds = {s.get("codec_type") for s in streams}
    if "video" not in kinds:
        raise VideoRejected("This file has no video track.")
    # ffprobe calls a photo a one-frame "video" stream: a renamed .jpg/.png must not get through.
    if all(s.get("codec_name") in IMAGE_CODECS for s in streams if s.get("codec_type") == "video"):
        raise VideoRejected("This looks like a photo, not a video.")
    duration = float(data.get("format", {}).get("duration") or 0.0)
    if duration < MIN_SECONDS:
        raise VideoRejected("This video is too short to analyse (under half a second).")
    return {"duration_s": duration, "has_audio": "audio" in kinds}


def guard(path: Path, filename: str | None = None) -> dict:
    """Reject anything outside mp4/mov, 50 MB, 60 s. Returns probe() info when OK."""
    suffix = Path(filename or path.name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise VideoRejected(f"Upload an .mp4 or .mov file (got '{suffix or 'no extension'}').")
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise VideoRejected(f"Video is {size / 1024 / 1024:.0f} MB; the limit is 50 MB.")
    info = probe(path)
    if info["duration_s"] > MAX_SECONDS + 0.5:
        raise VideoRejected(f"Video is {info['duration_s']:.0f} s; the limit is {MAX_SECONDS} s.")
    return info


def transcode(src: Path, dst: Path) -> Path:
    """720p, 30 fps H.264 + AAC, so every later step sees the same kind of file."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-vf", "scale=-2:720", "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(dst)],
        check=True,
    )
    return dst


# ---------------------------------------------------------------- measurements


def detect_cuts(path: Path) -> list[float]:
    """Cut times in seconds. Runs PySceneDetect in its own process (see scene_cuts.py for why)."""
    out = subprocess.run(
        [sys.executable, "-m", "backend.scene_cuts", str(path)],
        capture_output=True, text=True, check=True, cwd=Path(__file__).resolve().parent.parent,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


@lru_cache(maxsize=2)
def _whisper(size: str):
    # Imported here so importing video.py stays cheap (and tests that don't transcribe never load PyAV).
    from faster_whisper import WhisperModel

    return WhisperModel(size, device="cpu", compute_type="int8")


def load_audio(path: Path, sample_rate: int = 16_000):
    """Mono 16 kHz float32 samples, decoded by ffmpeg.

    We decode ourselves instead of letting faster-whisper use PyAV: faster-whisper
    1.2.1 passes `metadata_errors` to av.open(), which PyAV 19 rejects (TypeError).
    ffmpeg is already a hard requirement, so this removes a fragile dependency.
    """
    import numpy as np

    out = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(sample_rate), "-"],
        capture_output=True, check=True,
    )
    return np.frombuffer(out.stdout, dtype=np.float32)


def transcribe(path: Path, model_size: str = WHISPER_MODEL) -> list[Word]:
    """Word-level transcript. Empty list when there is no speech."""
    audio = load_audio(path)
    segments, _info = _whisper(model_size).transcribe(audio, word_timestamps=True, vad_filter=True)
    words: list[Word] = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append(Word(text=text, start=round(float(w.start), 2), end=round(float(w.end), 2)))
    return words


def frame_times(duration_s: float, cuts: list[float]) -> list[float]:
    """Hook-window frames plus one just after each cut, deduped and capped at MAX_FRAMES."""
    times: list[float] = []
    for t in sorted([*FRAME_TIMES, *(c + 0.2 for c in cuts)]):
        t = round(min(t, max(duration_s - 0.05, 0.0)), 2)
        if all(abs(t - x) >= 0.25 for x in times):
            times.append(t)
    return times[:MAX_FRAMES]


def sample_frames(path: Path, times: list[float], out_dir: Path) -> list[Frame]:
    """One JPEG per timestamp (ffmpeg seek; ~0.1 s each)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for t in times:
        dst = out_dir / f"frame_{t:05.2f}.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", str(path),
             "-frames:v", "1", "-vf", "scale=-2:512", "-q:v", "4", str(dst)],
            check=True,
        )
        if dst.exists():
            frames.append(Frame(t=t, path=dst))
    return frames


def measure(path: Path, work_dir: Path, *, transcoded: bool = False) -> tuple[VideoMeasurements, list[Frame], list[Word]]:
    """Everything code can measure. Vision fields stay None until vision.py fills them."""
    src = path if transcoded else transcode(path, work_dir / "draft_720p.mp4")
    info = probe(src)
    duration = round(info["duration_s"], 2)
    cuts = detect_cuts(src)
    words = transcribe(src) if info["has_audio"] else []
    frames = sample_frames(src, frame_times(duration, cuts), work_dir / "frames")

    null_reasons: dict[str, str] = {}
    first_word = words[0].start if words else None
    if first_word is None:
        null_reasons["first_word_at_s"] = "No speech detected" if info["has_audio"] else "No audio track"

    m = VideoMeasurements(
        duration_s=duration,
        cut_times_s=cuts,
        cuts_first_3s=sum(1 for c in cuts if c < 3.0),
        avg_shot_length_s=round(duration / (len(cuts) + 1), 2),
        transcript=" ".join(w.text for w in words),
        first_word_at_s=first_word,
        words_first_3s=" ".join(w.text for w in words if w.start < 3.0),
        null_reasons=null_reasons,
    )
    return m, frames, words
