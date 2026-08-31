import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")

CACHE_DIR = PROJECT_ROOT / ".page_cache"
OUTPUT_DIR = PROJECT_ROOT / "extraction_output"
# Learned selectors live in the repo: they are the reusable artifact the
# template-aware approach produces, and committing them proves reuse.
TEMPLATE_DIR = PROJECT_ROOT / "templates"
GOLD_DIR = PROJECT_ROOT / "samples" / "gold"

QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_BASE_URL = os.getenv(
    "QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)

# Two models with different jobs.
#
# EXTRACT_MODEL runs once per page in the LLM-only approach and on every
# fallback, so it is the cost driver: qwen-flash is the cheapest tier that
# still follows a "copy this text verbatim, drop that text" instruction.
#
# RULEGEN_MODEL runs once per template, ever. Reading an unfamiliar DOM and
# proposing selectors is a genuine reasoning task and a wrong selector is
# expensive because it silently corrupts every later page on that domain, so
# the strongest model is worth it at a per-template price.
EXTRACT_MODEL = os.getenv("EXTRACT_MODEL", "qwen-flash")
RULEGEN_MODEL = os.getenv("RULEGEN_MODEL", "qwen-max")

# Retained so older commands keep working; treated as the extraction model.
QWEN_MODEL = os.getenv("QWEN_MODEL", EXTRACT_MODEL)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

REQUEST_TIMEOUT = 30

# Sent to the model as plain text. Long postings still fit comfortably, and
# truncating keeps a single runaway page from dominating cost.
MAX_LLM_INPUT_CHARS = 24000

# Rule generation sees markup rather than text, which is far denser, so it
# gets its own larger budget.
MAX_RULEGEN_INPUT_CHARS = 60000
