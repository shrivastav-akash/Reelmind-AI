"""Turn the raw spike pages in samples/raw/ (gitignored) into redacted samples/ the tests use.

    .venv/bin/python scripts/make_samples.py

Redaction: Reel pages go through instagram_parse.redact_reel_page (no comments,
commenter names, commenter links or avatars). Grid and topic pages hold only
public creator info and captions. The Agent result keeps the picks, minus numbers.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import instagram_parse as ig  # noqa: E402
from backend.tinyfish_client import FetchedPage  # noqa: E402

RAW = ROOT / "samples" / "raw"
OUT = ROOT / "samples" / "instagram"


def load(path: Path) -> FetchedPage:
    data = json.loads(path.read_text())
    return FetchedPage(**data)


def save(name: str, page: FetchedPage) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(asdict(page), ensure_ascii=False, indent=1) + "\n")


def main() -> None:
    topic = load(RAW / "topic_cooking.json")
    # Topic page: links + a short text head are enough; image links are other people's thumbnails.
    save("topic_cooking", FetchedPage(**{**asdict(topic), "text": (topic.text or "")[:600], "image_links": []}))

    for path in sorted(RAW.glob("grid_*.json")):
        page = load(path)
        save(path.stem, FetchedPage(**{**asdict(page), "image_links": []}))

    for path in sorted(RAW.glob("reel*_*.json")):
        save(path.stem, ig.redact_reel_page(load(path)))

    agent = json.loads((RAW / "agent_topic_cooking.json").read_text())
    picks = agent["result"]
    for c in picks.get("creators", []):
        c["reason_raw_had_numbers"] = bool(c.get("reason")) and any(ch.isdigit() for ch in c["reason"])
        c["reason"] = ig.clean_agent_reason(c.get("reason"))
    (OUT / "agent_topic_cooking.json").write_text(json.dumps(
        {"retrieved_at": agent["retrieved_at"], "steps": agent["steps"], "duration_s": agent["duration_s"],
         "access_status": agent["access_status"], "result": picks}, ensure_ascii=False, indent=1) + "\n")

    wall = json.loads((RAW / "agent_pov__gil.json").read_text())
    (OUT / "agent_grid_login_wall.json").write_text(json.dumps(
        {k: wall[k] for k in ("status", "result", "access_status", "status_reason", "steps", "duration_s")},
        ensure_ascii=False, indent=1) + "\n")
    print("wrote", sorted(p.name for p in OUT.glob("*.json")))


if __name__ == "__main__":
    main()
