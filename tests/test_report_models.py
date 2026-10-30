"""The v2 mocks are the UI's copy of report_models.py: they must stay valid, cite only
what exists, and match what scripts/make_report_mocks.py builds (so nobody hand-edits them)."""

import importlib.util
import json

import pytest

from backend.report_models import STAGES, CreatorReport, ReportJob, UserPublic

from .conftest import MOCKS, ROOT

REPORT_MOCKS = {
    "report.creator.json": "creator",
    "report.creator.running.json": "creator",
    "report.reel.json": "reel",
    "report.niche.json": "niche",
}


def load(name: str) -> ReportJob:
    return ReportJob.model_validate(json.loads((MOCKS / name).read_text()))


@pytest.mark.parametrize("name,kind", REPORT_MOCKS.items())
def test_report_mocks_match_the_contract(name, kind):
    job = load(name)
    assert job.kind == kind
    assert list(job.stages) == list(STAGES[kind])
    assert job.events[0].message.startswith("MOCK DATA")  # never mistaken for a real run
    if job.status == "done":
        assert job.result is not None and job.result.kind == kind
    else:
        assert job.result is None


def test_creator_insights_cite_only_what_exists():
    report = load("report.creator.json").result
    keys, ids = report.citable(), report.reel_ids()
    assert report.insights
    for insight in report.insights:
        assert insight.keys and set(insight.keys) <= set(keys), insight.claim
        assert insight.reel_ids and set(insight.reel_ids) <= ids, insight.claim


def test_reel_report_cites_the_reel_and_its_creator():
    report = load("report.reel.json").result
    assert report.reel.id == "r0" and "r0" not in report.creator.reel_ids()
    keys, ids = report.creator.citable(), report.creator.reel_ids() | {"r0"}
    for insight in report.insights:
        assert set(insight.keys) <= set(keys) and set(insight.reel_ids) <= ids, insight.claim
    for row in report.comparison:
        assert set(row.keys) <= set(keys), row.label


def test_niche_insights_cite_only_what_exists():
    pulse = load("report.niche.json").result
    assert all(r.handle for r in pulse.reels)  # many creators: each Reel names its own
    for insight in pulse.insights:
        assert set(insight.keys) <= set(pulse.citable()) and set(insight.reel_ids) <= pulse.reel_ids()


def test_reel_ids_are_unique_and_numbers_agree():
    report = load("report.creator.json").result
    ids = [r.id for r in report.reels]
    assert len(ids) == len(set(ids))
    in_window = [r for r in report.reels if r.in_window]
    assert report.profile.reels_in_window == len(in_window)
    for r in report.reels:
        assert r.ratio_vs_median == round(r.views / report.profile.median_views, 2)


def test_citable_skips_missing_values():
    report = load("report.creator.json").result
    report.profile.following = None
    keys = report.citable()
    assert "p.following" not in keys and "p.handle" not in keys
    assert keys["p.median_views"] == report.profile.median_views
    assert keys["pat.hook_type.question"] == next(p.median_ratio for p in report.patterns if p.key == "pat.hook_type.question")


def test_result_kind_picks_the_model():
    job = load("report.creator.json")
    raw = job.model_dump(mode="json")
    assert isinstance(ReportJob.model_validate(raw).result, CreatorReport)
    raw["result"]["kind"] = "niche"
    with pytest.raises(ValueError):
        ReportJob.model_validate(raw)


def test_me_mock_has_no_secrets_and_points_at_a_report():
    raw = json.loads((MOCKS / "me.json").read_text())
    me = UserPublic.model_validate(raw)
    assert not {"password", "pw_hash", "pw_salt", "token"} & set(raw)
    assert me.latest_report_id == load("report.creator.json").id


def test_mocks_are_what_the_script_builds():
    spec = importlib.util.spec_from_file_location("make_report_mocks", ROOT / "scripts" / "make_report_mocks.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    creator = script.creator_report()
    done = script.creator_job(creator)
    built = {
        "report.creator.json": done,
        "report.creator.running.json": script.running_job(done),
        "report.reel.json": script.reel_job(creator),
        "report.niche.json": script.niche_job(),
    }
    for name, model in built.items():
        assert json.loads((MOCKS / name).read_text()) == model.model_dump(mode="json"), f"rerun the script: {name}"
