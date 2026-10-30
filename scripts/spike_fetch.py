"""Live test of TinyFish Fetch on public Instagram pages (free: Fetch never uses wallet credit).

    .venv/bin/python scripts/spike_fetch.py --topic cooking          # explore: topic page, grids, 3 Reels
    .venv/bin/python scripts/spike_fetch.py --recheck                # Fri 09:00: re-test samples/demo_creators.json

Pages go to samples/raw/ (gitignored); Reel pages are redacted before saving.
Run scripts/make_samples.py afterwards to write the samples the tests use.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import instagram_parse as ig  # noqa: E402
from backend import tinyfish_client as tf  # noqa: E402

RAW = ROOT / "samples" / "raw"


def save(name: str, page: tf.FetchedPage) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / f"{name}.json").write_text(json.dumps(asdict(page), ensure_ascii=False, indent=1))


def show(label: str, page: tf.FetchedPage, head: int = 600) -> None:
    print(f"\n=== {label}: {page.url}")
    if not page.ok:
        print(f"  ERROR: {page.error}")
        return
    print(f"  final_url: {page.final_url}\n  title: {page.title}\n  description: {(page.description or '')[:200]!r}")
    print(f"  published_date: {page.published_date}  from_cache: {page.from_cache}")
    print(f"  links: {len(page.links)}  image_links: {len(page.image_links)}  text chars: {len(page.text or '')}")
    print("  text head:\n    " + (page.text or "")[:head].replace("\n", "\n    "))


async def explore(topic: str, max_creators: int) -> None:
    print("wallet:", await tf.wallet_balance())

    [topic_page] = await tf.fetch_pages([ig.topic_url(topic)], purpose="Find creators posting Reels on this topic")
    save(f"topic_{topic}", topic_page)
    show("TOPIC", topic_page, 1500)
    handles = list(dict.fromkeys(h for h in (ig.handle_from_url(u) for u in topic_page.links) if h))
    reels = list(dict.fromkeys(c for c in (ig.canonical_reel_url(u) for u in topic_page.links) if c))
    print(f"\n  handles found: {handles[:20]}\n  reel links found: {len(reels)} e.g. {reels[:3]}")

    grids = await tf.fetch_pages([ig.reels_url(h) for h in handles[:max_creators]], purpose="Read a creator's Reels grid")
    for h, page in zip(handles, grids):
        save(f"grid_{h}", page)
        show(f"GRID @{h}", page, 1200)
        print(f"  reel links in grid: {sum(1 for u in page.links if ig.reel_shortcode(u))}")

    # Three single Reel pages, from the first grid with Reel links (else the topic page).
    first_grid = next((p for p in grids if p.ok and any(ig.reel_shortcode(u) for u in p.links)), topic_page)
    reel_urls = list(dict.fromkeys(c for c in (ig.canonical_reel_url(u) for u in first_grid.links) if c))[:3]
    for fmt in ("markdown", "html"):
        pages = await tf.fetch_pages(reel_urls, fmt=fmt, html_head=(fmt == "html"), purpose="Read one public Reel",
                                     redact=ig.redact_reel_page)  # never store comments, even locally
        for i, page in enumerate(pages):
            save(f"reel{i + 1}_{fmt}", page)
            show(f"REEL {i + 1} ({fmt})", page, 900 if fmt == "markdown" else 400)
            print("  og parse:", ig.parse_og_description(page.description))


async def recheck() -> None:
    creators = json.loads((ROOT / "samples" / "demo_creators.json").read_text())["creators"]
    print("wallet:", await tf.wallet_balance())
    pages = await tf.fetch_pages([ig.reels_url(c["handle"]) for c in creators], fallback_to_cache=False)
    for c, page in zip(creators, pages):
        links = sum(1 for u in page.links if ig.reel_shortcode(u)) if page.ok else 0
        status = "OK" if page.ok and links else ("NO REELS VISIBLE" if page.ok else f"ERROR {page.error}")
        print(f"  @{c['handle']:<28} {status:<20} reel links: {links}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="cooking")
    ap.add_argument("--max-creators", type=int, default=6)
    ap.add_argument("--recheck", action="store_true")
    args = ap.parse_args()
    asyncio.run(recheck() if args.recheck else explore(args.topic, args.max_creators))
