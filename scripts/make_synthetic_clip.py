"""Build samples/synthetic_clip.mp4: a 20 s vertical test clip for the video pipeline.

It is NOT the demo clip (that is the team's own footage). It exists so tests
can check cuts, transcript timing and frame sampling against known answers:

- 5 solid-colour cards with hard cuts at 4, 8, 12 and 16 s
- a title card first, and the "payoff" (finished dish) only at 16 s, i.e. a deliberately late payoff
- a voice-over (macOS `say`) that starts ~1 s in

Run (macOS, once): .venv/bin/python scripts/make_synthetic_clip.py
The output is committed, so teammates don't need to run this.
"""

import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples" / "synthetic_clip.mp4"
W, H, FPS, CARD_S = 720, 1280, 30, 4

# (BGR background, BGR text, lines). Order matters: the tests expect cuts at 4/8/12/16 s.
# Cards alternate dark/light AND change hue, so every cut is obvious to any detector
# (solid cards of similar brightness fooled both ffmpeg and PySceneDetect).
CARDS = [
    ((138, 58, 30), (255, 255, 255), ["2-Minute", "Dahi Curry"]),
    ((21, 204, 250), (0, 0, 0), ["Step 1:", "whisk the curd"]),
    ((52, 101, 22), (255, 255, 255), ["Step 2:", "temper spices"]),
    ((116, 186, 253), (0, 0, 0), ["Step 3:", "simmer 2 min"]),
    ((27, 27, 153), (255, 255, 255), ["The finished", "curry!"]),
]
VOICE = (
    "Today we are making a two minute dahi curry. "
    "First, whisk the curd until smooth. "
    "Then temper the spices in hot oil. "
    "Simmer everything for two minutes. "
    "And here is the finished curry."
)


def card_frame(bg, fg, lines) -> np.ndarray:
    frame = np.full((H, W, 3), bg, dtype=np.uint8)
    for i, line in enumerate(lines):
        (tw, th), _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_DUPLEX, 2.0, 4)
        y = H // 2 - 40 + i * (th + 40)
        cv2.putText(frame, line, ((W - tw) // 2, y), cv2.FONT_HERSHEY_DUPLEX, 2.0, fg, 4, cv2.LINE_AA)
    return frame


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        silent = Path(tmp) / "silent.mp4"
        writer = cv2.VideoWriter(str(silent), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
        for bg, fg, lines in CARDS:
            frame = card_frame(bg, fg, lines)
            for _ in range(FPS * CARD_S):
                writer.write(frame)
        writer.release()

        voice = Path(tmp) / "voice.aiff"
        subprocess.run(["say", "-r", "150", "-o", str(voice), VOICE], check=True)

        # Delay the voice by 1 s so first_word_at_s is ~1.0, then pad/trim to the video length.
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", str(silent), "-i", str(voice),
                "-filter_complex", "[1:a]adelay=1000:all=1,apad[a]",
                "-map", "0:v", "-map", "[a]", "-t", str(len(CARDS) * CARD_S),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
                "-c:a", "aac", str(OUT),
            ],
            check=True,
        )
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
