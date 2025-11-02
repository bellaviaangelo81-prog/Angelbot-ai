from flask import Flask, request
import requests
import os

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Home page di test (Render la userà per verificare che il server risponda)
@app.route('/', methods=['GET'])
def home():
    return "✅ AngelBot è vivo e online!"

# Questa è la route che Telegram userà per mandare i messaggi
@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()

    if not update:
        return "No update", 400

    # Controlla che ci sia un messaggio di testo
    if "message" in update and "text" in update["message"]:
        chat_id = update["message"]["chat"]["id"]
        user_text = update["message"]["text"]

        # Risposta base per test
        reply_text = f"Hai detto: {user_text}"

        # Invia la risposta a Telegram
        send_message(chat_id, reply_text)

    return "ok", 200


def send_message(chat_id, text):
    url = f"{TELEGRAM_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
