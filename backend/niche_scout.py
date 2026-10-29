"""Niche Scout: the TinyFish centrepiece. BUILT ON FRIDAY (tasks A1-A3 in docs/implementation-plan.md).

Design after the 29 Oct live tests (docs/decisions.md):
- The TinyFish **Agent** gets a login wall on creators' /reels/ tabs, but reads the public
  topic page fine. So the Agent does the judgement step: it *picks* individual creators on
  the topic page while judges watch its live browser.
- TinyFish **Fetch** (free, fast) reads everything else: the topic page (in parallel, as
  the fallback), each creator's Reels grid, and the outlier Reel pages.

    topic --+-- Agent: pick <=4 creators on the topic page (live view, 75 s cap) --+
            +-- Fetch: topic page -> handles -> prefetch their grids --------------+
                                                                                   v
           creators (Agent's picks, else code's) -> grids -> outliers -> Reel pages (Fetch)

Network only through tinyfish_client, called through the module
(`tinyfish_client.fetch_pages`, `tinyfish_client.run_agent`) so tests can swap in fakes.
Parsing and maths: instagram_parse + outliers (built and tested). "Done" is defined by
tests/test_niche_scout.py, which replays the real 29 Oct #cooking pages.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from backend import outliers
from backend.instagram_parse import GridPage
from backend.models import Creator, Example

# emit(source, kind, message, data=None) appends an Event to the job (jobs.py).
Emit = Callable[..., Awaitable[None] | None]

MAX_CREATORS = 4
MIN_CREATORS = 3
PREFETCH_GRIDS = 10  # grids fetched in parallel with the Agent, so the code fallback is instant
AGENT_MAX_SECONDS = 75
MAX_FOLLOWERS_FOR_CODE_PICK = 1_000_000  # code prefers individual creators, like the Agent is asked to
MIN_TILES_WITH_VIEWS = 6
# Big brands skew "outliers" and their advice doesn't transfer to small creators.
MEGA_ACCOUNTS = {
    "natgeo", "tasty", "buzzfeedtasty", "gordongram", "gordonramsay", "foodnetwork", "bonappetitmag",
    "nytcooking", "instagram", "creators", "zomato", "swiggyindia", "delish", "jamieoliver",
}

TOPIC_GOAL = (
    "You are on Instagram's public topic page for #{topic}. Do not log in, do not click "
    '"Log in" or "Sign up", do not submit anything. Look at the Reels shown without logging in. '
    "Pick up to 4 creators whose Reels appear here, preferring individual creators over brands, "
    "media companies or very large accounts. For each, return the handle exactly as shown, the "
    "Reel URL you saw for them, and one short reason about their content style. Do not include "
    "any numbers (followers, views or likes) in the reason. If a login wall or captcha blocks "
    "the page, return blocked=true with blocked_reason. Stop after reading the visible Reels."
)

TOPIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "topic": {"type": "string"},
        "blocked": {"type": "boolean"},
        "blocked_reason": {"type": "string"},
        "creators": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "handle": {"type": "string"},
                    "reel_url": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["handle"],
            },
        },
    },
    "required": ["topic", "blocked"],
}


async def agent_pick_creators(topic: str, emit: Emit) -> list[tuple[str, str | None]] | None:
    """A1 (Agent half). tinyfish_client.run_agent(topic_url, TOPIC_GOAL, TOPIC_SCHEMA,
    max_seconds=AGENT_MAX_SECONDS, on_event=...): forward the streaming URL as a
    kind="streaming_url" event with data={"url": ...} and each progress step as
    "Agent: <purpose>". Validate with models.AgentTopicPicks. Return [(handle, clean
    reason)] with instagram_parse.clean_agent_reason, deduped case-insensitively, MEGA_ACCOUNTS
    removed, at most MAX_CREATORS. Return None (and emit why) on a wall, block, timeout or no picks.
    Never raises for Instagram problems; TinyFishAccountError propagates.
    """
    raise NotImplementedError("A1: built on Friday")


async def fetch_topic_and_grids(topic: str, emit: Emit) -> tuple[list[str], dict[str, GridPage]]:
    """A1 (Fetch half). Fetch the topic page, instagram_parse.parse_topic_page, drop
    MEGA_ACCOUNTS, then fetch up to PREFETCH_GRIDS creators' /reels/ pages in one call and
    parse each with instagram_parse.parse_grid. Returns (handles in page order, grids by handle).
    A walled or failed topic page returns ([], {}) and emits why.
    """
    raise NotImplementedError("A1: built on Friday")


def choose_creators(
    agent_picks: list[tuple[str, str | None]] | None,
    page_handles: list[str],
    grids: dict[str, GridPage],
    topic: str,
) -> list[Creator]:
    """A1 (decision). Agent's picks first: keep only handles that are on the Fetch copy of the
    topic page or have a readable grid (drops invented handles); picked_by="agent".
    If fewer than MIN_CREATORS survive (or the Agent failed), fill from page_handles whose grid has
    >= MIN_TILES_WITH_VIEWS tiles with views, followers <= MAX_FOLLOWERS_FOR_CODE_PICK, smallest
    first; picked_by="code". Still short and samples/demo_creators.json lists this topic: fill
    from it, picked_by="saved_list". At most MAX_CREATORS.
    """
    raise NotImplementedError("A1: built on Friday")


async def read_grids(creators: list[Creator], grids: dict[str, GridPage], emit: Emit) -> list[outliers.Candidate]:
    """A2. Fetch any grid not prefetched; fill each Creator row honestly (followers, method="fetch",
    reels_read, pinned_skipped, median_views, access_status: accessible / login_wall / not_found /
    blocked with a plain status_reason, e.g. "Too few Reels with views" when no median).
    Return outliers.score_creator candidates for every accessible creator.
    """
    raise NotImplementedError("A2: built on Friday")


async def fetch_outlier_pages(candidates: list[outliers.Candidate], emit: Emit) -> list[Example]:
    """A3 (part). One Fetch call for the picked outliers' Reel pages, format="html",
    html_head=True, redact=instagram_parse.redact_reel_page; instagram_parse.parse_reel_page;
    Examples ex1..exN with views / median / ratio from the grid and likes / comments from the grid
    when known (og likes are rounded). A page that fails keeps its grid numbers but gets that
    failure's access_status, so it can't be cited. Every None field has a null_reasons entry.
    """
    raise NotImplementedError("A3: built on Friday")


async def run_niche_scout(topic: str, emit: Emit) -> tuple[list[Creator], list[Example]]:
    """A3. normalise_topic -> agent_pick_creators and fetch_topic_and_grids together
    (asyncio.gather) -> choose_creators -> read_grids -> outliers.pick_outliers ->
    fetch_outlier_pages. Emit one "creator" event naming who picked whom, and one "outlier"
    event per Example, e.g. "4.7x @pov__gil's median (26.4K vs 5.6K)".
    """
    raise NotImplementedError("A3: built on Friday")
