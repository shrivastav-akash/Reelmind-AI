"""tinyfish_client against a fake SDK: no network, no credits."""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest
from tinyfish import APIConnectionError, AuthenticationError, PaymentRequiredError, RateLimitError
from tinyfish.agent.types import CompleteEvent, ProgressEvent, StartedEvent, StreamingUrlEvent
from tinyfish.fetch.types import FetchError, FetchResponse, FetchResult
from tinyfish.runs.types import Run

from backend import tinyfish_client as tf

NOW = datetime.now(timezone.utc).isoformat()
REELS = {"handle": "a", "blocked": False, "reels": [{"reel_url": "https://www.instagram.com/reel/X1/", "views": "1K"}]}


def started():
    return StartedEvent.model_validate({"type": "STARTED", "runId": "run1", "timestamp": NOW})


def streaming():
    return StreamingUrlEvent.model_validate(
        {"type": "STREAMING_URL", "runId": "run1", "streamingUrl": "https://live.example/run1", "timestamp": NOW}
    )


def progress(text):
    return ProgressEvent.model_validate({"type": "PROGRESS", "runId": "run1", "purpose": text, "timestamp": NOW})


def complete(result=None, status="COMPLETED", error=None):
    return CompleteEvent.model_validate(
        {"type": "COMPLETE", "runId": "run1", "status": status, "timestamp": NOW, "result": result, "error": error}
    )


class FakeStream:
    def __init__(self, events, fail_after=None, delay=0.0):
        self.events, self.fail_after, self.delay = events, fail_after, delay

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for i, ev in enumerate(self.events):
            if self.fail_after is not None and i == self.fail_after:
                raise APIConnectionError("connection dropped")
            await asyncio.sleep(self.delay)
            yield ev


class Fake:
    """Stands in for AsyncTinyFish: .fetch, .agent, .runs, .search."""

    def __init__(self, pages=None, fetch_exc=None, streams=None, run=None):
        self.pages, self.fetch_exc = pages or {}, fetch_exc
        self.streams = list(streams or [])
        self.run = run
        self.fetch_calls, self.agent_calls = [], []
        self.fetch, self.agent, self.runs = self, self, self
        self.active = self.max_active = 0

    async def get_contents(self, urls, **kw):
        self.fetch_calls.append(list(urls))
        if self.fetch_exc:
            raise self.fetch_exc
        return FetchResponse(
            results=[FetchResult(url=u, format="markdown", **self.pages[u]) for u in urls if u in self.pages],
            errors=[FetchError(url=u, error="404") for u in urls if u not in self.pages],
        )

    def stream(self, **kw):
        self.agent_calls.append(kw)
        stream = self.streams.pop(0)
        fake = self

        class Counting(FakeStream):
            async def __aenter__(s):
                fake.active += 1
                fake.max_active = max(fake.max_active, fake.active)
                return s

            async def __aexit__(s, *a):
                fake.active -= 1
                return False

        return Counting(stream.events, stream.fail_after, stream.delay)

    async def get(self, run_id):
        return self.run


@pytest.fixture
def fake(isolated, monkeypatch):
    holder = {}

    def install(**kw):
        holder["fake"] = Fake(**kw)
        monkeypatch.setattr(tf, "_client", lambda kind: holder["fake"])
        return holder["fake"]

    return install


# ---------------------------------------------------------------- classify_access


@pytest.mark.parametrize(
    "status, result, code, expected",
    [
        ("COMPLETED", REELS, None, "accessible"),
        ("COMPLETED", {"handle": "a", "blocked": True, "blocked_reason": "Log in to see more"}, None, "login_wall"),
        ("COMPLETED", {"handle": "a", "blocked": True, "blocked_reason": "captcha shown"}, None, "blocked"),
        ("COMPLETED", {"handle": "a", "blocked": False, "reels": []}, None, "blocked"),
        ("COMPLETED", {"note": "Sorry, this page isn't available."}, None, "not_found"),
        ("FAILED", None, "SITE_BLOCKED", "blocked"),
        ("FAILED", None, "TIMEOUT", "timeout"),
        ("FAILED", None, "MAX_STEPS_EXCEEDED", "blocked"),
        (None, None, None, "timeout"),
    ],
)
def test_classify_access(status, result, code, expected):
    assert tf.classify_access(status, result, code, None)[0] == expected


def test_caption_words_cannot_fake_a_block():
    result = dict(REELS, reels=[{"reel_url": "u", "views": "1K", "caption": "I could not believe it, log in later"}])
    assert tf.classify_access("COMPLETED", result, None, None) == ("accessible", None)


# ---------------------------------------------------------------- Fetch


def drop_comments(page):
    return replace(page, text=page.text.replace(" COMMENTS by someone", ""))


async def test_fetch_batches_keeps_order_redacts_and_caches(fake, isolated):
    urls = [f"https://ex.com/{i}" for i in range(12)]
    f = fake(pages={u: {"text": f"body {u} COMMENTS by someone"} for u in urls if not u.endswith("/5")})
    pages = await tf.fetch_pages(urls, redact=drop_comments)
    assert [len(c) for c in f.fetch_calls] == [10, 2]
    assert [p.url for p in pages] == urls
    assert pages[5].error == "404" and not pages[5].ok
    assert pages[0].text == "body https://ex.com/0" and pages[0].retrieved_at
    assert len(list((isolated.data_dir / "cache").glob("*.json"))) == 11


async def test_logs_hold_redacted_pages_only(fake, isolated):  # G3
    fake(pages={"https://ex.com/r": {"text": "caption COMMENTS by someone"}})
    await tf.fetch_pages(["https://ex.com/r"], redact=drop_comments)
    for path in [*isolated.logs_dir.rglob("*.json"), *isolated.data_dir.rglob("*.json")]:
        assert "COMMENTS by someone" not in path.read_text(), path


async def test_duplicate_urls_are_fetched_once(fake):
    f = fake(pages={"https://ex.com/a": {"text": "a"}})
    pages = await tf.fetch_pages(["https://ex.com/a", "https://ex.com/a"])
    assert f.fetch_calls == [["https://ex.com/a"]] and [p.text for p in pages] == ["a", "a"]


async def test_empty_url_list_makes_no_call(fake):
    f = fake()
    assert await tf.fetch_pages([]) == [] and f.fetch_calls == []


async def test_cache_never_serves_markdown_for_an_html_request(fake):
    url = "https://ex.com/reel"
    fake(pages={url: {"text": "markdown copy"}})
    await tf.fetch_pages([url], fmt="markdown")
    fake(fetch_exc=APIConnectionError("wifi down"))
    [html_page] = await tf.fetch_pages([url], fmt="html", html_head=True)
    assert html_page.error and not html_page.from_cache  # real bug seen on 29 Oct


async def test_fetch_falls_back_to_cache_when_the_network_fails(fake):  # D15
    url = "https://ex.com/reel"
    fake(pages={url: {"text": "first copy"}})
    [live] = await tf.fetch_pages([url])
    fake(fetch_exc=APIConnectionError("wifi down"))
    [again] = await tf.fetch_pages([url])
    assert again.from_cache and again.text == "first copy" and again.retrieved_at == live.retrieved_at
    [uncached] = await tf.fetch_pages(["https://ex.com/never"])
    assert uncached.error.startswith("Fetch failed")


async def test_every_url_failing_returns_errors_not_an_exception(fake):
    fake(pages={})
    pages = await tf.fetch_pages(["https://ex.com/1", "https://ex.com/2"], fallback_to_cache=False)
    assert all(p.error == "404" for p in pages)


async def test_no_credits_is_an_account_error(fake):  # D16
    resp = httpx.Response(402, request=httpx.Request("POST", "https://api.fetch.tinyfish.ai"))
    fake(fetch_exc=PaymentRequiredError("no credits", response=resp))
    with pytest.raises(tf.TinyFishAccountError, match="402"):
        await tf.fetch_pages(["https://ex.com"])


async def test_wrong_key_is_an_account_error(fake):  # D17
    resp = httpx.Response(401, request=httpx.Request("POST", "https://api.fetch.tinyfish.ai"))
    fake(fetch_exc=AuthenticationError("bad key", response=resp))
    with pytest.raises(tf.TinyFishAccountError, match="rejected the API key"):
        await tf.fetch_pages(["https://ex.com"])


async def test_rate_limit_is_reported(fake):  # D18
    resp = httpx.Response(429, request=httpx.Request("POST", "https://agent.tinyfish.ai"))

    class Limited(FakeStream):
        async def __aenter__(self):
            raise RateLimitError("slow down", response=resp)

    f = fake()
    f.stream = lambda **kw: Limited([])
    out = await tf.run_agent("u", "g", {})
    assert out.access_status == "blocked" and "429" in out.status_reason


async def test_missing_key_is_an_account_error(isolated, monkeypatch):
    from dataclasses import replace

    monkeypatch.setattr(tf, "settings", replace(isolated, tinyfish_api_key=""))
    with pytest.raises(tf.TinyFishAccountError, match="missing"):
        await tf.fetch_pages(["https://ex.com"])


# ---------------------------------------------------------------- Agent


async def test_agent_happy_path_forwards_events_and_sends_only_allowed_fields(fake):
    f = fake(streams=[FakeStream([started(), streaming(), progress("open"), progress("scroll"), complete(REELS)])])
    seen = []
    out = await tf.run_agent("https://ig/a/reels/", "goal", {"type": "object"}, on_event=seen.append)
    assert out.access_status == "accessible" and out.steps == 2
    assert out.streaming_url == "https://live.example/run1" and out.run_id == "run1"
    assert [e.kind for e in seen] == ["started", "streaming_url", "progress", "progress", "complete"]
    sent = f.agent_calls[0]
    assert sent["agent_config"].model_dump(exclude_none=True) == {"max_duration_seconds": 90}
    assert "capture_config" not in sent and "proxy_config" not in sent
    assert str(sent["browser_profile"]) == "lite"


async def test_agent_stream_drop_falls_back_to_polling(fake):
    run = Run.model_validate(
        {"run_id": "run1", "status": "COMPLETED", "goal": "g", "created_at": NOW, "result": REELS}
    )
    fake(streams=[FakeStream([started(), progress("open"), complete(REELS)], fail_after=2)], run=run)
    out = await tf.run_agent("u", "g", {})
    assert out.access_status == "accessible" and out.result == REELS


async def test_login_wall_is_never_retried_in_stealth(fake):
    wall = {"handle": "a", "blocked": True, "blocked_reason": "Login required"}
    f = fake(streams=[FakeStream([started(), complete(wall)])])
    out = await tf.run_agent_with_stealth_retry("u", "g", {})
    assert out.access_status == "login_wall" and len(f.agent_calls) == 1


async def test_bot_block_gets_one_stealth_retry(fake):
    captcha = {"handle": "a", "blocked": True, "blocked_reason": "captcha"}
    f = fake(streams=[FakeStream([started(), complete(captcha)]), FakeStream([started(), complete(REELS)])])
    out = await tf.run_agent_with_stealth_retry("u", "g", {})
    assert out.access_status == "accessible" and out.profile == "stealth"
    assert str(f.agent_calls[1]["browser_profile"]) == "stealth" and f.agent_calls[1]["proxy_config"].enabled


async def test_no_retry_during_the_demo(fake):
    captcha = {"handle": "a", "blocked": True, "blocked_reason": "captcha"}
    f = fake(streams=[FakeStream([started(), complete(captcha)])])
    await tf.run_agent_with_stealth_retry("u", "g", {}, allow_retry=False)
    assert len(f.agent_calls) == 1


async def test_at_most_two_agent_runs_at_once(fake):
    f = fake(streams=[FakeStream([started(), complete(REELS)], delay=0.05) for _ in range(5)])
    outs = await asyncio.gather(*(tf.run_agent(f"u{i}", "g", {}) for i in range(5)))
    assert all(o.access_status == "accessible" for o in outs)
    assert f.max_active == 2


async def test_logs_never_contain_keys(fake, isolated):
    fake(streams=[FakeStream([started(), complete(REELS)])])
    await tf.run_agent("u", f"goal mentioning {isolated.tinyfish_api_key}", {})
    text = "".join(p.read_text() for p in isolated.logs_dir.rglob("*.json"))
    assert "tf-test-SECRET" not in text and "***" in text
