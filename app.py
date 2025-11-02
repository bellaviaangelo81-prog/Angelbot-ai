from flask import Flask, request
import os
import requests
import json
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# === VARIABILI DI AMBIENTE ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEETS_KEY = os.getenv("GOOGLE_SHEETS_KEY")  # la chiave JSON segreta

# === CONFIGURAZIONE GOOGLE SHEETS ===
creds_dict = json.loads(GOOGLE_SHEETS_KEY)
creds = Credentials.from_service_account_info(
    creds_dict,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
client = gspread.authorize(creds)

# ID del foglio (puoi cambiarlo con il tuo)
SHEET_ID = "10L2gum_HDbDWyFsdt8mW8lrKSRSYuYJ77ohAXFbgZvc"
worksheet = client.open_by_key(SHEET_ID).sheet1

# === FUNZIONE TELEGRAM ===
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"]["text"]

        # Esempio: se scrivi "saldo", legge dal foglio
        if text.lower() == "saldo":
            saldo = worksheet.acell("B2").value  # esempio: cella B2
            send_message(chat_id, f"💰 Il tuo saldo attuale è: {saldo}")
        else:
            send_message(chat_id, "Scrivi 'saldo' per vedere i dati dal foglio Google!")

    return "ok", 200

def send_message(chat_id, text):
    payload = {"chat_id": chat_id, "text": text}
    requests.post(TELEGRAM_URL, json=payload)

# === AVVIO SERVER ===
if __name__ == "__main__":
    app.run(port=5000)
