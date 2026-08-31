"""CLI: compare LLM-only, template-aware and hybrid job description extraction.

    python compare_extraction.py                    # all three approaches
    python compare_extraction.py --no-llm           # deterministic only, no API calls
    python compare_extraction.py --relearn          # discard cached rules and relearn
    python compare_extraction.py --url <job-url>    # ad-hoc page
"""

import argparse
import shutil
import sys
from pathlib import Path

from extraction import compare
from extraction.config import EXTRACT_MODEL, OUTPUT_DIR, RULEGEN_MODEL, TEMPLATE_DIR


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-llm", action="store_true", help="skip every model call")
    parser.add_argument("--no-cache", action="store_true", help="refetch pages")
    parser.add_argument(
        "--no-rulegen",
        action="store_true",
        help="never generate rules; use only what is already cached",
    )
    parser.add_argument(
        "--relearn",
        action="store_true",
        help="delete cached templates first, forcing fresh rule generation",
    )
    parser.add_argument(
        "--model", default=None, help=f"per-page extraction model (default {EXTRACT_MODEL})"
    )
    parser.add_argument(
        "--rulegen-model",
        default=None,
        help=f"rule generation model (default {RULEGEN_MODEL})",
    )
    parser.add_argument(
        "--llm-input",
        choices=["text", "html"],
        default="text",
        help="what to send the model: visible page text (default) or raw HTML",
    )
    parser.add_argument(
        "--templates-at-scale",
        type=int,
        default=compare.TEMPLATES_AT_SCALE,
        help="distinct templates assumed when projecting cost to 100k pages",
    )
    parser.add_argument("--url", action="append", help="ad-hoc URL (repeatable)")
    parser.add_argument("--samples", default=None, help="path to a urls.json file")
    args = parser.parse_args()

    if args.relearn and TEMPLATE_DIR.exists():
        shutil.rmtree(TEMPLATE_DIR)
        print(f"Cleared cached templates in {TEMPLATE_DIR}")

    if args.url:
        samples = [{"ats": "adhoc", "company": "", "url": u} for u in args.url]
    else:
        samples = compare.load_samples(Path(args.samples) if args.samples else None)

    records = compare.run(
        samples,
        use_llm=not args.no_llm,
        use_cache=not args.no_cache,
        model=args.model,
        input_mode=args.llm_input,
        allow_rulegen=not args.no_rulegen,
        rulegen_model=args.rulegen_model,
    )
    summary = compare.summarize(records, templates_at_scale=args.templates_at_scale)

    print(compare.format_report(records, summary))

    # A partial run must not overwrite the full three-way comparison, which is
    # the reported result.
    filename = "comparison.json"
    if args.no_llm:
        filename = "comparison_no_llm.json"
    elif args.url:
        filename = "comparison_adhoc.json"

    out = compare.save(records, summary, OUTPUT_DIR, filename=filename)
    print()
    print(f"Wrote metrics to {out / filename}")
    print(f"Wrote extracted text to {out / 'texts'}")
    print(f"Learned templates in {TEMPLATE_DIR}")

    fetch_errors = [r for r in records if "fetch_error" in r]
    llm_errors = [r for r in records if r.get("llm", {}).get("error")]
    if llm_errors:
        print()
        print("LLM errors:")
        for record in llm_errors:
            print(f"  {record['url']}: {record['llm']['error']}")
    return 1 if fetch_errors else 0


if __name__ == "__main__":
    sys.exit(main())
