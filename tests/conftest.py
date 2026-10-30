"""Shared fixtures. Tests never touch the real .env keys, logs/ or data/:
`isolated` points every module's settings at a temp folder with fake keys."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from backend import llm_client, tinyfish_client
from backend.config import settings
from backend.models import Job

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
MOCKS = ROOT / "frontend" / "src" / "mocks"


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    fake = replace(
        settings,
        tinyfish_api_key="tf-test-SECRET",
        gemini_api_key="gm-test-SECRET",
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        replay_dir=tmp_path / "replay",
    )
    monkeypatch.setattr(tinyfish_client, "settings", fake)
    monkeypatch.setattr(llm_client, "settings", fake)
    return fake


def load_mock(name: str) -> Job:
    return Job.model_validate(json.loads((MOCKS / f"job.{name}.json").read_text()))


@pytest.fixture
def done_job() -> Job:
    return load_mock("done")
