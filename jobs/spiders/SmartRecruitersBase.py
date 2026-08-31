import json
import scrapy


class SmartRecruitersBase(scrapy.Spider):
    company_identifier = ""  # Set by child class (e.g., 'visa')
    company_name = ""        # Set by child class (e.g., 'Visa')
    page_limit = 100

    def postings_url(self, offset):
        return (
            f"https://api.smartrecruiters.com/v1/companies/{self.company_identifier}"
            f"/postings?limit={self.page_limit}&offset={offset}&destination=PUBLIC"
        )

    async def start(self):
        if not self.company_identifier:
            raise ValueError("company_identifier must be defined in the spider class.")

        yield scrapy.Request(url=self.postings_url(0), callback=self.parse_postings)

    def parse_postings(self, response):
        data = json.loads(response.text)
        postings = data.get("content", [])

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
        if postings and next_offset < data.get("totalFound", 0):
            yield scrapy.Request(
                url=self.postings_url(next_offset), callback=self.parse_postings
            )
