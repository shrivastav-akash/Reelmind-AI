"""Niche Scout: the TinyFish centrepiece. BUILT ON FRIDAY (tasks A1-A3 in docs/implementation-plan.md).

    topic -> creators -> each creator's Reels grid (Agent) -> outliers -> outlier Reel pages (Fetch)

Emits a live event at every step so judges can watch it work. Network only
through tinyfish_client; parsing and maths through instagram_parse and
outliers (both done and tested). "Done" is defined by tests/test_niche_scout.py.

The constants below (goal + schema for the Agent) are final: the spike
script scripts/spike_agent.py already uses them.

Call TinyFish through the module (`tinyfish_client.fetch_pages`,
`tinyfish_client.run_agent`) so the tests can swap in fakes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from backend import outliers
from backend.models import Creator, Example

# emit(source, kind, message, data=None) appends an Event to the job (jobs.py).
Emit = Callable[..., Awaitable[None] | None]

MAX_CREATORS = 4
MIN_CREATORS = 3
AGENT_MAX_SECONDS = 90
# Big brands skew "outliers" and their advice doesn't transfer to small creators.
MEGA_ACCOUNTS = {
    "natgeo", "tasty", "buzzfeedtasty", "gordongram", "gordonramsay", "foodnetwork", "bonappetitmag",
    "nytcooking", "instagram", "creators", "zomato", "swiggyindia", "delish", "jamieoliver",
}

GRID_GOAL = (
    "You are on the public Instagram Reels tab of @{handle}. Do not log in, do not click "
    '"Log in" or "Sign up", do not submit anything. Read the Reel tiles visible without '
    "logging in (at most 12). For each tile return the Reel URL and the view, like and "
    'comment counts exactly as shown (e.g. "18.5K"); use null for any count not shown. '
    "If a login wall or captcha blocks the page, return blocked=true with blocked_reason. "
    "Stop after reading the visible tiles."
)

GRID_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "handle": {"type": "string"},
        "blocked": {"type": "boolean"},
        "blocked_reason": {"type": "string"},
        "reels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "reel_url": {"type": "string"},
                    "views": {"type": "string"},
                    "likes": {"type": "string"},
                    "comments": {"type": "string"},
                },
                "required": ["reel_url"],
            },
        },
    },
    "required": ["handle", "blocked"],
}


async def discover_creators(topic: str, emit: Emit) -> list[str]:
    """A1. Fetch the topic page (instagram_parse.topic_url), parse it with
    instagram_parse.parse_topic_page, and keep up to MAX_CREATORS handles, skipping
    MEGA_ACCOUNTS. If fewer than MIN_CREATORS are found and samples/demo_creators.json
    lists this topic, fill from that list and emit an info event saying so.
    """
    raise NotImplementedError("A1: built on Friday")


async def read_grid(handle: str, emit: Emit) -> tuple[Creator, list[outliers.Candidate]]:
    """A2. Agent run on the creator's /reels/ tab (tinyfish_client.run_agent with GRID_GOAL
    formatted for the handle, GRID_SCHEMA, AGENT_MAX_SECONDS). Validate the result as
    models.AgentGrid, convert counts with instagram_parse.to_int, then
    outliers.score_creator. Forward Agent progress / streaming_url as events.
    If the Agent is blocked or times out, fall back to Fetch + instagram_parse.parse_grid
    (method="fetch"). A login wall is NOT retried any other way: the row says login_wall.
    The Creator row always ends with an honest access_status.
    """
    raise NotImplementedError("A2: built on Friday")


async def fetch_outlier_pages(candidates: list[outliers.Candidate], emit: Emit) -> list[Example]:
    """A3 (part). One Fetch batch for the picked outliers' Reel pages
    (redact=instagram_parse.strip_comments), instagram_parse.parse_reel_page, then build
    Examples ex1..exN carrying the candidate's views, median and ratio. A page that
    fails keeps its numbers from the grid but gets the matching access_status.
    """
    raise NotImplementedError("A3: built on Friday")


async def run_niche_scout(topic: str, emit: Emit) -> tuple[list[Creator], list[Example]]:
    """A3. discover_creators -> read_grid for every creator via asyncio.gather (the
    client's semaphore keeps it to 2 Agent runs at once) -> outliers.pick_outliers ->
    fetch_outlier_pages. Emit one "outlier" event per Example, e.g.
    "3.1x @handle's median (412K vs 133K)".
    """
    raise NotImplementedError("A3: built on Friday")
