"""Caption analysis (v2 task 0.4): pure functions over one public caption. No network, no LLM.

Used by creator_metrics.fill_caption_fields for every ReelStat: hashtags, mentions, keywords,
caption length, call to action and the written hook's type. Rules are deliberately simple and
explainable (a judge can check any of them by reading the caption); captions mix languages,
e.g. "Yumurta Pişirmenin En Pratik Yolu! / The Easiest Way to Cook Eggs!".
"""

from __future__ import annotations

import re
from collections import Counter

HASHTAG = re.compile(r"#(\w+)")
MENTION = re.compile(r"@([\w.]+)")
URL = re.compile(r"https?://\S+")
# Starts with a letter, any script. Python's \w skips Indic vowel signs (the "ा" in "दाल"), so the
# Indic blocks (Devanagari to Sinhala) are allowed inside a word too.
WORD = re.compile(r"[^\W\d_][\wऀ-෿'’-]*")

STOPWORDS = frozenset("""
a about after again all also am an and any are as at be because been before being both but by can could
did do does doing done down each even every for from get gets go going got had has have having he her here
him his how i if in into is it its just let lets like make makes made me more most my no not now of off on
once only or other our out over own really same she should so some such than that the their them then there
these they this those through to too under until up us very was way we were what when where which while who
why will with would you your yours
recipe recipes food reel reels video videos follow comment share save link bio
hai ka ki ke ko se aur ye yeh kya bhi nahi main mein hum aap tum karo kar ek toh to na ho hota hoti
""".split())

CTA_PHRASES = (
    "link in bio", "comment", "save this", "save it", "save for later", "save the recipe", "follow for", "follow @",
    "share this", "share with", "send this", "tag a", "tag someone", "tag your", "dm me", "click the link",
    "full recipe", "recipe below", "recipe in",
)
QUESTION_STARTS = ("why", "what", "which", "who", "where", "when", "is ", "are ", "do ", "does ", "did ", "can ",
                   "could ", "should ", "would ", "will ", "have you", "ever ", "kya ", "kaise ", "kyun ", "kyu ")
HOW_TO = re.compile(r"\b(how to|how i|how we|way to|ways to|step by step|tutorial|guide to|easy recipe|recipe for)\b")
NUMBER_LIST = re.compile(r"^(top\s+)?\d+\s+\w|\b\d+\s+(ways|tips|things|recipes|hacks|steps|ideas|ingredients|minutes?|mins?|secrets)\b")
WARNING = re.compile(r"^(stop|don'?t|do not|never|avoid|warning|mistake|you'?re doing|you are doing|quit)\b|\bmistakes?\b")
STORY = re.compile(r"^(i|i'?m|i'?ve|my|we|our|when i|today i|yesterday|last (night|week)|this is how i|so i)\b")


def hashtags(caption: str | None) -> list[str]:
    """['#cooking', '#recipe'], lowercase, first use first, no repeats."""
    return list(dict.fromkeys(f"#{t.lower()}" for t in HASHTAG.findall(caption or "")))


def mentions(caption: str | None) -> list[str]:
    return list(dict.fromkeys(f"@{m.rstrip('.').lower()}" for m in MENTION.findall(caption or "")))


def keywords(caption: str | None, limit: int = 8) -> list[str]:
    """Content words of the caption (not hashtags, mentions, links or stopwords), most used first."""
    text = URL.sub(" ", caption or "")
    text = HASHTAG.sub(" ", MENTION.sub(" ", text))
    words = [w.lower().strip("'’-") for w in WORD.findall(text)]
    counts = Counter(w for w in words if len(w) >= 3 and w not in STOPWORDS)
    return [w for w, _ in counts.most_common(limit)]


def caption_chars(caption: str | None) -> int | None:
    return len(caption.strip()) if caption is not None else None


def has_cta(caption: str | None) -> bool | None:
    """Does the caption ask for an action (comment, save, share, follow, link in bio)?"""
    if caption is None:
        return None
    text = caption.lower()
    return any(p in text for p in CTA_PHRASES)


def hook_type(hook: str | None) -> str:
    """The written hook (caption's first line) as one of report_models.HookType. Checked in this
    order, first match wins: pov, how_to, question, number_list, warning, story, else statement."""
    text = re.sub(r"\s+", " ", (hook or "")).strip().lower()
    text = HASHTAG.sub("", text).strip()
    if not text:
        return "none"
    if text.startswith("pov"):
        return "pov"
    if HOW_TO.search(text):
        return "how_to"
    if "?" in text or text.startswith(QUESTION_STARTS):
        return "question"
    if NUMBER_LIST.search(text):
        return "number_list"
    if WARNING.search(text):
        return "warning"
    if STORY.search(text):
        return "story"
    return "statement"
