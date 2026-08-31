"""LLM-only extraction: hand the page to a cheap model and ask for the JD."""

from extraction import llm_client
from extraction.config import EXTRACT_MODEL, MAX_LLM_INPUT_CHARS
from extraction.html_text import html_to_text

SYSTEM_PROMPT = """You extract job descriptions from scraped career pages.

You are given the visible text of a single job posting page. It contains the
job description mixed with unrelated page furniture.

Return ONLY the job description: the role summary, responsibilities,
requirements, qualifications, skills, benefits, compensation and equal
opportunity statement when present.

Remove everything else, including:
- site navigation, breadcrumbs, search boxes and language pickers
- cookie and privacy consent banners
- page headers and footers, legal and social links
- "similar jobs", "recommended jobs" and other job listings
- application forms, upload buttons and form field labels
- company boilerplate repeated site-wide that is not part of this posting

Rules:
- Preserve the original wording. Do not summarise, translate or rewrite.
- Keep the original ordering and the heading/bullet structure.
- Use plain text with "- " for bullets.
- If the page contains no job description, reply with exactly: NO_JOB_DESCRIPTION
"""


def build_input(html_source, input_mode="text"):
    """Prepare the model input.

    "text" is the visible page text, which is what a text-based scraper sees.
    Client-rendered boards (Ashby) expose almost nothing this way, so "html"
    passes the raw markup instead: the model can then read embedded JSON-LD,
    at a much higher token cost.
    """
    if input_mode == "html":
        return html_source
    return html_to_text(html_source)


def extract(html_source, model=None, temperature=0.0, input_mode="text"):
    """Return the extracted text plus cost, latency and token metadata."""
    model = model or EXTRACT_MODEL
    page_text = build_input(html_source, input_mode)
    truncated = len(page_text) > MAX_LLM_INPUT_CHARS
    prompt_text = page_text[:MAX_LLM_INPUT_CHARS]

    response = llm_client.chat(
        model, SYSTEM_PROMPT, prompt_text, temperature=temperature
    )

    text = response["text"]
    if text == "NO_JOB_DESCRIPTION":
        text = ""

    return {
        "text": text,
        "error": response["error"],
        "model": model,
        "latency_s": response["latency_s"],
        "prompt_tokens": response["prompt_tokens"],
        "completion_tokens": response["completion_tokens"],
        "cost_usd": response["cost_usd"],
        "input_chars": len(prompt_text),
        "input_truncated": truncated,
        "input_mode": input_mode,
    }
