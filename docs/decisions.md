# Decisions

_Newest first. Log the why, not just the what._

### 2026-10-25 · README is for the team and the judges
- Context: the README will likely be the public GitHub page judges see.
- Options: team setup only; team + judges; product-style landing page.
- Decision: team + judges. Pitch, how TinyFish is used, setup, replay mode, responsible data use, limitations.
- Why: one page has to explain TinyFish's central role and also get a teammate running. Revisit if the project becomes a public product.
- Made by: Akash · recorded by claude-opus-5-5

### 2026-10-25 · PRD covers the MVP plus a short roadmap
- Context: Nish wants to take ReelMind forward as a startup, but Friday needs a tight MVP.
- Options: hackathon MVP only; MVP + short Now/Next/Later and business sketch; full startup PRD.
- Decision: MVP + short roadmap and business sketch.
- Why: judges usually score product potential, and the deck already has Now/Next/Later. A full startup PRD would be guesswork before any user testing.
- Made by: Akash · recorded by claude-opus-5-5

### 2026-10-25 · Frontend: React + Vite, built by Sujita
- Context: the brief allowed React (Vite) or plain HTML/JS, and left open whether Sujita codes.
- Options: React + Vite (Sujita); React + Vite (Akash, after the backend); plain HTML/JS.
- Decision: React + Vite, Sujita owns it.
- Why: frees Akash for the TinyFish + integration path, which is the critical path. Fallback: a plain HTML page served by FastAPI if the UI slips. Agree the `Job` JSON early so the UI can be built against mock data.
- Made by: Akash · recorded by claude-opus-5-5

### 2026-10-25 · LLM and vision provider: Google Gemini
- Context: one provider must accept images (frames, covers) and return JSON. The brief said "one provider the team already has a key for".
- Options: Claude, OpenAI, Gemini, provider-agnostic.
- Decision: Gemini via `google-genai`. Default `gemini-3.8-flash` (newest stable Flash, free tier), fallback `gemini-3.5-flash-lite`. All calls go through `llm_client.py`, so switching providers later touches one file.
- Why: team's choice; free tier keeps student costs at zero; structured output from a pydantic schema. Model IDs checked on ai.google.dev on 2026-10-25. Revisit if free-tier rate limits are too tight in rehearsal.
- Trade-off noted: free-tier prompts may be used to improve Google's products, so we upload only the team's own footage.
- Made by: Akash · recorded by claude-opus-5-5

### 2026-10-25 · Keep frames + local transcription (not whole-video upload to Gemini)
- Context: Gemini can take a whole video and has a transcription model with word timestamps.
- Options: send sampled frames + local faster-whisper transcript (brief's plan); send the whole clip to Gemini.
- Decision: keep the brief's plan.
- Why: cuts and transcript timings stay measured by code (deterministic, citable), only payoff is an LLM estimate, and less depends on venue Wi-Fi upload speed.
- Made by: claude-opus-5-5 (following the brief), open to team review

### 2026-10-25 · Decisions carried over from the project brief
- Context: made by the team before these docs, recorded here so the reasons aren't lost.
- **TinyFish is the research engine via Niche Scout.** The hackathon requires TinyFish to be central; the 14-page "TinyFish-light" strategy deck conflicts with that.
- **Submit the 10-page Idea Deck for Round 1**, not the 14-page strategy deck, for the same reason.
- **Compare only what's visible on both sides.** Example videos can't be fetched, so no claims about their timing.
- **Outlier ratio, not raw views:** `views / median(views of that creator's last ~12 Reels)`, keep ≥ 2.0. Advice from mega-accounts doesn't transfer to small creators.
- **One flow only.** No accounts, results logging, Postgres, beat sync or comment mining, to fit the ~4.5 h build.
- **JSON files, polling, one page.** Demo-safe and debuggable.
- Made by: Team Ctrl Alt Fin · recorded by claude-opus-5-5
