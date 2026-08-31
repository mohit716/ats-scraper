"""Deterministic extraction: apply CSS rules to a page, no LLM call.

The per-site rules are not written by hand. They are produced once per
template by extraction.rulegen and read back from extraction.template_store,
which is what makes this path free to run.

When no rules have been learned yet, this falls back to structured data
(schema.org JobPosting) and then to a small set of generic containers, so a
brand-new template still produces something rather than nothing.
"""

import copy
import json

from lxml import html as lxml_html
from lxml.cssselect import CSSSelector
from parsel import Selector

from extraction.html_text import html_to_text

# Below this, a container is assumed to be a teaser rather than the description.
MIN_CHARS = 200

# A CSS rule can quietly grab only part of a posting. When the page also
# publishes schema.org data and that data is substantially longer, the
# structured version is the more complete one and wins.
JSONLD_PREFERENCE_RATIO = 1.3

# Used only until a template has been learned.
GENERIC_RULES = [
    "div.job-description",
    "#job-description",
    "[itemprop='description']",
    "main",
    "article",
]


def _parse(html_source):
    try:
        return lxml_html.fromstring(html_source)
    except Exception:
        return None


def _select(root, css):
    try:
        selector = CSSSelector(css)
    except Exception:
        # The model can propose syntax cssselect does not implement.
        return []
    try:
        return selector(root)
    except Exception:
        return []


def _text_from_nodes(nodes, remove_selectors=()):
    chunks = []
    for node in nodes:
        clone = copy.deepcopy(node)
        for css in remove_selectors:
            for junk in _select(clone, css):
                parent = junk.getparent()
                if parent is not None:
                    parent.remove(junk)
        chunks.append(html_to_text(lxml_html.tostring(clone, encoding="unicode")))
    return "\n\n".join(c for c in chunks if c).strip()


def page_text_of(html_source):
    return html_to_text(html_source)


def extract_jsonld(html_source):
    """schema.org JobPosting.description, used by many boards including Ashby."""
    selector = Selector(html_source)
    for block in selector.css("script[type='application/ld+json']::text").getall():
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            # Some boards emit several concatenated objects in one tag.
            continue
        for candidate in data if isinstance(data, list) else [data]:
            if not isinstance(candidate, dict):
                continue
            if candidate.get("@type") != "JobPosting":
                continue
            description = candidate.get("description")
            if isinstance(description, str) and description.strip():
                looks_like_html = "<" in description and ">" in description
                return html_to_text(description) if looks_like_html else description.strip()
    return ""


def apply_rules(html_source, rules):
    """Run learned rules. Returns (text, rule_used); empty text means a miss."""
    tree = _parse(html_source)
    if tree is None:
        return "", "parse-failed"

    removes = rules.get("remove_selectors") or []
    jsonld_text = extract_jsonld(html_source)
    jsonld_usable = len(jsonld_text) >= MIN_CHARS

    if rules.get("use_jsonld") and jsonld_usable:
        return jsonld_text, "jsonld:JobPosting.description"

    for css in rules.get("container_selectors") or []:
        nodes = _select(tree, css)
        if not nodes:
            continue
        text = _text_from_nodes(nodes, removes)
        if len(text) < MIN_CHARS:
            continue
        if jsonld_usable and len(jsonld_text) > len(text) * JSONLD_PREFERENCE_RATIO:
            return jsonld_text, f"jsonld:JobPosting.description(over {css})"
        return text, f"css:{css}"

    if jsonld_usable:
        return jsonld_text, "jsonld:JobPosting.description"

    return "", "learned-rules-missed"


def extract_generic(html_source):
    """Best effort for a template that has not been learned yet."""
    text = extract_jsonld(html_source)
    if len(text) >= MIN_CHARS:
        return text, "jsonld:JobPosting.description"

    tree = _parse(html_source)
    if tree is None:
        return "", "parse-failed"

    for css in GENERIC_RULES:
        nodes = _select(tree, css)
        if not nodes:
            continue
        text = _text_from_nodes(nodes)
        if len(text) >= MIN_CHARS:
            return text, f"generic-css:{css}"

    return "", "no-rule-matched"


def extract(url, html_source, rules=None):
    """Deterministic extraction. Uses learned rules when supplied."""
    if rules:
        text, rule = apply_rules(html_source, rules)
        if text:
            return text, rule
        # A learned template that stops matching usually means the site
        # changed. Fall through so the caller still gets something, and let
        # the confidence score flag it for relearning.
        fallback_text, fallback_rule = extract_generic(html_source)
        return fallback_text, f"{rule}->{fallback_rule}"

    return extract_generic(html_source)
