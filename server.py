from flask import Flask, request
import requests
import os
from openai import OpenAI

app = Flask(__name__)

# Legge i token dalle variabili d'ambiente
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Inizializza il client OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

# URL base per Telegram
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

@app.route('/')
def home():
    return "✅ AngelBot-AI (GPT-5) è online e pronto a rispondere!"

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

    # Risposte base /start e saluto
    if text.lower() in ["/start", "ciao", "hello"]:
        reply = "Ciao 👋 Sono AngelBot-AI, potenziato da GPT-5! Dimmi qualcosa e ti risponderò con intelligenza 🤖"
    else:
        try:
            # Richiesta a GPT-5
            response = client.chat.completions.create(
                model="gpt-5",  # <<< qui usiamo GPT-5
                messages=[
                    {"role": "system", "content": "Sei AngelBot-AI, un assistente Telegram gentile, utile e chiaro. Rispondi in italiano."},
                    {"role": "user", "content": text}
                ],
                max_tokens=300,
                temperature=0.8
            )

            reply = response.choices[0].message.content.strip()

        except Exception as e:
            reply = f"⚠️ Errore con l'AI: {str(e)}"

    # Invia la risposta al messaggio su Telegram
    requests.post(f"{TELEGRAM_URL}/sendMessage", json={"chat_id": chat_id, "text": reply})

    return {"ok": True}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
