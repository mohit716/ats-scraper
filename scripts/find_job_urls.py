"""Collect real posting URLs per ATS using each platform's public board API.

Used to assemble samples/urls.json. Boards open and close constantly, so this
re-probes rather than trusting a hardcoded list.

    python scripts/find_job_urls.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from extraction.config import USER_AGENT

HEADERS = {"User-Agent": USER_AGENT}
LIMIT = 2


def get_json(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def lever(company):
    data = get_json(f"https://api.lever.co/v0/postings/{company}?mode=json")
    return [p["hostedUrl"] for p in data[:LIMIT]]


def ashby(company):
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{company}")
    return [p["jobUrl"] for p in data.get("jobs", [])[:LIMIT]]


def workable(company):
    data = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{company}")
    return [j["url"] for j in data.get("jobs", [])[:LIMIT]]


def recruitee(company):
    data = get_json(f"https://{company}.recruitee.com/api/offers/")
    return [o["careers_url"] for o in data.get("offers", [])[:LIMIT]]


def greenhouse(company):
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs")
    return [j["absolute_url"] for j in data.get("jobs", [])[:LIMIT]]


def breezy(company):
    data = get_json(f"https://{company}.breezy.hr/json")
    return [j["url"] for j in data[:LIMIT]]


def smartrecruiters(company):
    data = get_json(
        f"https://api.smartrecruiters.com/v1/companies/{company}"
        f"/postings?limit={LIMIT}&offset=0&destination=PUBLIC"
    )
    return [
        f"https://jobs.smartrecruiters.com/{company}/{p['id']}"
        for p in data.get("content", [])
    ]


PROBES = [
    ("smartrecruiters", smartrecruiters, "BoschGroup"),
    ("smartrecruiters", smartrecruiters, "Equinox"),
    ("greenhouse", greenhouse, "anthropic"),
    ("greenhouse", greenhouse, "stripe"),
    ("greenhouse", greenhouse, "databricks"),
    ("lever", lever, "palantir"),
    ("lever", lever, "voleon"),
    ("ashby", ashby, "openai"),
    ("ashby", ashby, "ramp"),
    ("workable", workable, "dxc-technology"),
    ("workable", workable, "workable"),
    ("recruitee", recruitee, "recruitee"),
    # Named in the challenge brief as Example 1.
    ("breezy", breezy, "barloworldequipment"),
]


def main():
    found = {}
    for name, fn, company in PROBES:
        try:
            urls = fn(company)
        except Exception as exc:
            print(f"{name}/{company}: FAILED {type(exc).__name__} {exc}")
            continue
        print(f"{name}/{company}: {len(urls)} urls")
        for url in urls:
            print("   ", url)
        if urls:
            found.setdefault(f"{name}/{company}", urls)

    print()
    print(json.dumps(found, indent=2))


if __name__ == "__main__":
    main()
