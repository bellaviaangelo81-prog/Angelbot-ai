from flask import Flask, request
import os
import requests

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

@app.route('/')
def home():
    return "Bot attivo su Render 🚀"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data:
        return {"ok": False}

    chat_id = data['message']['chat']['id']
    text = data['message'].get('text', '')

    # Risposta di test
    reply = f"Hai detto: {text}"
    send_message(chat_id, reply)
    return {"ok": True}

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
