"""Confidence score for a deterministic extraction.

The hybrid router needs to answer one question without a human or an LLM in
the loop: did these rules actually work on this page? The signals below are
all things that can be checked locally against the extracted text, so scoring
is free.

A low score means either the rules missed, or the page changed shape. Either
way the caller should fall back to the LLM and consider relearning.
"""

from extraction import metrics

MIN_USABLE_CHARS = 200
MAX_PLAUSIBLE_CHARS = 60000

DEFAULT_THRESHOLD = 0.70

WEIGHTS = {
    "has_text": 0.20,
    "rule_quality": 0.15,
    "has_sections": 0.20,
    "low_boilerplate": 0.15,
    "plausible_share": 0.10,
    "grounded": 0.20,
}


def _rule_quality(rule):
    rule = rule or ""
    if "->" in rule:
        # Learned rule missed and something else caught it.
        return 0.25
    if rule.startswith("css:"):
        return 1.0
    if rule.startswith("jsonld:"):
        return 0.9
    if rule.startswith("generic-css:"):
        return 0.5
    return 0.0


def _low_boilerplate(hits):
    return {0: 1.0, 1: 0.6, 2: 0.3}.get(hits, 0.0)


def _grounded(value):
    """Text that is not present in the source page was invented."""
    if value is None:
        return 0.5
    if value >= 0.98:
        return 1.0
    if value >= 0.90:
        return 0.8
    if value >= 0.75:
        return 0.35
    return 0.0


def _plausible_share(kept_ratio):
    if kept_ratio is None:
        return 0.5
    if 0.05 <= kept_ratio <= 0.85:
        return 1.0
    if kept_ratio > 0.85:
        # Kept nearly the whole page: navigation and footer came along.
        return 0.2
    return 0.4


def score(text, rule, page_text=None, scored=None):
    """Return (confidence, signals). `scored` reuses metrics.score if present."""
    scored = scored if scored is not None else metrics.score(text, page_text=page_text)
    length = len(text or "")

    signals = {
        "has_text": 1.0 if MIN_USABLE_CHARS <= length <= MAX_PLAUSIBLE_CHARS else 0.0,
        "rule_quality": _rule_quality(rule),
        "has_sections": min(scored.get("jd_sections_hits", 0) / 3.0, 1.0),
        "low_boilerplate": _low_boilerplate(scored.get("boilerplate_hits", 0)),
        "plausible_share": _plausible_share(scored.get("kept_ratio")),
        "grounded": _grounded(scored.get("grounding")),
    }

    total = sum(WEIGHTS[k] * v for k, v in signals.items())
    return round(total, 3), {k: round(v, 3) for k, v in signals.items()}
