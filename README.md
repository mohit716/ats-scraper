# ATS Scraper

Scrapy project that pulls public job postings from the [SmartRecruiters API](https://api.smartrecruiters.com) and writes them as a single JSON array.

## Setup

From the project root:

```bat
pip install -r requirements.txt
```

Requires Python 3.10+ and Scrapy 2.18+.

## Project layout

```
ats-scraper/
├── scrapy.cfg
├── requirements.txt
└── jobs/
    ├── items.py
    ├── middlewares.py
    ├── pipelines.py
    ├── settings.py
    └── spiders/
        ├── SmartRecruitersBase.py          # Shared API extraction
        └── spiders_in_SmartRecruiters.py   # Company spiders
```

## Run a spider

All company spiders write to the same `jobs.json`. Each crawl merges new unique jobs into that file:

```bat
scrapy crawl smartrecruiters -o jobs.json
scrapy crawl equinox -o jobs.json
scrapy crawl westerndigital -o jobs.json
scrapy crawl bosch -o jobs.json
```

Each spider pages through the whole board, so a large company like Bosch yields
several thousand jobs and takes about a minute.

List spiders:

```bat
scrapy list
```

## Output schema

Each file is one JSON array of unique job objects:

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

In `jobs/spiders/spiders_in_SmartRecruiters.py`, subclass `SmartRecruitersBase`:

```python
class AcmeSpider(SmartRecruitersBase):
    name = "acme"
    company_name = "Acme"
    company_identifier = "acme"
```

`company_identifier` is the slug in the SmartRecruiters careers URL / API path.
It is case-sensitive and often differs from the display name (Bosch is
`BoschGroup`). A wrong slug is not an error: the API returns `200` with
`totalFound: 0`, so verify against
`https://api.smartrecruiters.com/v1/companies/<slug>/postings?limit=1&destination=PUBLIC`.
