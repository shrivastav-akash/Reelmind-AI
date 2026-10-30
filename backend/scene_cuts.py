"""Scene-cut detection, run as its own process: `python -m backend.scene_cuts <video>`.

Why a separate process: PySceneDetect needs OpenCV, faster-whisper needs PyAV,
and on macOS both bundle libavdevice. Loading both into the backend process
triggers an objc "implemented in both ... may cause mysterious crashes"
warning. video.detect_cuts() calls this module via subprocess so the two
libraries never share a process. Prints a JSON list of cut times in seconds.
"""

import json
import sys

from scenedetect import ContentDetector, detect


def cut_times(path: str, threshold: float = 27.0) -> list[float]:
    scenes = detect(path, ContentDetector(threshold=threshold))
    # Each scene after the first starts at a cut.
    return [round(start.seconds, 2) for start, _ in scenes[1:]]


if __name__ == "__main__":
    print(json.dumps(cut_times(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 27.0)))
