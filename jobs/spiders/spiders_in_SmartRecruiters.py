"""Company spiders for the SmartRecruiters ATS.

Each class inherits from SmartRecruitersBase and only declares which board to
crawl. Spider names match the company name, so run them as::

    scrapy crawl Bosch -o jobs.json
"""

from jobs.spiders.SmartRecruitersBase import SmartRecruitersBase


class SmartRecruitersSpider(SmartRecruitersBase):
    name = "SmartRecruiters"
    company_name = "SmartRecruiters"
    start_url = "https://jobs.smartrecruiters.com/smartrecruiters"
    start_urls = [start_url]


class BoschSpider(SmartRecruitersBase):
    name = "Bosch"
    company_name = "Bosch"
    start_url = "https://jobs.smartrecruiters.com/BoschGroup"
    start_urls = [start_url]


class EquinoxSpider(SmartRecruitersBase):
    name = "Equinox"
    company_name = "Equinox"
    start_url = "https://jobs.smartrecruiters.com/Equinox"
    start_urls = [start_url]


class WesternDigitalSpider(SmartRecruitersBase):
    name = "WesternDigital"
    company_name = "Western Digital"
    start_url = "https://jobs.smartrecruiters.com/WesternDigital"
    start_urls = [start_url]


# Visa and Plaid are the two companies named in the challenge brief. Both
# identifiers still resolve on the API but currently return totalFound: 0,
# so they crawl cleanly and yield nothing. They are kept here because an
# empty board is a normal state a production crawler has to tolerate, not a
# bug to be worked around.
class VisaSpider(SmartRecruitersBase):
    name = "Visa"
    company_name = "Visa"
    start_url = "https://jobs.smartrecruiters.com/visa"
    start_urls = [start_url]


class PlaidSpider(SmartRecruitersBase):
    name = "Plaid"
    company_name = "Plaid"
    start_url = "https://jobs.smartrecruiters.com/plaid"
    start_urls = [start_url]
