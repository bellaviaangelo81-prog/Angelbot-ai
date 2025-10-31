from flask import Flask, request
from openai import OpenAI
import os
import requests

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"


@app.route("/", methods=["GET"])
def home():
    return "✅ AngelBot-AI (GPT-5) è online e operativo!", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    if not data or "message" not in data:
        return {"ok": False, "error": "Nessun messaggio ricevuto"}, 200

    message = data["message"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()

    # Se non c’è testo, non rispondere
    if not text:
        return {"ok": True, "note": "Messaggio vuoto"}, 200

    # Gestione dei comandi base
    if text.lower() in ["/start", "ciao", "hello"]:
        reply = (
            "👋 Ciao! Sono **AngelBot-AI**, potenziato da GPT-5.\n"
            "Scrivimi qualsiasi cosa e ti risponderò come un vero assistente AI."
        )
    else:
        try:
            # Richiesta al modello GPT-5
            response = client.responses.create(
                model="gpt-5",
                input=f"L'utente dice: {text}",
                reasoning={"effort": "medium"},
                text={"verbosity": "medium"}
            )

            reply = response.output_text.strip()

        except Exception as e:
            reply = f"⚠️ Errore con l'AI: {str(e)}"

    # Invia la risposta su Telegram
    requests.post(TELEGRAM_URL, json={
        "chat_id": chat_id,
        "text": reply,
        "parse_mode": "Markdown"
    })

    return {"ok": True}, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
