# ReelMind AI

**Test your Reel before you post it, with receipts.**

Upload a draft Reel and a topic. ReelMind measures your video, sends a [TinyFish](https://www.tinyfish.ai) web agent to find what is outperforming in your niche right now, and gives you **one evidence-backed change to test as an A/B experiment**. Every claim links to the real Reel it came from.

Built by **Team Ctrl Alt Fin** for **Swim with TinyFish** (Presidency University, Bengaluru, 30 Oct 2026).

> **Status: planning.** This repo holds the product and technical docs. The code is built during the finale on 30 Oct 2026. The setup commands below describe the planned layout and will work once the code lands.

---

## The problem

- Creators see **views, not reasons**. Insights say what happened after posting, never why.
- Generic AI tips ("use a stronger hook") never look at your draft or at what's working in your niche this week.
- Raw view counts mislead: a mega-account's average Reel beats a small creator's best one.

## What ReelMind does

1. **You upload** an unposted draft (≤ 60 s) and type a topic, e.g. `cooking`.
2. **We measure your video:** cuts, pacing, first spoken words, on-screen text in the first 3 seconds, and an *estimated* payoff time.
3. **Niche Scout (TinyFish) researches live:** it opens the topic page, picks a few creators, reads their Reels grids and flags Reels that did **at least 2x that creator's own median views**.
4. **You get one card:** **Observed → Evidence → Hypothesis → Experiment**, with links to the outlier Reels and a Cut A vs Cut B plan.

We never promise virality. You get a test to run, and it says which evidence it rests on.

## How TinyFish powers it: Niche Scout

TinyFish is the research engine, not a side feature. Niche Scout is a multi-step job with a judgement in the middle, which a single LLM call can't do: an LLM can't open today's pages.

| Step | What happens | TinyFish API |
|---|---|---|
| 1 | Open the topic page (`/explore/tags/{topic}/`) and collect creators and Reel links | **Fetch** |
| 2 | Open each creator's Reels tab and read views, likes and comments for up to 12 Reels as structured JSON, with a live browser view | **Agent** (`run-sse`, `output_schema`) |
| 3 | Compute each creator's median views and each Reel's **outlier ratio** | our code |
| 4 | Open the outlier Reels and read caption, hook line, audio label, date and cover | **Fetch** |
| fallback | Find creators if the topic page is walled | **Search** |

Why an outlier ratio? A Reel at 3x its creator's median from a 20k account is better evidence for a small creator than a Reel from an account with 268M followers.

## Architecture

```
            Upload draft (mp4) + topic word
                     │
        ┌────────────┴─────────────┐   both start at once
        ▼                          ▼
 VIDEO ANALYSIS (Python)       NICHE SCOUT (TinyFish)
  cuts · transcript ·           topic page → creators →
  frames → Gemini vision        Reel grids → outliers → Reel pages
        └────────────┬─────────────┘
                     ▼
     Gemini recommendation + grounding validator
     (drops any claim without our number + a valid example)
                     ▼
     Card: Observed · Evidence links · Hypothesis · A/B experiment
```

**The rule that holds it together:** code measures, TinyFish fetches, and the LLM only interprets numbers it is given and must cite them.

## What a result looks like

_Illustrative example of the format, not real data:_

> **Observed:** Payoff arrives at ~6.2 s (estimated), after a title card. `m.payoff_at_s`
> **Evidence:** In 2 of 3 outliers (3.1x and 2.4x their creator's median), the caption's first line and the cover show the finished dish. Each links to the Reel, with its retrieval time.
> **Hypothesis:** Opening on the payoff may hold viewers past the first seconds.
> **Experiment:** Cut A = original. Cut B = start on the finished dish, title card after 2 s. Measure 3-second hold and views against your last 5 Reels.

## Tech stack

| Part | Choice |
|---|---|
| Frontend | React + Vite, one page, polls the backend every 2 s |
| Backend | Python 3.11+, FastAPI, httpx, pydantic v2 |
| Research | TinyFish Fetch, Agent and Search |
| Video | ffmpeg, PySceneDetect, faster-whisper |
| LLM + vision | Google Gemini (`gemini-3.8-flash`, fallback `gemini-3.5-flash-lite`) via `google-genai` |
| Storage | JSON files and a URL-keyed cache (no database) |

## Getting started

**Requirements:** Python 3.11+, Node 20+, `ffmpeg` on your PATH, a [TinyFish API key](https://www.tinyfish.ai) and a [Gemini API key](https://aistudio.google.com/apikey).

```bash
cp .env.example .env          # then fill in your keys
```

**Backend** (from the repo root):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

**Replay mode** (for demos on bad Wi-Fi): set `REPLAY=1` in `.env` and restart the backend. The UI shows "Replay of a recorded run, \<timestamp>" the whole time. A replay is never presented as live.

### Environment variables

| Variable | Purpose |
|---|---|
| `TINYFISH_API_KEY` | TinyFish Fetch / Search / Agent |
| `GEMINI_API_KEY` | Gemini vision and recommendation calls |
| `LLM_MODEL` | Primary model, default `gemini-3.8-flash` |
| `LLM_FALLBACK_MODEL` | Fallback model, default `gemini-3.5-flash-lite` |
| `REPLAY` | `1` serves a recorded run instead of live calls |
| `VITE_API_URL` | In `frontend/.env`: backend URL, default `http://localhost:8000` |

Keys live only in the backend's `.env`. Never commit them, never put them in the frontend.

## Project structure

```
backend/     FastAPI app: job runner, TinyFish client, Niche Scout, video pipeline, Gemini calls, validator
frontend/    React + Vite single page: upload, live research panel, recommendation card
samples/     demo clip and saved Instagram fetch outputs for tests
tests/       parser, outlier-maths and validator tests
scripts/     setup helpers and live TinyFish / Gemini test scripts
```

## Responsible data use

- **Public, logged-out pages only.** We never log in to Instagram and never bypass a login wall or captcha.
- **Small and read-only:** a handful of creators and at most ~20 pages per analysis.
- **Every source is linked** with the time we retrieved it.
- **No personal data:** we don't store commenter usernames or comment text.
- **No invented numbers:** a count we can't see is shown as missing, with the reason.
- **Honest failures:** each example shows whether it was accessible, behind a login wall, blocked, not found or timed out.

## Limitations

- We **can't see the example videos**, only what a public page shows (caption, cover, audio label, counts, date). We compare only what's visible on both sides.
- 3–5 examples show a **pattern, not proof**. That's why the output is an experiment.
- Instagram's logged-out view changes often, so a page that works today may be walled tomorrow.
- Instagram only for now. No YouTube Shorts or TikTok yet.

## Roadmap

- **Now:** one flow, from draft + topic to one cited experiment.
- **Next:** log your Cut A/B results against your own baseline, accounts and saved analyses, more signals.
- **Later:** official APIs with creator consent, YouTube Shorts and TikTok, a team plan for freelance editors.

## Team

| Name | Role |
|---|---|
| Sujita Boruah (lead) | Frontend, data checks, deck and story |
| Nishit Singh | Idea owner; video pipeline and LLM recommendation |
| Akash Shrivastav | Backend, TinyFish integration, outlier logic, integration |

## Docs

The planning docs (PRD, TRD, implementation plan, decisions, handover) and the project brief are kept privately by the team and are not in this repo.

## Thanks

[TinyFish](https://www.tinyfish.ai), Ignite Room and Presidency E-Cell for hosting **Swim with TinyFish**. #SwimWithTinyFish
