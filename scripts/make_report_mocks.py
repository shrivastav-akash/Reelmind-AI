"""Build the v2 UI mocks from backend/report_models.py (task 0.2). Free: no network.

    .venv/bin/python scripts/make_report_mocks.py

Writes frontend/src/mocks/report.creator.json, report.creator.running.json,
report.reel.json, report.niche.json and me.json. Every handle, URL and number here is
made up (handles start with mock_, URLs with /reel/MOCK) and the first event says
"MOCK DATA", so a mock can't pass for a real run. Medians, ratios and pattern rows are
computed from the made-up Reels, so the numbers on screen agree with each other.
Rerun after changing report_models.py; tests/test_report_models.py checks the output.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.models import Event, StageState  # noqa: E402
from backend.report_models import (  # noqa: E402
    STAGES,
    ComparisonRow,
    CoverNotes,
    CreatorReport,
    Insight,
    NichePulse,
    PatternRow,
    ProfileStats,
    ReelReport,
    ReelStat,
    ReportJob,
    UserPublic,
    WebSignal,
)

MOCKS = ROOT / "frontend" / "src" / "mocks"
TODAY = date(2026, 10, 30)
RETRIEVED = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)
CREATED = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)
MOCK_NOTE = "MOCK DATA for building the UI. Not a real run."

# (days ago, views, likes, comments, caption, hook type, audio, cover notes or None)
CREATOR_REELS = [
    (1, 48200, 3100, 88, "3 chutneys you can make in 5 minutes 🌿\nSave this for later!\n#chutney #indianfood #quickrecipes", "number_list", "Original audio", CoverNotes(text_on_cover="3 CHUTNEYS IN 5 MIN", face=False, setting="kitchen counter, top-down", style="bright, close-up")),
    (3, 9100, 610, 21, "Aaj kuch naya try karte hain\n#dinner #homecooking", "statement", "Mock Artist · Mock Song", CoverNotes(text_on_cover=None, face=True, setting="kitchen, wide shot", style="dim, talking head")),
    (5, 61500, 4400, 132, "Why does restaurant dal taste better? 🤔\nThe secret is the tadka. Save this!\n#dal #indianfood #cookingtips", "question", "Original audio", CoverNotes(text_on_cover="RESTAURANT DAL SECRET?", face=True, setting="stove close-up", style="bright, steam visible")),
    (6, 12300, 700, 19, "My mom's Sunday rajma\n#rajma #homecooking", "story", "Mock Artist · Slow Song", None),
    (9, 15800, 980, 30, "How to make soft rotis every time\nComment ROTI for the full recipe\n#roti #cookingtips #indianfood", "how_to", "Original audio", CoverNotes(text_on_cover="SOFT ROTIS", face=False, setting="hands on dough", style="warm, close-up")),
    (11, 7400, 400, 9, "Lunch box idea for Monday\n#lunchbox #homecooking", "statement", "Mock Artist · Mock Song", CoverNotes(text_on_cover=None, face=False, setting="tiffin box on table", style="flat, wide")),
    (13, 52000, 3900, 140, "Is ghee actually healthy? Let's test it\n#ghee #cookingtips #indianfood", "question", "Original audio", None),
    (15, 11000, 690, 25, "POV: you forgot to soak the chana\n#chana #homecooking", "pov", "Mock Artist · Funny Clip", None),
    (17, 9800, 520, 12, "Simple dinner tonight\n#dinner", "statement", "Mock Artist · Mock Song", None),
    (19, 14100, 900, 41, "Stop adding salt before this step\n#cookingtips", "warning", "Original audio", None),
    (21, 8600, 470, 8, "Weekend thali\n#thali #homecooking", "statement", "Mock Artist · Slow Song", None),
    (23, 13200, 820, 27, "How to temper spices the right way\n#cookingtips #indianfood", "how_to", "Original audio", None),
]


def caption_parts(caption: str) -> tuple[str, list[str]]:
    first = caption.split("\n", 1)[0]
    return first, [w.lower() for w in caption.split() if w.startswith("#")]


def build_reels(rows, prefix: str = "MOCK", handle: str | None = None, start: int = 1) -> list[ReelStat]:
    out = []
    for n, (ago, views, likes, comments, caption, hook_type, audio, cover) in enumerate(rows, start=start):
        hook, tags = caption_parts(caption)
        posted = TODAY - timedelta(days=ago)
        out.append(
            ReelStat(
                id=f"r{n}",
                source_url=f"https://www.instagram.com/reel/{prefix}{n:07d}/",
                retrieved_at=RETRIEVED,
                access_status="accessible",
                handle=handle,
                posted_date=posted,
                in_window=ago <= 7,
                views=views,
                likes=likes,
                comments=comments,
                caption=caption,
                hook_line=hook,
                hook_type=hook_type,
                hashtags=tags,
                keywords=[w for w in hook.lower().replace("?", "").split() if len(w) > 3][:4],
                caption_chars=len(caption),
                has_cta=any(c in caption.lower() for c in ("save this", "comment ")),
                audio_label=audio,
                original_audio=audio.startswith("Original audio"),
                cover_url=f"https://picsum.photos/seed/{prefix.lower()}{n}/360/640",
                cover_notes=cover,
                null_reasons={} if cover else {"cover_notes": "Only the top 3 and bottom 3 covers are analysed"},
            )
        )
    return out


def add_ratios(reels: list[ReelStat]) -> int:
    median = int(statistics.median(r.views for r in reels))
    for r in reels:
        r.ratio_vs_median = round(r.views / median, 2)
    return median


def patterns(reels: list[ReelStat]) -> list[PatternRow]:
    ranked = sorted(reels, key=lambda r: r.ratio_vs_median, reverse=True)
    third = max(1, len(ranked) // 3)
    top, bottom = {r.id for r in ranked[:third]}, {r.id for r in ranked[-third:]}
    groups: dict[tuple[str, str], list[ReelStat]] = defaultdict(list)
    for r in reels:
        groups[("hook_type", r.hook_type)].append(r)
        groups[("audio", "original" if r.original_audio else "named track")].append(r)
        groups[("caption_length", "short (< 60)" if r.caption_chars < 60 else "longer (60+)")].append(r)
        groups[("weekday", r.posted_date.strftime("%A"))].append(r)
        for tag in r.hashtags:
            groups[("hashtag", tag)].append(r)
    rows = []
    for (dim, value), members in groups.items():
        if dim in ("hashtag", "weekday") and len(members) < 2:
            continue  # one Reel isn't a pattern
        ids = [m.id for m in members]
        rows.append(
            PatternRow(
                dimension=dim,
                value=value,
                reel_ids=ids,
                median_ratio=round(statistics.median(m.ratio_vs_median for m in members), 2),
                in_top=len(top & set(ids)),
                in_bottom=len(bottom & set(ids)),
            )
        )
    return sorted(rows, key=lambda p: (p.dimension, -(p.median_ratio or 0)))


def done_stages(kind: str) -> dict[str, StageState]:
    return {name: StageState(status="done") for name in STAGES[kind]}


def events(lines: list[tuple[float, str, str, str]]) -> list[Event]:
    first = Event(t=0.0, source="system", kind="info", message=MOCK_NOTE)
    return [first] + [Event(t=t, source=s, kind=k, message=m) for t, s, k, m in lines]


def creator_report(handle: str = "mock_kitchen_a") -> CreatorReport:
    reels = build_reels(CREATOR_REELS)
    median = add_ratios(reels)
    in_window = [r for r in reels if r.in_window]
    engagement = statistics.median((r.likes + r.comments) / r.views for r in reels)
    return CreatorReport(
        profile=ProfileStats(
            handle=handle,
            profile_url=f"https://www.instagram.com/{handle}/",
            followers=48300,
            following=512,
            posts=386,
            reels_read=len(reels),
            pinned_skipped=1,
            median_views=median,
            reels_in_window=len(in_window),
            posts_per_week=round(len(reels) / ((CREATOR_REELS[-1][0] + 1) / 7), 1),
            median_engagement=round(engagement, 3),
        ),
        reels=reels,
        patterns=patterns(reels),
        insights=[
            Insight(kind="working", claim="Question hooks are your strongest opener: both question Reels reached about 4x your median views.", keys=["pat.hook_type.question", "p.median_views"], reel_ids=["r3", "r7"]),
            Insight(kind="working", claim="Original audio Reels sit well above your named-track Reels on views.", keys=["pat.audio.original", "pat.audio.named track"], reel_ids=["r1", "r3", "r7"]),
            Insight(kind="not_working", claim="Plain statement hooks (\"Simple dinner tonight\") all landed below your median.", keys=["pat.hook_type.statement"], reel_ids=["r2", "r6", "r9", "r11"]),
            Insight(kind="try_next", claim="Test a question hook with a text cover on your next recipe, e.g. a myth-check like the ghee Reel.", keys=["pat.hook_type.question", "pat.hashtag.#cookingtips"], reel_ids=["r7"]),
        ],
        insights_source="llm",
        null_reasons={"video_length": "Video length isn't on public Reel pages", "spoken_hook": "Spoken words need the video file, which public pages don't include"},
    )


def creator_job(report: CreatorReport) -> ReportJob:
    return ReportJob(
        id="mockcreator1",
        kind="creator",
        status="done",
        created_at=CREATED,
        input={"handle_or_url": report.profile.handle},
        stages=done_stages("creator"),
        events=events([
            (2.1, "scout", "progress", f"Reading @{report.profile.handle}'s Reels grid"),
            (9.4, "scout", "progress", "12 Reels read (1 pinned Reel skipped)"),
            (21.0, "scout", "progress", "Read 12 Reel pages: captions, dates, audio"),
            (22.3, "system", "progress", "4 Reels in the last 7 days; median views 13K"),
            (34.8, "llm", "progress", "Described 6 covers"),
            (51.2, "llm", "info", "4 insights passed every check"),
        ]),
        result=report,
    )


def running_job(done: ReportJob) -> ReportJob:
    job = done.model_copy(deep=True)
    job.id, job.status, job.result = "mockcreator2", "running", None
    job.stages = {"fetch": StageState(status="done"), "analyse": StageState(status="running"), "visuals": StageState(), "insights": StageState()}
    job.events = job.events[:4]
    return job


def reel_job(creator: CreatorReport) -> ReportJob:
    reel = build_reels([(2, 39000, 2800, 96, "Why is my biryani always dry? 🍚\nFix it in one step. Save this!\n#biryani #cookingtips #indianfood", "question", "Original audio", CoverNotes(text_on_cover="DRY BIRYANI FIX", face=True, setting="pot close-up", style="bright, steam visible"))], start=0)[0]
    reel.ratio_vs_median = round(reel.views / creator.profile.median_views, 2)
    report = ReelReport(
        reel=reel,
        creator=creator,
        comparison=[
            ComparisonRow(label="Views vs the creator's median", this_reel=f"{reel.ratio_vs_median}x", creator_usual="1.0x", keys=["p.median_views"]),
            ComparisonRow(label="Hook type", this_reel="question", creator_usual="statement (4 of 12 Reels)", keys=["pat.hook_type.question", "pat.hook_type.statement"]),
            ComparisonRow(label="Audio", this_reel="Original audio", creator_usual="original in 6 of 12", keys=["pat.audio.original"]),
            ComparisonRow(label="Call to action", this_reel="Save this", creator_usual="in 3 of 12 Reels", note="Their top Reels mostly ask viewers to save"),
        ],
        insights=[
            Insight(kind="working", claim="This Reel uses the creator's best hook type (a question) and beat their median about 3x.", keys=["pat.hook_type.question", "p.median_views"], reel_ids=["r0", "r3", "r7"]),
            Insight(kind="try_next", claim="Borrow the problem-question + 'save this' combination; the creator's statement hooks underperform.", keys=["pat.hook_type.statement"], reel_ids=["r0", "r2", "r9"]),
        ],
        insights_source="llm",
    )
    return ReportJob(
        id="mockreel0001",
        kind="reel",
        status="done",
        created_at=CREATED,
        input={"url": reel.source_url},
        stages=done_stages("reel"),
        events=events([(3.0, "scout", "progress", "Read the Reel page"), (24.5, "scout", "progress", "Read @mock_kitchen_a's last 12 Reels"), (48.0, "llm", "info", "2 insights passed every check")]),
        result=report,
    )


PULSE_REELS = [
    (1, 210000, 15000, 410, "Is this the easiest dal ever? 🤔\n#dal #indianfood #easyrecipes", "question", "Original audio", None),
    (2, 96000, 6100, 150, "3 monsoon snacks under 10 minutes\n#monsoonrecipes #snacks #indianfood", "number_list", "Original audio", None),
    (1, 88000, 5200, 98, "Why your dal tastes flat\n#dal #cookingtips", "question", "Mock Artist · Mock Song", None),
    (4, 54000, 3000, 61, "POV: mom tastes your dal\n#dal #homecooking", "pov", "Mock Artist · Funny Clip", None),
    (3, 47000, 2600, 44, "Monsoon pakoda in 5 steps\n#monsoonrecipes #pakoda", "number_list", "Original audio", None),
]
PULSE_HANDLES = ["mock_kitchen_b", "mock_kitchen_c", "mock_kitchen_b", "mock_kitchen_d", "mock_kitchen_e"]
PULSE_RATIOS = [5.6, 3.9, 2.4, 3.1, 2.2]  # each Reel against its own creator's median
PULSE_TOPICS = ["dal", "cooking", "dal", "dal", "cooking"]  # the keyword whose page each came from


def niche_job() -> ReportJob:
    reels = build_reels(PULSE_REELS, prefix="MOCKP")
    for r, handle, ratio, topic in zip(reels, PULSE_HANDLES, PULSE_RATIOS, PULSE_TOPICS):
        r.handle, r.ratio_vs_median, r.topic = handle, ratio, topic
    pulse = NichePulse(
        keywords=["cooking", "dal"],
        run_date=TODAY,
        creators_read=8,
        reels=reels,
        patterns=patterns(reels),
        web=[
            WebSignal(title="Mock article: monsoon recipes are trending", url="https://example.com/mock-monsoon-recipes", snippet="MOCK snippet for the UI.", retrieved_at=RETRIEVED),
            WebSignal(title="Mock post: dal hacks round-up", url="https://example.com/mock-dal-hacks", snippet=None, retrieved_at=RETRIEVED),
        ],
        previous_run_date=TODAY - timedelta(days=1),
        since_last_run=["New hashtag in outliers: #monsoonrecipes", "New hook type in outliers: number_list"],
        insights=[
            Insight(kind="working", claim="Question hooks about a common problem lead today's dal outliers.", keys=["pat.hook_type.question"], reel_ids=["r1", "r3"]),
            Insight(kind="try_next", claim="Worth testing: a quick monsoon snack list (#monsoonrecipes showed up in 2 outliers since yesterday).", keys=["pat.hashtag.#monsoonrecipes"], reel_ids=["r2", "r5"]),
        ],
        insights_source="llm",
    )
    return ReportJob(
        id="mockniche001",
        kind="niche",
        status="done",
        created_at=CREATED,
        input={"keywords": pulse.keywords},
        stages=done_stages("niche"),
        events=events([(4.0, "scout", "progress", "Reading #cooking and #dal"), (66.0, "scout", "progress", "5 outliers from 8 creators"), (70.2, "scout", "progress", "2 web results"), (88.0, "llm", "info", "2 insights passed every check")]),
        result=pulse,
    )


def write(name: str, model) -> None:
    path = MOCKS / name
    path.write_text(json.dumps(model.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n")
    print("wrote", path.relative_to(ROOT))


def main() -> None:
    creator = creator_report()
    done = creator_job(creator)
    write("report.creator.json", done)
    write("report.creator.running.json", running_job(done))
    write("report.reel.json", reel_job(creator))
    write("report.niche.json", niche_job())
    write("me.json", UserPublic(id=1, email="mock.user@example.com", ig_handle="mock_kitchen_a", profile_url="https://www.instagram.com/mock_kitchen_a/", created_at=CREATED, latest_report_id=done.id))


if __name__ == "__main__":
    main()
