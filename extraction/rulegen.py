"""Learn reusable extraction rules for a page template using a strong LLM.

Sending raw HTML to the model would be slow, expensive and mostly wasted on
attributes it does not need. Instead the page is reduced to a *digest*: one
line per text-bearing element, giving its selector, how much text it holds
and a short preview. That is enough to decide which container is the job
description, at a fraction of the tokens.

Whatever the model proposes is executed against the page before it is
trusted. A selector that does not match, or that swallows the whole page, is
rejected rather than cached.
"""

import json
import re

from lxml import html as lxml_html

from extraction import llm_client, template_aware
from extraction.config import MAX_RULEGEN_INPUT_CHARS, RULEGEN_MODEL
from extraction.html_text import DROP_TAGS

MIN_NODE_TEXT = 120
MAX_DIGEST_NODES = 90
PREVIEW_CHARS = 90

SYSTEM_PROMPT = """You are given a structural digest of a single job posting
web page. Each line describes one element: a CSS selector, the number of
characters of text it contains, and a short preview of that text.

Your job is to write reusable CSS selector rules that extract the job
description from ANY page on this same site template, not just this one page.

Return a JSON object with exactly these keys:
{
  "container_selectors": ["..."],
  "remove_selectors": ["..."],
  "use_jsonld": false,
  "confidence": 0.0,
  "notes": "..."
}

container_selectors: ordered list of CSS selectors that together capture the
  full job description (summary, responsibilities, requirements, benefits,
  compensation, EEO statement). The first selector that matches and yields
  enough text wins, so put the most specific one first. If the description is
  split across sibling blocks, use a single selector that matches all of them.

remove_selectors: selectors for junk *inside* the containers that should be
  stripped, such as apply forms, share buttons, cookie notices or
  "similar jobs" lists. Use [] if there is none.

use_jsonld: true if the page embeds a schema.org JobPosting whose description
  field is the most reliable source. Prefer this when the visible DOM is
  client-rendered and nearly empty.

confidence: your confidence from 0.0 to 1.0 that these rules generalise.

Rules:
- Prefer stable hooks: semantic class names, data attributes, itemprop, ids.
- Avoid selectors that depend on this page's wording or on nth-child position.
- Avoid framework-hashed class names unless nothing else is available.
- Never select <body> or <html>. Never select a container that holds the
  entire page including navigation and footer.
- Output ONLY the JSON object, no commentary.
"""


def _selector_for(node):
    tag = node.tag
    node_id = (node.get("id") or "").strip()
    if node_id and re.fullmatch(r"[A-Za-z][\w-]*", node_id):
        return f"{tag}#{node_id}"

    classes = [
        c
        for c in (node.get("class") or "").split()
        if re.fullmatch(r"[A-Za-z_][\w-]*", c)
    ][:3]
    if classes:
        return tag + "".join(f".{c}" for c in classes)

    for attr in ("itemprop", "data-ui", "data-qa", "data-automation-id", "data-testid"):
        value = (node.get(attr) or "").strip()
        if value:
            return f"{tag}[{attr}='{value}']"
    return tag


def dom_digest(html_source):
    """Reduce a page to one line per text-bearing element."""
    try:
        tree = lxml_html.fromstring(html_source)
    except Exception:
        return "", False

    for tag in DROP_TAGS:
        for node in tree.xpath(f".//{tag}"):
            node.getparent().remove(node)

    rows = []
    for node in tree.iter():
        if not isinstance(node.tag, str) or node.tag in ("html", "body"):
            continue
        text = re.sub(r"\s+", " ", node.text_content() or "").strip()
        if len(text) < MIN_NODE_TEXT:
            continue
        depth = sum(1 for _ in node.iterancestors())
        rows.append((len(text), depth, _selector_for(node), text[:PREVIEW_CHARS]))

    rows.sort(key=lambda r: -r[0])
    lines = [
        f"{selector}  | chars={size} depth={depth} | {preview}"
        for size, depth, selector, preview in rows[:MAX_DIGEST_NODES]
    ]

    has_jsonld = bool(template_aware.extract_jsonld(html_source))
    return "\n".join(lines), has_jsonld


def _parse_rules(raw):
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?|\n?```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    containers = [
        s for s in data.get("container_selectors") or [] if isinstance(s, str) and s.strip()
    ]
    removes = [
        s for s in data.get("remove_selectors") or [] if isinstance(s, str) and s.strip()
    ]
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    return {
        "container_selectors": containers,
        "remove_selectors": removes,
        "use_jsonld": bool(data.get("use_jsonld")),
        "model_confidence": round(max(0.0, min(1.0, confidence)), 3),
        "notes": str(data.get("notes") or "")[:400],
    }


def validate(rules, url, html_source):
    """Run the proposed rules. Returns (ok, reason, text)."""
    if not rules:
        return False, "model did not return usable JSON", ""
    if not rules["container_selectors"] and not rules["use_jsonld"]:
        return False, "no selectors and no jsonld", ""

    text, _ = template_aware.apply_rules(html_source, rules)
    if len(text) < template_aware.MIN_CHARS:
        return False, f"rules matched only {len(text)} chars", text

    page_text_len = len(template_aware.page_text_of(html_source))
    if page_text_len and len(text) > page_text_len * 0.97:
        return False, "rules captured essentially the whole page", text

    return True, "ok", text


def generate(url, html_source, model=None):
    """Ask the strong model for rules, validate, and retry once on failure.

    Returns a dict with the rules (or None) plus the cost of learning them.
    """
    model = model or RULEGEN_MODEL
    digest, has_jsonld = dom_digest(html_source)

    if not digest:
        # A client-rendered board (Ashby is the common case) serves markup with
        # no readable text, so there is nothing for the model to reason about.
        # If the page still publishes schema.org data, that is the answer and
        # no model call is needed.
        free = {
            "model": "none (structured-data)",
            "attempts": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": 0.0,
            "latency_s": 0.0,
        }
        if has_jsonld:
            return {
                "rules": {
                    "container_selectors": [],
                    "remove_selectors": [],
                    "use_jsonld": True,
                    "model_confidence": 0.9,
                    "notes": (
                        "Served DOM carries no text (client-rendered), but the "
                        "page embeds a schema.org JobPosting. Resolved without "
                        "a model call."
                    ),
                },
                "ok": True,
                "reason": "structured-data shortcut",
                **free,
            }
        return {
            "rules": None,
            "ok": False,
            "reason": "empty digest and no structured data",
            **free,
        }

    user = (
        f"URL: {url}\n"
        f"Page embeds a schema.org JobPosting with a description: {has_jsonld}\n\n"
        f"Structural digest (largest text blocks first):\n{digest}"
    )[:MAX_RULEGEN_INPUT_CHARS]

    totals = {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0, "latency_s": 0.0}
    rules = None
    reason = "not attempted"

    for attempt in (1, 2):
        response = llm_client.chat(model, SYSTEM_PROMPT, user, json_object=True)
        totals["prompt_tokens"] += response["prompt_tokens"]
        totals["completion_tokens"] += response["completion_tokens"]
        totals["cost_usd"] += response["cost_usd"]
        totals["latency_s"] += response["latency_s"]

        if response["error"]:
            reason = response["error"]
            break

        candidate = _parse_rules(response["text"])
        ok, reason, _ = validate(candidate, url, html_source)
        if ok:
            rules = candidate
            break

        # Give the model the concrete failure so the retry is informed.
        user = (
            f"{user}\n\nYour previous answer was rejected: {reason}\n"
            f"Previous answer: {response['text'][:600]}\n"
            "Return corrected JSON."
        )[:MAX_RULEGEN_INPUT_CHARS]

    return {
        "rules": rules,
        "ok": rules is not None,
        "reason": reason,
        "model": model,
        "attempts": attempt,
        **{k: (round(v, 6) if k == "cost_usd" else round(v, 2) if k == "latency_s" else v)
           for k, v in totals.items()},
    }
