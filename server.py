from flask import Flask, request
from openai import OpenAI
import os
import requests

# Inizializza Flask
app = Flask(__name__)

# Configurazione chiavi
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Inizializza client GPT-5
client = OpenAI(api_key=OPENAI_API_KEY)

# URL base di Telegram
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"


@app.route("/webhook", methods=["POST"])
def webhook():
    """Riceve gli aggiornamenti da Telegram."""
    data = request.get_json()

    if not data or "message" not in data:
        return "no message", 200

    message = data["message"]
    chat_id = message["chat"]["id"]
    user_text = message.get("text", "")

    # Se non c’è testo, ignora
    if not user_text:
        return "no text", 200

    try:
        # Chiamata a GPT-5
        response = client.responses.create(
            model="gpt-5",
            input=user_text,
            reasoning={"effort": "medium"},     # Può essere "low", "medium" o "high"
            text={"verbosity": "medium"}        # Controlla la lunghezza delle risposte
        )

        # Estrai testo di output
        bot_reply = response.output_text.strip()

    except Exception as e:
        bot_reply = f"Errore durante la risposta: {e}"

    # Invia la risposta a Telegram
    requests.post(TELEGRAM_URL, json={
        "chat_id": chat_id,
        "text": bot_reply
    })

    return "ok", 200


@app.route("/", methods=["GET"])
def index():
    return "Bot GPT-5 attivo e funzionante!", 200


if __name__ == "__main__":
    # Avvia il server Flask
    app.run(host="0.0.0.0", port=5000, debug=True)
