"""Grounding validator: deterministic checks on what the LLM suggested.

Called by recommend.py (Fri) after every Gemini answer. The LLM may only
interpret numbers we measured and examples TinyFish actually reached, so a
suggestion is dropped if it:
- cites no measurement key, or a key we don't have;
- has an observation that quotes neither a number nor one of its keys;
- cites no example, an ID we didn't collect, or an example that wasn't accessible;
- uses a banned hype word anywhere.
There is deliberately no LLM in here: these rules must hold even when the model misbehaves.
"""

from __future__ import annotations

import re

from backend.models import Example, Suggestion, SuggestionSet, ValidatorNote, VideoMeasurements

# Prefix matches catch "virality", "algorithms", "guaranteed" as well.
BANNED_PATTERN = re.compile(r"\b(viral\w*|guarantee\w*|algorithm\w*|secret\w*|will get)\b", re.IGNORECASE)


def banned_words(text: str) -> list[str]:
    return [m.group(0).lower() for m in BANNED_PATTERN.finditer(text or "")]


def check_suggestion(s: Suggestion, known_keys: set[str], examples: dict[str, Example]) -> list[str]:
    """Every reason this suggestion breaks the grounding rules; empty means it may be shown."""
    reasons: list[str] = []

    if not s.measurement_keys:
        reasons.append("cites no measurement key")
    for key in s.measurement_keys:
        if key not in known_keys:
            reasons.append(f"measurement {key} does not exist")
    if not re.search(r"\d", s.observation) and not any(k in s.observation for k in s.measurement_keys):
        reasons.append("observation quotes no measured number")

    if not s.evidence_ids:
        reasons.append("cites no example")
    for ex_id in s.evidence_ids:
        ex = examples.get(ex_id)
        if ex is None:
            reasons.append(f"evidence id {ex_id} does not exist")
        elif ex.access_status != "accessible":
            reasons.append(f"evidence {ex_id} was not accessible ({ex.access_status})")

    texts = (s.observation, s.evidence_summary, s.hypothesis, s.experiment.cut_a, s.experiment.cut_b, s.experiment.measure)
    found = sorted({w for t in texts for w in banned_words(t)})
    if found:
        reasons.append("uses banned words: " + ", ".join(found))
    return reasons


def validate(
    answer: SuggestionSet, video: VideoMeasurements, examples: list[Example]
) -> tuple[list[Suggestion], list[ValidatorNote]]:
    """Split an LLM answer into suggestions we can show, plus a note per suggestion."""
    known = set(video.citable())
    by_id = {e.id: e for e in examples}
    kept: list[Suggestion] = []
    notes: list[ValidatorNote] = []
    for i, s in enumerate(answer.suggestions):
        reasons = check_suggestion(s, known, by_id)
        notes.append(ValidatorNote(suggestion_index=i, dropped=bool(reasons), reasons=reasons))
        if not reasons:
            kept.append(s)
    return kept, notes


def has_citable_evidence(examples: list[Example]) -> bool:
    """False means recommend.py must return `insufficient_evidence`, never a card without receipts."""
    return any(e.access_status == "accessible" for e in examples)


def retry_reasons(notes: list[ValidatorNote]) -> list[str]:
    """Reasons formatted for the regenerate prompt (docs/prompts.md §3)."""
    return [f"suggestion {n.suggestion_index + 1}: {r}" for n in notes for r in n.reasons]
