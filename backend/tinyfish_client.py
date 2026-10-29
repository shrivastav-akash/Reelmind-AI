"""The only module that talks to TinyFish.

Called by niche_scout.py (Fri) and the scripts/spike_*.py test scripts.
It does three jobs so callers don't have to:

1. Wraps Fetch, Search, Agent and Wallet from the official async SDK
   (`tinyfish.AsyncTinyFish`), with our limits: Agent runs go through a
   2-slot semaphore (the per-account concurrency limit), and Agent runs are
   never auto-retried by the SDK because each run costs money.
2. Turns every TinyFish outcome into one of our access statuses
   (accessible / login_wall / blocked / not_found / timeout). A COMPLETED run
   can still describe a login wall, so "completed" alone never means success.
3. Logs every request and response to logs/ (keys redacted) and keeps a URL
   cache in data/cache/ so a Fetch that fails mid-demo can fall back to the
   last good copy, with its original retrieved_at still visible.

Account-level problems (missing key, 401, 402 no credits, 403) raise
TinyFishAccountError: the job runner shows them as a job failure instead of
blaming Instagram.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import weakref
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from tinyfish import (
    APIConnectionError,
    AsyncTinyFish,
    AuthenticationError,
    PaymentRequiredError,
    PermissionDeniedError,
    RateLimitError,
    SDKError,
)
from tinyfish.agent.types import (
    AgentConfig,
    BrowserProfile,
    CompleteEvent,
    ProgressEvent,
    ProxyConfig,
    StartedEvent,
    StreamingUrlEvent,
)

from backend.config import settings
from backend.models import AccessStatus

AGENT_CONCURRENCY = 2  # TinyFish allows 2 concurrent Agent runs per account
FETCH_BATCH = 10  # SDK limit: 1-10 URLs per Fetch call
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}

# Words that show up when a page was reached but not readable. Only scanned when a
# run returned no data, so a caption saying "I could not believe it" can't trip them.
LOGIN_MARKERS = ("log in", "login", "sign up", "signup", "logged in")
NOT_FOUND_MARKERS = ("not found", "isn't available", "is not available", "doesn't exist", "does not exist")
BLOCK_MARKERS = ("captcha", "blocked", "access denied", "could not", "unable to", "verify you are human")


class TinyFishAccountError(Exception):
    """Key missing or rejected, or no credits left. Not Instagram's fault: fail the job, say why."""


# ---------------------------------------------------------------- results


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class FetchedPage:
    url: str
    retrieved_at: str
    final_url: str | None = None
    title: str | None = None
    description: str | None = None  # Instagram puts "711K likes, 1,838 comments - ..." here
    published_date: str | None = None
    text: str | None = None
    links: list[str] = field(default_factory=list)
    image_links: list[str] = field(default_factory=list)
    from_cache: bool = False  # True: live fetch failed, this is the last good copy
    error: str | None = None  # set when neither live nor cache worked

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str


@dataclass
class AgentEvent:
    """What run_agent forwards to the caller's on_event, already in plain words."""

    kind: str  # started | streaming_url | progress | complete | poll
    message: str
    run_id: str | None = None
    streaming_url: str | None = None


@dataclass
class AgentOutcome:
    url: str
    profile: str  # lite | stealth
    access_status: AccessStatus
    status_reason: str | None
    run_id: str | None = None
    status: str | None = None  # TinyFish RunStatus, e.g. COMPLETED
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    streaming_url: str | None = None
    steps: int = 0  # PROGRESS events seen, a close proxy for billed steps
    duration_s: float = 0.0
    retrieved_at: str = field(default_factory=_now)


# ---------------------------------------------------------------- clients

# One SDK client per event loop: the SDK holds an httpx.AsyncClient, which must
# not be shared across loops (pytest-asyncio uses a fresh loop per test).
_clients: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_slots: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _client(kind: str) -> AsyncTinyFish:
    if not settings.tinyfish_api_key:
        raise TinyFishAccountError("TINYFISH_API_KEY is missing from .env")
    loop = asyncio.get_running_loop()
    per_loop = _clients.setdefault(loop, {})
    if kind not in per_loop:
        # Fetch/Search are free, so one SDK retry is fine. Agent runs cost money: no auto-retry.
        retries = 0 if kind == "agent" else 1
        per_loop[kind] = AsyncTinyFish(api_key=settings.tinyfish_api_key, max_retries=retries, timeout=120)
    return per_loop[kind]


def _agent_slots() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    if loop not in _slots:
        _slots[loop] = asyncio.Semaphore(AGENT_CONCURRENCY)
    return _slots[loop]


def _account_error(exc: Exception) -> TinyFishAccountError | None:
    if isinstance(exc, AuthenticationError):
        return TinyFishAccountError("TinyFish rejected the API key (401). Check TINYFISH_API_KEY.")
    if isinstance(exc, PaymentRequiredError):
        return TinyFishAccountError("TinyFish wallet can't cover this (402). Top up or switch to the spare key.")
    if isinstance(exc, PermissionDeniedError):
        return TinyFishAccountError(f"TinyFish refused the request (403): {exc}")
    return None


# ---------------------------------------------------------------- logging + cache


def _log(kind: str, payload: dict[str, Any]) -> None:
    """Write one JSON file per call to logs/<date>/. Keys are scrubbed even though the SDK sends them as headers."""
    now = datetime.now()
    folder = settings.logs_dir / now.strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, default=str, ensure_ascii=False, indent=1)
    for secret in (settings.tinyfish_api_key, settings.gemini_api_key):
        if secret:
            text = text.replace(secret, "***")
    (folder / f"{now.strftime('%H%M%S_%f')}-tinyfish-{kind}.json").write_text(text)


def _cache_path(url: str):
    return settings.data_dir / "cache" / f"{hashlib.sha1(url.encode()).hexdigest()}.json"


def _cache_put(page: FetchedPage) -> None:
    path = _cache_path(page.url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(page), ensure_ascii=False))


def _cache_get(url: str) -> FetchedPage | None:
    path = _cache_path(url)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    data["from_cache"] = True
    data["error"] = None
    return FetchedPage(**data)


# ---------------------------------------------------------------- Fetch + Search (free)


async def fetch_pages(
    urls: list[str],
    *,
    fmt: str = "markdown",
    html_head: bool = False,
    purpose: str | None = None,
    redact: Callable[[str], str] | None = None,
    fallback_to_cache: bool = True,
) -> list[FetchedPage]:
    """Fetch public pages (free), in input order, batching 10 per call.

    `redact` runs on page text before it is cached or returned; Instagram pages
    pass instagram_parse.strip_comments so commenter usernames are never stored.
    """
    client = _client("fetch")
    pages: dict[str, FetchedPage] = {}
    for i in range(0, len(urls), FETCH_BATCH):
        batch = urls[i : i + FETCH_BATCH]
        request = {"urls": batch, "format": fmt, "html_head": html_head, "purpose": purpose}
        started = time.monotonic()
        try:
            resp = await client.fetch.get_contents(
                batch,
                format=fmt,
                links=True,
                image_links=True,
                include_html_head=True if (html_head and fmt == "html") else None,
                purpose=purpose,
                per_url_timeout_ms=45_000,
            )
        except SDKError as exc:
            if acct := _account_error(exc):
                raise acct from exc
            _log("fetch", {"request": request, "exception": repr(exc), "seconds": time.monotonic() - started})
            for url in batch:
                pages[url] = _fallback(url, f"Fetch failed: {exc}", fallback_to_cache)
            continue

        _log("fetch", {"request": request, "response": resp.model_dump(), "seconds": time.monotonic() - started})
        retrieved = _now()
        for r in resp.results:
            text = redact(r.text) if (redact and r.text) else r.text
            page = FetchedPage(
                url=r.url,
                retrieved_at=retrieved,
                final_url=r.final_url,
                title=r.title,
                description=r.description,
                published_date=r.published_date,
                text=text,
                links=list(r.links or []),
                image_links=list(r.image_links or []),
            )
            pages[r.url] = page
            _cache_put(page)
        for e in resp.errors:
            pages[e.url] = _fallback(e.url, e.error, fallback_to_cache)

    return [pages.get(u) or _fallback(u, "No result returned for this URL", fallback_to_cache) for u in urls]


def _fallback(url: str, error: str, use_cache: bool) -> FetchedPage:
    if use_cache and (cached := _cache_get(url)):
        return cached
    return FetchedPage(url=url, retrieved_at=_now(), error=error)


async def search(query: str) -> list[SearchHit]:
    """Free web search. Fallback for finding creators when a topic page is walled."""
    client = _client("search")
    try:
        resp = await client.search.query(query)
    except SDKError as exc:
        if acct := _account_error(exc):
            raise acct from exc
        _log("search", {"query": query, "exception": repr(exc)})
        return []
    _log("search", {"query": query, "response": resp.model_dump()})
    return [SearchHit(title=r.title, url=r.url, snippet=r.snippet) for r in resp.results]


async def wallet_balance() -> str | None:
    """Spendable balance as TinyFish reports it (e.g. "7.84 USD"), for the pre-flight check."""
    try:
        w = await _client("fetch").wallet.get()
    except SDKError as exc:
        if acct := _account_error(exc):
            raise acct from exc
        return None
    return f"{w.available_balance} {w.currency}"


# ---------------------------------------------------------------- Agent (paid)

OnEvent = Callable[[AgentEvent], Awaitable[None] | None]


async def _emit(on_event: OnEvent | None, event: AgentEvent) -> None:
    if on_event is None:
        return
    out = on_event(event)
    if asyncio.iscoroutine(out):
        await out


async def run_agent(
    url: str,
    goal: str,
    output_schema: dict[str, Any],
    *,
    on_event: OnEvent | None = None,
    max_seconds: int = 90,
    stealth: bool = False,
) -> AgentOutcome:
    """One Agent run over SSE. Waits for a free slot (max 2 at once).

    Sends only url, goal, output_schema, browser_profile, agent_config.max_duration_seconds
    and (stealth only) proxy_config. Never max_steps, mode or capture_config: those are
    gated and return 403 on our accounts.
    """
    profile = "stealth" if stealth else "lite"
    kwargs: dict[str, Any] = {
        "goal": goal,
        "url": url,
        "output_schema": output_schema,
        "browser_profile": BrowserProfile.STEALTH if stealth else BrowserProfile.LITE,
        "agent_config": AgentConfig(max_duration_seconds=max_seconds),
    }
    if stealth:
        kwargs["proxy_config"] = ProxyConfig(enabled=True, country_code="IN")

    async with _agent_slots():
        started = time.monotonic()
        out = AgentOutcome(url=url, profile=profile, access_status="timeout", status_reason=None)
        client = _client("agent")
        try:
            # Hard ceiling so a silent stream can't hang the job.
            async with asyncio.timeout(max_seconds + 30):
                async with client.agent.stream(**kwargs) as stream:
                    async for ev in stream:
                        await _handle_event(ev, out, on_event)
                        if isinstance(ev, CompleteEvent):
                            break
        except (APIConnectionError, SDKError, TimeoutError) as exc:
            if acct := _account_error(exc):
                raise acct from exc
            if isinstance(exc, RateLimitError):
                out.error_code, out.error_message = "RATE_LIMIT_EXCEEDED", str(exc)
            elif out.run_id and out.status not in TERMINAL:
                # SSE has no reconnection: fall back to polling the run.
                await _emit(on_event, AgentEvent("poll", "Stream dropped, checking the run directly…", out.run_id))
                await _poll_run(client, out, deadline=started + max_seconds + 30)
            else:
                out.error_code = "TIMEOUT" if isinstance(exc, TimeoutError) else "STREAM_FAILED"
                out.error_message = str(exc) or type(exc).__name__

        out.duration_s = round(time.monotonic() - started, 1)
        out.retrieved_at = _now()
        out.access_status, out.status_reason = classify_access(
            out.status, out.result, out.error_code, out.error_message
        )
        _log("agent", {"request": {k: str(v) for k, v in kwargs.items()}, "outcome": asdict(out)})
        return out


async def _handle_event(ev: Any, out: AgentOutcome, on_event: OnEvent | None) -> None:
    if isinstance(ev, StartedEvent):
        out.run_id = ev.run_id
        await _emit(on_event, AgentEvent("started", "Agent run started", ev.run_id))
    elif isinstance(ev, StreamingUrlEvent):
        out.streaming_url = ev.streaming_url
        await _emit(on_event, AgentEvent("streaming_url", "Live browser view ready", ev.run_id, ev.streaming_url))
    elif isinstance(ev, ProgressEvent):
        out.steps += 1
        await _emit(on_event, AgentEvent("progress", ev.purpose, ev.run_id))
    elif isinstance(ev, CompleteEvent):
        out.status = str(ev.status)
        out.result = ev.result_json
        if ev.error:
            out.error_code, out.error_message = ev.error.code, ev.error.message
        await _emit(on_event, AgentEvent("complete", f"Agent run {out.status.lower()}", ev.run_id))


async def _poll_run(client: AsyncTinyFish, out: AgentOutcome, *, deadline: float) -> None:
    while time.monotonic() < deadline:
        try:
            run = await client.runs.get(out.run_id)
        except SDKError:
            await asyncio.sleep(3)
            continue
        out.status = str(run.status)
        out.streaming_url = out.streaming_url or run.streaming_url
        if out.status in TERMINAL:
            out.result = run.result
            if run.error:
                out.error_code, out.error_message = run.error.code, run.error.message
            return
        await asyncio.sleep(3)
    out.error_code, out.error_message = "TIMEOUT", "Run did not finish before our deadline"


async def run_agent_with_stealth_retry(
    url: str,
    goal: str,
    output_schema: dict[str, Any],
    *,
    on_event: OnEvent | None = None,
    max_seconds: int = 90,
    allow_retry: bool = True,
) -> AgentOutcome:
    """Lite first; one stealth retry only for a bot check (captcha / SITE_BLOCKED).

    Never retries a login wall: getting past a login is off-limits. Pass
    allow_retry=False during the live demo (brief: never retry mid-demo).
    """
    out = await run_agent(url, goal, output_schema, on_event=on_event, max_seconds=max_seconds)
    if allow_retry and is_bot_block(out):
        await _emit(on_event, AgentEvent("progress", "Bot check hit, retrying once in stealth mode"))
        out = await run_agent(url, goal, output_schema, on_event=on_event, max_seconds=max_seconds, stealth=True)
    return out


# ---------------------------------------------------------------- status mapping


def _has_data(result: dict[str, Any] | None) -> bool:
    """True if the result carries any non-empty list (e.g. reels). Plain flags don't count."""
    return bool(result) and any(isinstance(v, list) and v for v in result.values())


def classify_access(
    status: str | None,
    result: dict[str, Any] | None,
    error_code: str | None,
    error_message: str | None,
) -> tuple[AccessStatus, str | None]:
    """Map a TinyFish outcome to our access status plus a short human reason."""
    code = (error_code or "").upper()
    if code == "SITE_BLOCKED":
        return "blocked", "Site blocked the agent (SITE_BLOCKED)"
    if code in ("TIMEOUT", "STREAM_FAILED"):
        return "timeout", error_message or code
    if code == "RATE_LIMIT_EXCEEDED":
        return "blocked", "Rate limited by TinyFish (429)"
    if code:
        return "blocked", f"Failed: {code}"

    if status and status != "COMPLETED":
        return "blocked", f"Run {status.lower()}: {error_message or 'no reason given'}"
    if status is None:
        return "timeout", error_message or "No result from TinyFish"

    result = result or {}
    reason_text = str(result.get("blocked_reason") or "")
    if result.get("blocked") is True:
        return _from_text(reason_text) or ("blocked", reason_text or "Agent reported the page as blocked")
    if _has_data(result):
        return "accessible", None
    # COMPLETED but empty: read the result for why.
    return _from_text(json.dumps(result).lower()) or ("blocked", "Completed but returned no data")


def _from_text(text: str) -> tuple[AccessStatus, str] | None:
    t = text.lower()
    if any(m in t for m in LOGIN_MARKERS):
        return "login_wall", "Login wall: public view not available"
    if any(m in t for m in NOT_FOUND_MARKERS):
        return "not_found", "Page not found"
    if any(m in t for m in BLOCK_MARKERS):
        return "blocked", "Blocked (captcha or bot check)"
    return None


def is_bot_block(out: AgentOutcome) -> bool:
    reason = (out.status_reason or "").lower()
    return out.access_status == "blocked" and ("captcha" in reason or "site_blocked" in reason or "bot" in reason)
