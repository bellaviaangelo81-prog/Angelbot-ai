from flask import Flask, request
import requests
import os

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN", "8497761155:AAEpJggDUpnWVC7wR6OCJpQdsAr4lFruxQ8")
URL = f"https://api.telegram.org/bot{TOKEN}/"

@app.route('/')
def home():
    return "✅ AngelBot-AI è online e operativo!"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Dati ricevuti dal webhook:", data)

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        reply = f"Ciao 👋, hai scritto: {text}"
        requests.get(URL + f"sendMessage?chat_id={chat_id}&text={reply}")

    return {"ok": True}, 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
