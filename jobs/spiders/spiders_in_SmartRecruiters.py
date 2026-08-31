from jobs.spiders.SmartRecruitersBase import SmartRecruitersBase


class SmartRecruitersSpider(SmartRecruitersBase):
    name = "SmartRecruiters"
    company_name = "SmartRecruiters"
    company_identifier = "smartrecruiters"


class VisaSpider(SmartRecruitersBase):
    name = "Visa"
    company_name = "Visa"
    company_identifier = "visa"


class PlaidSpider(SmartRecruitersBase):
    name = "Plaid"
    company_name = "Plaid"
    company_identifier = "plaid"
