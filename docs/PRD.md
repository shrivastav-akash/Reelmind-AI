# PRD: ReelMind AI

_Last updated: 2026-10-25 · claude-opus-5-5_
_Sources: [`REELMIND_PROJECT_BRIEF.md`](../REELMIND_PROJECT_BRIEF.md) (single source of truth) and [`ReelMind AI Deep Idea Analysis.md`](../ReelMind%20AI%20Deep%20Idea%20Analysis.md). If this doc and the brief disagree, the brief wins until both are updated._

## One line
Upload a draft Reel and a topic. ReelMind measures your video, uses a TinyFish agent to find what is outperforming in your niche right now, and gives you **one evidence-backed change to test as an A/B experiment**, with every claim linked to its source.

## Problem
- **Creators see views, not reasons.** Instagram Insights tells you what happened after you posted, only for your own account, and never why.
- **Generic AI tips don't look at anything.** "Use a stronger hook" ignores your actual draft and what is working in your niche this week.
- **Raw view counts mislead.** A mega-account's average Reel beats a small creator's best one, so copying "top Reels" gives advice that doesn't transfer to a 20k-follower creator.
- **Why now:** web agents (TinyFish) can open today's public pages, navigate between them and return structured data. An LLM alone can't open today's pages or link its sources.

## Users
| Persona | Situation | What they need from ReelMind |
|---|---|---|
| Early-stage solo creator | Posts several Reels a week, no analyst, guesses at edits | One concrete change to try on *this* draft before posting |
| Student or small-brand team | Shared account, debates over which cut to post | Evidence to settle "which version" |
| Freelance social editor | Edits for clients, has to justify choices | A source-linked rationale and a test plan to show the client |

## Product principles
1. **Inform, never promise.** No virality claims. Output is labelled **Observed → Evidence → Hypothesis → Experiment**.
2. **Receipts for every claim.** Each suggestion quotes a number we measured in the draft and links at least one real Reel, with when we retrieved it.
3. **Code measures, TinyFish fetches, the LLM only interprets** numbers it is given and must cite them.
4. **Honest gaps.** A missing count is `null` plus a reason, never an estimate. A page we couldn't read is shown as `login_wall` / `blocked` / `not_found` / `timeout`.
5. **Public, logged-out pages only.** Never log in, never bypass a wall, small read-only volume.
6. **TinyFish is the research engine**, not an add-on (hackathon rule and our core value).

## Goals (hackathon, Fri 30 Oct 2026)
- **G1:** By the 15:15 freeze, the full flow runs on the demo clip in **under 3 minutes**, live or in labelled replay.
- **G2:** TinyFish is visibly central: judges watch Niche Scout move from topic → creators → grids → outliers in a live panel.
- **G3:** Every suggestion on screen passes the grounding validator (cites ≥ 1 measurement and ≥ 1 accessible example).
- **G4:** A judge can click any evidence link and land on the real Reel.
- **G5:** No silent failures: every example shows its `access_status`.

## Non-goals (v1)
- Accounts, login, saved history, results logging
- Postgres or any hosted database
- Comparing against example *videos* (they can't be fetched); we compare only what is visible on both sides
- "Trending audio" claims, virality scores, view predictions
- Beat sync, comment mining, mobile UI, scheduled monitoring
- YouTube Shorts, TikTok
- Posting to Instagram, private Instagram analytics, model training, vector DBs, bulk scraping

## Core features (v1)
| # | Feature | Why it matters | Priority |
|---|---|---|---|
| F1 | Upload a draft (mp4/mov, ≤ 60 s, ≤ 50 MB) + a topic word ("cooking") | Entry point | must |
| F2 | **Video breakdown:** cut timestamps, cuts in first 3 s, average shot length, transcript, first spoken word time, words in first 3 s, on-screen text in first 3 s, estimated payoff time (labelled "estimated", with a reason) | "What we measured in your video" | must |
| F3 | **Niche Scout (TinyFish):** topic page → 3–4 creators → each creator's Reels grid → outlier maths → outlier Reel pages | The centrepiece: live evidence from the niche | must |
| F4 | **Live research panel:** progress lines, per-creator status, outlier flags ("3.1x this creator's median"), live browser view if it can be embedded | Makes the agent's work visible | must |
| F5 | **Recommendation card:** one primary suggestion with Observed · Evidence (links + `retrieved_at`) · Hypothesis · Experiment (Cut A vs Cut B, what to measure) | The output | must |
| F6 | **Grounding validator:** drops suggestions without our numbers or valid example IDs, blocks hype words, regenerates once, then falls back to a template | Keeps "evidence-backed" true | must |
| F7 | **Per-example status:** accessible / login_wall / blocked / not_found / timeout | Trust, and demo beat "when we can't see it, we say so" | must |
| F8 | **Replay mode** with a visible "Replay of a recorded run, <timestamp>" banner | Demo safety on venue Wi-Fi | must |
| F9 | Logs of every TinyFish and Gemini request/response | Debugging under time pressure | should |
| F10 | Up to 2 extra suggestions below the primary one | More value per run | could |
| F11 | Cover comparison: draft's first frame vs outliers' cover images | One more visible-on-both-sides signal | could |

## What we compare (and what we can't)
| Signal | Your draft (we measure) | Outlier examples (we can see) |
|---|---|---|
| Opening / hook | First frame, on-screen text and spoken words in first 3 s | Cover image, caption's first line (the written hook) |
| Payoff timing | Estimated `payoff_at_s` | Not visible (no video). Only whether the cover or hook line shows the result |
| Pacing | Cuts, cuts in first 3 s, average shot length | Not visible |
| Audio | Speech present, first word time | Audio label ("Original audio" vs a track name) |
| Performance | none (unposted) | Views, likes, comments, post date, **outlier ratio** = views ÷ median views of that creator's last ~12 Reels (keep ≥ 2.0) |

## User flow (happy path)
1. Open the page, upload the draft, type a topic, press **Analyse**.
2. Two panels fill in parallel: **Your video** (breakdown) and **Niche Scout** (live research).
3. Outliers appear one by one, each with ratio, link, retrieval time and status.
4. The recommendation card appears. Clicking an evidence link opens the real Reel.
5. The user takes the Cut A / Cut B plan away and posts both versions (logging results is a Next feature).

## User stories
- As a solo creator, I want to upload my unposted draft and a topic so that I get one specific change to test before posting.
- As a creator, I want each suggestion to show the number from my video and the Reels it's based on, so that I can decide whether to trust it.
- As a creator, I want to see which examples couldn't be read, so that I know how much evidence the suggestion rests on.
- As a freelance editor, I want a Cut A / Cut B plan with what to measure, so that I can run a test and show my client the result.
- As a judge, I want to watch the agent research live and click a source, so that I can see the TinyFish work is real.

## Success metrics
**Hackathon (Fri 30 Oct)**
- End-to-end time on the demo clip: < 3 min (target ~2 min live)
- Niche Scout returns ≥ 3 accessible outliers (ratio ≥ 2.0) for the demo topic
- 0 suggestions on screen fail validation; 0 banned words on screen
- 5 of 5 hand-checked numbers match Instagram
- TinyFish Agent spend ≤ ~$0.50 per analysis (estimate: 4 runs × ≤ 8 steps × $0.016; measure real step counts on Thursday)

**After the hackathon (if Nish takes it forward)**
- Share of users who actually post both cuts (self-reported, then logged)
- Repeat analyses per creator per week
- Free → paid conversion

## Roadmap
- **Now (Fri 30 Oct):** the one flow above.
- **Next (weeks after):** log Cut A/B results against the creator's own last 5 Reels; accounts and saved analyses; caption length and post-time signals; more reliable caching; a hosted deploy.
- **Later:** official APIs with creator consent (own insights); YouTube Shorts and TikTok via the Agent; a team plan for freelancers; learning, across many logged experiments, which kinds of change tend to move numbers.

## Business model (startup sketch)
- Freemium per analysis, then a paid creator tier, then a team plan for freelancers and small agencies.
- Paid tools in this space charge $10–$149/month, which shows creators pay.
- Cost per analysis is mostly TinyFish Agent steps (~$0.016/step) and Gemini tokens. Fetch and Search are free.
- Moat to test: draft-before-posting + niche-relative outliers + an experiment loop that builds results data over time.

## Competition and positioning
Reelyze, Creator Decoder, Virlo, VideoToTextAI, TikAlyzer, Brika, Retensis ([BIGVU roundup, Aug 2026](https://bigvu.tv/blog/5-best-ai-instagram-reel-analyzers-2026-stop-guessing-why-your-reels-flop/)).
Don't claim the category. Claim the combination: **your unposted draft + live, source-linked outliers from your niche + one experiment.** They give scores. We give a test with receipts.

## Product risks
| Risk | Mitigation |
|---|---|
| Instagram's logged-out wall tightens before Friday | Re-test every demo URL Thu 29 Oct; URL cache; honest status per example |
| 3–5 examples is a tiny sample; correlation isn't causation | Hypothesis + experiment labels; say "pattern in N examples", never "this works" |
| Judges ask about scraping / Instagram terms | Public pages, no login, small read-only volume, every source linked, no commenter usernames stored |
| Crowded market | Combination positioning above |
| Agent runs are slow | Run both streams in parallel, cap each run, show outliers as they arrive, labelled replay as backup |

## Open questions
- Judging criteria (revealed at the 10:00 workshop on Fri 30 Oct).
- Is pre-written code allowed before the finale? Until confirmed, pre-event work is setup only.
- Demo topic and its 5 creators (likely "cooking"; pick and re-test by Thu 29 Oct).
- Is the $8 TinyFish wallet per account enough, or will organisers add credits?
- Does Niche Scout fit the demo's time budget? The script allows ~80 s for research (see TRD, risks).
