"""Hybrid extraction: deterministic rules first, LLM only when they fail.

Per page the router does the following.

1. Look up learned rules for this page's template. If none exist, pay once to
   learn them with the strong model.
2. Run the rules. This is free.
3. Score the result locally. A good score ends the page here, which is the
   common case and costs nothing.
4. A bad score means the rules missed or the site changed shape. Relearn once
   and retry.
5. If it is still bad, fall back to the cheap LLM so the page is never lost.

The first page of a template therefore costs one strong-model call; every
later page on that template is usually free.
"""

import time

from extraction import (
    confidence,
    llm_only,
    metrics,
    rulegen,
    template_aware,
    template_store,
)

GENERATION_FIELDS = (
    "ok",
    "reason",
    "model",
    "attempts",
    "prompt_tokens",
    "completion_tokens",
    "cost_usd",
    "latency_s",
)


def ensure_template(url, html, rulegen_model=None, force=False, previous=None):
    """Return (stored_record, generation_info). Generation is None on a cache hit."""
    key = template_store.template_key(url)
    stored = previous if force else template_store.load(key)

    if stored is not None and not force:
        return stored, None

    generation = rulegen.generate(url, html, model=rulegen_model)
    if generation["ok"]:
        stored = template_store.save(
            key,
            generation["rules"],
            source_url=url,
            generated_by=generation["model"],
            generation_meta={
                "prompt_tokens": generation["prompt_tokens"],
                "completion_tokens": generation["completion_tokens"],
                "cost_usd": round(generation["cost_usd"], 6),
                "latency_s": generation["latency_s"],
                "attempts": generation["attempts"],
            },
            previous=stored,
        )
    return stored, {k: generation[k] for k in GENERATION_FIELDS}


def run_rules(url, html, rules, page_text):
    """Deterministic pass plus its local quality score."""
    started = time.time()
    text, rule = template_aware.extract(url, html, rules)
    latency = round(time.time() - started, 3)
    scored = metrics.score(text, page_text=page_text, source=html)
    conf, signals = confidence.score(text, rule, page_text=page_text, scored=scored)
    return {
        "text": text,
        "rule": rule,
        "latency_s": latency,
        "confidence": conf,
        "signals": signals,
        "scored": scored,
    }


def extract(
    url,
    html,
    page_text=None,
    threshold=confidence.DEFAULT_THRESHOLD,
    allow_rulegen=True,
    allow_llm_fallback=True,
    extract_model=None,
    rulegen_model=None,
):
    page_text = page_text if page_text is not None else template_aware.page_text_of(html)
    key = template_store.template_key(url)
    stored = template_store.load(key)

    result = {
        "template_key": key,
        "template_reused": stored is not None,
        "rulegen": None,
        "relearned": False,
        "llm": None,
        "rulegen_cost_usd": 0.0,
        "llm_cost_usd": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "latency_s": 0.0,
    }

    def absorb_generation(generation):
        result["rulegen"] = generation
        result["rulegen_cost_usd"] += generation["cost_usd"]
        result["prompt_tokens"] += generation["prompt_tokens"]
        result["completion_tokens"] += generation["completion_tokens"]
        result["latency_s"] += generation["latency_s"]

    if stored is None and allow_rulegen:
        stored, generation = ensure_template(url, html, rulegen_model=rulegen_model)
        if generation:
            absorb_generation(generation)

    result["template_revision"] = (stored or {}).get("revision", 0)
    attempt = run_rules(url, html, (stored or {}).get("rules"), page_text)
    result["latency_s"] += attempt["latency_s"]

    # A previously learned template scoring badly usually means the page
    # structure moved. Relearn once against this page and retry.
    if attempt["confidence"] < threshold and stored and allow_rulegen:
        stored, generation = ensure_template(
            url, html, rulegen_model=rulegen_model, force=True, previous=stored
        )
        result["relearned"] = True
        absorb_generation(generation)
        if generation["ok"]:
            result["template_revision"] = (stored or {}).get("revision", 0)
            retry = run_rules(url, html, stored["rules"], page_text)
            result["latency_s"] += retry["latency_s"]
            if retry["confidence"] > attempt["confidence"]:
                attempt = retry

    best = attempt
    if best["rule"].startswith(("css:", "jsonld:")):
        route = "rules-after-relearn" if result["relearned"] else "rules"
    else:
        route = "rules-generic"

    if best["confidence"] < threshold and allow_llm_fallback:
        llm_result = llm_only.extract(html, model=extract_model, input_mode="text")
        result["llm"] = {
            k: llm_result[k]
            for k in (
                "model",
                "error",
                "latency_s",
                "prompt_tokens",
                "completion_tokens",
                "cost_usd",
                "input_mode",
            )
        }
        result["llm_cost_usd"] += llm_result["cost_usd"]
        result["prompt_tokens"] += llm_result["prompt_tokens"]
        result["completion_tokens"] += llm_result["completion_tokens"]
        result["latency_s"] += llm_result["latency_s"]

        if llm_result["text"]:
            llm_scored = metrics.score(
                llm_result["text"], page_text=page_text, source=html
            )
            llm_conf, llm_signals = confidence.score(
                llm_result["text"], "llm", page_text=page_text, scored=llm_scored
            )
            # The LLM path has no CSS rule, so the rule_quality signal drags
            # its score down for a reason that does not apply. Credit it back
            # and judge the LLM on content signals alone.
            llm_conf = round(
                min(1.0, llm_conf + confidence.WEIGHTS["rule_quality"]), 3
            )
            if llm_conf >= best["confidence"]:
                best = {
                    "text": llm_result["text"],
                    "rule": "llm",
                    "confidence": llm_conf,
                    "signals": llm_signals,
                    "scored": llm_scored,
                }
                route = "llm-fallback"

    if stored:
        template_store.record_use(
            key, hit=route.startswith("rules") and best["confidence"] >= threshold
        )

    result.update(
        {
            "text": best["text"],
            "rule": best["rule"],
            "route": route,
            "confidence": best["confidence"],
            "signals": best["signals"],
            "cost_usd": round(result["rulegen_cost_usd"] + result["llm_cost_usd"], 6),
            "rulegen_cost_usd": round(result["rulegen_cost_usd"], 6),
            "llm_cost_usd": round(result["llm_cost_usd"], 6),
            "latency_s": round(result["latency_s"], 2),
            **best["scored"],
        }
    )
    return result
