import os
import requests
from flask import Flask, request
from datetime import datetime, timedelta
import threading
import time
import yfinance as yf
from openai import OpenAI

# === CONFIG ===
app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")  # Imposta questo su Render
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # Imposta questo su Render
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://angelbot-ai.onrender.com")

# === VARIABILI ===
client = OpenAI(api_key=OPENAI_API_KEY)
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
user_monitor_settings = {}  # {chat_id: {"interval": minuti, "active": bool, "last_check": datetime}}

# === FUNZIONI TELEGRAM ===
def send_message(chat_id, text):
    requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={"chat_id": chat_id, "text": text})

def send_typing(chat_id):
    requests.post(f"{TELEGRAM_API_URL}/sendChatAction", json={"chat_id": chat_id, "action": "typing"})

def build_monitoraggio_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [{"text": "Ogni 30 minuti", "callback_data": "30"}],
            [{"text": "Ogni 1 ora", "callback_data": "60"}],
            [{"text": "Ogni 6 ore", "callback_data": "360"}],
            [{"text": "Ogni giorno", "callback_data": "1440"}],
            [{"text": "Ogni settimana", "callback_data": "10080"}],
            [{"text": "Disattiva", "callback_data": "off"}]
        ]
    }
    requests.post(
        f"{TELEGRAM_API_URL}/sendMessage",
        json={"chat_id": chat_id, "text": "Scegli la frequenza di monitoraggio:", "reply_markup": keyboard}
    )

# === FUNZIONI DATI AZIONI ===
def get_stock_info(symbol):
    ticker = yf.Ticker(symbol)
    data = ticker.history(period="1d")
    if data.empty:
        return None
    price = round(data["Close"].iloc[-1], 2)
    change = round(data["Close"].iloc[-1] - data["Open"].iloc[-1], 2)
    perc = round((change / data["Open"].iloc[-1]) * 100, 2)
    return f"{symbol}: {price}$ ({perc}%)"

# === FUNZIONE OPENAI ===
def ask_openai(question):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Sei un assistente esperto di investimenti e analisi azionarie."},
                {"role": "user", "content": question}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Errore OpenAI: {e}"

# === MONITORAGGIO AUTOMATICO ===
def monitor_loop():
    while True:
        now = datetime.utcnow()
        for chat_id, settings in user_monitor_settings.items():
            if not settings["active"]:
                continue
            last = settings.get("last_check", datetime.min)
            if now - last > timedelta(minutes=settings["interval"]):
                stocks = ["AAPL", "AMZN", "MSFT", "TSLA", "BIDU", "BMPS.MI"]
                results = [get_stock_info(s) for s in stocks]
                results = [r for r in results if r]
                if results:
                    send_message(chat_id, "📈 Aggiornamento automatico:\n" + "\n".join(results))
                user_monitor_settings[chat_id]["last_check"] = now
        time.sleep(60)

threading.Thread(target=monitor_loop, daemon=True).start()

# === WEBHOOK TELEGRAM ===
@app.route(f"/{os.getenv('TELEGRAM_TOKEN')}", methods=["POST"])
def webhook():
    data = request.get_json()

    # Gestione messaggi testuali
    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "").lower()

        if text in ["/start", "start"]:
            send_message(chat_id, "👋 Benvenuto! Puoi chiedermi analisi su azioni, consigli o impostare un monitoraggio.")
            build_monitoraggio_menu(chat_id)

        elif "monitoraggio" in text:
            build_monitoraggio_menu(chat_id)

        elif text.startswith("analisi") or text.startswith("consiglio") or text.startswith("dimmi"):
            send_typing(chat_id)
            reply = ask_openai(text)
            send_message(chat_id, reply)

        else:
            send_typing(chat_id)
            ai_reply = ask_openai(text)
            send_message(chat_id, ai_reply)

    # Gestione pulsanti (callback)
    elif "callback_query" in data:
        chat_id = data["callback_query"]["message"]["chat"]["id"]
        selection = data["callback_query"]["data"]

        if selection == "off":
            user_monitor_settings[chat_id] = {"active": False, "interval": 0}
            send_message(chat_id, "🔕 Monitoraggio disattivato.")
        else:
            interval = int(selection)
            user_monitor_settings[chat_id] = {"active": True, "interval": interval, "last_check": datetime.utcnow()}
            send_message(chat_id, f"✅ Monitoraggio attivo ogni {interval} minuti.")

    return "OK", 200

# === IMPOSTAZIONE WEBHOOK ===
@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    url = f"{WEBHOOK_URL}/{TELEGRAM_TOKEN}"
    response = requests.get(f"{TELEGRAM_API_URL}/setWebhook?url={url}")
    return response.text

@app.route("/", methods=["GET"])
def home():
    return "Bot attivo!"

# === AVVIO APP ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
