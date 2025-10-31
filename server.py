from flask import Flask, request
import requests
import os

# Crea l'app Flask
app = Flask(__name__)

# --- CONFIGURAZIONE TOKEN TELEGRAM ---
# Prende il token da variabile d’ambiente (meglio su Render)
# oppure usa quello scritto direttamente nel codice per test locale
TOKEN = os.getenv("BOT_TOKEN", "8497761155:AAEpJggDUpnWVC7wR6OCJpQdsAr4lFruxQ8")
URL = f"https://api.telegram.org/bot{TOKEN}/"

# --- HOME PAGE (per test) ---
@app.route('/')
def home():
    return "✅ AngelBot-AI è online e operativo!"

# --- WEBHOOK (Telegram manda qui i messaggi) ---
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Dati ricevuti dal webhook:", data)

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        # Messaggio di risposta
        reply = f"Ciao 👋, hai scritto: {text}"
        requests.get(URL + f"sendMessage?chat_id={chat_id}&text={reply}")

    return {"ok": True}, 200

# --- AVVIO SERVER ---
if __name__ == '__main__':
    # Render o Replit usano la porta fornita dal sistema
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
