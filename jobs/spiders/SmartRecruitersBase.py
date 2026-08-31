"""Base crawler for companies hosted on SmartRecruiters.

Every public SmartRecruiters board is backed by the same JSON API, so a
company spider only has to declare its board URL::

    class PlaidSpider(SmartRecruitersBase):
        name = "Plaid"
        company_name = "Plaid"
        start_url = "https://jobs.smartrecruiters.com/plaid"
        start_urls = [start_url]

The trailing path segment of ``start_url`` is the identifier the API expects,
and it is case sensitive: "BoschGroup", not "boschgroup".
"""

import json
from urllib.parse import urlparse

import scrapy


class SmartRecruitersBase(scrapy.Spider):
    start_url = ""
    start_urls = []
    company_name = ""
    # Derived from start_url when a child class leaves it blank.
    company_identifier = ""
    page_limit = 100

    def resolve_company_identifier(self):
        if self.company_identifier:
            return self.company_identifier

        source = self.start_url or (self.start_urls[0] if self.start_urls else "")
        slug = urlparse(source).path.strip("/").split("/")[-1]
        if not slug:
            raise ValueError(
                f"{type(self).__name__} must set start_url or company_identifier."
            )
        return slug

    def postings_url(self, offset):
        return (
            f"https://api.smartrecruiters.com/v1/companies/{self.company_identifier}"
            f"/postings?limit={self.page_limit}&offset={offset}&destination=PUBLIC"
        )

    async def start(self):
        self.company_identifier = self.resolve_company_identifier()
        yield scrapy.Request(url=self.postings_url(0), callback=self.parse_postings)

    def parse_postings(self, response):
        data = json.loads(response.text)
        postings = data.get("content", [])

        total = data.get("totalFound", 0)
        if not postings and not total:
            self.logger.warning(
                "%s returned no postings. The board may be closed or the "
                "identifier %r may be wrong.",
                self.name,
                self.company_identifier,
            )

        for item in postings:
            posting_id = item.get("id")
            job_href = (
                f"https://jobs.smartrecruiters.com/{self.company_identifier}/{posting_id}"
                if posting_id
                else ""
            )

            # Some companies (Bosch, Western Digital) leave department empty
            # but always populate function.
            details_job = (
                item.get("department", {}).get("label")
                or item.get("function", {}).get("label")
                or ""
            )

            location = item.get("location", {})
            job_city_des = location.get("fullLocation") or ", ".join(
                filter(
                    None,
                    [
                        location.get("city"),
                        location.get("region"),
                        location.get("country"),
                    ],
                )
            )

            yield {
                "internalType": "",
                "category_name": (item.get("typeOfEmployment", {}).get("label") or "").strip(),
                "company_name": (item.get("company", {}).get("name") or self.company_name).strip(),
                "job_title": (item.get("name") or "").strip(),
                "job_href": job_href,
                "job_city_des": job_city_des.strip() if job_city_des else "",
                "details_job": details_job.strip(),
            }

        offset = data.get("offset", 0)
        limit = data.get("limit", self.page_limit)
        next_offset = offset + limit
        if postings and next_offset < total:
            yield scrapy.Request(
                url=self.postings_url(next_offset), callback=self.parse_postings
            )
