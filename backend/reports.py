"""Report runner for v2 (tasks 1.5, 3.1, 5.1). One report = one creator, Reel or niche study.

Called by main.py, like jobs.py is for the v1 draft analyser:

    create_report()      write a queued ReportJob to data/reports/{id}.json
    run_creator_report() fetch (1.1) -> analyse (1.2) -> visuals (1.3) -> insights (1.4)
    run_reel_report()    reel page -> creator (1.1 + 1.2 + comparison) -> visuals -> insights (3.2)
    run_niche_report()   research (5.1) -> patterns vs the previous run (5.2) -> insights (5.2);
                         each run is kept as data/pulse/<keywords>/<date>.json for the next diff
    start_replay()       REPLAY=1: re-emit the newest recording of that kind, replay=true

Every change appends an Event and rewrites the file, which GET /reports/{id} returns.

Stages after the fetch come from the intelligence lane. Until a module is on main, its stage
is "skipped" with "Not built yet" and the report still finishes, so the routes and the UI
work in the meantime. The functions looked up by name (`_STEPS`):
    creator_metrics.analyse(report, today)        sync: caption fields, 7-day window, ratios, patterns
    creator_metrics.fill_caption_fields(reel)     sync: caption fields of one Reel (the pasted one)
    vision.analyse_covers(report[, also=[...]])   async: cover_notes; `also` Reels are always described
    creator_report.write_insights(report)         async: insights + insights_source
    creator_report.write_reel_insights(report)    async: the same for a ReelReport
    creator_metrics.analyse_pulse(pulse, previous) sync: caption fields, patterns, since_last_run
    creator_report.write_pulse_insights(pulse)    async: insights for a NichePulse

Failure rules (as in jobs.py): a failed stage is marked failed with a reason and the report
carries on; TinyFishAccountError (key / credits) fails the whole report with a plain message;
an unreadable account or Reel fails the report but keeps what loaded.
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
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from backend import creator_profiler, niche_pulse, reel_report
from backend.config import settings
from backend.jobs import JOB_ID, ReplayUnavailable
from backend.models import Event, StageState
from backend.niche_scout import _short
from backend.report_models import STAGES, CreatorReport, NichePulse, ReelReport, ReportJob, ReportKind
from backend.tinyfish_client import TinyFishAccountError

_REPORT_ID_RE = re.compile(JOB_ID)  # same 12-hex ids as jobs: never a path
_replays: set[asyncio.Task] = set()  # asyncio keeps only weak references to tasks

# step -> (module in backend/, function, the plan task that builds it)
_STEPS = {
    "analyse": ("creator_metrics", "analyse", "1.2"),
    "fill": ("creator_metrics", "fill_caption_fields", "1.2"),
    "visuals": ("vision", "analyse_covers", "1.3"),
    "insights": ("creator_report", "write_insights", "1.4"),
    "reel_insights": ("creator_report", "write_reel_insights", "3.2"),
    "pulse_patterns": ("creator_metrics", "analyse_pulse", "5.2"),
    "pulse_insights": ("creator_report", "write_pulse_insights", "5.2"),
}
INSIGHT_LINES = {
    "llm": "{n} insight(s) passed every grounding check",
    "llm_retry": "{n} insight(s) passed the grounding checks on the second try",
    "template": "Gemini's answers didn't pass the grounding checks, so these are rule-based insights",
    "insufficient_evidence": "Not enough readable Reels to back an insight; showing the numbers only",
}

Emit = Callable[..., None]


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
    """The intelligence lane's function for a step, or None while it isn't on main yet.
    Only a missing module or function counts as "not built"; any other import error is raised."""
    try:
        mod = importlib.import_module(f"backend.{module}")
    except ModuleNotFoundError as exc:
        if exc.name != f"backend.{module}":
            raise
        return None
    return getattr(mod, name, None)


async def _call(fn: Callable, *args: Any, **kwargs: Any) -> Any:
    out = fn(*args, **kwargs)
    return await out if inspect.isawaitable(out) else out


# ---------------------------------------------------------------- shared by every runner


def _emitter(job: ReportJob) -> Emit:
    started = time.monotonic()

    def emit(source: str, kind: str, message: str, data: dict[str, Any] | None = None) -> None:
        # Sync on purpose: every caller runs on the event loop, so events land in call order.
        job.events.append(Event(t=round(time.monotonic() - started, 2), source=source, kind=kind, message=message, data=data))
        save_report(job)

    return emit


def _skip_rest(job: ReportJob, after: str, reason: str) -> None:
    names = STAGES[job.kind]
    for name in names[names.index(after) + 1:]:
        job.stages[name] = StageState(status="skipped", reason=reason)


def _fail_job(job: ReportJob, stage: str, reason: str, error: str, skip_reason: str = "Nothing to analyse") -> None:
    job.stages[stage] = StageState(status="failed", reason=reason)
    _skip_rest(job, stage, skip_reason)
    job.status, job.error = "failed", error


def _account_failure(job: ReportJob, stage: str, exc: TinyFishAccountError, emit: Emit) -> ReportJob:
    """Key or credits: not Instagram's fault, and nothing after this stage can run."""
    _fail_job(job, stage, str(exc), str(exc), skip_reason="The research step failed")
    emit("scout", "error", str(exc))
    return job


async def _step(job: ReportJob, emit: Emit, stage: str, step: str, run: Callable[[Callable], Awaitable[None]],
                needs: str | None = None) -> None:
    """Run one intelligence-lane step as a stage: skipped while not built (or when the stage it
    `needs` didn't finish), failed with a reason if it raises; the report carries on either way."""
    module, fn_name, task = _STEPS[step]
    fn = _stage_fn(module, fn_name)
    if fn is None:
        job.stages[stage] = StageState(status="skipped", reason=f"Not built yet (task {task})")
    elif needs and job.stages[needs].status != "done":
        job.stages[stage] = StageState(status="skipped", reason="Insights need the analysis step")
    else:
        job.stages[stage].status = "running"
        save_report(job)
        try:
            await run(fn)
            job.stages[stage].status = "done"
        except Exception as exc:
            job.stages[stage] = StageState(status="failed", reason=f"{stage.capitalize()} step stopped: {exc}")
            emit("system" if stage == "analyse" else "llm", "error", job.stages[stage].reason)
    save_report(job)


async def _describe_covers(fn: Callable, report: CreatorReport, emit: Emit, also: list | None = None) -> None:
    emit("llm", "progress", "Gemini is looking at the covers")
    if also and "also" in inspect.signature(fn).parameters:
        await _call(fn, report, also=also)
    else:
        await _call(fn, report)
    described = sum(1 for r in [*report.reels, *(also or [])] if r.cover_notes)
    emit("llm", "progress", f"Described {described} covers")


async def _write_insights(fn: Callable, report: CreatorReport | ReelReport, emit: Emit) -> None:
    emit("llm", "progress", "Writing insights from the numbers")
    await _call(fn, report)
    emit("llm", "info", INSIGHT_LINES[report.insights_source].format(n=len(report.insights)))


# ---------------------------------------------------------------- creator report (1.5)


async def run_creator_report(report_id: str, today: date | None = None) -> ReportJob:
    """Run every stage of a creator report. Returns the final ReportJob (also saved)."""
    job = get_report(report_id)
    if job is None:
        raise ValueError(f"No report {report_id!r}")
    handle = job.input["handle"]
    today = today or date.today()
    emit = _emitter(job)
    try:
        job.status = "running"
        job.stages["fetch"].status = "running"
        save_report(job)
        try:
            report: CreatorReport = await creator_profiler.fetch_creator(handle, emit)
        except TinyFishAccountError as exc:
            return _account_failure(job, "fetch", exc, emit)
        job.result = report
        profile = report.profile
        if profile.access_status != "accessible" or not report.reels:
            reason = profile.status_reason or "No Reels could be read"
            _fail_job(job, "fetch", reason, f"@{handle}: {reason}")
            return job
        job.stages["fetch"].status = "done"
        save_report(job)

        async def analyse(fn: Callable) -> None:
            await _call(fn, report, today)
            median = f"median views {_short(profile.median_views)}" if profile.median_views else "no median (too few view counts)"
            emit("system", "progress", f"{profile.reels_in_window} Reels in the last {profile.window_days} days; {median}")

        await _step(job, emit, "analyse", "analyse", analyse)
        await _step(job, emit, "visuals", "visuals", lambda fn: _describe_covers(fn, report, emit))
        await _step(job, emit, "insights", "insights", lambda fn: _write_insights(fn, report, emit), needs="analyse")
        job.status = "done"
    except Exception as exc:  # last resort: the UI must always get a final state
        job.status, job.error = "failed", f"Something went wrong: {exc}"
    finally:
        save_report(job)
    return job


# ---------------------------------------------------------------- Reel report (3.1)


async def run_reel_report(report_id: str, today: date | None = None) -> ReportJob:
    """Read the pasted Reel, then its creator; compare; covers; insights. Returns the final ReportJob.
    An unreadable Reel fails the report. An unreadable creator keeps the Reel's own numbers and
    finishes with the comparison and insights skipped."""
    job = get_report(report_id)
    if job is None:
        raise ValueError(f"No report {report_id!r}")
    today = today or date.today()
    emit = _emitter(job)
    try:
        job.status = "running"
        job.stages["reel"].status = "running"
        save_report(job)
        try:
            reel, handle = await reel_report.fetch_reel(job.input["reel_url"], emit)
        except TinyFishAccountError as exc:
            return _account_failure(job, "reel", exc, emit)
        if reel.access_status != "accessible" or not handle:
            reason = reel.status_reason or "The Reel page didn't say who posted it"
            _fail_job(job, "reel", reason, f"Couldn't read this Reel: {reason}")
            emit("scout", "error", job.error)
            return job
        job.stages["reel"].status = "done"
        posted = f", posted {reel.posted_date:%d %b %Y}" if reel.posted_date else ""
        emit("scout", "progress", f"Reel by @{handle}{posted}", {"handle": handle, "url": reel.source_url})

        job.stages["creator"].status = "running"
        save_report(job)
        try:
            creator = await creator_profiler.fetch_creator(handle, emit)
        except TinyFishAccountError as exc:
            return _account_failure(job, "creator", exc, emit)
        report = ReelReport(reel=reel, creator=creator)
        job.result = report
        if creator.profile.access_status != "accessible" or not creator.reels:
            reason = creator.profile.status_reason or "No Reels could be read"
            job.stages["creator"] = StageState(status="failed", reason=f"@{handle}: {reason}")
            _skip_rest(job, "creator", "No creator baseline to compare against")
            job.status = "done"  # the Reel's own numbers are still worth showing
            return job

        found = reel_report.take_from_grid(reel, creator)
        emit("scout", "progress", f"This Reel is in @{handle}'s recent grid: exact numbers, left out of their median"
             if found else f"This Reel isn't among @{handle}'s recent Reels, so its view count isn't public")
        analyse, fill = _stage_fn(*_STEPS["analyse"][:2]), _stage_fn(*_STEPS["fill"][:2])
        reason = None
        try:
            if analyse:
                await _call(analyse, creator, today)
            if fill:
                await _call(fill, reel)
        except Exception as exc:
            reason = f"Analysis step stopped: {exc}"
            emit("system", "error", reason)
        if reel.views is not None and creator.profile.median_views:
            reel.ratio_vs_median = round(reel.views / creator.profile.median_views, 2)
        report.comparison = reel_report.compare(reel, creator)
        emit("system", "progress", f"Compared with @{handle}'s {len(creator.reels)} recent Reels")
        if reason or not analyse:
            job.stages["creator"] = StageState(status="failed" if reason else "done",
                                               reason=reason or "Analysis not built yet (task 1.2): raw numbers only")
        else:
            job.stages["creator"].status = "done"
        save_report(job)

        await _step(job, emit, "visuals", "visuals", lambda fn: _describe_covers(fn, creator, emit, also=[reel]))
        analysed = analyse is not None and reason is None
        if analysed:
            await _step(job, emit, "insights", "reel_insights", lambda fn: _write_insights(fn, report, emit))
        else:
            job.stages["insights"] = StageState(status="skipped", reason="Insights need the analysis step")
        job.status = "done"
    except Exception as exc:  # last resort: the UI must always get a final state
        job.status, job.error = "failed", f"Something went wrong: {exc}"
    finally:
        save_report(job)
    return job


# ---------------------------------------------------------------- Niche Pulse (5.1)


def _pulse_dir(keywords: list[str]) -> Path:
    return settings.data_dir / "pulse" / "+".join(sorted(keywords))


def _previous_pulse(keywords: list[str], today: date) -> NichePulse | None:
    """The newest saved run of the same keywords from an earlier day, for "since last run"."""
    folder = _pulse_dir(keywords)
    earlier = sorted(p for p in folder.glob("*.json") if p.stem < today.isoformat()) if folder.exists() else []
    for path in reversed(earlier):
        try:
            return NichePulse.model_validate_json(path.read_text())
        except ValueError:
            continue
    return None


def _save_pulse(pulse: NichePulse) -> None:
    folder = _pulse_dir(pulse.keywords)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{pulse.run_date}.{uuid.uuid4().hex}.tmp"
    tmp.write_text(pulse.model_dump_json())
    tmp.replace(folder / f"{pulse.run_date}.json")


async def run_niche_report(report_id: str, today: date | None = None) -> ReportJob:
    """Research the keywords, then patterns against the previous run, then insights. A day with no
    outliers still finishes (with its web signals) and is saved, so tomorrow has a baseline."""
    job = get_report(report_id)
    if job is None:
        raise ValueError(f"No report {report_id!r}")
    keywords: list[str] = job.input["keywords"]
    today = today or date.today()
    emit = _emitter(job)
    try:
        job.status = "running"
        job.stages["research"].status = "running"
        save_report(job)
        try:
            pulse = await niche_pulse.run_pulse(keywords, emit, today)
        except TinyFishAccountError as exc:
            return _account_failure(job, "research", exc, emit)
        job.result = pulse
        job.stages["research"].status = "done"
        previous = _previous_pulse(keywords, today)
        _save_pulse(pulse)
        if not pulse.reels:
            job.stages["research"].reason = pulse.null_reasons.get("reels")
            _skip_rest(job, "research", "No outliers to learn from today")
            job.status = "done"
            return job
        save_report(job)

        async def patterns(fn: Callable) -> None:
            await _call(fn, pulse, previous)
            since = f"; since {previous.run_date:%d %b}: {len(pulse.since_last_run)} change(s)" if previous else "; first run for these keywords"
            emit("system", "progress", f"{len(pulse.patterns)} patterns across {len(pulse.reels)} outliers{since}")
            _save_pulse(pulse)  # with patterns, so the next run's diff has them

        await _step(job, emit, "patterns", "pulse_patterns", patterns)
        await _step(job, emit, "insights", "pulse_insights", lambda fn: _write_insights(fn, pulse, emit), needs="patterns")
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


async def start_replay(kind: ReportKind, speed: float = 1.0, *, handle: str | None = None,
                       owner_id: int | None = None) -> ReportJob:
    """Newest recording of this kind -> a new ReportJob with replay=True, returned at once; a
    background task re-emits its events on their original timing (divided by `speed`) and sets
    the result at the end. Never calls TinyFish or Gemini. None recorded -> ReplayUnavailable.

    `handle`: only a recording of that creator (My Studio must never show someone else's
    report as yours, replay or not)."""
    folder = _recordings_dir()
    recordings = sorted(folder.glob(f"{kind}_*.json"), key=lambda p: p.stat().st_mtime) if folder.exists() else []
    candidates = (ReportJob.model_validate_json(p.read_text()) for p in reversed(recordings))
    recorded = next((r for r in candidates if handle is None or r.input.get("handle") == handle), None)
    if recorded is None:
        whose = f" of @{handle}" if handle else ""
        raise ReplayUnavailable(f"No recorded {kind} report{whose} to replay yet. Record one with "
                                "scripts/record_replay.py --report <id>, or set REPLAY=0.")
    # The replay shows the recorded input, whatever was typed: it's a recording, not a new run.
    job = ReportJob(id=secrets.token_hex(6), kind=kind, status="running", created_at=datetime.now(timezone.utc),
                    input=recorded.input, owner_id=owner_id, replay=True, replay_recorded_at=recorded.created_at,
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
