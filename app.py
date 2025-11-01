import os
import requests
from flask import Flask, request
from openai import OpenAI
from datetime import datetime, timedelta
import threading
import time

# === CONFIGURAZIONE BASE ===
app = Flask(__name__)
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")  # Inseriscilo su Render come variabile ambiente
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # Anche questa come variabile ambiente
client = OpenAI(api_key=OPENAI_API_KEY)

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
USER_CHAT_ID = None  # viene aggiornato dinamicamente quando l’utente scrive

# Frequenze di monitoraggio possibili (in minuti)
FREQUENZE = {
    "30 minuti": 30,
    "1 ora": 60,
    "6 ore": 360,
    "giornaliero": 1440,
    "settimanale": 10080,
    "off": 0
}

monitoraggio_attivo = False
frequenza_monitoraggio = "off"

# === FUNZIONI TELEGRAM ===
def send_message(chat_id, text):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})


# === FUNZIONE AI CHAT ===
def chat_with_ai(message):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Sei un assistente di investimento finanziario e analisi di mercato."},
                {"role": "user", "content": message}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Errore AI: {e}"


# === FUNZIONE DI MONITORAGGIO AUTOMATICO ===
def monitoraggio_mercato():
    global monitoraggio_attivo, frequenza_monitoraggio, USER_CHAT_ID
    while True:
        if monitoraggio_attivo and USER_CHAT_ID and frequenza_monitoraggio != "off":
            try:
                testo = analisi_mercato()
                send_message(USER_CHAT_ID, f"📊 Aggiornamento automatico:\n{testo}")
            except Exception as e:
                send_message(USER_CHAT_ID, f"Errore nel monitoraggio: {e}")
        minuti = FREQUENZE.get(frequenza_monitoraggio, 0)
        time.sleep(minuti * 60 if minuti > 0 else 60)


# === ANALISI MERCATO (DATI REALI DA API) ===
def analisi_mercato():
    azioni = ["AAPL", "GOOG", "TSLA", "MSFT", "BIDU", "BMPS.MI"]
    testo = ""
    for simbolo in azioni:
        try:
            url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={simbolo}"
            r = requests.get(url).json()
            info = r["quoteResponse"]["result"][0]
            nome = info.get("longName", simbolo)
            prezzo = info.get("regularMarketPrice", "N/A")
            variazione = info.get("regularMarketChangePercent", 0)
            emoji = "🟩" if variazione > 0 else "🟥"
            testo += f"{emoji} {nome} ({simbolo}): {prezzo}$ ({variazione:.2f}%)\n"
        except Exception:
            testo += f"⚠️ Errore per {simbolo}\n"
    return testo


# === FLASK ENDPOINT TELEGRAM ===
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    global USER_CHAT_ID, monitoraggio_attivo, frequenza_monitoraggio
    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").lower()
    USER_CHAT_ID = chat_id

    if text == "/start":
        send_message(chat_id, "Ciao 👋 Sono il tuo assistente AI per gli investimenti.\n"
                              "Scrivimi qualsiasi domanda oppure scegli un’opzione:\n\n"
                              "📈 /monitoraggio – imposta aggiornamenti automatici\n"
                              "🤖 /ai – chiedi qualcosa all’intelligenza artificiale")
    elif text == "/monitoraggio":
        opzioni = "\n".join([f"- {k}" for k in FREQUENZE.keys()])
        send_message(chat_id, f"Scegli frequenza monitoraggio:\n{opzioni}")
    elif text in FREQUENZE.keys():
        frequenza_monitoraggio = text
        monitoraggio_attivo = text != "off"
        send_message(chat_id, f"✅ Monitoraggio impostato su: {text}")
    elif text.startswith("/ai"):
        domanda = text.replace("/ai", "").strip()
        if not domanda:
            send_message(chat_id, "Scrivi dopo /ai la tua domanda, es: `/ai Quali azioni sono sottovalutate?`")
        else:
            risposta = chat_with_ai(domanda)
            send_message(chat_id, risposta)
    else:
        risposta = chat_with_ai(text)
        send_message(chat_id, risposta)

    return {"ok": True}


@app.route("/", methods=["GET"])
def home():
    return "Bot Telegram AI per investimenti attivo 🚀"


# === THREAD DI MONITORAGGIO ===
threading.Thread(target=monitoraggio_mercato, daemon=True).start()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
