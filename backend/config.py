"""Settings, loaded once from the repo-root .env.

Every backend module imports `settings` from here, so keys are read in one
place. Keys are excluded from repr() so printing or logging `settings` can
never leak them.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    tinyfish_api_key: str = field(repr=False)
    gemini_api_key: str = field(repr=False)
    llm_model: str
    llm_fallback_model: str
    # REPLAY=1 serves a recorded run instead of live calls (demo safety on bad Wi-Fi).
    replay: bool
    data_dir: Path
    logs_dir: Path
    replay_dir: Path


def _load() -> Settings:
    return Settings(
        tinyfish_api_key=os.getenv("TINYFISH_API_KEY", "").strip(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        llm_model=os.getenv("LLM_MODEL", "gemini-3.8-flash"),
        llm_fallback_model=os.getenv("LLM_FALLBACK_MODEL", "gemini-3.5-flash-lite"),
        replay=os.getenv("REPLAY", "0") == "1",
        data_dir=ROOT / "data",
        logs_dir=ROOT / "logs",
        replay_dir=ROOT / "backend" / "cache" / "replay",
    )


settings = _load()


def write_log(cfg: Settings, name: str, payload: dict) -> None:
    """One JSON file per external call in logs/<date>/, with both API keys replaced by ***.

    Used by tinyfish_client and llm_client. They pass their own module's `settings`, so
    the tests' `isolated` fixture (which swaps those) still keeps logs in a temp folder.
    """
    now = datetime.now()
    folder = cfg.logs_dir / now.strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, default=str, ensure_ascii=False, indent=1)
    for secret in (cfg.tinyfish_api_key, cfg.gemini_api_key):
        if secret:
            text = text.replace(secret, "***")
    (folder / f"{now.strftime('%H%M%S_%f')}-{name}.json").write_text(text)
