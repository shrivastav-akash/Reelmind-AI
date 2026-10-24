# Handover

## Current state
_Last updated: 2026-10-25 · claude-opus-5-5_
- **Working on:** planning docs for ReelMind AI (Swim with TinyFish finale, Fri 30 Oct 2026).
- **Done:** `docs/PRD.md`, `docs/TRD.md`, `README.md`, `docs/decisions.md`, this file. Stack chosen: React + Vite (Sujita), FastAPI, TinyFish, Gemini `gemini-3.8-flash`.
- **Next step:**
  - Tonight (Sun 25 Oct): Sujita submits the 10-page Idea Deck before 23:59; Akash creates his TinyFish account.
  - Before Tue 27 Oct: regenerate the TinyFish keys posted in WhatsApp; ask organisers whether pre-written code is allowed.
  - If shortlisted: work through the **[verify]** list in `TRD.md` (grid number order, output_schema allowlist, Fetch fields, iframe embedding, Gemini rate limits, real Agent run times).
  - Remaining planning docs if wanted: UI/UX brief, app flow, backend schema, implementation plan. `constraints.md` needs the team's sign-off.
- **Blocked on / open questions:** judging criteria (revealed Fri 10:00); pre-written code rule; demo topic + 5 creators; whether $8 TinyFish credit per account is enough.
- **Gotchas:**
  - `REELMIND_PROJECT_BRIEF.md` is the source of truth. If a doc disagrees with it, ask before deviating.
  - **No feature code before the pre-written-code rule is confirmed.** Setup, test scripts and cached samples only.
  - TinyFish `COMPLETED` does not mean success: check the result for login walls and captchas.
  - Don't send `agent_config.max_steps`, `agent_config.mode` or `capture_config` to TinyFish (403).
  - Niche Scout's worst case (2 rounds × 90 s) is longer than the ~80 s the demo script gives research. Measure on Thursday.
  - Never present a replay as live.
  - The folder isn't a git repo yet.

## Session log
_Newest first. One short entry per session._

### 2026-10-25 · claude-opus-5-5
- What changed: wrote PRD, TRD, README, decisions log and this handover from the project brief and the idea analysis, after 4 clarifying questions (LLM = Gemini, frontend = React + Vite by Sujita, PRD = MVP + short roadmap, README = team + judges). Checked current Gemini model IDs and free-tier availability on ai.google.dev.
- Why: the team needed a shared spec before the hackathon.
- Left unfinished: UI/UX brief, app flow, backend schema, implementation plan, constraints.md; no git repo; no code (by design).
