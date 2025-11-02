from flask import Flask, request
import os, json, requests, gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI
import yfinance as yf
from datetime import datetime
from report import genera_report_giornaliero, avvia_report_programmato

app = Flask(__name__)

# === VARIABILI DI AMBIENTE ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEETS_KEY = os.getenv("GOOGLE_SHEETS_KEY")
CHAT_ID_PERSONALE = os.getenv("CHAT_ID_PERSONALE")

# === CONFIGURAZIONE OPENAI ===
client = OpenAI(api_key=OPENAI_API_KEY)

# === GOOGLE SHEETS ===
creds_dict = json.loads(GOOGLE_SHEETS_KEY)
creds = Credentials.from_service_account_info(
    creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
gclient = gspread.authorize(creds)
SHEET_ID = "10L2gum_HDbDWyFsdt8mW8lrKSRSYuYJ77ohAXFbgZvc"
sheet = gclient.open_by_key(SHEET_ID).sheet1

# === FUNZIONE TELEGRAM ===
def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    requests.post(url, json=payload)

# === TRADUZIONE SIMBOLI / NOMI ===
mappa_titoli = {
    "apple": "AAPL",
    "aapl": "AAPL",
    "amazon": "AMZN",
    "amzn": "AMZN",
    "tesla": "TSLA",
    "tsla": "TSLA",
    "microsoft": "MSFT",
    "msft": "MSFT",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "nvda": "NVDA",
    "nvidia": "NVDA",
}

def trova_simbolo(nome):
    return mappa_titoli.get(nome.lower().replace("-", ""), None)

# === GESTIONE MESSAGGI TELEGRAM ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    if "message" not in data:
        return "no message", 200

    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text", "").lower().strip()

    if text == "/start":
        send_message(chat_id, "👋 Benvenuto in <b>AngelBot AI</b>!\n\nComandi disponibili:\n"
                              "• <b>saldo</b> – Mostra il saldo dal foglio Google\n"
                              "• <b>scrivi C5 1234</b> – Aggiorna una cella\n"
                              "• <b>analisi</b> – Analizza i dati del foglio\n"
                              "• <b>grafico</b> o <b>prezzo</b> + nome titolo\n"
                              "• <b>portafoglio</b> – Mostra le tue azioni salvate\n"
                              "• <b>report</b> – Report globale giornaliero\n\n"
                              "Puoi scrivere sia ‘AAPL’ che ‘Apple’, ottieni lo stesso risultato.")

    elif text == "saldo":
        saldo = sheet.acell("B2").value
        send_message(chat_id, f"💰 Il tuo saldo attuale è: {saldo}")

    elif text.startswith("scrivi"):
        try:
            parti = text.split()
            cella, valore = parti[1], " ".join(parti[2:])
            sheet.update(cella, valore)
            send_message(chat_id, f"✅ Aggiornato {cella} con '{valore}'")
        except:
            send_message(chat_id, "❌ Formato non valido. Usa: scrivi <cella> <valore>")

    elif text.startswith("prezzo") or text.startswith("grafico"):
        parti = text.split()
        if len(parti) < 2:
            send_message(chat_id, "❌ Scrivi: prezzo <titolo> o grafico <titolo>")
        else:
            nome = parti[1]
            symbol = trova_simbolo(nome) or nome.upper()
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.info
                prezzo = info.get("regularMarketPrice", "N/D")
                variazione = info.get("regularMarketChangePercent", 0)
                send_message(chat_id, f"📊 {symbol}: {prezzo}$ ({round(variazione, 2)}%)")
            except Exception as e:
                send_message(chat_id, f"⚠️ Errore nel recupero dati: {e}")

    elif text == "analisi":
        send_message(chat_id, "📈 Analizzo i dati in corso...")
        try:
            dati = sheet.get_all_records()
            testo = json.dumps(dati, indent=2, ensure_ascii=False)
            risposta = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Sei un analista finanziario conciso e accurato."},
                    {"role": "user", "content": f"Analizza questi dati:\n{testo}"}
                ]
            )
            send_message(chat_id, risposta.choices[0].message.content.strip())
        except Exception as e:
            send_message(chat_id, f"Errore: {e}")

    elif text == "portafoglio":
        try:
            dati = sheet.get_all_records()
            azioni = [r for r in dati if r.get("Ticker")]
            msg = "📘 <b>Portafoglio Attuale</b>:\n"
            for a in azioni:
                msg += f"• {a['Ticker']}: {a['Quantità']} azioni a {a['Prezzo medio']} USD\n"
            send_message(chat_id, msg)
        except Exception as e:
            send_message(chat_id, f"Errore lettura portafoglio: {e}")

    elif text == "report":
        send_message(chat_id, "🧠 Genero il report globale...")
        try:
            genera_report_giornaliero(chat_id)
        except Exception as e:
            send_message(chat_id, f"Errore nel report: {e}")

    else:
        send_message(chat_id, "💡 Comandi disponibili:\n/start\nsaldo\nanalisi\nprezzo <titolo>\ngrafico <titolo>\nportafoglio\nreport")

    return "ok", 200

# === AVVIO SERVER + THREAD REPORT ===
if __name__ == "__main__":
    import threading
    threading.Thread(target=avvia_report_programmato, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
