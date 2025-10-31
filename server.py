from flask import Flask, request
import requests
import os

app = Flask(__name__)

# --- TOKEN TELEGRAM ---
TOKEN = os.getenv("BOT_TOKEN", "8497761155:AAEpJggDUpnWVC7wR6OCJpQdsAr4lFruxQ8")
URL = f"https://api.telegram.org/bot{TOKEN}/"

# --- HOME PAGE ---
@app.route('/')
def home():
    return "✅ AngelBot-AI è online e operativo!"

# --- WEBHOOK TELEGRAM ---
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Dati ricevuti dal webhook:", data)

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "").strip()

        # Gestione comandi
        if text == "/start":
            reply = (
                "👋 Benvenuto su *AngelBot-AI!*\n\n"
                "Puoi usare questi comandi:\n"
                "• `/start` → avvia il bot\n"
                "• `/info` → scopri cosa può fare\n"
                "• `/ai [domanda]` → ricevi una risposta intelligente\n\n"
                "Scrivi ad esempio `/ai qual è la capitale del Giappone?`"
            )
        elif text == "/info":
            reply = (
                "ℹ️ *AngelBot-AI* è un bot Telegram creato per parlare, "
                "fornire informazioni e collegarsi a servizi intelligenti. "
                "In futuro potrà analizzare dati, prevedere mercati, "
                "o darti risposte con intelligenza artificiale."
            )
        elif text.startswith("/ai "):
            domanda = text[4:]
            reply = f"🧠 (Risposta simulata) Hai chiesto: {domanda}\n\nRisposta: la sto elaborando con logica e dati!"
        else:
            reply = f"Hai scritto: {text}"

        # Invia risposta
        requests.get(URL + f"sendMessage?chat_id={chat_id}&text={reply}&parse_mode=Markdown")

    return {"ok": True}, 200


# --- AVVIO SERVER ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
