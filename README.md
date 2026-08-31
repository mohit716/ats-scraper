# ATS Scraper

Two parts:

1. **ATS job posting extraction** — a Scrapy project that pulls public postings
   from the [SmartRecruiters API](https://api.smartrecruiters.com) into a single
   JSON array.
2. **Job description content cleaning & structuring** — a pipeline that pulls
   the full job description out of a job page while dropping navigation, cookie
   banners, headers, footers and recommended-job rails. Compares LLM-only
   extraction against LLM-generated reusable rules, and combines them.

## Setup

From the project root:

```bat
pip install -r requirements.txt
copy .env.example .env
```

Requires Python 3.10+. Part 2 needs an Alibaba Cloud Model Studio key in `.env`.

## Project layout

```
ats-scraper/
├── scrapy.cfg
├── requirements.txt
├── compare_extraction.py               # Part 2 CLI
├── jobs/                               # Part 1: Scrapy project
│   ├── items.py
│   ├── middlewares.py
│   ├── pipelines.py
│   ├── feedstorage.py                  # Merges -o output into one JSON array
│   ├── settings.py
│   └── spiders/
│       ├── SmartRecruitersBase.py      # Shared API extraction
│       └── spiders_in_SmartRecruiters.py
├── extraction/                         # Part 2
│   ├── config.py                       # Models, paths, limits
│   ├── pricing.py                      # Token rates, USD cost
│   ├── llm_client.py                   # Shared Qwen client
│   ├── fetch.py                        # HTTP + on-disk page cache
│   ├── html_text.py                    # HTML to readable text
│   ├── rulegen.py                      # Strong LLM writes reusable selectors
│   ├── template_store.py               # Learned rules, cached per template
│   ├── template_aware.py               # Applies rules; no model call
│   ├── llm_only.py                     # Cheap LLM reads the whole page
│   ├── confidence.py                   # Did the rules actually work?
│   ├── hybrid.py                        # Router: rules first, LLM on failure
│   ├── metrics.py                      # Scoring
│   └── compare.py                      # Runner and report
├── templates/                          # Learned rules (committed)
├── samples/
│   ├── urls.json                       # The 10 pages under test
│   └── gold/                           # Ground truth
└── scripts/
    ├── find_job_urls.py                # Refresh sample URLs
    └── make_gold.py                    # Scaffold ground-truth drafts
```

---

# Part 1 — ATS job posting extraction

## How the data is extracted

SmartRecruiters runs every public careers board off one documented JSON API, so
no HTML parsing is needed. Any company's board at
`https://jobs.smartrecruiters.com/<slug>` is backed by:

```
https://api.smartrecruiters.com/v1/companies/<slug>/postings
    ?limit=100&offset=0&destination=PUBLIC
```

No key, no auth. The response is a `content` array plus a `totalFound` count:

```json
{
  "offset": 0,
  "limit": 100,
  "totalFound": 4775,
  "content": [
    {
      "id": "744000146486959",
      "name": "Software Engineer",
      "typeOfEmployment": { "label": "Full-time" },
      "company": { "name": "Bosch Group" },
      "location": { "city": "Bengaluru", "region": "KA", "country": "in" },
      "department": { "label": "" },
      "function": { "label": "Engineering" }
    }
  ]
}
```

Field mapping in `SmartRecruitersBase.parse_postings`:

| Output field | Source |
|---|---|
| `internalType` | Always `""`; SmartRecruiters exposes no equivalent |
| `category_name` | `typeOfEmployment.label` |
| `company_name` | `company.name`, falling back to the spider's `company_name` |
| `job_title` | `name` |
| `job_href` | Built as `https://jobs.smartrecruiters.com/<slug>/<id>` |
| `job_city_des` | `location.fullLocation`, else `city, region, country` joined |
| `details_job` | `department.label`, falling back to `function.label` |

Two things worth calling out.

**`job_href` is constructed, not returned.** The API gives `id` but no public
URL, so the spider builds it from the slug and id.

**`details_job` needs a fallback.** Several companies (Bosch, Western Digital)
leave `department` empty on every posting but always populate `function`.
Taking `department` alone left the field blank on 87% of rows; the fallback
brings that to near zero without inventing data.

Pagination is offset-based: the spider keeps requesting `offset += limit` while
`offset + limit < totalFound`. Without it a board returns only its first 100
jobs.

## Run a spider

Spider names match the company name:

```bat
scrapy crawl SmartRecruiters -o jobs.json
scrapy crawl Bosch -o jobs.json
scrapy crawl Equinox -o jobs.json
scrapy crawl WesternDigital -o jobs.json
```

All spiders write to the same `jobs.json`, and each crawl merges new unique
jobs into it rather than overwriting or appending a second array. Bosch alone
yields several thousand jobs and takes about a minute.

List spiders with `scrapy list`.

## Output schema

One JSON array of unique job objects:

```json
[
  {
    "internalType": "",
    "category_name": "Full-time",
    "company_name": "SmartRecruiters Inc",
    "job_title": "Senior Information Security Engineer",
    "job_href": "https://jobs.smartrecruiters.com/smartrecruiters/744000143115219",
    "job_city_des": "Poland, REMOTE, Poland",
    "details_job": "Engineering"
  }
]
```

Duplicates are dropped by `job_href` in `UniqueJobPipeline`.

## Add another SmartRecruiters company

Subclass `SmartRecruitersBase` in `jobs/spiders/spiders_in_SmartRecruiters.py`:

```python
class AcmeSpider(SmartRecruitersBase):
    name = "Acme"
    company_name = "Acme"
    start_url = "https://jobs.smartrecruiters.com/Acme"
    start_urls = [start_url]
```

The last path segment of `start_url` is the API identifier. It is
case-sensitive and often differs from the display name — Bosch is
`BoschGroup`. A wrong slug is not an error: the API returns `200` with
`totalFound: 0`. Verify with:

```
https://api.smartrecruiters.com/v1/companies/<slug>/postings?limit=1&destination=PUBLIC
```

`VisaSpider` and `PlaidSpider` are the two companies named in the brief. Both
identifiers still resolve but their boards currently return `totalFound: 0`, so
they crawl cleanly and yield nothing. They are kept because an empty board is a
normal state a crawler has to tolerate.

---

# Part 2 — Job description content cleaning & structuring

## Technical design

The pipeline treats a *page template* as the unit of work, not a page. Every
posting on `jobs.lever.co` shares one DOM, so the expensive question — "where
does the description live in this markup?" — should be answered once and then
reused for free.

```
                       ┌──────────────┐
   job page URL ──────▶│    fetch     │  cached to .page_cache/
                       └──────┬───────┘
                              ▼
                   ┌──────────────────────┐
                   │  template known?     │  key = domain
                   └──────┬────────┬──────┘
                       no │        │ yes
                          ▼        │
              ┌────────────────┐   │   one strong-LLM call
              │  rulegen       │   │   per template, ever
              │  (qwen-max)    │   │
              │  DOM digest →  │   │
              │  CSS selectors │   │
              └───────┬────────┘   │
                      │ validate   │
                      ▼            ▼
                   ┌──────────────────┐
                   │  apply rules     │  free, ~15 ms
                   └────────┬─────────┘
                            ▼
                   ┌──────────────────┐
                   │ confidence score │  free, local
                   └───┬──────────┬───┘
                  ≥0.70│          │<0.70
                       ▼          ▼
                   ┌───────┐  ┌──────────────────────┐
                   │ done  │  │ relearn once, retry  │
                   └───────┘  └──────────┬───────────┘
                                         │ still low
                                         ▼
                              ┌──────────────────────┐
                              │ LLM fallback         │
                              │ (qwen-flash)         │
                              └──────────────────────┘
```

### Rule generation

Sending raw HTML to the model would be slow, expensive, and mostly wasted on
attributes it does not need. Instead `rulegen.dom_digest` reduces the page to
one line per text-bearing element:

```
div.job-post-container      | chars=5441 depth=3 | Account Executive, Emerging Enterprise...
div.job__description.body   | chars=4624 depth=5 | Figma is growing our team of passionate...
footer.footer.section       | chars=1263 depth=4 | Products and pricingPricingAtlas...
```

That is enough to pick the description container, at roughly 1,300 prompt
tokens instead of tens of thousands. The model returns JSON:

```json
{
  "container_selectors": ["div.job__description.body"],
  "remove_selectors": [],
  "use_jsonld": false,
  "confidence": 0.95,
  "notes": "Stable Greenhouse container; description sits in .job__description"
}
```

**Nothing the model proposes is trusted.** `rulegen.validate` runs the
selectors against the page and rejects them if they match nothing, yield under
200 characters, or swallow more than 97% of the page. A rejection is fed back
with the concrete reason and retried once. Only validated rules are cached to
`templates/`.

One special case is handled without any model call: a client-rendered board
(Ashby) serves markup with no readable text, so the digest comes out empty. If
such a page still embeds a schema.org `JobPosting`, that *is* the answer, and
the rule is written directly at zero cost.

### Confidence, and handling failure

The router needs to know whether the rules worked, without a human or another
model. `confidence.py` scores five free, local signals:

| Signal | Weight | Catches |
|---|---|---|
| `has_text` | 0.20 | Rule matched nothing |
| `rule_quality` | 0.15 | Fell through to a generic container |
| `has_sections` | 0.20 | Grabbed a teaser instead of the description |
| `low_boilerplate` | 0.15 | Swallowed nav, cookie banner or footer |
| `plausible_share` | 0.10 | Kept the whole page, or almost none of it |
| `grounded` | 0.20 | Text that is not on the page at all |

Below 0.70 the router assumes the site changed shape, relearns the template
once against the current page, and retries. If that still fails, the cheap LLM
takes the page so nothing is lost. Each learned template records a
`revision` and hit/miss counts in `templates/`, so drift is visible.

`grounded` deserves its own note — see the findings below.

### Model choice

Two models, because the two jobs have opposite cost profiles.

| Job | Model | Rate (per 1M tokens) | Why |
|---|---|---|---|
| Per-page extraction and fallback | `qwen-flash` | $0.05 in / $0.40 out | Runs on every fallback, so it drives cost. Copying text verbatim and dropping furniture needs instruction-following, not reasoning. |
| Rule generation | `qwen-max` | $1.60 in / $6.40 out | Runs once per template, ever. Reading an unfamiliar DOM is genuine reasoning, and a bad selector silently corrupts every later page on that domain. |

Rates are Alibaba Cloud Model Studio international list prices, verified
against the [pricing page](https://www.alibabacloud.com/help/en/model-studio/model-pricing)
(Aug 2026). Both are overridable via `EXTRACT_MODEL` / `RULEGEN_MODEL` in
`.env`, or `--model` / `--rulegen-model` on the CLI.

Qwen 2.5 was the original intent but is no longer served on this account; the
`qwen-flash` / `qwen-max` pair is the current equivalent split.

## Configuration

`.env`:

```
QWEN_API_KEY=your-model-studio-key
QWEN_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
EXTRACT_MODEL=qwen-flash
RULEGEN_MODEL=qwen-max
```

## Run

```bat
python compare_extraction.py                    :: all three approaches
python compare_extraction.py --no-llm           :: deterministic only, no API calls
python compare_extraction.py --relearn          :: discard cached rules and relearn
python compare_extraction.py --url <job-url>    :: ad-hoc page
```

Pages are cached in `.page_cache/` so all three approaches see identical bytes
and reruns cost nothing. Results land in `extraction_output/`, learned rules in
`templates/`.

To regenerate ground-truth drafts: `python scripts/make_gold.py`.

## Metrics

| Metric | Meaning |
|---|---|
| `boilerplate_hits` | Known furniture phrases still present. Lower is better. |
| `jd_sections_hits` | Description headings detected. Higher is better. |
| `kept_ratio` | Share of the page's words retained. |
| `grounding` | Share of extracted words that actually occur in the page. |
| `confidence` | Router's local estimate that extraction succeeded. |
| `agreement` | Token Jaccard between template and LLM output. |
| `latency_s`, tokens, `cost_usd` | Cost. |

`samples/gold/<page-id>.txt` holds ground truth; token precision, recall and F1
are reported for any page that has it. Files still carrying the
`# UNVERIFIED` header written by `make_gold.py` are ignored, so an unreviewed
draft can never be scored as if it were verified.

## The 10 pages

Ten job detail pages over six templates. Four templates appear twice, which is
what demonstrates reuse: the second page of a template must cost nothing.

| # | ATS / template | Company | Template key |
|---|---|---|---|
| 1 | SmartRecruiters | Bosch Group | `jobs.smartrecruiters.com` |
| 2 | SmartRecruiters | Equinox | `jobs.smartrecruiters.com` |
| 3 | Greenhouse | Anthropic | `job-boards.greenhouse.io` |
| 4 | Greenhouse | Anthropic | `job-boards.greenhouse.io` |
| 5 | Lever | Palantir | `jobs.lever.co` |
| 6 | Lever | Palantir | `jobs.lever.co` |
| 7 | Ashby | OpenAI | `jobs.ashbyhq.com` |
| 8 | Ashby | Ramp | `jobs.ashbyhq.com` |
| 9 | Breezy | Barloworld Equipment | `breezy.hr` |
| 10 | Greenhouse (legacy board) | Figma | `boards.greenhouse.io` |

Breezy/Barloworld is Example 1 from the brief. Greenhouse appears twice as two
genuinely different templates: `job-boards.greenhouse.io` and the older
`boards.greenhouse.io` have different DOMs.

## Comparison

Cold start — all six templates learned during the run. Full output in
`extraction_output/report_full.txt`.

| | Template-aware | LLM-only | Hybrid |
|---|---|---|---|
| Full-extraction rate | **10/10** | **10/10** | **10/10** |
| Avg words kept | 808 | 679 | 808 |
| Avg boilerplate hits | 0.7 | **0.3** | 0.7 |
| Avg JD sections found | 6.6 | **6.7** | 6.6 |
| Avg grounding | **100%** | 89.4% | **100%** |
| Pages with invented text | **0** | **2** | **0** |
| Avg latency | **0.015 s** | 5.56 s | **0.013 s** |
| Total tokens | 0 | 22,422 | 0 |
| One-time learning | $0.0156 | $0 | $0.0156 |
| Runtime cost per page | **$0** | $0.000418 | **$0** |
| **Total for 10 pages** | $0.0156 | $0.0042 | $0.0156 |
| **Projected 100,000 pages** | **$0.13** | $41.79 | **$0.13** |

Template learning: 6 of 6 templates learned successfully, 1 attempt each,
$0.0026 and 2.1 s per template, 8,007 prompt + 440 completion tokens total.

Hybrid routing: all 10 pages served by rules, 0% LLM fallback, 0 relearns.

The 100k projection assumes 50 distinct templates. Only LLM-only scales with
pages; the deterministic approaches scale with templates, which grows far more
slowly because a few dozen ATS platforms cover most postings. Even at a
pessimistic 500 templates the hybrid comes to $1.30.

### What the numbers say

**The LLM invents job descriptions when the page is client-rendered.** This is
the finding that matters most. Ashby ships 6 words of visible text; the real
posting is in JavaScript. Asked to extract a description from nothing,
`qwen-flash` did not refuse — it wrote a fluent, well-structured, entirely
fictional one from the job title:

> Lead end-to-end execution of complex technical programs across engineering,
> operations, and product teams. Define program goals, success metrics,
> timelines, and dependencies…

The real posting, which the rules read from JSON-LD, opens:

> **About the Team.** The compute infrastructure team runs the GPU fleet and
> large-scale compute clusters that serve the models backing ChatGPT and the
> API…

The fabricated version scores *better* than the real one on every content
metric: zero boilerplate, 5 detected sections, clean prose. Only the token
agreement (0.23) hints that anything is wrong. This is why `grounding` exists —
it checks what share of the extracted words actually occur anywhere in the
source HTML, and it puts the two Ashby pages at 65% and 39%, meaning a third to
two-thirds of the "job description" was never on the page. It is cheap to
compute and it is the single most useful guard in the pipeline.

**Boilerplate and completeness pull in opposite directions.** The LLM is
cleaner (0.3 vs 0.7 boilerplate hits) but keeps 16% fewer words. On the
SmartRecruiters/Equinox page the rules trailed `I'm interested / Privacy Notice
/ OneTrust Cookies Settings button` into the output, while the LLM dropped
genuine content. Cutting furniture and cutting description are the same
behaviour aimed differently.

**Structured data beats both.** Five of the ten pages resolved through
schema.org `JobPosting` rather than CSS, including all of Lever and Ashby.
Where a site publishes it, JSON-LD is more complete than any selector and
immune to layout changes. `apply_rules` therefore prefers JSON-LD whenever it
is more than 1.3× longer than what the CSS returned.

**Rule reuse works exactly as intended.** Six templates, ten pages, six model
calls. Pages 2, 4, 6 and 8 cost nothing and completed in ~15 ms.

**Speed differs by ~400x.** 0.015 s against 5.56 s per page. Over the 5,868
postings from Part 1 that is 90 seconds versus 9 hours.

**One sample URL was not what it claimed.** `stripe.com/jobs/search?gh_jid=…`
looks like a job page and returns 200, but the served HTML is the careers
*search* page with the posting rendered client-side. The rule generator
faithfully learned a selector for Stripe's EEO disclaimer, because that was the
only description-shaped text present. It was replaced with Figma. Worth
remembering that a page can be well-formed, fetchable, and still not contain
the thing you are extracting.

## Recommendation

**Run the hybrid.** It matched template-aware quality exactly on this sample at
identical cost, while carrying a fallback that only costs money on pages that
need it. Concretely:

1. **Rules first, always.** Free, 15 ms, and on this sample they handled 10/10
   pages.
2. **Prefer schema.org JSON-LD** where it exists. More complete than CSS and it
   survives redesigns.
3. **Gate every result on confidence, and gate the LLM on grounding.** An
   ungrounded LLM answer is worse than no answer, because it is undetectable
   downstream. Anything under ~90% grounding should be dropped or flagged, not
   stored.
4. **Learn templates lazily, on first sight of a domain**, with the strong
   model. At $0.0026 each this never becomes a budget line.
5. **Use the cheap model only as fallback.** At a 0% fallback rate the hybrid
   costs $0.13 per 100k pages; even at a 20% fallback rate it is ~$8.50,
   still 5x cheaper than LLM-only.

The one case where LLM-only earns its keep is a brand-new template with no
JSON-LD, where it produces something usable on the first page while rules are
still being learned. That is precisely the fallback slot the hybrid gives it.

## Limitations

- **Ground truth is drafted, not yet verified.** `scripts/make_gold.py` wrote
  drafts for all 10 pages from the best available extraction. Each carries an
  `# UNVERIFIED` header and is excluded from scoring until reviewed by hand, so
  no precision/recall/F1 figures are claimed above.
- **Marker lists are English-only.** Boilerplate and section detection will
  understate quality on non-English postings.
- **Ten pages is a small sample**, and a 0% fallback rate should not be read as
  "rules always work" — it means rules worked on six templates chosen partly
  because they are mainstream.
- **`grounding` catches invention, not omission.** A model that silently drops
  half a posting still scores 100%.
- **Latency for template-aware excludes the fetch**, which dominates in
  production and is identical for all three approaches.
