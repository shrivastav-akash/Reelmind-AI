"""Live test of one Gemini vision call (free tier): frames from the synthetic clip + a pydantic schema.

    .venv/bin/python scripts/spike_gemini.py [--clip samples/synthetic_clip.mp4]

Confirms the key works, the model answers with valid JSON, and how long it
takes. Not the real vision prompt: that is vision.py, built Friday from
docs/prompts.md §1. On the synthetic clip the payoff card starts at 16 s.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import llm_client, video  # noqa: E402
from backend.config import settings  # noqa: E402
from backend.models import VisionResult  # noqa: E402

PROMPT = (
    "These are frames from a short vertical cooking video, each labelled with its timestamp. "
    "Return JSON: text_overlay_first_3s = on-screen text in frames from 0 to 3 s, copied exactly (null if none); "
    "opening_description = one sentence on what the first 2 seconds show; "
    "payoff_at_s = timestamp of the first frame that shows the finished result (null if none); "
    "payoff_reason = one sentence naming that frame. Use only the timestamps given."
)


async def main(clip: Path) -> None:
    with tempfile.TemporaryDirectory() as d:
        info = video.probe(clip)
        cuts = video.detect_cuts(clip)
        frames = video.sample_frames(clip, video.frame_times(info["duration_s"], cuts), Path(d))
        images = [(f.label, f.path.read_bytes()) for f in frames]
        print(f"model={settings.llm_model} fallback={settings.llm_fallback_model} frames={[f.label for f in frames]}")
        t0 = time.monotonic()
        result = await llm_client.generate_json(PROMPT, VisionResult, images=images)
        print(f"{time.monotonic() - t0:.1f}s ->", result.model_dump_json(indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", type=Path, default=ROOT / "samples" / "synthetic_clip.mp4")
    asyncio.run(main(ap.parse_args().clip))
