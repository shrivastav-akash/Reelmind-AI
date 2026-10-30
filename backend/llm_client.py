"""The only module that talks to Gemini.

Called by vision.py and recommend.py (Fri). One function, generate_json():
send a prompt (plus optional labelled images) and get back an instance of a
pydantic model.
- Model from LLM_MODEL; on a rate limit, server error or network error, one
  retry on LLM_FALLBACK_MODEL. A rejected key is not retried (it can't succeed).
- JSON is enforced twice: Gemini's response_schema, then pydantic here.
- Every call is logged to logs/ (prompt, model, seconds, raw answer); images
  are logged as sizes only, keys are scrubbed.
"""

from __future__ import annotations

import time
from typing import TypeVar

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from backend.config import settings, write_log

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Gemini couldn't give a valid answer. Callers fall back (null vision fields, template card)."""


def _log(payload: dict) -> None:
    write_log(settings, "gemini", payload)


def _contents(prompt: str, images: list[tuple[str, bytes]]) -> list:
    """Prompt first, then each image preceded by its text label (e.g. "t=1.5s")."""
    contents: list = [prompt]
    for label, jpg in images:
        contents += [label, types.Part.from_bytes(data=jpg, mime_type="image/jpeg")]
    return contents


async def generate_json(
    prompt: str,
    schema: type[T],
    *,
    images: list[tuple[str, bytes]] | None = None,
    temperature: float = 0.2,
) -> T:
    if not settings.gemini_api_key:
        raise LLMError("GEMINI_API_KEY is missing from .env")
    images = images or []
    client = genai.Client(api_key=settings.gemini_api_key)
    config = types.GenerateContentConfig(
        temperature=temperature,
        response_mime_type="application/json",
        response_schema=schema,
    )
    last_error = "no attempt made"
    for model in dict.fromkeys([settings.llm_model, settings.llm_fallback_model]):  # dedupe, keep order
        started = time.monotonic()
        log = {"model": model, "schema": schema.__name__, "prompt": prompt,
               "images": [{"label": lbl, "bytes": len(b)} for lbl, b in images]}
        try:
            resp = await client.aio.models.generate_content(model=model, contents=_contents(prompt, images), config=config)
        except errors.APIError as exc:
            log.update(error=f"{exc.code}: {exc}", seconds=round(time.monotonic() - started, 2))
            _log(log)
            if exc.code in (401, 403):
                raise LLMError("Gemini rejected the API key. Check GEMINI_API_KEY.") from exc
            if exc.code == 429 or exc.code >= 500:
                last_error = f"{model}: {exc.code}"
                continue  # try the fallback model
            raise LLMError(f"Gemini error {exc.code}: {exc}") from exc
        except httpx.HTTPError as exc:
            # Wi-Fi drop or timeout: the SDK raises httpx's own errors, not APIError. Treat it like
            # a 5xx so callers still get an LLMError they can fall back on.
            log.update(error=f"network: {exc!r}", seconds=round(time.monotonic() - started, 2))
            _log(log)
            last_error = f"{model}: network error"
            continue

        log.update(seconds=round(time.monotonic() - started, 2), answer=resp.text)
        _log(log)
        try:
            return schema.model_validate_json(resp.text or "")
        except ValidationError as exc:
            raise LLMError(f"Gemini answer didn't match {schema.__name__}: {exc.errors()[:3]}") from exc
    raise LLMError(f"Gemini unavailable ({last_error})")
