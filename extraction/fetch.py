import hashlib
import re

import requests

from extraction.config import CACHE_DIR, REQUEST_TIMEOUT, USER_AGENT


def cache_path(url):
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    slug = re.sub(r"[^a-z0-9]+", "-", url.lower().split("://")[-1])[:60].strip("-")
    return CACHE_DIR / f"{slug}-{digest}.html"


def fetch_html(url, use_cache=True):
    """Return page HTML, caching to disk.

    Both extractors must run against identical bytes, otherwise a page edit
    between runs would show up as a difference between the two approaches.
    """
    path = cache_path(url)
    if use_cache and path.exists():
        return path.read_text(encoding="utf-8", errors="replace")

    response = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    # requests falls back to ISO-8859-1 whenever the server omits a charset,
    # which mangles the curly quotes and dashes common in job descriptions.
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding or "utf-8"
    html = response.text

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8", errors="replace")
    return html
