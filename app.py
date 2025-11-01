from flask import Flask, request
import requests
import os
import yfinance as yf
import matplotlib.pyplot as plt
from io import BytesIO
import threading
import time

app = Flask(__name__)

# --- CONFIGURAZIONE ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
USER_SETTINGS = {}

# --- TITOLI PER REGIONE ---
STOCKS = {
    "🇺🇸 Stati Uniti": {
        "AAPL": "Apple",
        "AMZN": "Amazon",
        "MSFT": "Microsoft",
        "GOOGL": "Alphabet",
        "TSLA": "Tesla",
        "NVDA": "NVIDIA",
        "META": "Meta Platforms"
    },
    "🇪🇺 Europa": {
        "ISP.MI": "Intesa Sanpaolo",
        "BMPS.MI": "Monte dei Paschi di Siena",
        "ENI.MI": "ENI",
        "LUX.MI": "Luxottica",
        "RACE.MI": "Ferrari",
        "UNI.MI": "Unicredit"
    },
    "🇨🇳 Asia": {
        "BIDU": "Baidu",
        "BABA": "Alibaba",
        "TCEHY": "Tencent",
        "SONY": "Sony",
        "TM": "Toyota",
        "NTDOY": "Nintendo"
    }
}

# --- FREQUENZE MONITORAGGIO ---
FREQUENZE = {
    "30 Minuti": 1800,
    "1 Ora": 3600,
    "2 Ore": 7200,
    "5 Ore": 18000,
    "Giornaliero": 86400,
    "Settimanale": 604800,
    "Off": 0
}

# --- INVIO MESSAGGIO TELEGRAM ---
def send_message(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = reply_markup
    requests.post(f"{TELEGRAM_URL}/sendMessage", json=data)

# --- INVIO GRAFICO ---
def send_chart(chat_id, symbol):
    data = yf.download(symbol, period="5d", interval="1h")
    if data.empty:
        send_message(chat_id, "❌ Nessun dato disponibile per questo titolo.")
        return

    plt.figure()
    plt.plot(data.index, data["Close"])
    plt.title(symbol)
    plt.xlabel("Tempo")
    plt.ylabel("Prezzo")
    plt.grid(True)

    bio = BytesIO()
    plt.savefig(bio, format="png")
    bio.seek(0)
    files = {"photo": bio}
    requests.post(f"{TELEGRAM_URL}/sendPhoto", data={"chat_id": chat_id}, files=files)

# --- MONITORAGGIO AUTOMATICO ---
def monitor_stocks(chat_id):
    while True:
        settings = USER_SETTINGS.get(chat_id, {})
        freq = settings.get("frequenza", 0)
        titoli = settings.get("titoli", [])

        if not titoli or freq == 0:
            time.sleep(10)
            continue

        for symbol in titoli:
            data = yf.Ticker(symbol)
            hist = data.history(period="5d")
            if hist.empty:
                continue

            price_now = hist["Close"].iloc[-1]
            price_old = hist["Close"].iloc[0]
            change = ((price_now - price_old) / price_old) * 100

            nome = next((n for region in STOCKS.values() for s, n in region.items() if s == symbol), symbol)

            if change > 2:
                msg = f"📈 {nome} ({symbol}) è in rialzo del {change:.2f}%. Potresti considerare un investimento."
            elif change < -2:
                msg = f"📉 {nome} ({symbol}) è in ribasso del {change:.2f}%. Forse conviene attendere."
            else:
                msg = f"📊 {nome} ({symbol}) è stabile. Nessun grande movimento per ora."

            send_message(chat_id, msg)

        time.sleep(freq)

def start_monitoring(chat_id):
    t = threading.Thread(target=monitor_stocks, args=(chat_id,), daemon=True)
    t.start()

# --- BARRA DI RICERCA ---
def trova_titolo(query):
    query = query.lower().strip()
    for regione, titoli in STOCKS.items():
        for simbolo, nome in titoli.items():
            if query in simbolo.lower() or query in nome.lower():
                return simbolo, nome
    return None, None

# --- WEBHOOK PRINCIPALE ---
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if "message" not in data:
        return "OK", 200

    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text", "").strip()

    if text == "/start":
        keyboard = {
            "keyboard": [
                [{"text": "📊 Controlla titoli"}],
                [{"text": "🔍 Cerca titolo"}],
                [{"text": "⚙️ Imposta monitoraggio"}],
                [{"text": "💡 Consigli automatici"}]
            ],
            "resize_keyboard": True
        }
        send_message(chat_id, "Benvenuto nel tuo assistente finanziario AI! 💹", reply_markup=keyboard)
        USER_SETTINGS[chat_id] = {"titoli": [], "frequenza": 0}
        start_monitoring(chat_id)

    elif text == "📊 Controlla titoli":
        region_keyboard = {"keyboard": [[{"text": key}] for key in STOCKS.keys()], "resize_keyboard": True}
        send_message(chat_id, "Seleziona una regione:", reply_markup=region_keyboard)

    elif text in STOCKS.keys():
        region = text
        titles_keyboard = {"keyboard": [[{"text": f"{s} / {n}"}] for s, n in STOCKS[region].items()],
                           "resize_keyboard": True}
        send_message(chat_id, "Scegli un titolo da analizzare:", reply_markup=titles_keyboard)

    elif "/" in text:
        symbol = text.split("/")[0].strip()
        send_chart(chat_id, symbol)
        send_message(chat_id, f"Analisi completata per {symbol} ✅")

    elif text == "🔍 Cerca titolo":
        send_message(chat_id, "Scrivi il nome o simbolo del titolo che vuoi cercare (es. Apple o AAPL).")

    elif text.upper() in [s for region in STOCKS.values() for s in region.keys()] or any(
        text.lower() in n.lower() for region in STOCKS.values() for n in region.values()):
        symbol, nome = trova_titolo(text)
        if symbol:
            send_chart(chat_id, symbol)
            send_message(chat_id, f"Grafico e analisi per {nome} ({symbol}) completati.")
        else:
            send_message(chat_id, "❌ Nessun titolo trovato. Riprova.")

    elif text == "⚙️ Imposta monitoraggio":
        freq_keyboard = {"keyboard": [[{"text": f}] for f in FREQUENZE.keys()], "resize_keyboard": True}
        send_message(chat_id, "Scegli la frequenza di monitoraggio:", reply_markup=freq_keyboard)

    elif text in FREQUENZE:
        USER_SETTINGS[chat_id]["frequenza"] = FREQUENZE[text]
        send_message(chat_id, f"✅ Frequenza impostata su: {text}")

    elif text == "💡 Consigli automatici":
        all_symbols = [s for region in STOCKS.values() for s in region.keys()]
        choice = all_symbols[int(time.time()) % len(all_symbols)]
        nome = next((n for region in STOCKS.values() for s, n in region.items() if s == choice), choice)
        hist = yf.Ticker(choice).history(period="5d")
        if not hist.empty:
            change = ((hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0]) * 100
            trend = "in rialzo" if change > 0 else "in ribasso"
            send_message(chat_id, f"📈 {nome} ({choice}) è {trend} del {abs(change):.2f}%. Potrebbe essere interessante da osservare.")
        else:
            send_message(chat_id, "Non riesco a ottenere i dati al momento.")

    else:
        symbol, nome = trova_titolo(text)
        if symbol:
            send_chart(chat_id, symbol)
            send_message(chat_id, f"Analisi trovata per {nome} ({symbol}) ✅")
        else:
            send_message(chat_id, "❌ Non ho capito. Puoi usare i comandi del menu principale.")

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
