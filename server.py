import os
import re
import logging
from typing import Optional

import requests
from requests.adapters import HTTPAdapter, Retry
from flask import Flask, request, jsonify, abort
from openai import OpenAI

# Config logging
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

app = Flask(__name__)

# === CONFIGURATION ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# Optional: secret token to verify Telegram webhook source (set in setWebhook secret_token)
TELEGRAM_SECRET_TOKEN = os.getenv("TELEGRAM_SECRET_TOKEN")

# Validate required env vars early (avoid leaking tokens in logs)
missing = []
if not TELEGRAM_TOKEN:
    missing.append("TELEGRAM_TOKEN")
if not OPENAI_API_KEY:
    missing.append("OPENAI_API_KEY")
if missing:
    logger.error("Missing required environment variables: %s", ", ".join(missing))
    # Exit early to fail fast in the runtime environment
    raise SystemExit(1)

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

# Requests session with retries and timeouts
session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retries)
session.mount("https://", adapter)
session.headers.update({"Content-Type": "application/json"})

# Telegram limits
TELEGRAM_MAX_MESSAGE = 4096

# Characters to escape for MarkdownV2 according to Telegram docs
_MD_V2_CHARS_RE = re.compile(r"([_\*\[\]\(\)~`>#+\-=|{}.!\\])")

def escape_markdown_v2(text: str) -> str:
    """Escape text for Telegram MarkdownV2."""
    if not text:
        return text
    return _MD_V2_CHARS_RE.sub(r"\\\1", text)

def truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    # Reserve some space for a truncation note
    note = "\n\n[...] (troncato)"
    return text[:limit - len(note)] + note
