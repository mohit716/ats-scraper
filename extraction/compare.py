"""Run all three extraction approaches over a URL set and score the results.

The three approaches share one page fetch and one template-learning step, so
the numbers are comparable: any difference between them comes from the
extraction strategy, not from a different view of the page.
"""

import json
import re

from extraction import hybrid, llm_only, metrics, template_store
from extraction.config import (
    EXTRACT_MODEL,
    GOLD_DIR,
    OUTPUT_DIR,
    PROJECT_ROOT,
    RULEGEN_MODEL,
)
from extraction.fetch import fetch_html
from extraction.html_text import html_to_text

APPROACHES = ("template", "llm", "hybrid")

# How many distinct page templates a 100k-page crawl is assumed to span.
# The ATS long tail is real but bounded: a few dozen platforms cover the vast
# majority of postings, and every company on a platform shares its template.
TEMPLATES_AT_SCALE = 50
PROJECTION_PAGES = 100_000


def load_samples(path=None):
    path = path or PROJECT_ROOT / "samples" / "urls.json"
    return json.loads(path.read_text(encoding="utf-8"))


def sample_id(url):
    """Filesystem-safe id for a page, used for gold and output filenames."""
    tail = url.rstrip("/").split("/")[-1]
    return re.sub(r"[^A-Za-z0-9._-]+", "-", tail)[:60].strip("-") or "page"


def _gold_for(sample):
    if not GOLD_DIR.exists():
        return None
    candidate = GOLD_DIR / f"{sample_id(sample['url'])}.txt"
    if candidate.exists():
        text = candidate.read_text(encoding="utf-8").strip()
        # Placeholder files written by scripts/make_gold.py are not verified
        # yet and must not be scored as if they were.
        if text and not text.startswith("# UNVERIFIED"):
            return text
    return None


def run_one(
    sample,
    use_llm=True,
    use_cache=True,
    model=None,
    input_mode="text",
    allow_rulegen=True,
    rulegen_model=None,
):
    url = sample["url"]
    record = {"ats": sample.get("ats"), "company": sample.get("company"), "url": url}

    try:
        html = fetch_html(url, use_cache=use_cache)
    except Exception as exc:
        record["fetch_error"] = f"{type(exc).__name__}: {exc}"
        return record

    page_text = html_to_text(html)
    gold = _gold_for(sample)
    record["page_chars"] = len(html)
    record["page_text_chars"] = len(page_text)
    record["has_gold"] = gold is not None
    record["template_key"] = template_store.template_key(url)

    # Shared step: learn this template once. Both the template-aware and the
    # hybrid approach depend on it, so its cost is tracked separately rather
    # than charged to whichever approach happened to run first.
    stored = template_store.load(record["template_key"])
    record["template_reused"] = stored is not None
    record["learning"] = None
    if stored is None and allow_rulegen and use_llm:
        stored, generation = hybrid.ensure_template(
            url, html, rulegen_model=rulegen_model
        )
        record["learning"] = generation

    rules = (stored or {}).get("rules")
    record["template_rules"] = rules

    # 1. Template-aware: deterministic, no per-page model call.
    attempt = hybrid.run_rules(url, html, rules, page_text)
    record["template"] = {
        "rule": attempt["rule"],
        "latency_s": attempt["latency_s"],
        "confidence": attempt["confidence"],
        "signals": attempt["signals"],
        "cost_usd": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "model": None,
        "text": attempt["text"],
        **metrics.score(attempt["text"], page_text=page_text, source=html, gold=gold),
    }

    if not use_llm:
        return record

    # 2. LLM-only.
    llm_result = llm_only.extract(html, model=model, input_mode=input_mode)
    record["llm"] = {
        "model": llm_result["model"],
        "input_mode": llm_result["input_mode"],
        "error": llm_result["error"],
        "latency_s": llm_result["latency_s"],
        "prompt_tokens": llm_result["prompt_tokens"],
        "completion_tokens": llm_result["completion_tokens"],
        "cost_usd": round(llm_result["cost_usd"], 6),
        "input_truncated": llm_result["input_truncated"],
        "text": llm_result["text"],
        **metrics.score(llm_result["text"], page_text=page_text, source=html, gold=gold),
    }

    # 3. Hybrid: rules first, cheap model only where confidence is low.
    hybrid_result = hybrid.extract(
        url,
        html,
        page_text=page_text,
        allow_rulegen=allow_rulegen,
        extract_model=model,
        rulegen_model=rulegen_model,
    )
    hybrid_result.update(
        metrics.score(hybrid_result["text"], page_text=page_text, source=html, gold=gold)
    )
    record["hybrid"] = hybrid_result

    record["agreement"] = metrics.agreement(
        record["template"]["text"], record["llm"]["text"]
    )
    return record


def run(samples=None, **kwargs):
    samples = samples or load_samples()
    return [run_one(s, **kwargs) for s in samples]


def _avg(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 4) if values else 0.0


def summarize(records, templates_at_scale=TEMPLATES_AT_SCALE):
    pages = [r for r in records if "fetch_error" not in r]
    summary = {
        "pages": len(records),
        "pages_fetched": len(pages),
        "pages_with_gold": sum(1 for r in pages if r.get("has_gold")),
        "models": {"extraction": EXTRACT_MODEL, "rule_generation": RULEGEN_MODEL},
        "approaches": {},
    }

    learnings = [r["learning"] for r in pages if r.get("learning")]
    learning_cost = sum(g["cost_usd"] for g in learnings)

    # On a warm run nothing is learned, so the per-template cost is read back
    # from the cached templates. Without this the projection would claim that
    # the deterministic approaches are free, which is only true once someone
    # else has already paid to learn the template.
    if learnings:
        cost_basis = [g["cost_usd"] for g in learnings]
        basis = "measured this run"
    else:
        cost_basis = [
            t.get("generation", {}).get("cost_usd", 0.0)
            for t in template_store.all_templates()
        ]
        basis = "recorded when the cached templates were learned"

    summary["template_learning"] = {
        "templates_learned_this_run": len(learnings),
        "templates_succeeded": sum(1 for g in learnings if g["ok"]),
        "distinct_templates_seen": len({r.get("template_key") for r in pages}),
        "spent_this_run_usd": round(learning_cost, 6),
        "cost_basis": basis,
        "avg_cost_per_template_usd": round(sum(cost_basis) / len(cost_basis), 6)
        if cost_basis
        else 0.0,
        "avg_latency_s": _avg([g["latency_s"] for g in learnings]),
        "total_prompt_tokens": sum(g["prompt_tokens"] for g in learnings),
        "total_completion_tokens": sum(g["completion_tokens"] for g in learnings),
    }

    # What learning these templates costs, whether or not this particular run
    # paid for it.
    attributable_learning = (
        summary["template_learning"]["avg_cost_per_template_usd"]
        * summary["template_learning"]["distinct_templates_seen"]
    )

    for approach in APPROACHES:
        rows = [r[approach] for r in pages if approach in r]
        if not rows:
            continue

        runtime_cost = sum(r.get("cost_usd", 0.0) for r in rows)
        stats = {
            "pages_with_output": sum(1 for r in rows if not r["empty"]),
            "failures": sum(1 for r in rows if r["empty"]),
            "full_extraction_rate": round(
                sum(1 for r in rows if not r["empty"]) / len(rows), 4
            ),
            "avg_words": _avg([r["words"] for r in rows]),
            "avg_boilerplate_hits": _avg([r["boilerplate_hits"] for r in rows]),
            "avg_jd_sections": _avg([r["jd_sections_hits"] for r in rows]),
            "avg_kept_ratio": _avg([r.get("kept_ratio") for r in rows]),
            "avg_grounding": _avg([r.get("grounding") for r in rows]),
            "pages_with_invented_text": sum(
                1 for r in rows if (r.get("grounding") or 1.0) < 0.90
            ),
            "avg_confidence": _avg([r.get("confidence") for r in rows]),
            "avg_latency_s": _avg([r["latency_s"] for r in rows]),
            "total_prompt_tokens": sum(r.get("prompt_tokens", 0) for r in rows),
            "total_completion_tokens": sum(r.get("completion_tokens", 0) for r in rows),
            "runtime_cost_usd": round(runtime_cost, 6),
            "runtime_cost_per_page_usd": round(runtime_cost / len(rows), 8),
        }

        # The deterministic approaches only exist because a template was
        # learned, so their true cost includes that one-time spend.
        if approach in ("template", "hybrid"):
            stats["one_time_learning_cost_usd"] = round(attributable_learning, 6)
            stats["total_cost_usd"] = round(runtime_cost + attributable_learning, 6)
        else:
            stats["one_time_learning_cost_usd"] = 0.0
            stats["total_cost_usd"] = round(runtime_cost, 6)
        stats["cost_per_page_usd"] = round(stats["total_cost_usd"] / len(rows), 8)

        scored = [r for r in rows if "f1" in r]
        if scored:
            stats["avg_precision"] = _avg([r["precision"] for r in scored])
            stats["avg_recall"] = _avg([r["recall"] for r in scored])
            stats["avg_f1"] = _avg([r["f1"] for r in scored])
            stats["pages_scored_against_gold"] = len(scored)

        summary["approaches"][approach] = stats

    hybrid_rows = [r["hybrid"] for r in pages if "hybrid" in r]
    if hybrid_rows:
        routes = {}
        for row in hybrid_rows:
            routes[row["route"]] = routes.get(row["route"], 0) + 1
        summary["hybrid_routing"] = {
            "routes": routes,
            "llm_fallback_rate": round(
                sum(1 for r in hybrid_rows if r["route"] == "llm-fallback")
                / len(hybrid_rows),
                4,
            ),
            "templates_reused": sum(1 for r in hybrid_rows if r["template_reused"]),
            "relearned": sum(1 for r in hybrid_rows if r["relearned"]),
        }

    summary["projection"] = project(summary, templates_at_scale)
    return summary


def project(summary, templates_at_scale=TEMPLATES_AT_SCALE, pages=PROJECTION_PAGES):
    """Extrapolate cost to a production crawl.

    Only the LLM-only approach scales linearly with pages. The deterministic
    approaches scale with the number of *templates*, which grows far more
    slowly, plus whatever share of pages still needs a model.
    """
    approaches = summary.get("approaches", {})
    learning = summary.get("template_learning", {})
    per_template = learning.get("avg_cost_per_template_usd", 0.0)
    llm_per_page = approaches.get("llm", {}).get("runtime_cost_per_page_usd", 0.0)
    fallback_rate = summary.get("hybrid_routing", {}).get("llm_fallback_rate", 0.0)

    out = {
        "pages": pages,
        "assumed_templates": templates_at_scale,
        "assumed_llm_fallback_rate": fallback_rate,
        "notes": (
            f"Template learning is charged once per template "
            f"({templates_at_scale} assumed for a {pages:,}-page crawl), not per page."
        ),
    }

    if "llm" in approaches:
        out["llm_usd"] = round(llm_per_page * pages, 2)
    if "template" in approaches:
        out["template_usd"] = round(per_template * templates_at_scale, 2)
    if "hybrid" in approaches:
        out["hybrid_usd"] = round(
            per_template * templates_at_scale + llm_per_page * fallback_rate * pages, 2
        )
    return out


def save(records, summary, output_dir=None, filename="comparison.json"):
    output_dir = output_dir or OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    # Keep the full text out of the metrics file so it stays readable.
    slim = []
    for record in records:
        copy = json.loads(json.dumps(record))
        for approach in APPROACHES:
            if approach in copy:
                copy[approach].pop("text", None)
        slim.append(copy)

    (output_dir / filename).write_text(
        json.dumps({"summary": summary, "records": slim}, indent=2), encoding="utf-8"
    )

    texts_dir = output_dir / "texts"
    texts_dir.mkdir(exist_ok=True)
    for record in records:
        stem = sample_id(record["url"])
        for approach in APPROACHES:
            if approach in record and record[approach].get("text"):
                (texts_dir / f"{record['ats']}-{stem}.{approach}.txt").write_text(
                    record[approach]["text"], encoding="utf-8"
                )
    return output_dir


def _money(value):
    return f"${value:.6f}" if value < 0.01 else f"${value:.4f}"


def format_report(records, summary):
    lines = []
    lines.append("=" * 100)
    lines.append("JOB DESCRIPTION EXTRACTION - LLM-only vs Template-aware vs Hybrid")
    lines.append(
        f"extraction model: {summary['models']['extraction']}   "
        f"rule generation: {summary['models']['rule_generation']}"
    )
    lines.append("=" * 100)
    lines.append("")

    header = (
        f"{'ATS':<15}{'approach':<10}{'words':>7}{'boiler':>8}{'sect':>6}"
        f"{'kept':>7}{'grnd':>7}{'conf':>7}{'sec':>7}{'tokens':>8}{'cost':>12}"
    )
    lines.append(header)
    lines.append("-" * len(header))

    for record in records:
        ats = (record.get("ats") or "")[:14]
        if "fetch_error" in record:
            lines.append(f"{ats:<15}FETCH FAILED: {record['fetch_error']}")
            continue

        gold_flag = "" if record.get("has_gold") else "  (no gold)"
        lines.append(
            f"{ats:<15}{record.get('company', '')}  "
            f"[page: {record['template'].get('page_words', 0)} words]{gold_flag}"
        )
        if record.get("learning"):
            gen = record["learning"]
            state = "learned" if gen["ok"] else f"FAILED ({gen['reason'][:40]})"
            lines.append(
                f"{'':<15}template {state} by {gen['model']} "
                f"in {gen['latency_s']}s for {_money(gen['cost_usd'])} "
                f"({gen['attempts']} attempt(s))"
            )
        elif record.get("template_reused"):
            lines.append(f"{'':<15}template reused from cache (no model call)")

        for approach in APPROACHES:
            if approach not in record:
                continue
            row = record[approach]
            kept_ratio = row.get("kept_ratio")
            kept = "n/a" if kept_ratio is None else f"{kept_ratio * 100:.0f}%"
            tokens = row.get("prompt_tokens", 0) + row.get("completion_tokens", 0)
            conf = row.get("confidence")
            conf_text = "-" if conf is None else f"{conf:.2f}"
            ground = row.get("grounding")
            ground_text = "-" if ground is None else f"{ground * 100:.0f}%"

            if row.get("error"):
                flag = f"  <-- {row['error'][:40]}"
            elif row["empty"]:
                flag = "  <-- NO OUTPUT"
            elif ground is not None and ground < 0.90:
                flag = f"  <-- {(1 - ground) * 100:.0f}% NOT ON PAGE (invented)"
            elif approach == "hybrid":
                flag = f"  [{row['route']}]"
            else:
                flag = ""

            lines.append(
                f"{'':<15}{approach:<10}{row['words']:>7}"
                f"{row['boilerplate_hits']:>8}{row['jd_sections_hits']:>6}"
                f"{kept:>7}{ground_text:>7}{conf_text:>7}{row['latency_s']:>7.2f}"
                f"{tokens:>8}{_money(row.get('cost_usd', 0.0)):>12}{flag}"
            )

        if record.get("has_gold"):
            f1s = " ".join(
                f"{a}={record[a]['f1']:.2f}" for a in APPROACHES if a in record and "f1" in record[a]
            )
            lines.append(f"{'':<25}F1 vs gold: {f1s}")
        if "agreement" in record:
            lines.append(
                f"{'':<25}template/llm token agreement (Jaccard): {record['agreement']}"
            )
        lines.append("")

    lines.append("-" * len(header))
    lines.append("TEMPLATE LEARNING (one-time, per template)")
    for key, value in summary["template_learning"].items():
        lines.append(f"      {key:<32}{value}")
    lines.append("")

    if "hybrid_routing" in summary:
        lines.append("HYBRID ROUTING")
        for key, value in summary["hybrid_routing"].items():
            lines.append(f"      {key:<32}{value}")
        lines.append("")

    lines.append("PER-APPROACH SUMMARY")
    for approach, stats in summary["approaches"].items():
        lines.append(f"  {approach}:")
        for key, value in stats.items():
            lines.append(f"      {key:<32}{value}")
        lines.append("")

    projection = summary.get("projection", {})
    if projection:
        lines.append(f"PROJECTED COST FOR {projection['pages']:,} PAGES")
        lines.append(f"      {projection['notes']}")
        for approach in APPROACHES:
            key = f"{approach}_usd"
            if key in projection:
                lines.append(f"      {approach:<32}${projection[key]:,.2f}")
        lines.append("")

    lines.append("boiler = boilerplate phrases still present (lower is better)")
    lines.append("sect   = job-description headings detected (higher is better)")
    lines.append("kept   = share of page words retained")
    lines.append("grnd   = share of extracted words that exist on the page (100% = nothing invented)")
    lines.append("conf   = local confidence score used by the hybrid router")
    return "\n".join(lines)
