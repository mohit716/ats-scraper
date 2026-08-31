BOT_NAME = "jobs"

SPIDER_MODULES = ["jobs.spiders"]
NEWSPIDER_MODULE = "jobs.spiders"

# Respect robots.txt policies
ROBOTSTXT_OBEY = False

# Configure UTF-8 encoding for JSON exports
FEED_EXPORT_ENCODING = "utf-8"
