import os
import requests
from flask import Flask, request
from openai import OpenAI
from datetime import datetime, timedelta
import threading
import time

app = Flask(__name__)
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("TELEGRAM_TOKEN e OPENAI_API_KEY devono essere impostate come variabili ambiente.")
client = OpenAI(api_key=OPENAI_API_KEY)
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

FREQUENZE = {
    "30 minuti": 30,
    "1 ora": 60,
    "6 ore": 360,
    "giornaliero": 1440,
    "settimanale": 10080,
    "off": 0
}

# Multiutente e monitoraggio personalizzato
stato_utenti = {}  # {chat_id: {"attivo": bool, "frequenza": str, "ultimo_invio": datetime, "titoli": set(), "alert": dict, "portafoglio": dict}}
lock = threading.Lock()

def send_message(chat_id, text):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})
    if not resp.ok:
        print(f"Errore Telegram: {resp.text}")

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

def get_price(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbol}"
        r = requests.get(url).json()
        info = r["quoteResponse"]["result"][0]
        prezzo = info.get("regularMarketPrice", "N/A")
        return prezzo
    except Exception as e:
        print(f"Errore prezzo {symbol}: {e}")
        return "N/A"

def analisi_mercato(titoli=None):
    azioni = titoli if titoli else ["AAPL", "GOOG", "TSLA", "MSFT", "BIDU", "BMPS.MI"]
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

def monitoraggio_mercato_multiutente():
    while True:
        now = datetime.utcnow()
        with lock:
            for chat_id, stato in stato_utenti.items():
                attivo = stato.get("attivo", False)
                frequenza = stato.get("frequenza", "off")
                ultimo_invio = stato.get("ultimo_invio", None)
                minuti = FREQUENZE.get(frequenza, 0)
                titoli = list(stato.get("titoli", [])) or None
                # Monitoraggio automatico
                if attivo and frequenza != "off" and minuti > 0:
                    if not ultimo_invio or (now - ultimo_invio).total_seconds() >= minuti * 60:
                        try:
                            testo = analisi_mercato(titoli)
                            send_message(chat_id, f"📊 Aggiornamento automatico:\n{testo}")
                            stato_utenti[chat_id]["ultimo_invio"] = now
                        except Exception as e:
                            send_message(chat_id, f"Errore nel monitoraggio: {e}")
                # Alert di prezzo
                alerts = stato.get("alert", {})
                for titolo, soglia in list(alerts.items()):
                    prezzo = get_price(titolo)
                    try:
                        if prezzo != "N/A" and float(prezzo) >= soglia:
                            send_message(chat_id, f"🚨 ALERT: {titolo} ha raggiunto la soglia di {soglia}$ (prezzo attuale: {prezzo}$)")
                            # Alert singolo: lo rimuovo dopo invio
                            stato_utenti[chat_id]["alert"].pop(titolo)
                    except Exception:
                        pass
        time.sleep(30)

def get_news():
    # Sostituisci con una vera API news finanziarie!
    news = [
        "Apple annuncia risultati trimestrali oltre le attese.",
        "Tesla presenta nuove batterie a basso costo.",
        "Microsoft acquisisce una startup AI."
    ]
    return "\n".join([f"📰 {n}" for n in news])

def get_storico(titolo):
    # Esempio statico, integra con API reali
    return f"Storico di {titolo}: 249$, 251$, 259$, 263$ (ultimi giorni)"

def get_grafico(titolo):
    # Simula link a immagine grafico. Puoi integrare con API/plotly/matplotlib e inviare immagini
    return f"https://finviz.com/chart.ashx?t={titolo}"

def portafoglio_testo(portafoglio):
    if not portafoglio:
        return "Il tuo portafoglio è vuoto."
    testo = "Portafoglio virtuale:\n"
    for titolo, quantità in portafoglio.items():
        prezzo = get_price(titolo)
        testo += f"- {titolo}: {quantità} azioni (prezzo attuale: {prezzo}$)\n"
    return testo

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = str(message.get("chat", {}).get("id"))
    text = message.get("text", "").strip()

    with lock:
        if chat_id not in stato_utenti:
            stato_utenti[chat_id] = {"attivo": False, "frequenza": "off", "ultimo_invio": None, "titoli": set(), "alert": {}, "portafoglio": {}}

    # Comandi disponibili
    if text.lower() == "/start":
        send_message(chat_id,
            "Ciao 👋 Sono il tuo assistente AI per gli investimenti.\n"
            "Comandi disponibili:\n\n"
            "📈 /monitoraggio – imposta aggiornamenti automatici\n"
            "📰 /notizie – ultime news finanziarie\n"
            "💼 /portafoglio – portafoglio virtuale\n"
            "📊 /storico [TITOLO] – storico prezzi\n"
            "🚨 /alert [TITOLO] [SOGLIA] – ricevi alert\n"
            "📋 /lista – titoli monitorati\n"
            "➕ /aggiungi [TITOLO] – aggiungi titolo\n"
            "➖ /rimuovi [TITOLO] – rimuovi titolo\n"
            "📈 /grafico [TITOLO] – ricevi grafico\n"
            "🤖 /ai [DOMANDA] – chiedi all’AI\n"
            "💰 /compra [TITOLO] [QUANTITÀ] – acquista azioni virtuali\n"
            "💸 /vendi [TITOLO] [QUANTITÀ] – vendi azioni virtuali\n"
            "❓ /help – elenco comandi\n"
        )
    elif text.lower() == "/monitoraggio":
        opzioni = "\n".join([f"- {k}" for k in FREQUENZE.keys()])
        send_message(chat_id, f"Scegli frequenza monitoraggio:\n{opzioni}")
    elif text.lower() in FREQUENZE.keys():
        with lock:
            stato_utenti[chat_id]["frequenza"] = text.lower()
            stato_utenti[chat_id]["attivo"] = text.lower() != "off"
            stato_utenti[chat_id]["ultimo_invio"] = None
        send_message(chat_id, f"✅ Monitoraggio impostato su: {text}")
    elif text.lower().startswith("/notizie"):
        send_message(chat_id, get_news())
    elif text.lower().startswith("/portafoglio"):
        portafoglio = stato_utenti[chat_id]["portafoglio"]
        send_message(chat_id, portafoglio_testo(portafoglio))
    elif text.lower().startswith("/storico"):
        parts = text.split()
        if len(parts) >= 2:
            titolo = parts[1].upper()
            send_message(chat_id, get_storico(titolo))
        else:
            send_message(chat_id, "Usa /storico [TITOLO], es: /storico TSLA")
    elif text.lower().startswith("/alert"):
        parts = text.split()
        if len(parts) == 3:
            titolo = parts[1].upper()
            try:
                soglia = float(parts[2])
                with lock:
                    stato_utenti[chat_id]["alert"][titolo] = soglia
                send_message(chat_id, f"🔔 Alert impostato: {titolo} sopra {soglia}$")
            except ValueError:
                send_message(chat_id, "Soglia non valida. Esempio: /alert TSLA 300")
        else:
            send_message(chat_id, "Usa /alert [TITOLO] [SOGLIA], es: /alert TSLA 300")
    elif text.lower().startswith("/lista"):
        titoli = stato_utenti[chat_id]["titoli"]
        if titoli:
            send_message(chat_id, "Titoli monitorati:\n" + "\n".join(titoli))
        else:
            send_message(chat_id, "Non stai monitorando alcun titolo. Usa /aggiungi [TITOLO].")
    elif text.lower().startswith("/aggiungi"):
        parts = text.split()
        if len(parts) == 2:
            titolo = parts[1].upper()
            with lock:
                stato_utenti[chat_id]["titoli"].add(titolo)
            send_message(chat_id, f"Aggiunto {titolo} ai titoli monitorati.")
        else:
            send_message(chat_id, "Usa /aggiungi [TITOLO], es: /aggiungi TSLA")
    elif text.lower().startswith("/rimuovi"):
        parts = text.split()
        if len(parts) == 2:
            titolo = parts[1].upper()
            with lock:
                stato_utenti[chat_id]["titoli"].discard(titolo)
            send_message(chat_id, f"Rimosso {titolo} dai titoli monitorati.")
        else:
            send_message(chat_id, "Usa /rimuovi [TITOLO], es: /rimuovi TSLA")
    elif text.lower().startswith("/grafico"):
        parts = text.split()
        if len(parts) == 2:
            titolo = parts[1].upper()
            send_message(chat_id, f"Grafico di {titolo}: {get_grafico(titolo)}")
        else:
            send_message(chat_id, "Usa /grafico [TITOLO], es: /grafico TSLA")
    elif text.lower().startswith("/ai"):
        domanda = text[3:].strip()
        if not domanda:
            send_message(chat_id, "Scrivi dopo /ai la tua domanda, es: `/ai Quali azioni sono sottovalutate?`")
        else:
            risposta = chat_with_ai(domanda)
            send_message(chat_id, risposta)
    elif text.lower() == "/help":
        send_message(chat_id,
            "Comandi disponibili:\n"
            "📈 /monitoraggio – imposta aggiornamenti automatici\n"
            "📰 /notizie – ultime news finanziarie\n"
            "💼 /portafoglio – portafoglio virtuale\n"
            "📊 /storico [TITOLO] – storico prezzi\n"
            "🚨 /alert [TITOLO] [SOGLIA] – ricevi alert\n"
            "📋 /lista – titoli monitorati\n"
            "➕ /aggiungi [TITOLO] – aggiungi titolo\n"
            "➖ /rimuovi [TITOLO] – rimuovi titolo\n"
            "📈 /grafico [TITOLO] – ricevi grafico\n"
            "🤖 /ai [DOMANDA] – chiedi all’AI\n"
            "💰 /compra [TITOLO] [QUANTITÀ] – acquista azioni virtuali\n"
            "💸 /vendi [TITOLO] [QUANTITÀ] – vendi azioni virtuali\n"
            "❓ /help – elenco comandi\n"
        )
    # Portafoglio virtuale
    elif text.lower().startswith("/compra"):
        parts = text.split()
        if len(parts) == 3:
            titolo = parts[1].upper()
            try:
                quantità = int(parts[2])
                with lock:
                    stato_utenti[chat_id]["portafoglio"][titolo] = stato_utenti[chat_id]["portafoglio"].get(titolo, 0) + quantità
                send_message(chat_id, f"Hai comprato {quantità} azioni di {titolo}.")
            except ValueError:
                send_message(chat_id, "Quantità non valida. Esempio: /compra TSLA 2")
        else:
            send_message(chat_id, "Usa /compra [TITOLO] [QUANTITÀ], es: /compra TSLA 2")
    elif text.lower().startswith("/vendi"):
        parts = text.split()
        if len(parts) == 3:
            titolo = parts[1].upper()
            try:
                quantità = int(parts[2])
                with lock:
                    attuali = stato_utenti[chat_id]["portafoglio"].get(titolo, 0)
                    if quantità > attuali:
                        send_message(chat_id, f"Non hai abbastanza azioni di {titolo} da vendere.")
                    else:
                        stato_utenti[chat_id]["portafoglio"][titolo] = attuali - quantità
                        send_message(chat_id, f"Hai venduto {quantità} azioni di {titolo}.")
            except ValueError:
                send_message(chat_id, "Quantità non valida. Esempio: /vendi TSLA 1")
        else:
            send_message(chat_id, "Usa /vendi [TITOLO] [QUANTITÀ], es: /vendi TSLA 1")
    else:
        risposta = chat_with_ai(text)
        send_message(chat_id, risposta)

    return {"ok": True}

@app.route("/", methods=["GET"])
def home():
    return "Bot Telegram AI per investimenti attivo 🚀"

def start_monitoraggio_thread():
    t = threading.Thread(target=monitoraggio_mercato_multiutente, daemon=True)
    t.start()
    return t

if __name__ == "__main__":
    start_monitoraggio_thread()
    app.run(host="0.0.0.0", port=10000)
