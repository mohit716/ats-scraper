"""On-disk store of learned extraction rules, keyed by page template.

One JSON file per template. This is what makes the template-aware approach
cheap: the strong model is called once to write the rules, and every later
page on the same template reads them from here instead.
"""

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from extraction.config import TEMPLATE_DIR

# Multi-tenant boards give every customer its own subdomain but serve the
# identical DOM, so they collapse to one template.
SHARED_TEMPLATE_SUFFIXES = [
    "myworkdayjobs.com",
    "breezy.hr",
    "applytojob.com",
    "bamboohr.com",
    "teamtailor.com",
    "recruitee.com",
    "factorialhr.com",
    "zohorecruit.com",
]


def template_key(url):
    domain = urlparse(url).netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    for suffix in SHARED_TEMPLATE_SUFFIXES:
        if domain == suffix or domain.endswith("." + suffix):
            return suffix
    return domain


def _path(key):
    return TEMPLATE_DIR / f"{re.sub(r'[^a-z0-9.-]+', '_', key)}.json"


def load(key):
    path = _path(key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def save(key, rules, source_url, generated_by, generation_meta=None, previous=None):
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "template_key": key,
        "source_url": source_url,
        "generated_by": generated_by,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generation": generation_meta or {},
        "rules": rules,
        "stats": (previous or {}).get("stats") or {"uses": 0, "hits": 0, "misses": 0},
        "revision": ((previous or {}).get("revision") or 0) + 1,
    }
    _path(key).write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def record_use(key, hit):
    """Track how often a learned template holds up, for the reuse metrics."""
    record = load(key)
    if not record:
        return None
    stats = record.setdefault("stats", {"uses": 0, "hits": 0, "misses": 0})
    stats["uses"] += 1
    stats["hits" if hit else "misses"] += 1
    _path(key).write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def all_templates():
    if not TEMPLATE_DIR.exists():
        return []
    out = []
    for path in sorted(TEMPLATE_DIR.glob("*.json")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return out
