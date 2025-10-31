# app.py
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# Token e chat ID Telegram (personali)
TELEGRAM_TOKEN = "8497761155:AAEpJggDUpnWVC7wR6OCJpQdsAr4lFruxQ8"
CHAT_ID = "1122092272"

# Funzione per inviare messaggi su Telegram
def invia_messaggio_telegram(testo):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": testo}
    requests.post(url, json=payload)

@app.route('/')
def home():
    return jsonify({"messaggio": "Server attivo su Render e collegato a Telegram!"})

@app.route('/messaggio', methods=['POST'])
def ricevi_messaggio():
    dati = request.get_json()
    utente = dati.get("utente", "Sconosciuto")
    testo = dati.get("testo", "")
    print(f"📩 Messaggio da {utente}: {testo}")

    risposta = f"Ciao {utente}, ho ricevuto: '{testo}'!"
    invia_messaggio_telegram(f"📩 Nuovo messaggio da {utente}: {testo}")

    return jsonify({"risposta": risposta})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
