"""Defines "done" for caption_analysis.py (v2 task 0.4): real captions from the 29-30 Oct pages
plus the hooks creators actually write, in English, Hinglish and mixed languages."""

import pytest

from backend import caption_analysis as ca

PRINCIA = "Egg Flower Omelette 🍳\n\nRecipe inspired by : @foodtalesofparomita \n\n#explorepage #foryou #cooking #recipes #omelette"
EYLEM = "Yumurta Pişirmenin En Pratik Yolu! 🍳/ The Easiest Way to Cook Eggs! \n\n#food #foodlover #cooking #recipe #eggs"


def test_hashtags_lowercase_in_order_without_repeats():
    assert ca.hashtags(PRINCIA) == ["#explorepage", "#foryou", "#cooking", "#recipes", "#omelette"]
    assert ca.hashtags("#Dal #dal #DAL tadka") == ["#dal"]
    assert ca.hashtags(None) == [] and ca.hashtags("no tags") == []


def test_mentions():
    assert ca.mentions(PRINCIA) == ["@foodtalesofparomita"]
    assert ca.mentions("thanks @chef.anna.") == ["@chef.anna"]


def test_keywords_skip_tags_mentions_links_and_stopwords():
    words = ca.keywords(PRINCIA)
    assert words[:3] == ["egg", "flower", "omelette"]
    assert not any(w.startswith(("#", "@")) for w in words) and "inspired" in words
    assert "recipe" not in words  # too common in this domain to say anything
    assert ca.keywords("Check https://example.com/x for the best dal dal dal") == ["dal", "check", "best"]


def test_keywords_in_other_scripts():
    assert "pişirmenin" in ca.keywords(EYLEM) and "yumurta" in ca.keywords(EYLEM)
    assert ca.keywords("दाल तड़का बनाने का तरीका")[:2] == ["दाल", "तड़का"]  # whole words, vowel signs kept


def test_caption_chars_and_none():
    assert ca.caption_chars("  abc  ") == 3 and ca.caption_chars("") == 0 and ca.caption_chars(None) is None


@pytest.mark.parametrize(
    "caption, cta",
    [
        ("Save this for later!", True),
        ("Comment ROTI for the full recipe", True),
        ("Link in bio 🔗", True),
        ("Follow for more easy dinners", True),
        ("Tag someone who needs this", True),
        ("Sosisli Tost 🌭 / Sausage Toast\n\n#food", False),
        (None, None),
    ],
)
def test_has_cta(caption, cta):
    assert ca.has_cta(caption) is cta


@pytest.mark.parametrize(
    "hook, kind",
    [
        ("POV: you forgot to soak the chana", "pov"),
        ("pov - mom tastes your dal", "pov"),
        ("How to make soft rotis every time", "how_to"),
        ("Yumurta Pişirmenin En Pratik Yolu! 🍳/ The Easiest Way to Cook Eggs!", "how_to"),
        ("Why does restaurant dal taste better? 🤔", "question"),
        ("Is ghee actually healthy", "question"),
        ("Kya aapne kabhi aisa paneer banaya hai", "question"),
        ("3 chutneys you can make in 5 minutes 🌿", "number_list"),
        ("Top 5 breakfast ideas", "number_list"),
        ("Dinner ready in 10 minutes", "number_list"),
        ("Stop adding salt before this step", "warning"),
        ("Don't make this mistake with rice", "warning"),
        ("My mom's Sunday rajma", "story"),
        ("I tried the viral feta pasta", "story"),
        ("Sosisli Tost 🌭 / Sausage Toast", "statement"),
        ("Viral Egg 🍳", "statement"),
        ("#cooking #recipe", "none"),
        ("", "none"),
        (None, "none"),
    ],
)
def test_hook_type(hook, kind):
    assert ca.hook_type(hook) == kind


def test_hook_types_are_the_contracts():
    from typing import get_args

    from backend.report_models import HookType

    allowed = set(get_args(HookType))
    for hook in ("POV x", "How to x", "Why x?", "3 ways", "Stop x", "My x", "x", None):
        assert ca.hook_type(hook) in allowed
