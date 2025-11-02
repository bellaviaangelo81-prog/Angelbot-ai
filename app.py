from flask import Flask, request
import os
import requests
import json
import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI

app = Flask(__name__)

# === VARIABILI DI AMBIENTE ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEETS_KEY = os.getenv("GOOGLE_SHEETS_KEY")

# === CONFIGURAZIONE OPENAI ===
client = OpenAI(api_key=OPENAI_API_KEY)

# === CONFIGURAZIONE GOOGLE SHEETS ===
creds_dict = json.loads(GOOGLE_SHEETS_KEY)
creds = Credentials.from_service_account_info(
    creds_dict,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
gclient = gspread.authorize(creds)

# ID del foglio (sostituiscilo con il tuo)
SHEET_ID = "10L2gum_HDbDWyFsdt8mW8lrKSRSYuYJ77ohAXFbgZvc"
sheet = gclient.open_by_key(SHEET_ID).sheet1

# === FUNZIONE TELEGRAM ===
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

def send_message(chat_id, text):
    payload = {"chat_id": chat_id, "text": text}
    requests.post(TELEGRAM_URL, json=payload)

# === ANALISI CON OPENAI ===
def analizza_dati_foglio():
    # Legge tutto il foglio e lo trasforma in testo
    dati = sheet.get_all_records()
    testo_dati = json.dumps(dati, indent=2, ensure_ascii=False)

    prompt = f"""
    Analizza questi dati finanziari in formato JSON e fornisci un breve report:
    {testo_dati}

    Riassumi le tendenze, eventuali rischi e opportunità di investimento.
    """

    risposta = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Sei un analista finanziario preciso e conciso."},
            {"role": "user", "content": prompt}
        ]
    )

    return risposta.choices[0].message.content.strip()

# === GESTIONE MESSAGGI TELEGRAM ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"]["text"].lower().strip()

        if text == "saldo":
            saldo = sheet.acell("B2").value
            send_message(chat_id, f"💰 Il tuo saldo attuale è: {saldo}")

        elif text == "analisi":
            send_message(chat_id, "📊 Sto analizzando i tuoi dati, attendi un momento...")
            try:
                report = analizza_dati_foglio()
                send_message(chat_id, f"📈 Analisi automatica:\n\n{report}")
            except Exception as e:
                send_message(chat_id, f"⚠️ Errore nell'analisi: {e}")

        elif text.startswith("scrivi"):
            # Esempio: "scrivi C5 12345"
            try:
                parti = text.split()
                cella, valore = parti[1], " ".join(parti[2:])
                sheet.update(cella, valore)
                send_message(chat_id, f"✅ Aggiornato {cella} con '{valore}'")
            except:
                send_message(chat_id, "❌ Formato non valido. Usa: scrivi <cella> <valore>")

        else:
            send_message(chat_id, "💡 Comandi disponibili:\n- saldo\n- scrivi <cella> <valore>\n- analisi")

    return "ok", 200

# === AVVIO SERVER ===
if __name__ == "__main__":
    app.run(port=5000)
