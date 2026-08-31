"""Scaffold ground-truth files for manual verification.

The challenge asks for *manually verified* ground truth. Typing ten job
descriptions by hand is not the point, so this writes a starting draft per
page and marks it UNVERIFIED. Open each file, compare it against the live
page, fix what is wrong, then delete the UNVERIFIED header line.

Scoring ignores any file that still carries that header, so an unreviewed
draft can never be mistaken for verified truth.

    python scripts/make_gold.py            # draft any missing files
    python scripts/make_gold.py --force    # overwrite drafts (keeps verified)
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extraction import compare, hybrid, template_aware
from extraction.config import GOLD_DIR
from extraction.fetch import fetch_html
from extraction.html_text import html_to_text

HEADER = (
    "# UNVERIFIED DRAFT - review against the live page, correct it, then\n"
    "# delete these header lines. Files keeping this header are not scored.\n"
    "# url: {url}\n"
    "# drafted from: {source}\n"
    "\n"
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite existing drafts")
    parser.add_argument("--samples", default=None)
    args = parser.parse_args()

    samples = compare.load_samples(Path(args.samples) if args.samples else None)
    GOLD_DIR.mkdir(parents=True, exist_ok=True)

    for sample in samples:
        url = sample["url"]
        path = GOLD_DIR / f"{compare.sample_id(url)}.txt"

        if path.exists():
            existing = path.read_text(encoding="utf-8")
            verified = not existing.startswith("# UNVERIFIED")
            if verified:
                print(f"  verified, leaving alone : {path.name}")
                continue
            if not args.force:
                print(f"  draft exists, skipping  : {path.name}")
                continue

        try:
            html = fetch_html(url)
        except Exception as exc:
            print(f"  FETCH FAILED            : {url} ({exc})")
            continue

        page_text = html_to_text(html)
        result = hybrid.extract(url, html, page_text=page_text)
        text = result["text"]
        source = f"{result['route']} / {result['rule']} (confidence {result['confidence']})"

        if not text:
            text = template_aware.page_text_of(html)
            source = "raw page text - rules and LLM both failed, expect heavy editing"

        path.write_text(
            HEADER.format(url=url, source=source) + text + "\n", encoding="utf-8"
        )
        print(f"  drafted                 : {path.name}  [{source}]")

    print()
    print(f"Drafts in {GOLD_DIR}")
    print("Review each one, then delete the '# UNVERIFIED' header to enable scoring.")


if __name__ == "__main__":
    main()
