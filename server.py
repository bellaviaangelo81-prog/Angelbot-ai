import os
import re
import logging
from typing import Optional
from datetime import datetime

from flask import Flask, request, jsonify, abort
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from openai import OpenAI

# Configure logging
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

app = Flask(__name__)

# === CONFIGURATION ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# Optional: secret token to verify Telegram webhook source (set when creating the webhook)
TELEGRAM_SECRET_TOKEN = os.getenv("TELEGRAM_SECRET_TOKEN")

# Validate required env vars early (fail fast)
_missing = []
if not TELEGRAM_TOKEN:
    _missing.append("TELEGRAM_TOKEN")
if not OPENAI_API_KEY:
    _missing.append("OPENAI_API_KEY")
if _missing:
    logger.error("Missing required environment variables: %s", ", ".join(_missing))
    raise SystemExit(1)

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
TELEGRAM_MAX_MESSAGE = 4096

# Requests session with retries and timeouts
session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retries)
session.mount("https://", adapter)
session.headers.update({"Content-Type": "application/json"})

# Characters to escape for MarkdownV2 according to Telegram docs
_MD_V2_CHARS_RE = re.compile(r"([_\*\[\]\(\)~`>#+\-=|{}.!\\])")


def escape_markdown_v2(text: str) -> str:
    """Escape text for Telegram MarkdownV2."""
    if not text:
        return ""
    return _MD_V2_CHARS_RE.sub(r"\\\1", text)


def truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    note = "\n\n[...] (troncato)"
    return text[: max(0, limit - len(note))] + note


@app.route("/", methods=["GET"])
def home():
    return "✅ AngelBot-AI (GPT-5) è online e operativo!", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    # Optional verification of the secret token to ensure webhook source
    if TELEGRAM_SECRET_TOKEN:
        header_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if not header_token or header_token != TELEGRAM_SECRET_TOKEN:
            logger.warning("Invalid or missing secret token on webhook request")
            # Return 401 so misconfigured clients can notice, but Telegram will not retry a 401 by default
            return jsonify({"ok": False, "error": "Unauthorized"}), 401

    data = request.get_json(silent=True)
    if not data or "message" not in data:
        logger.info("Webhook received empty or non-message update: %s", data)
        # Respond 200 to acknowledge the webhook but do not process
        return jsonify({"ok": True, "note": "No message to process"}), 200

    message = data["message"]
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = message.get("text")

    if not chat_id:
        logger.warning("Message without chat id: %s", message)
        return jsonify({"ok": True, "note": "No chat id"}), 200

    if not text:
        # Non-text messages (stickers, photos, etc.)
        logger.info("Non-text message received in chat %s: %s", chat_id, message.keys())
        # Optionally notify users that only text is supported
        try:
            payload = {
                "chat_id": chat_id,
                "text": "Mi dispiace, al momento supporto solo messaggi di testo.",
            }
            session.post(TELEGRAM_URL, json=payload, timeout=3)  # Reduced timeout for faster response
        except Exception:
            logger.exception("Failed to send non-text reply to chat %s", chat_id)
        return jsonify({"ok": True}), 200

    text = text.strip()
    # Handle basic commands
    if text.lower() in ["/start", "/help", "ciao", "hello"]:
        reply = (
            "👋 Ciao! Sono *AngelBot-AI*, potenziato da GPT-4o con accesso al web in tempo reale.\n\n"
            "🌐 Posso navigare sul web e fornire informazioni aggiornate!\n"
            "⚡ Ottimizzato per risposte veloci e precise.\n\n"
            "Scrivimi qualsiasi cosa e ti risponderò come un vero assistente AI."
        )
        # Escape and send reply as MarkdownV2
        safe = escape_markdown_v2(reply)
        try:
            session.post(
                TELEGRAM_URL,
                json={
                    "chat_id": chat_id,
                    "text": safe,
                    "parse_mode": "MarkdownV2",
                    "disable_web_page_preview": True,
                },
                timeout=3,  # Reduced timeout for faster response
            )
        except Exception:
            logger.exception("Failed to send command reply to chat %s", chat_id)
        return jsonify({"ok": True}), 200

    # Build prompt for the model with web search capability
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    # Enhanced system prompt with web search instructions
    system_instructions = (
        f"Sei AngelBot-AI, un assistente AI avanzato con accesso al web in tempo reale. "
        f"Data attuale: {current_date}. "
        f"Quando l'utente chiede informazioni che richiedono dati aggiornati o ricerche web, "
        f"rispondi con precisione usando le tue capacità di navigazione web. "
        f"Fornisci sempre risposte complete e dettagliate."
    )
    
    try:
        # Use Chat Completions API for faster response with streaming capability
        # This is more performant than the Responses API
        response = client.chat.completions.create(
            model="gpt-4o",  # Using gpt-4o for faster performance and web capabilities
            messages=[
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": text}
            ],
            temperature=0.7,
            max_tokens=1500,  # Optimized for faster responses
            timeout=20  # Reduced timeout for faster response
        )
        
        reply = response.choices[0].message.content
        
        if not reply:
            reply = "Mi dispiace, non sono riuscito a ottenere una risposta dall'AI."

    except Exception as e:
        logger.exception("Error while calling OpenAI for chat %s", chat_id)
        reply = f"⚠️ Errore con l'AI: {str(e)}"

    # Escape and truncate for Telegram MarkdownV2
    safe_reply = escape_markdown_v2(reply)
    safe_reply = truncate_text(safe_reply, TELEGRAM_MAX_MESSAGE)

    # Send reply to Telegram
    payload = {
        "chat_id": chat_id,
        "text": safe_reply,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }

    try:
        session.post(TELEGRAM_URL, json=payload, timeout=3)  # Reduced timeout for faster response
    except Exception:
        logger.exception("Failed to send reply to chat %s", chat_id)

    # Always acknowledge the webhook to Telegram with 200 to avoid retries
    return jsonify({"ok": True}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
