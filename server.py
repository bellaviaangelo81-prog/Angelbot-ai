from flask import Flask, request
from openai import OpenAI
import os
import requests

# === CONFIGURAZIONE ===
app = Flask(__name__)

# Recupera le chiavi dalle variabili d’ambiente su Render
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Inizializza il client GPT-5
client = OpenAI(api_key=OPENAI_API_KEY)

# URL base Telegram
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"


@app.route("/", methods=["GET"])
def home():
    """Pagina di test base."""
    return "✅ AngelBot-AI (GPT-5) è online su Render!", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    """Gestione dei messaggi Telegram."""
    data = request.get_json()

    if not data or "message" not in data:
        return {"ok": False, "error": "Nessun messaggio ricevuto"}, 200

    message = data["message"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    if not text:
        return {"ok": True, "note": "Nessun testo da elaborare"}, 200

    try:
        # === Richiesta a GPT-5 ===
        response = client.responses.create(
            model="gpt-5",
            input=text,
            reasoning={"effort": "medium"},
            text={"verbosity": "medium"}
        )

        # Estrai il testo dalla risposta
        bot_reply = response.output_text.strip()

    except Exception as e:
        bot_reply = f"⚠️ Errore con l'AI: {str(e)}"

    # === Risposta Telegram ===
    requests.post(TELEGRAM_URL, json={
        "chat_id": chat_id,
        "text": bot_reply
    })

    return {"ok": True}, 200


if __name__ == "__main__":
    # Flask parte sulla porta richiesta da Render
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
