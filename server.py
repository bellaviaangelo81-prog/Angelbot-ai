from flask import Flask, request
import requests
import os

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# URL base di Telegram
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

@app.route('/')
def home():
    return "✅ AngelBot-AI con Intelligenza Artificiale è online!"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()

    if not data:
        return {"ok": False, "error": "Nessun JSON ricevuto"}

    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text")

    if not chat_id or not text:
        return {"ok": True}

    # Risposte base
    if text.lower() in ["/start", "ciao", "hello"]:
        reply = "Ciao 👋 Sono AngelBot-AI! Come posso aiutarti oggi?"
    elif "meteo" in text.lower():
        reply = "🌤️ Al momento non posso consultare i dati meteo reali, ma presto potrò!"
    elif "notizie" in text.lower():
        reply = "📰 Le ultime notizie? Sto lavorando per portarti aggiornamenti in tempo reale!"
    else:
        reply = "🤖 Al momento rispondo solo a comandi base, ma sto migliorando!"

    # Invia la risposta a Telegram
    requests.post(f"{TELEGRAM_URL}/sendMessage", json={"chat_id": chat_id, "text": reply})

    return {"ok": True}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
