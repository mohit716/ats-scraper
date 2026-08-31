import scrapy


class JobItem(scrapy.Item):
    internalType = scrapy.Field()
    category_name = scrapy.Field()
    company_name = scrapy.Field()
    job_title = scrapy.Field()
    job_href = scrapy.Field()
    job_city_des = scrapy.Field()
    details_job = scrapy.Field()
