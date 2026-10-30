"""Pre-download the faster-whisper models so venue Wi-Fi never blocks transcription.

Run once per laptop that will run the backend:
    .venv/bin/python scripts/download_models.py

Models land in the Hugging Face cache (~/.cache/huggingface). video.py loads
them from there; with HF_HUB_OFFLINE=1 nothing touches the network.
"""

from faster_whisper import WhisperModel

for size in ("base", "small"):
    print(f"Downloading faster-whisper '{size}'...")
    WhisperModel(size, device="cpu", compute_type="int8")
    print(f"  ok: {size}")
