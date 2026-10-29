"""Live test of one TinyFish Agent run. COSTS CREDITS (~$0.016/step; ~$0.05 per run on 29 Oct).

    .venv/bin/python scripts/spike_agent.py --topic cooking           # the job it does on Friday
    .venv/bin/python scripts/spike_agent.py --grid-handle pov__gil    # shows the login wall on /reels/

Prints every event with timings, the step count and cost, checks whether the live
browser URL can be embedded in an iframe, and saves the raw outcome to samples/raw/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import instagram_parse as ig  # noqa: E402
from backend import tinyfish_client as tf  # noqa: E402
from backend.niche_scout import TOPIC_GOAL, TOPIC_SCHEMA  # noqa: E402

STEP_PRICE = 0.016
GRID_GOAL = (
    "You are on the public Instagram Reels tab of @{handle}. Do not log in. Read the visible Reel tiles "
    "(at most 12) and return each Reel URL with its view count as shown. If a login wall blocks the page, "
    "return blocked=true with blocked_reason."
)
GRID_SCHEMA = {
    "type": "object",
    "properties": {"blocked": {"type": "boolean"}, "blocked_reason": {"type": "string"},
                   "reels": {"type": "array", "items": {"type": "object", "properties": {
                       "reel_url": {"type": "string"}, "views": {"type": "string"}}}}},
    "required": ["blocked"],
}
checks: list[asyncio.Task] = []


async def check_embeddable(url: str) -> None:
    """Can our page show the live browser in an iframe? Look at the headers that forbid it."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as c:
            r = await c.get(url)
        xfo = r.headers.get("x-frame-options")
        csp = r.headers.get("content-security-policy", "")
        fa = next((p.strip() for p in csp.split(";") if "frame-ancestors" in p), None)
        verdict = "BLOCKED" if (xfo or (fa and "*" not in fa)) else "looks embeddable"
        print(f"  [iframe] status {r.status_code}, X-Frame-Options={xfo!r}, frame-ancestors={fa!r} -> {verdict}")
    except httpx.HTTPError as exc:
        print(f"  [iframe] check failed: {exc}")


async def main(url: str, goal: str, schema: dict, name: str, max_seconds: int) -> None:
    print("wallet before:", await tf.wallet_balance())
    t0 = time.monotonic()

    def on_event(ev: tf.AgentEvent) -> None:
        print(f"  {time.monotonic() - t0:5.1f}s  {ev.kind:<13} {ev.message}")
        if ev.streaming_url:
            checks.append(asyncio.create_task(check_embeddable(ev.streaming_url)))

    out = await tf.run_agent(url, goal, schema, on_event=on_event, max_seconds=max_seconds)
    await asyncio.gather(*checks)
    print(f"\nstatus={out.status} access={out.access_status} reason={out.status_reason}")
    print(f"steps={out.steps} duration={out.duration_s}s est. cost=${out.steps * STEP_PRICE:.3f}")
    print(json.dumps(out.result, indent=1, ensure_ascii=False)[:2000])
    raw = ROOT / "samples" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / f"agent_{name}.json").write_text(json.dumps(asdict(out), indent=1, default=str, ensure_ascii=False))
    print("wallet after:", await tf.wallet_balance())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic")
    ap.add_argument("--grid-handle")
    ap.add_argument("--max-seconds", type=int, default=75)
    a = ap.parse_args()
    if a.grid_handle:
        asyncio.run(main(ig.reels_url(a.grid_handle), GRID_GOAL.format(handle=a.grid_handle), GRID_SCHEMA,
                         a.grid_handle, a.max_seconds))
    else:
        topic = ig.normalise_topic(a.topic or "cooking")
        asyncio.run(main(ig.topic_url(topic), TOPIC_GOAL.format(topic=topic), TOPIC_SCHEMA, f"topic_{topic}", a.max_seconds))
