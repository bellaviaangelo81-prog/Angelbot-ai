from flask import Flask, request
import requests
import os
import logging
import yfinance as yf
import matplotlib.pyplot as plt
import io
import base64
from openai import OpenAI

# === CONFIGURAZIONE BASE ===
app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Legge le variabili d’ambiente
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://angelbot-ai.onrender.com")  # Fallback
client = OpenAI(api_key=OPENAI_API_KEY)

# URL base Telegram
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# === ROTTA PRINCIPALE ===
@app.route("/", methods=["GET"])
def home():
    return "AngelBot AI attivo ✅", 200


# === WEBHOOK TELEGRAM ===
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        update = request.get_json()
        logger.info(f"Update ricevuto: {update}")

        if "message" not in update:
            return "OK", 200

        message = update["message"]
        chat_id = message["chat"]["id"]
        text = message.get("text", "")

        # Comandi base
        if text.startswith("/start"):
            send_message(chat_id, "👋 Ciao! Sono AngelBot AI. Posso aiutarti con finanza, AI e dati in tempo reale!")
        elif text.startswith("/help"):
            send_message(chat_id, "📘 Comandi disponibili:\n/start\n/help\n/stock <simbolo>\n/ai <domanda>")
        elif text.startswith("/stock"):
            handle_stock_command(chat_id, text)
        elif text.startswith("/ai"):
            handle_ai_command(chat_id, text)
        else:
            send_message(chat_id, "Non capisco questo comando 🤔. Usa /help per l’elenco.")

        return "OK", 200
    except Exception as e:
        logger.error(f"Errore nel webhook: {e}")
        return "Error", 500


# === FUNZIONE MESSAGGI TELEGRAM ===
def send_message(chat_id, text):
    url = f"{TELEGRAM_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)


# === COMANDO: STOCK ===
def handle_stock_command(chat_id, text):
    try:
        parts = text.split(" ")
        if len(parts) < 2:
            send_message(chat_id, "📉 Usa /stock <simbolo> (es. /stock AAPL)")
            return

        symbol = parts[1].upper()
        data = yf.Ticker(symbol)
        hist = data.history(period="5d")

        if hist.empty:
            send_message(chat_id, f"Nessun dato trovato per {symbol}.")
            return

        # Grafico
        plt.figure(figsize=(6, 3))
        plt.plot(hist.index, hist["Close"], label=f"{symbol} - Prezzo Chiusura")
        plt.title(f"Andamento {symbol}")
        plt.xlabel("Data")
        plt.ylabel("Prezzo ($)")
        plt.legend()

        # Salva grafico come immagine base64
        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        buf.seek(0)
        plt.close()
        img_b64 = base64.b64encode(buf.read()).decode("utf-8")

        # Invia il grafico
        send_photo(chat_id, img_b64)

        prezzo = hist["Close"].iloc[-1]
        send_message(chat_id, f"💰 Prezzo attuale di {symbol}: ${prezzo:.2f}")

    except Exception as e:
        logger.error(f"Errore stock: {e}")
        send_message(chat_id, f"Errore nel recupero dati di {symbol}.")


def send_photo(chat_id, img_b64):
    url = f"{TELEGRAM_URL}/sendPhoto"
    img_data = base64.b64decode(img_b64)
    files = {'photo': ('chart.png', img_data)}
    data = {'chat_id': chat_id}
    requests.post(url, files=files, data=data)


# === COMANDO: AI ===
def handle_ai_command(chat_id, text):
    try:
        question = text.replace("/ai", "").strip()
        if not question:
            send_message(chat_id, "💬 Usa /ai <domanda> (es. /ai spiegami la blockchain)")
            return

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Sei un assistente esperto di finanza e tecnologia."},
                {"role": "user", "content": question}
            ]
        )

        answer = response.choices[0].message.content.strip()
        send_message(chat_id, f"🤖 {answer}")

    except Exception as e:
        logger.error(f"Errore OpenAI: {e}")
        send_message(chat_id, "Errore nel generare la risposta AI.")


# === SET WEBHOOK AUTOMATICO (solo al primo avvio) ===
def set_webhook():
    url = f"{TELEGRAM_URL}/setWebhook"
    data = {"url": f"{WEBHOOK_URL}/webhook"}
    response = requests.post(url, json=data)
    logger.info(f"Webhook impostato: {response.text}")


if __name__ == "__main__":
    logger.info("==> Avvio AngelBot AI 🚀")
    set_webhook()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
