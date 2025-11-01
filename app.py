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

if not BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("TELEGRAM_TOKEN e OPENAI_API_KEY devono essere impostate come variabili ambiente.")

client = OpenAI(api_key=OPENAI_API_KEY)

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Frequenze di monitoraggio possibili (in minuti)
FREQUENZE = {
    "30 minuti": 30,
    "1 ora": 60,
    "6 ore": 360,
    "giornaliero": 1440,
    "settimanale": 10080,
    "off": 0
}

# Stato monitoraggio per ogni utente: {chat_id: {"attivo": bool, "frequenza": str, "ultimo_invio": datetime}}
stato_utenti = {}

lock = threading.Lock()  # Per thread safety

# === FUNZIONI TELEGRAM ===
def send_message(chat_id, text):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": text})
    if not resp.ok:
        print(f"Errore Telegram: {resp.text}")

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
        print(f"Errore AI: {e}")
        return f"Errore AI: {e}"

# === FUNZIONE DI MONITORAGGIO AUTOMATICO MULTIUTENTE ===
def monitoraggio_mercato_multiutente():
    while True:
        now = datetime.utcnow()
        with lock:
            for chat_id, stato in stato_utenti.items():
                attivo = stato.get("attivo", False)
                frequenza = stato.get("frequenza", "off")
                ultimo_invio = stato.get("ultimo_invio", None)
                minuti = FREQUENZE.get(frequenza, 0)
                if attivo and frequenza != "off" and minuti > 0:
                    if not ultimo_invio or (now - ultimo_invio).total_seconds() >= minuti * 60:
                        try:
                            testo = analisi_mercato()
                            send_message(chat_id, f"📊 Aggiornamento automatico:\n{testo}")
                            stato_utenti[chat_id]["ultimo_invio"] = now
                        except Exception as e:
                            send_message(chat_id, f"Errore nel monitoraggio: {e}")
        time.sleep(30)  # Controlla ogni 30 secondi

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
        except Exception as e:
            print(f"Errore per {simbolo}: {e}")
            testo += f"⚠️ Errore per {simbolo}\n"
    return testo

# === FLASK ENDPOINT TELEGRAM ===
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = str(message.get("chat", {}).get("id"))  # chat_id come stringa per sicurezza
    text = message.get("text", "").strip().lower()

    with lock:
        if chat_id not in stato_utenti:
            stato_utenti[chat_id] = {"attivo": False, "frequenza": "off", "ultimo_invio": None}

    if text == "/start":
        send_message(chat_id, "Ciao 👋 Sono il tuo assistente AI per gli investimenti.\n"
                              "Scrivimi qualsiasi domanda oppure scegli un’opzione:\n\n"
                              "📈 /monitoraggio – imposta aggiornamenti automatici\n"
                              "🤖 /ai – chiedi qualcosa all’intelligenza artificiale")
    elif text == "/monitoraggio":
        opzioni = "\n".join([f"- {k}" for k in FREQUENZE.keys()])
        send_message(chat_id, f"Scegli frequenza monitoraggio:\n{opzioni}")
    elif text in FREQUENZE.keys():
        with lock:
            stato_utenti[chat_id]["frequenza"] = text
            stato_utenti[chat_id]["attivo"] = text != "off"
            stato_utenti[chat_id]["ultimo_invio"] = None
        send_message(chat_id, f"✅ Monitoraggio impostato su: {text}")
    elif text.startswith("/ai"):
        domanda = message.get("text")[3:].strip()
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

# === THREAD DI MONITORAGGIO MULTIUTENTE ===
def start_monitoraggio_thread():
    t = threading.Thread(target=monitoraggio_mercato_multiutente, daemon=True)
    t.start()
    return t

if __name__ == "__main__":
    start_monitoraggio_thread()
    app.run(host="0.0.0.0", port=10000)
