"""Report runner for v2 (task 1.5). One report = one creator, Reel or niche study.

Called by main.py, like jobs.py is for the v1 draft analyser:

    create_report()      write a queued ReportJob to data/reports/{id}.json
    run_creator_report() fetch (1.1) -> analyse (1.2) -> visuals (1.3) -> insights (1.4);
                         every change appends an Event and rewrites the file, which
                         GET /reports/{id} returns
    start_replay()       REPLAY=1: re-emit the newest recording of that kind, replay=true

The stages after fetch come from the intelligence lane. Until a module is on main, its stage
is "skipped" with "Not built yet" and the report still finishes, so the routes and the UI
work in the meantime. The functions each stage looks for (`_STEPS`):
    creator_metrics.analyse(report, today)   sync: caption fields, 7-day window, ratios, patterns
    vision.analyse_covers(report)            async: cover_notes for the top and bottom covers
    creator_report.write_insights(report)    async: insights + insights_source

Failure rules (as in jobs.py): a failed stage is marked failed with a reason and the report
carries on; TinyFishAccountError (key / credits) fails the whole report with a plain message;
an unreadable account (private, not found, no Reels) fails the report but keeps its profile.
Replay recordings live in replay_dir/reports/, so v1's replay (replay_dir/*.json) never sees them.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import re
import secrets
import time
import uuid
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from backend import creator_profiler
from backend.config import settings
from backend.jobs import JOB_ID, ReplayUnavailable
from backend.models import Event, StageState
from backend.niche_scout import _short
from backend.report_models import STAGES, CreatorReport, ReportJob, ReportKind
from backend.tinyfish_client import TinyFishAccountError

_REPORT_ID_RE = re.compile(JOB_ID)  # same 12-hex ids as jobs: never a path
_replays: set[asyncio.Task] = set()  # asyncio keeps only weak references to tasks

# stage -> (module in backend/, function, the plan task that builds it)
_STEPS = {
    "analyse": ("creator_metrics", "analyse", "1.2"),
    "visuals": ("vision", "analyse_covers", "1.3"),
    "insights": ("creator_report", "write_insights", "1.4"),
}
INSIGHT_LINES = {
    "llm": "{n} insight(s) passed every grounding check",
    "llm_retry": "{n} insight(s) passed the grounding checks on the second try",
    "template": "Gemini's answers didn't pass the grounding checks, so these are rule-based insights",
    "insufficient_evidence": "Not enough readable Reels to back an insight; showing the numbers only",
}


def _reports_dir() -> Path:
    return settings.data_dir / "reports"


def _recordings_dir() -> Path:
    return settings.replay_dir / "reports"


def save_report(job: ReportJob) -> None:
    """Write data/reports/{id}.json atomically (temp file + rename) so a poll never reads half a file."""
    folder = _reports_dir()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{job.id}.{uuid.uuid4().hex}.tmp"
    tmp.write_text(job.model_dump_json())
    tmp.replace(folder / f"{job.id}.json")


def get_report(report_id: str) -> ReportJob | None:
    if not isinstance(report_id, str) or not _REPORT_ID_RE.fullmatch(report_id):
        return None
    try:
        return ReportJob.model_validate_json((_reports_dir() / f"{report_id}.json").read_text())
    except (OSError, ValueError):
        return None


def create_report(kind: ReportKind, input: dict[str, Any], owner_id: int | None = None) -> ReportJob:
    job = ReportJob(id=secrets.token_hex(6), kind=kind, created_at=datetime.now(timezone.utc), input=input,
                    owner_id=owner_id, stages={name: StageState() for name in STAGES[kind]})
    save_report(job)
    return job


def _stage_fn(module: str, name: str) -> Callable | None:
    """The intelligence lane's function for a stage, or None while it isn't on main yet.
    Only a missing module or function counts as "not built"; any other import error is raised."""
    try:
        mod = importlib.import_module(f"backend.{module}")
    except ModuleNotFoundError as exc:
        if exc.name != f"backend.{module}":
            raise
        return None
    return getattr(mod, name, None)


async def _call(fn: Callable, *args: Any) -> Any:
    out = fn(*args)
    return await out if inspect.isawaitable(out) else out


async def run_creator_report(report_id: str, today: date | None = None) -> ReportJob:
    """Run every stage of a creator report. Returns the final ReportJob (also saved)."""
    job = get_report(report_id)
    if job is None:
        raise ValueError(f"No report {report_id!r}")
    handle = job.input["handle"]
    today = today or date.today()
    started = time.monotonic()

    def emit(source: str, kind: str, message: str, data: dict[str, Any] | None = None) -> None:
        # Sync on purpose: every caller runs on the event loop, so events land in call order.
        job.events.append(Event(t=round(time.monotonic() - started, 2), source=source, kind=kind, message=message, data=data))
        save_report(job)

    def skip_rest(after: str, reason: str) -> None:
        names = STAGES["creator"]
        for name in names[names.index(after) + 1:]:
            job.stages[name] = StageState(status="skipped", reason=reason)

    try:
        job.status = "running"
        job.stages["fetch"].status = "running"
        save_report(job)
        try:
            report: CreatorReport = await creator_profiler.fetch_creator(handle, emit)
        except TinyFishAccountError as exc:  # key or credits: not Instagram's fault
            job.stages["fetch"] = StageState(status="failed", reason=str(exc))
            skip_rest("fetch", "The research step failed")
            job.status, job.error = "failed", str(exc)
            emit("scout", "error", str(exc))
            return job
        job.result = report
        profile = report.profile
        if profile.access_status != "accessible" or not report.reels:
            reason = profile.status_reason or "No Reels could be read"
            job.stages["fetch"] = StageState(status="failed", reason=reason)
            skip_rest("fetch", "Nothing to analyse")
            job.status, job.error = "failed", f"@{handle}: {reason}"
            return job
        job.stages["fetch"].status = "done"
        save_report(job)

        for name in ("analyse", "visuals", "insights"):
            module, fn_name, task = _STEPS[name]
            fn = _stage_fn(module, fn_name)
            if fn is None:
                job.stages[name] = StageState(status="skipped", reason=f"Not built yet (task {task})")
                save_report(job)
                continue
            if name == "insights" and job.stages["analyse"].status != "done":
                job.stages[name] = StageState(status="skipped", reason="Insights need the analysis step")
                save_report(job)
                continue
            job.stages[name].status = "running"
            save_report(job)
            try:
                if name == "analyse":
                    await _call(fn, report, today)
                    median = f"median views {_short(profile.median_views)}" if profile.median_views else "no median (too few view counts)"
                    emit("system", "progress", f"{profile.reels_in_window} Reels in the last {profile.window_days} days; {median}")
                elif name == "visuals":
                    emit("llm", "progress", "Gemini is looking at the covers")
                    await _call(fn, report)
                    described = sum(1 for r in report.reels if r.cover_notes)
                    emit("llm", "progress", f"Described {described} covers")
                else:
                    emit("llm", "progress", "Writing insights from the numbers")
                    await _call(fn, report)
                    emit("llm", "info", INSIGHT_LINES[report.insights_source].format(n=len(report.insights)))
                job.stages[name].status = "done"
            except Exception as exc:
                job.stages[name] = StageState(status="failed", reason=f"{name.capitalize()} step stopped: {exc}")
                emit("llm" if name != "analyse" else "system", "error", job.stages[name].reason)
            save_report(job)
        job.status = "done"
    except Exception as exc:  # last resort: the UI must always get a final state
        job.status, job.error = "failed", f"Something went wrong: {exc}"
    finally:
        save_report(job)
    return job


# ---------------------------------------------------------------- replay (demo safety)


def record(job: ReportJob) -> Path:
    """Save a finished live report as a recording (scripts/record_replay.py --report)."""
    if job.replay or job.status != "done":
        raise ValueError(f"Report {job.id} is {'a replay' if job.replay else job.status}: record a finished live run instead.")
    folder = _recordings_dir()
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / f"{job.kind}_{job.created_at:%Y%m%d-%H%M%S}_{job.id}.json"
    dst.write_text(job.model_dump_json(indent=1))
    return dst


async def start_replay(kind: ReportKind, speed: float = 1.0) -> ReportJob:
    """Newest recording of this kind -> a new ReportJob with replay=True, returned at once; a
    background task re-emits its events on their original timing (divided by `speed`) and sets
    the result at the end. Never calls TinyFish or Gemini. None recorded -> ReplayUnavailable."""
    folder = _recordings_dir()
    recordings = sorted(folder.glob(f"{kind}_*.json"), key=lambda p: p.stat().st_mtime) if folder.exists() else []
    if not recordings:
        raise ReplayUnavailable(f"No recorded {kind} report to replay yet. Record one with "
                                "scripts/record_replay.py --report <id>, or set REPLAY=0.")
    recorded = ReportJob.model_validate_json(recordings[-1].read_text())
    # The replay shows the recorded input, whatever was typed: it's a recording, not a new run.
    job = ReportJob(id=secrets.token_hex(6), kind=kind, status="running", created_at=datetime.now(timezone.utc),
                    input=recorded.input, replay=True, replay_recorded_at=recorded.created_at,
                    stages={name: StageState(status="running" if i == 0 else "pending") for i, name in enumerate(STAGES[kind])})
    save_report(job)
    task = asyncio.create_task(_replay(job, recorded, speed))
    _replays.add(task)
    task.add_done_callback(_replays.discard)
    return job


async def _replay(job: ReportJob, recorded: ReportJob, speed: float) -> None:
    started = time.monotonic()
    try:
        for ev in recorded.events:
            await asyncio.sleep(max(0.0, ev.t / speed - (time.monotonic() - started)))
            job.events.append(ev)
            save_report(job)
    finally:
        job.result, job.stages, job.error = recorded.result, recorded.stages, recorded.error
        job.status = recorded.status if recorded.status in ("done", "failed") else "done"
        save_report(job)
