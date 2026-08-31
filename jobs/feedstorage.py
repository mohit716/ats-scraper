import json
from pathlib import Path

from itemadapter import ItemAdapter
from scrapy.exporters import BaseItemExporter
from scrapy.utils.python import to_bytes


def _load_existing_items(path):
    file_path = Path(path)
    if not file_path.exists() or file_path.stat().st_size == 0:
        return []
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


class MergingFileFeedStorage:
    """Open the output file for rewrite after loading any existing JSON array."""

    def __init__(self, uri, *, feed_options=None):
        self.path = uri[5:] if uri.startswith("file:") else uri
        self.existing_items = _load_existing_items(self.path)

    def open(self, spider):
        dirname = Path(self.path).parent
        if str(dirname) and not dirname.exists():
            dirname.mkdir(parents=True)
        file = Path(self.path).open("wb")
        file.existing_items = self.existing_items
        return file

    def store(self, file):
        file.close()
        return None


class MergingJsonItemExporter(BaseItemExporter):
    """Write a single JSON array, merging new jobs into any existing file."""

    def __init__(self, file, **kwargs):
        super().__init__(dont_fail=True, **kwargs)
        self.file = file
        self.items = list(getattr(file, "existing_items", []) or [])
        self.seen_hrefs = {
            item.get("job_href")
            for item in self.items
            if isinstance(item, dict) and item.get("job_href")
        }

    def export_item(self, item):
        itemdict = dict(self.get_serialized_fields(item))
        job_href = itemdict.get("job_href")
        if job_href and job_href in self.seen_hrefs:
            return
        if job_href:
            self.seen_hrefs.add(job_href)
        self.items.append(itemdict)

    def finish_exporting(self):
        indent = self.indent if self.indent is not None and self.indent > 0 else 2
        data = json.dumps(self.items, indent=indent, ensure_ascii=False)
        self.file.write(to_bytes(data, self.encoding or "utf-8"))
        self.file.write(b"\n")
