from flask import Flask, request
import os
import requests
import json
import yfinance as yf
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import schedule
import time
import threading
from io import BytesIO
from openai import OpenAI

# Inizializzazione Flask
app = Flask(__name__)

# Variabili ambiente
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
BOT_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

client = OpenAI(api_key=OPENAI_API_KEY)


# ==============================
# Funzioni di utilità Telegram
# ==============================

def send_message(chat_id, text):
    url = f"{BOT_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)


def send_photo(chat_id, photo_bytes):
    url = f"{BOT_URL}/sendPhoto"
    files = {"photo": ("graph.png", photo_bytes)}
    data = {"chat_id": chat_id}
    requests.post(url, files=files, data=data)


# ==============================
# Funzioni di logica bot
# ==============================

def get_stock_info(symbol):
    try:
        data = yf.Ticker(symbol)
        hist = data.history(period="1mo")

        plt.figure()
        hist["Close"].plot(title=f"Andamento {symbol}")
        buf = BytesIO()
        plt.savefig(buf, format="png")
        buf.seek(0)
        plt.close()

        price = hist["Close"].iloc[-1]
        return price, buf
    except Exception as e:
        return None, None


def ask_gpt(prompt):
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Sei un assistente Telegram intelligente e gentile."},
                {"role": "user", "content": prompt}
            ]
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Errore GPT: {e}"


# ==============================
# Flask routes
# ==============================

@app.route('/')
def index():
    return "✅ AngelBot è vivo e online!"


@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()

    if "message" in update:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "")

        if text.startswith("/start"):
            send_message(chat_id, "Ciao 👋 Sono AngelBot! Posso darti info su azioni, rispondere con IA o mandarti aggiornamenti.\n\nComandi:\n/start\n/ai [testo]\n/stock [ticker]\n/help")

        elif text.startswith("/help"):
            send_message(chat_id, "📘 *Comandi disponibili:*\n\n/ai [domanda] → Parla con GPT\n/stock [ticker] → Ottieni grafico e prezzo\n/remind → Attiva notifiche periodiche")

        elif text.startswith("/ai "):
            prompt = text.replace("/ai ", "")
            reply = ask_gpt(prompt)
            send_message(chat_id, reply)

        elif text.startswith("/stock "):
            symbol = text.replace("/stock ", "").upper().strip()
            price, graph = get_stock_info(symbol)
            if price:
                send_message(chat_id, f"📊 Prezzo attuale di {symbol}: {price:.2f} USD")
                send_photo(chat_id, graph)
            else:
                send_message(chat_id, "Errore nel recupero dati per quel simbolo.")

        elif text.startswith("/remind"):
            send_message(chat_id, "⏰ Ti manderò aggiornamenti periodici di esempio.")
            schedule.every(1).hours.do(lambda: send_message(chat_id, "Promemoria automatico 🕐"))
            threading.Thread(target=run_scheduler, daemon=True).start()

        else:
            send_message(chat_id, "Non ho capito il comando. Scrivi /help per la lista.")

    return "OK", 200


# ==============================
# Scheduler
# ==============================

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(30)


# ==============================
# Avvio app Flask
# ==============================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
