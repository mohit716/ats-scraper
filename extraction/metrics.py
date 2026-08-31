"""Scoring for extracted job descriptions.

There is no ground truth for an arbitrary career page, so the primary signals
are reference-free: did recognisable boilerplate survive, and do the expected
job-description sections appear. When a gold file exists, token-level
precision and recall are reported alongside.
"""

import re
from collections import Counter

from extraction.html_text import normalize

# Phrases that should never survive extraction. Matched case-insensitively
# against the extracted text.
BOILERPLATE_MARKERS = [
    "accept all cookies",
    "cookie policy",
    "cookie settings",
    "cookie preferences",
    "we use cookies",
    "privacy policy",
    "terms of use",
    "terms of service",
    "all rights reserved",
    "sign in",
    "log in",
    "create an account",
    "similar jobs",
    "recommended jobs",
    "related jobs",
    "other jobs",
    "jobs you might",
    "share this job",
    "back to search",
    "back to jobs",
    "view all jobs",
    "search jobs",
    "follow us",
    "subscribe to",
    "newsletter",
    "skip to main content",
    "resume/cv",
    "upload resume",
    "attach resume",
    "drop files here",
    "first name",
    "last name",
    "email address",
    "phone number",
    "linkedin profile",
]

# Headings that indicate real job-description content was captured.
JD_SECTION_MARKERS = [
    "responsibilities",
    "qualifications",
    "requirements",
    "what you",
    "who you are",
    "about the role",
    "about the team",
    "about the job",
    "the role",
    "your profile",
    "your tasks",
    "skills",
    "experience",
    "benefits",
    "we offer",
    "compensation",
    "salary",
    "equal opportunity",
]


def _count_markers(text, markers):
    lowered = (text or "").lower()
    return sorted(m for m in markers if m in lowered)


def token_prf(predicted, gold):
    """Token-level precision/recall/F1 using multiset overlap."""
    pred_counts = Counter(normalize(predicted))
    gold_counts = Counter(normalize(gold))
    if not pred_counts or not gold_counts:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    overlap = sum((pred_counts & gold_counts).values())
    precision = overlap / sum(pred_counts.values())
    recall = overlap / sum(gold_counts.values())
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def grounding(text, source):
    """Share of extracted tokens that actually occur in the source page.

    A page that is rendered client-side gives a text-mode LLM almost nothing
    to work with, and the model will happily invent a fluent, well-structured
    job description from the title alone. Such output looks excellent on every
    other metric here, so this is the check that catches it.

    The source is the raw HTML, which is deliberately permissive: markup,
    attributes and embedded JSON all count as present. Anything below ~1.0 is
    therefore text the page genuinely does not contain.
    """
    predicted = set(normalize(text))
    if not predicted:
        return None
    available = set(normalize(source))
    return round(len(predicted & available) / len(predicted), 4)


def score(text, page_text=None, source=None, gold=None):
    words = normalize(text)
    boilerplate = _count_markers(text, BOILERPLATE_MARKERS)
    sections = _count_markers(text, JD_SECTION_MARKERS)

    result = {
        "chars": len(text or ""),
        "words": len(words),
        "boilerplate_hits": len(boilerplate),
        "boilerplate_found": boilerplate,
        "jd_sections_hits": len(sections),
        "jd_sections_found": sections,
        "empty": not (text or "").strip(),
    }

    if page_text is not None:
        page_words = len(normalize(page_text))
        result["page_words"] = page_words
        # How much of the served page survived. High means boilerplate came
        # along. Meaningless when the page is client-rendered and exposes
        # almost no text, so it is left unset in that case.
        result["kept_ratio"] = (
            round(len(words) / page_words, 4) if page_words >= 50 else None
        )

    if source is not None:
        result["grounding"] = grounding(text, source)

    if gold:
        result.update(token_prf(text, gold))

    return result


def agreement(text_a, text_b):
    """Token overlap between the two approaches, as a Jaccard index."""
    a, b = set(normalize(text_a)), set(normalize(text_b))
    if not a or not b:
        return 0.0
    return round(len(a & b) / len(a | b), 4)


def sentence_leak_examples(text, limit=3):
    """Lines that look like leftover furniture, for eyeballing failures."""
    leaks = []
    for line in re.split(r"\n+", text or ""):
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if any(marker in lowered for marker in BOILERPLATE_MARKERS):
            leaks.append(stripped[:120])
        if len(leaks) >= limit:
            break
    return leaks
