import os
import json
import logging
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request
from report import (
    send_price_for_chat,
    send_chart_for_chat,
    send_analysis_for_chat,
    send_portfolio,
    genera_report_giornaliero,
)
from report import telegram_send_message, ask_openai_text

app = Flask(__name__)
logger = logging.getLogger("angelbot.app")
logger.setLevel(logging.INFO)

# Config
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "angel_secret")
TZ_ITALY = ZoneInfo("Europe/Rome")
DATA_FILE = "users.json"

# Carica la memoria mini locale
def load_user_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logger.exception("Errore caricando users.json")
    return {}

def save_user_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.exception("Errore salvando users.json")

# Mini memoria contestuale
def append_user_context(chat_id: str, role: str, content: str):
    data = load_user_data()
    u = data.get(str(chat_id), {})
    ctx = u.get("context", [])
    ctx.append({"role": role, "content": content})
    # mantiene solo ultimi 5 messaggi
    u["context"] = ctx[-5:]
    data[str(chat_id)] = u
    save_user_data(data)

def get_user_context(chat_id: str):
    data = load_user_data()
    return data.get(str(chat_id), {}).get("context", [])

@app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def telegram_webhook():
    update = request.json
    if not update:
        return "no update", 200

    message = update.get("message", {})
    chat_id = str(message.get("chat", {}).get("id"))
    text = message.get("text", "").strip()

    if not chat_id or not text:
        return "no message", 200

    # Comandi principali
    if text.startswith("/start"):
        telegram_send_message(chat_id, "👋 Ciao! Sono AngelBot, il tuo assistente AI finanziario e personale.")
    elif text.startswith("/price"):
        parts = text.split()
        if len(parts) >= 2:
            send_price_for_chat(chat_id, parts[1].upper())
        else:
            telegram_send_message(chat_id, "Usa /price TICKER (es. /price AAPL)")
    elif text.startswith("/chart"):
        parts = text.split()
        if len(parts) >= 2:
            send_chart_for_chat(chat_id, parts[1].upper())
        else:
            telegram_send_message(chat_id, "Usa /chart TICKER")
    elif text.startswith("/analisi"):
        parts = text.split()
        if len(parts) >= 2:
            send_analysis_for_chat(chat_id, parts[1].upper())
        else:
            telegram_send_message(chat_id, "Usa /analisi TICKER")
    elif text.startswith("/portfolio"):
        send_portfolio(chat_id)
    elif text.startswith("/report"):
        genera_report_giornaliero(chat_id)
    else:
        # Chat AI contestuale
        append_user_context(chat_id, "user", text)
        context = get_user_context(chat_id)
        messages = [{"role": "system", "content": "Sei AngelBot, un AI che risponde in italiano in modo sintetico e chiaro."}] + context
        response = ask_openai_text("\n".join([m["content"] for m in messages]), max_tokens=150)
        append_user_context(chat_id, "assistant", response)
        telegram_send_message(chat_id, response)

    return "ok", 200

@app.route("/")
def home():
    return f"AngelBot attivo {datetime.now(TZ_ITALY).strftime('%d/%m %H:%M')} 🇮🇹"

# Avvio thread per report automatico (giornaliero ogni 24 ore)
def start_report_thread():
    def loop():
        while True:
            genera_report_giornaliero()
            logger.info("Report giornaliero completato.")
            import time
            time.sleep(24 * 3600)  # ogni 24 ore
    th = threading.Thread(target=loop, daemon=True)
    th.start()

if __name__ == "__main__":
    start_report_thread()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
