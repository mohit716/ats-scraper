from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem


class UniqueJobPipeline:
    def __init__(self):
        self.seen_hrefs = set()

    def process_item(self, item):
        adapter = ItemAdapter(item)
        job_href = adapter.get("job_href")
        if job_href and job_href in self.seen_hrefs:
            raise DropItem(f"Duplicate job: {job_href}")
        if job_href:
            self.seen_hrefs.add(job_href)
        return item
