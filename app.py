from flask import Flask, request
import os, requests, json, gspread, yfinance as yf, matplotlib.pyplot as plt
import io, base64
import pandas as pd
from google.oauth2.service_account import Credentials
from openai import OpenAI

app = Flask(__name__)

# === VARIABILI DI AMBIENTE ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEETS_KEY = os.getenv("GOOGLE_SHEETS_KEY")

# === CONFIGURAZIONE ===
client = OpenAI(api_key=OPENAI_API_KEY)
creds_dict = json.loads(GOOGLE_SHEETS_KEY)
creds = Credentials.from_service_account_info(
    creds_dict,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
gclient = gspread.authorize(creds)

SHEET_ID = "10L2gum_HDbDWyFsdt8mW8lrKSRSYuYJ77ohAXFbgZvc"
sheet = gclient.open_by_key(SHEET_ID).sheet1

TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

def send_message(chat_id, text):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    requests.post(TELEGRAM_URL, json=payload)

def send_photo(chat_id, image_bytes):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    files = {"photo": image_bytes}
    data = {"chat_id": chat_id}
    requests.post(url, data=data, files=files)

# === MAPPATURA NOMI AZIONI ===
stocks_map = {
    "apple": "AAPL", "aapl": "AAPL",
    "amazon": "AMZN", "amzn": "AMZN",
    "tesla": "TSLA", "tsla": "TSLA",
    "microsoft": "MSFT", "msft": "MSFT",
    "bmw": "BMW.DE", "bmw.de": "BMW.DE",
    "samsung": "005930.KS", "samsung electronics": "005930.KS",
    "nestle": "NESN.SW", "nesn": "NESN.SW"
}

# === CATEGORIE ===
continenti = {
    "europa": ["BMW.DE", "NESN.SW"],
    "usa": ["AAPL", "AMZN", "TSLA", "MSFT"],
    "asia": ["005930.KS"],
    "africa": []
}

# === FUNZIONI DATI FINANZIARI ===
def get_price(symbol):
    stock = yf.Ticker(symbol)
    data = stock.history(period="1d")
    if data.empty:
        return None
    return round(data["Close"].iloc[-1], 2)

def get_graph(symbol):
    stock = yf.Ticker(symbol)
    data = stock.history(period="1mo")
    plt.figure(figsize=(6, 3))
    plt.plot(data.index, data["Close"], linewidth=2)
    plt.title(f"Andamento {symbol}")
    plt.xlabel("Data")
    plt.ylabel("Prezzo ($)")
    plt.grid(True)
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    return buf

def analisi_approfondita(symbol):
    stock = yf.Ticker(symbol)
    info = stock.info
    testo = f"""
Nome: {info.get('longName', 'N/A')}
Settore: {info.get('sector', 'N/A')}
Prezzo attuale: {info.get('currentPrice', 'N/A')}
Target medio: {info.get('targetMeanPrice', 'N/A')}
Raccomandazione: {info.get('recommendationKey', 'N/A')}
"""
    risposta = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Agisci come un consulente finanziario esperto e realistico."},
            {"role": "user", "content": f"Analizza questi dati: {testo}. Fornisci una previsione logica sul trend futuro."}
        ]
    )
    return risposta.choices[0].message.content.strip()
 # === PORTAFOGLIO ===
def aggiorna_portafoglio(symbol, quantity, price):
    sheet.append_row([symbol, quantity, price])
    return f"Aggiunto {quantity}x {symbol} al portafoglio."

# === WEBHOOK TELEGRAM ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if "message" not in data:
        return "no message", 200

    chat_id = data["message"]["chat"]["id"]
    text = data["message"]["text"].lower().strip()

    if text in ["/start", "start"]:
        send_message(chat_id, "👋 Benvenuto nel tuo assistente finanziario! Scrivi una delle opzioni:\n"
                              "📊 Prezzo\n📈 Grafico\n🔍 Analisi\n💼 Portafoglio\n🌍 Categorie (Europa, USA, Asia, Africa)")

    elif text == "prezzo":
        send_message(chat_id, "Inserisci il nome o simbolo dell’azione (es: Apple o AAPL):")

    elif text == "grafico":
        send_message(chat_id, "Scrivi il nome o simbolo dell’azione di cui vuoi vedere il grafico:")

    elif text == "analisi":
        send_message(chat_id, "Indica il titolo per un’analisi approfondita:")

    elif text in continenti:
        lista = "\n".join(continenti[text])
        send_message(chat_id, f"📊 Titoli in {text.capitalize()}:\n{lista}")

    elif text.startswith("aggiungi"):
        try:
            _, symbol, q, p = text.split()
            msg = aggiorna_portafoglio(symbol.upper(), q, p)
            send_message(chat_id, msg)
        except:
            send_message(chat_id, "Usa: aggiungi <simbolo> <quantità> <prezzo>")

    else:
        nome = text.replace(" ", "").lower()
        if nome in stocks_map:
            symbol = stocks_map[nome]
            prezzo = get_price(symbol)
            grafico = get_graph(symbol)
            analisi = analisi_approfondita(symbol)
            send_message(chat_id, f"💰 <b>{symbol}</b>\nPrezzo: ${prezzo}")
            send_photo(chat_id, grafico)
            send_message(chat_id, f"🧠 Analisi:\n{analisi}")
        else:
            send_message(chat_id, "❌ Titolo non trovato. Prova con un nome o simbolo valido (es: Apple, TSLA, BMW).")

    return "ok", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port) 
import threading, time, datetime

def genera_report_giornaliero():
    simboli = ["AAPL", "AMZN", "TSLA", "MSFT"]
    report = "📅 <b>Report giornaliero mercati</b>\n\n"
    for s in simboli:
        prezzo = get_price(s)
        if prezzo is None:
            continue
        stock = yf.Ticker(s)
        info = stock.info
        nome = info.get("shortName", s)
        delta = info.get("regularMarketChangePercent", 0)
        tendenza = "📈 In rialzo" if delta > 0 else "📉 In ribasso"
        report += f"{nome} ({s})\nPrezzo: ${prezzo}\nVariazione: {round(delta, 2)}%\n{tendenza}\n\n"

    # Analisi GPT generale
    analisi_globale = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Agisci come un analista finanziario professionale."},
            {"role": "user", "content": f"Scrivi un breve commento giornaliero sul mercato basato su questi dati:\n{report}"}
        ]
    ).choices[0].message.content.strip()

    report += f"🧠 <b>Analisi GPT:</b>\n{analisi_globale}"

    # Chat ID da inviare automaticamente (inserisci il tuo ID)
    CHAT_ID_PERSONALE = os.getenv("CHAT_ID_PERSONALE")
    if CHAT_ID_PERSONALE:
        send_message(CHAT_ID_PERSONALE, report)

def avvia_report_programmato():
    while True:
        ora = datetime.datetime.now()
        # Esegui ogni giorno alle 9:00
        if ora.hour == 9 and ora.minute == 0:
            genera_report_giornaliero()
            time.sleep(60)  # evita doppio invio
        time.sleep(30)

# Avvia il thread separato
threading.Thread(target=avvia_report_programmato, daemon=True).start()
