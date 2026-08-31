import json
import scrapy


class SmartRecruitersBase(scrapy.Spider):
    company_identifier = ""  # Set by child class (e.g., 'visa')
    company_name = ""        # Set by child class (e.g., 'Visa')

    def start_requests(self):
        if not self.company_identifier:
            raise ValueError("company_identifier must be defined in the spider class.")

        url = f"https://api.smartrecruiters.com/v1/companies/{self.company_identifier}/postings?limit=100&offset=0&destination=PUBLIC"
        yield scrapy.Request(url=url, callback=self.parse_postings)

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
                "category_name": item.get("typeOfEmployment", {}).get("label", ""),
                "company_name": item.get("company", {}).get("name", self.company_name),
                "job_title": item.get("name", ""),
                "job_href": job_href,
                "job_city_des": job_city_des,
                "details_job": item.get("department", {}).get("label", ""),
            }
