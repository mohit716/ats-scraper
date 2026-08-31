from jobs.spiders.SmartRecruitersBase import SmartRecruitersBase


class SmartRecruitersSpider(SmartRecruitersBase):
    name = "smartrecruiters"
    company_name = "SmartRecruiters"
    company_identifier = "smartrecruiters"


class EquinoxSpider(SmartRecruitersBase):
    name = "equinox"
    company_name = "Equinox"
    company_identifier = "Equinox"


class WesternDigitalSpider(SmartRecruitersBase):
    name = "westerndigital"
    company_name = "Western Digital"
    company_identifier = "WesternDigital"


class BoschSpider(SmartRecruitersBase):
    name = "bosch"
    company_name = "Bosch"
    company_identifier = "BoschGroup"
