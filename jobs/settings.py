BOT_NAME = "jobs"

SPIDER_MODULES = ["jobs.spiders"]
NEWSPIDER_MODULE = "jobs.spiders"

# Respect robots.txt policies
ROBOTSTXT_OBEY = False

# Configure UTF-8 encoding for JSON exports
FEED_EXPORT_ENCODING = "utf-8"
FEED_EXPORT_INDENT = 2

# ``-o jobs.json`` merges into one valid JSON array instead of appending
# raw arrays or writing a separate file per spider.
FEED_STORAGES = {
    "": "jobs.feedstorage.MergingFileFeedStorage",
    "file": "jobs.feedstorage.MergingFileFeedStorage",
}
FEED_EXPORTERS = {
    "json": "jobs.feedstorage.MergingJsonItemExporter",
}

ITEM_PIPELINES = {
    "jobs.pipelines.UniqueJobPipeline": 300,
}
