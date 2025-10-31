from flask import Flask, request, jsonify
import os
import requests
import logging
import yfinance as yf

app = Flask(__name__)

# === CONFIG ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

logging.basicConfig(level=logging.INFO)

# === HOME ===
@app.route('/')
def home():
    return "🌍 Bot Telegram con GPT-4o + Dati Azioni per Continente è online!"

# === WEBHOOK ===
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logging.info(data)

        if "message" in data:
            handle_message(data["message"])
        elif "callback_query" in data:
            handle_callback(data["callback_query"])

        return jsonify({"ok": True})
    except Exception as e:
        logging.error(f"Errore nel webhook: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# === GESTIONE MESSAGGI ===
def handle_message(message):
    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()

    if text.lower() == "/start":
        send_message(
            chat_id,
            "Ciao! 🌍 Sono il tuo assistente connesso a GPT-4o.\n\n"
            "Puoi chattare con me oppure esplorare i mercati per continente:",
            buttons=[
                {"text": "💬 Chatta con GPT-4o", "callback_data": "chat"},
                {"text": "📊 Azioni per Continente", "callback_data": "continenti"},
            ]
        )
    else:
        # Risposta GPT
        answer = ask_gpt(text)
        send_message(chat_id, answer)


# === CALLBACK HANDLER ===
def handle_callback(query):
    chat_id = query["message"]["chat"]["id"]
    data = query["data"]

    if data == "chat":
        send_message(chat_id, "Scrivimi qualsiasi cosa e risponderò con GPT-4o ✨")

    elif data == "continenti":
        send_message(
            chat_id,
            "Scegli un continente per vedere le azioni principali:",
            buttons=[
                {"text": "🇺🇸 America", "callback_data": "america"},
                {"text": "🇪🇺 Europa", "callback_data": "europa"},
                {"text": "🇨🇳 Asia", "callback_data": "asia"},
                {"text": "🌍 Altri", "callback_data": "altri"},
            ]
        )

    elif data in ["america", "europa", "asia", "altri"]:
        show_stocks(chat_id, data)

    elif data.startswith("stock_"):
        ticker = data.split("_")[1]
        info = get_stock_info(ticker)
        send_message(chat_id, info)

    else:
        send_message(chat_id, "❓ Comando non riconosciuto.")


# === GPT-4o ===
def ask_gpt(prompt):
    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}]
        }

        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload
        )

        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    except Exception as e:
        logging.error(f"Errore GPT: {e}")
        return "⚠️ Errore nella connessione con GPT-4o."


# === DATI AZIONI ===
def show_stocks(chat_id, continent):
    stocks = {
        "america": {
            "Apple": "AAPL",
            "Tesla": "TSLA",
            "Microsoft": "MSFT",
            "Amazon": "AMZN",
            "Coca-Cola": "KO"
        },
        "europa": {
            "ENI": "ENI.MI",
            "Volkswagen": "VOW3.DE",
            "LVMH": "MC.PA",
            "BP": "BP.L",
            "Nestlé": "NESN.SW"
        },
        "asia": {
            "Toyota": "7203.T",
            "Alibaba": "BABA",
            "Samsung": "005930.KS",
            "Tencent": "0700.HK",
            "Sony": "6758.T"
        },
        "altri": {
            "BHP Group (Australia)": "BHP.AX",
            "Petrobras (Brasile)": "PBR",
            "Naspers (Sudafrica)": "NPN.JO",
            "Saudi Aramco": "2222.SR"
        }
    }

    continent_stocks = stocks.get(continent, {})
    buttons = [{"text": f"{k}", "callback_data": f"stock_{v}"} for k, v in continent_stocks.items()]
    send_message(chat_id, f"📈 Azioni principali in {continent.capitalize()}:", buttons=buttons)


def get_stock_info(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        name = info.get("longName", ticker)
        price = info.get("regularMarketPrice", "N/D")
        currency = info.get("currency", "")
        change = info.get("regularMarketChangePercent", 0)

        return (
            f"📊 {name}\n"
            f"💵 Prezzo: {price} {currency}\n"
            f"📈 Variazione: {round(change, 2)}%\n\n"
            f"(Dati forniti da Yahoo Finance)"
        )
    except Exception as e:
        logging.error(f"Errore nel recupero dati azione {ticker}: {e}")
        return f"❌ Errore nel recupero dati per {ticker}"


# === INVIO MESSAGGIO TELEGRAM ===
def send_message(chat_id, text, buttons=None):
    payload = {"chat_id": chat_id, "text": text}

    if buttons:
        keyboard = {"inline_keyboard": [[b] for b in buttons]}
        payload["reply_markup"] = keyboard

    try:
        requests.post(f"{TELEGRAM_URL}/sendMessage", json=payload)
    except Exception as e:
        logging.error(f"Errore nell'invio messaggio: {e}")


# === AVVIO SERVER ===
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
