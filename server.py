from flask import Flask, request, jsonify
import requests
import os
import logging

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

logging.basicConfig(level=logging.INFO)

@app.route("/")
def home():
    return "✅ Bot attivo su Render!"

@app.route("/status")
def status():
    return jsonify({"status": "running", "webhook_url": WEBHOOK_URL})

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    if not update:
        return jsonify({"error": "no update"}), 400

    if "message" in update:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "")
        send_message(chat_id, f"Hai scritto: {text}")

    return jsonify({"ok": True})

def send_message(chat_id, text):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)

def set_webhook():
    if WEBHOOK_URL:
        url = f"{TELEGRAM_API_URL}/setWebhook"
        requests.post(url, json={"url": f"{WEBHOOK_URL}/webhook"})
        logging.info(f"Webhook impostato su {WEBHOOK_URL}/webhook")

if __name__ == "__main__":
    set_webhook()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
