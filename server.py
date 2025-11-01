from flask import Flask, request, jsonify
import requests
import os
import logging

app = Flask(__name__)

# Prendi le variabili d'ambiente
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# URL base Telegram
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Log per debug
logging.basicConfig(level=logging.INFO)


@app.route("/")
def home():
    return "✅ Bot finanziario attivo su Render!"


@app.route("/status")
def status():
    return jsonify({
        "status": "running",
        "webhook_url": WEBHOOK_URL
    })


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()

    if not update:
        return jsonify({"error": "No update received"}), 400

    if "message" in update:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "")

        if text.lower() == "/start":
            send_message(chat_id, "Ciao! 🤖 Il bot finanziario è online e pronto!")
        else:
            send_message(chat_id, f"Hai scritto: {text}")

    return jsonify({"status": "ok"})


def send_message(chat_id, text):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)


# Imposta il webhook automaticamente se non è già impostato
def set_webhook():
    if WEBHOOK_URL:
        url = f"{TELEGRAM_API_URL}/setWebhook"
        response = requests.post(url, json={"url": f"{WEBHOOK_URL}/webhook"})
        if response.status_code == 200:
            logging.info(f"✅ Webhook impostato su {WEBHOOK_URL}/webhook")
        else:
            logging.error(f"❌ Errore impostando il webhook: {response.text}")
    else:
        logging.warning("⚠️ Variabile WEBHOOK_URL non impostata.")


if __name__ == "__main__":
    set_webhook()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
