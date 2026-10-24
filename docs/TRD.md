# TRD: ReelMind AI

_Last updated: 2026-10-25 · claude-opus-5-5_
_Builds on [`PRD.md`](PRD.md). Raw facts (TinyFish limits, Instagram test results) come from [`REELMIND_PROJECT_BRIEF.md`](../REELMIND_PROJECT_BRIEF.md) §5–§8. Items marked **[verify]** are unconfirmed: test them before relying on them._

## Ground rules for the build
- **Code measures, TinyFish fetches, the LLM only interprets** numbers it is handed and must cite them.
- **TinyFish stays central.** Never refactor it into an optional add-on.
- Keys live in `.env` on the backend only: never in code, the frontend, on-screen logs or git. Ship `.env.example`.
- Public, logged-out pages only. No vault credentials, no browser profiles, no getting past a login wall.
- Never invent data: a missing count is `null` plus a reason.
- Prefer demo-safe choices: JSON files, polling over websockets, one page.

## Tech stack
| Layer | Choice | Why | Alternatives considered |
|---|---|---|---|
| Frontend | React + Vite, one page, polls the backend every 2 s. Built by Sujita. Styling: plain CSS or Tailwind, whichever she's faster with | Team knows React; Vite needs no config; polling is simpler than websockets | Plain HTML/JS served by FastAPI (fallback if the UI slips); Next.js (overkill) |
| Backend | Python 3.11+, FastAPI, uvicorn, httpx (async), pydantic v2, python-multipart, python-dotenv | Video and ML tooling is Python; async runs both streams in parallel | Node/Express (weak video and transcription tooling) |
| Research engine | **TinyFish**: Fetch (free), Agent via `run-sse` ($0.016/step), Search (free, optional) via the `tinyfish` SDK + raw httpx for SSE | Hackathon rule; multi-step navigation, structured JSON, live browser view | Our own Playwright scraper (would make TinyFish a side add-on) |
| Video | ffmpeg (system), PySceneDetect `[opencv]`, faster-whisper (`base` or `small`, CPU, word timestamps) | Runs locally and deterministically, so it doesn't depend on venue Wi-Fi | Gemini 3.5 Transcribe (has word timestamps, but adds a network upload) |
| LLM + vision | **Google Gemini** via `google-genai`. Default `gemini-3.8-flash`, fallback `gemini-3.5-flash-lite` | Team's choice; image input; JSON output from a pydantic schema; both models have a free tier | Claude, OpenAI (no team key) |
| Storage | JSON files under `data/` + a URL-keyed cache with `retrieved_at` | Zero setup, easy to inspect, easy to replay | SQLite (only if we need queries); Postgres (out of scope) |
| Auth | None | Single-user local demo | Next phase |
| Hosting | Akash's laptop for the demo, phone hotspot as backup | No deploy risk on the day | Railway / Render (Next phase) |

Model IDs checked against [Gemini models](https://ai.google.dev/gemini-api/docs/models) (page updated 2026-10-22) and [pricing](https://ai.google.dev/gemini-api/docs/pricing) on 2026-10-25. Free-tier rate limits for our key are **[verify]** in AI Studio.

## System overview
```
          React page: upload draft (mp4) + topic word
                           │  POST /analyze  → job_id
                           ▼
                 FastAPI job runner (jobs.py)
          ┌────────────────┴─────────────────┐   asyncio.gather, both start at once
          ▼                                  ▼
 VIDEO STREAM (video.py, vision.py)   NICHE SCOUT (niche_scout.py)        ← the star
  1. ffmpeg transcode to 720p          1. Topic page          TinyFish Fetch
  2. Cuts: PySceneDetect               2. Creators' Reel grids TinyFish Agent (run-sse, ≤ 2 at once)
  3. Transcript: faster-whisper        3. Outlier maths        our code
  4. Frames → Gemini vision            4. Outlier Reel pages   TinyFish Fetch
          └────────────────┬─────────────────┘
                           ▼
        recommend.py: one Gemini call → validate.py (deterministic)
                           ▼
           job JSON in data/jobs/  ←  GET /jobs/{id} every 2 s  ←  React
```
- **Job runner:** `POST /analyze` saves the upload, creates a job, starts `video_task` and `scout_task` as asyncio tasks, then runs `recommend` once both finish (or once Scout has ≥ 3 accessible outliers and the video is done; see Risks).
- Every stage appends human-readable events to the job (`"Opening @handle's Reels tab"`, `"3.1x this creator's median"`) that the live panel renders.
- All TinyFish and Gemini calls go through two thin wrappers (`tinyfish_client.py`, `llm_client.py`) that log the request and response to `logs/`.

## Backend API
| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/analyze` | multipart: `file` (mp4/mov), `topic` (string) | `202 {"job_id": "..."}`; `400` with a reason if the file fails the guard |
| GET | `/jobs/{job_id}` | none | Full `Job` (below). Frontend polls every 2 s until `status` is `done` or `failed` |
| GET | `/health` | none | `{"ok": true, "replay": false, "tinyfish_key_loaded": true, "gemini_key_loaded": true}` (booleans only, never the keys) |

CORS allows `http://localhost:5173`. The frontend reads the API base from `VITE_API_URL`.

## Data models (pydantic, `models.py`)
**Job**
```
id, status: queued|running|done|failed, created_at, topic
replay: bool, replay_recorded_at: str | None
stages: {video, scout, recommend}: pending|running|done|failed (+ reason)
events: [{t, source: video|scout|llm, kind: progress|streaming_url|outlier|error, message}]
video: VideoMeasurements | None
examples: [Example]
recommendation: Recommendation | None
```

**VideoMeasurements.** Every field has a citable key (`m.<name>`), and each is tagged `measured` or `estimated`.
| Key | Source | Tag |
|---|---|---|
| `m.duration_s` | ffprobe | measured |
| `m.cut_times_s`, `m.cuts_first_3s`, `m.avg_shot_length_s` | PySceneDetect | measured |
| `m.transcript`, `m.first_word_at_s`, `m.words_first_3s` | faster-whisper | measured |
| `m.text_overlay_first_3s`, `m.opening_description` | Gemini vision | estimated |
| `m.payoff_at_s` + `payoff_reason` | Gemini vision | **estimated** (always labelled so in the UI) |

**Example** (one per outlier Reel, IDs `ex1`…`ex5`)
```
id, source_url, retrieved_at (ISO), method: fetch|agent
access_status: accessible|login_wall|blocked|not_found|timeout, status_reason
handle, caption, hook_line (first caption line), audio_label, posted_date
likes, comments, views (int | None), creator_median_views, outlier_ratio
cover_url, null_reasons: {field: reason}
```
Never stored: commenter usernames or comment text. Comments are counts only.

**Recommendation**
```
suggestions: [{observation, measurement_keys: [m.*], evidence_ids: [ex*],
               evidence_summary, hypothesis,
               experiment: {cut_a, cut_b, measure}}]
source: llm | llm_retry | template | insufficient_evidence
validator_report: [{suggestion_index, dropped: bool, reasons: [...]}]
```

**Files on disk**
```
data/uploads/{job_id}.mp4          transcoded draft (local only)
data/jobs/{job_id}.json            job state, rewritten on each update
data/cache/{sha1(url)}.json        {url, retrieved_at, method, raw, parsed}
backend/cache/replay/*.json        recorded full jobs for REPLAY=1
logs/                              every TinyFish + Gemini request/response (gitignored, keys redacted)
samples/                           demo clip + saved Instagram fetch outputs for tests
```

## TinyFish integration (`tinyfish_client.py`, `niche_scout.py`, `instagram_parse.py`)

### Which surface does which step
| Step | Surface | Cost | Detail |
|---|---|---|---|
| 1. Topic page | Fetch `https://www.instagram.com/explore/tags/{topic}/` (redirects to `/popular/{topic}/`) | free | Collect creator handles and Reel links. Pick 3–4 creators; prefer smaller accounts, skip mega-brands |
| 2. Creator grids | **Agent** `run-sse` on `https://www.instagram.com/{handle}/reels/` with `output_schema`; `asyncio.Semaphore(2)` | $0.016/step | Up to 12 Reels per creator with views/likes/comments + URL. Fallback: Fetch + grid parser |
| 3. Outlier maths | our code | none | `median_views` per creator; `outlier_ratio = views / median_views`; keep ≥ 2.0; take the top 3–5 overall |
| 4. Outlier Reel pages | Fetch, up to 10 URLs per call | free | Parse `og:description`, audio label, `published_date`, `og:image` (download the cover right away, since CDN URLs expire) |
| (fallback) Find creators | Search | free | Only if the topic page is walled |

Limits: Fetch 150 URLs/min and 1,000/day; Search 30/min; Agent **2 concurrent runs per account**; $8 starting wallet per account.

### Agent calls
- Endpoint `POST https://agent.tinyfish.ai/v1/automation/run-sse`, header `X-API-Key`. Body: `url`, `goal`, `output_schema`, `browser_profile` (`lite`), `agent_config.max_duration_seconds` (90).
- **Never send** `agent_config.max_steps`, `agent_config.mode` or `capture_config` (gated, they return `403`). No vault, no profiles.
- Forward `PROGRESS` and `STREAMING_URL` events to the job's event list. SSE has **no reconnection**: if the stream drops, poll `GET /v1/runs/{id}`.
- **COMPLETED is not success.** Scan the result for `captcha`, `blocked`, `access denied`, `log in`, `could not`, `unable to` and set `access_status` from what you find.
- Try `lite` first. Retry once with `stealth` + TinyFish proxy (`country_code: IN`) **only on a bot block, never on a login wall**. Never retry mid-demo: fall back to the cache.
- Validate the agent result with pydantic even though `output_schema` was sent.

Goal template and schema (grid step), from brief §7:
```
You are on the public Instagram Reels tab of @{handle}. Do not log in, do not click
"Log in" or "Sign up", do not submit anything. Read the Reel tiles visible without
logging in (at most 12). For each tile return the Reel URL and the view, like and
comment counts exactly as shown (e.g. "18.5K"); use null for any count not shown.
If a login wall or captcha blocks the page, return blocked=true with blocked_reason.
Stop after reading the visible tiles.
```
```json
{"type": "object",
 "properties": {
   "handle": {"type": "string"}, "blocked": {"type": "boolean"}, "blocked_reason": {"type": "string"},
   "reels": {"type": "array", "items": {"type": "object",
     "properties": {"reel_url": {"type": "string"}, "views": {"type": "string"},
                    "likes": {"type": "string"}, "comments": {"type": "string"}},
     "required": ["reel_url"]}}},
 "required": ["handle", "blocked"]}
```

### Failure → status mapping
| What TinyFish returns | Example / job outcome | Shown in UI |
|---|---|---|
| COMPLETED, `blocked=false`, reels present | `accessible` | numbers + link |
| COMPLETED but result mentions log in, or `blocked=true` | `login_wall` | "Login wall, skipped" |
| Captcha, `SITE_BLOCKED` | `blocked` (retry once with stealth, not mid-demo) | "Blocked" |
| `TIMEOUT`, or `max_duration_seconds` hit | `timeout` | "Timed out" |
| Page missing | `not_found` | "Not found" |
| `TASK_FAILED`, `MAX_STEPS_EXCEEDED` | `blocked`, `status_reason` = raw code | "Failed: TASK_FAILED" |
| `401`, `403`, `BILLING_REJECTED` | job-level error | "TinyFish key or credits problem": swap to the spare key or use replay |
| `429 RATE_LIMIT_EXCEEDED` | wait `retry_after` once (rehearsal only) | "Rate limited" |

### Instagram parsing (`instagram_parse.py`)
- `og:description` regex (DOTALL) from brief §6A, including the hidden-likes variant. Use it instead of the page's jammed counts line (`711.3K1.8K`).
- Count normaliser: `"18.5K"` → 18500, `"1.9M"` → 1900000, `"8,340"` → 8340, hidden → `None` + reason.
- Grid parser (Fetch fallback): three unlabelled numbers per tile, read as likes, comments, views. **[verify]** that order and the tile-to-link mapping against 3 single Reel pages.

### Budget
- About 4 Agent runs per analysis. At ≤ 8 steps each that's ~$0.50, so one $8 wallet covers ~15 live analyses. **Rehearse in replay mode** and save live runs for real tests.
- Default step cap is 150 (up to $2.40 for one runaway run), so keep goals bounded with an explicit stop.

## Gemini integration (`llm_client.py`, `vision.py`, `recommend.py`)
- SDK `google-genai`: `client = genai.Client(api_key=settings.gemini_api_key)`, async via `client.aio.models.generate_content`.
- Model from `LLM_MODEL` (default `gemini-3.8-flash`). On a rate-limit or 5xx error, retry once on `LLM_FALLBACK_MODEL` (`gemini-3.5-flash-lite`).
- JSON output: `response_mime_type="application/json"` + `response_schema=<pydantic model>`, then `Model.model_validate_json(resp.text)` anyway. Temperature 0.2.
- Images are sent as `types.Part.from_bytes(data=jpg, mime_type="image/jpeg")`.

```python
resp = await client.aio.models.generate_content(
    model=settings.llm_model,
    contents=[prompt, *[types.Part.from_bytes(data=f, mime_type="image/jpeg") for f in frames]],
    config=types.GenerateContentConfig(
        temperature=0.2,
        response_mime_type="application/json",
        response_schema=VisionResult,
    ),
)
vision = VisionResult.model_validate_json(resp.text)
```

**Call 1, vision:** sampled frames (with their timestamps) + transcript with word times → `payoff_at_s`, `payoff_reason`, `text_overlay_first_3s`, `opening_description`.
**Call 2, recommendation:** keyed measurements (`m.payoff_at_s=6.2`, …) + accessible examples (`ex1`…`ex5`) → `Recommendation`. The prompt forbids virality claims and anything not in the inputs.

## Video pipeline (`video.py`)
1. **Guard:** mp4/mov, ≤ 60 s, ≤ 50 MB; otherwise `400` with a reason.
2. **Transcode:** `ffmpeg -i in -vf scale=-2:720 -r 30 -c:v libx264 -preset veryfast -c:a aac out.mp4`.
3. **Cuts:** PySceneDetect `ContentDetector` → `cut_times_s`, `cuts_first_3s`, `avg_shot_length_s`.
4. **Transcript:** faster-whisper `base` (or `small` if time allows), CPU, `word_timestamps=True` → `first_word_at_s`, `words_first_3s`.
5. **Frames:** at 0, 0.5, 1, 1.5, 2, 3 s plus one per cut, capped at ~12, JPEG.
6. **Vision call** (above). Skip beat sync.

## Grounding validator (`validate.py`, deterministic)
Drop a suggestion if:
- `measurement_keys` is empty or names a key that isn't in `VideoMeasurements`;
- `evidence_ids` is empty or names an ID that isn't in the collected examples;
- any cited example has `access_status != accessible`;
- any text field contains a banned word (case-insensitive): `viral`, `guarantee`, `guaranteed`, `algorithm`, `will get`, `secret`.

Then:
1. If at least one suggestion survives → render it (`source: llm`).
2. Else regenerate **once**, passing the validator's reasons back in the prompt (`source: llm_retry`).
3. Else build a **template** suggestion from the measurements and the accessible examples (`source: template`).
4. If there are **no accessible examples at all**, show `insufficient_evidence`: the breakdown and the statuses, but no hypothesis card. Never a suggestion without receipts.

Rendering rules: every evidence item shows `source_url` + `retrieved_at`; copy says "pattern in N examples", never "this works"; `payoff_at_s` always shows "estimated".

## Frontend (`frontend/`, Sujita)
- Components: `UploadForm`, `VideoBreakdown`, `NicheScoutPanel` (event lines, creator rows with status, outlier chips, live browser iframe or link), `ExampleCard` (status badge with a text label, not colour only), `RecommendationCard`, `ReplayBanner`.
- One hook, `useJob(jobId)`, polls `GET /jobs/{id}` every 2 s and stops on `done`/`failed`.
- Evidence links open in a new tab (`target="_blank" rel="noopener noreferrer"`).
- **[verify]** whether TinyFish's `streaming_url` can be embedded in an iframe; if not, show it as a link.

## Replay mode and caching
- `REPLAY=1`: `/analyze` loads the newest recorded job from `backend/cache/replay/` and replays its events with the original relative timing, so the panel still animates. The UI shows **"Replay of a recorded run, <recorded_at>"** at all times. Never present a replay as live.
- Recording: a finished live job in `data/jobs/` is copied into `backend/cache/replay/` (manual step at the 15:15 freeze).
- URL cache: if a live fetch fails, use the cached response for that URL and show its original `retrieved_at`, so it's clear the data is older.

## Non-functional requirements
- **Performance:** end-to-end < 3 min on a 30 s clip. Video stream < 60 s on CPU. Niche Scout should take ≤ ~80–100 s to match the demo script (see Risks). Polling every 2 s.
- **Security and privacy:** keys only in backend `.env`; `logs/` redacts `X-API-Key` and the Gemini key; `.env`, `logs/`, `data/` are gitignored. **Regenerate the keys that were posted in the WhatsApp group.** No commenter usernames stored. ≤ ~20 Instagram pages per analysis. Uploaded drafts stay on the laptop. Gemini's free tier may use prompts to improve Google's products, so upload only the team's own footage.
- **Accessibility:** keyboard-usable upload; statuses use text labels as well as colour; high contrast for the projector.
- **Scale:** one user, one laptop, one analysis at a time (Agent concurrency is 2 per account).
- **Reliability:** every external call has a timeout; every failure maps to a visible status; replay, URL cache and a screen recording as backups.

## Environments and deployment
- **Local only for Friday.** Backend: `uvicorn backend.main:app --reload --port 8000`. Frontend: `npm run dev` (Vite, port 5173).
- System requirements: Python 3.11+, Node 20+, ffmpeg on `PATH`.
- Python deps (`backend/requirements.txt`): `fastapi`, `uvicorn[standard]`, `httpx`, `pydantic>=2`, `python-multipart`, `python-dotenv`, `tinyfish`, `google-genai`, `scenedetect[opencv]`, `faster-whisper`.

| Env var | Example | Purpose |
|---|---|---|
| `TINYFISH_API_KEY` | (secret) | TinyFish Fetch / Search / Agent |
| `GEMINI_API_KEY` | (secret) | Gemini vision + recommendation |
| `LLM_MODEL` | `gemini-3.8-flash` | Primary model |
| `LLM_FALLBACK_MODEL` | `gemini-3.5-flash-lite` | Used once on a rate-limit or server error |
| `REPLAY` | `0` | `1` serves a recorded run |
| `VITE_API_URL` | `http://localhost:8000` | Frontend → backend base URL (`frontend/.env`) |

Spare TinyFish key: swap it into `.env` and restart the backend.

## Repo layout
```
backend/
  main.py              FastAPI routes: POST /analyze, GET /jobs/{id}, GET /health
  config.py            env loading, REPLAY flag
  models.py            pydantic schemas (Job, VideoMeasurements, Example, Recommendation)
  jobs.py              job store; runs video + scout in parallel, then recommend
  tinyfish_client.py   fetch(), search(), agent_stream(), run polling; logs every call
  instagram_parse.py   og:description regex, count normaliser, grid parser
  niche_scout.py       topic → creators → grids → outliers → reel pages
  video.py             ffmpeg transcode, scene cuts, whisper, frame sampling
  llm_client.py        Gemini wrapper: model + fallback, JSON schema, logging
  vision.py            hook / payoff / overlay call
  recommend.py         recommendation prompt + call
  validate.py          grounding rules
  cache/replay/        recorded runs for REPLAY=1
  requirements.txt
frontend/              Vite React app
samples/               demo clip, saved Instagram fetch outputs
tests/                 parser, outlier and validator tests
data/  logs/           runtime output (gitignored)
docs/                  PRD, TRD, decisions, handover
.env.example
README.md
```

## Testing
- **Unit:** `og:description` regex (with and without likes), count normaliser, grid parser against saved fetch outputs in `samples/`; outlier maths (missing views, fewer than 3 Reels, ratio threshold); validator (unknown key, unknown ID, non-accessible example, banned word, the insufficient-evidence path).
- **End to end at 14:45:** (1) demo clip live, (2) demo clip in replay, (3) a run where one creator is walled, to show the honest status.
- **Data check:** Sujita hand-checks 5 numbers against Instagram.

## Build plan (Fri 30 Oct, 11:30–16:00)
| Time | Akash (backend + TinyFish) | Nish (video + LLM) | Sujita (React UI + data + story) |
|---|---|---|---|
| 11:30 | Repo, `.env`, FastAPI stub, 1 Fetch + 1 Agent call | ffmpeg + whisper ready, one Gemini call with a frame | Vite app shell, demo clip, check demo URLs load |
| 11:50 | Fetch parser, Niche Scout agent, outlier maths | Cuts, transcript, frames, vision call | Upload form, live panel, card with mock JSON; hand-check 5 numbers |
| 13:30 (lunch) | Job runner joins streams, cache + REPLAY | Recommendation prompt + validator | Wire UI to the real API, slides with real screenshots |
| 14:45 | **Everyone:** 3 end-to-end test cases, fix only blockers | | |
| **15:15 freeze** | Record a replay run | Screen-recording backup | Final slides + script |
| 15:45 | **Everyone:** rehearse twice on venue Wi-Fi; demos at 16:00 | | |

Agree the `Job` JSON shape first thing, so Sujita can build against mock data while the backend is in progress.

## Risks and unknowns
| Risk | Impact | Mitigation |
|---|---|---|
| **Niche Scout time vs demo script.** 4 runs at 2 concurrent = 2 rounds; at the 90 s cap that is up to 180 s, but the script gives research ~80 s | Card arrives late on stage | Measure real run times Thursday; use 3–4 creators; consider a 60–75 s cap for the demo; show outliers as each creator finishes; start `recommend` once ≥ 3 accessible outliers exist; replay as backup |
| Instagram wall tightens | Fewer or no examples | Re-test demo URLs Thu 29 Oct; URL cache; honest statuses |
| Agent credits run out | No live research | Rehearse in replay; spare key; check wallet before the demo |
| Venue Wi-Fi | Live calls fail | Hotspot, replay, screen recording |
| Gemini free-tier limits | Vision or recommend call fails | Fallback model; cached vision result for the demo clip |

**[verify] before Friday**
- `/reels/` grid number order (likes, comments, views) and the tile-to-link mapping
- TinyFish Structured Output keyword allowlist; test the grid `output_schema`
- Fetch response fields via SDK/REST (`published_date`, og tags); else request `format="html"` and parse `<meta property="og:...">`
- Raw REST endpoints for Fetch and Search
- Whether `streaming_url` embeds in an iframe
- Gemini free-tier rate limits for `gemini-3.8-flash` on the team's key
- Real Agent step counts and durations per grid run
- Whether pre-written code is allowed before the finale (until then, setup only)
