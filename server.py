from flask import Flask, request
import requests, os

app = Flask(__name__)

# Ottieni il token in modo sicuro
TOKEN = os.getenv("BOT_TOKEN")
URL = f"https://api.telegram.org/bot{TOKEN}/"

@app.route('/')
def home():
    return "✅ AngelBot-AI è online!"

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    data = request.get_json()
    print(data)

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        reply = f"Ciao 👋, hai scritto: {text}"
        requests.get(URL + f"sendMessage?chat_id={chat_id}&text={reply}")

    return {"ok": True}

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)
