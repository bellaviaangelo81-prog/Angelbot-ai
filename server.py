import os
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

app = Flask(__name__)

# Variabili d’ambiente (Render → Environment)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_TELEGRAM_ID = os.getenv("OWNER_TELEGRAM_ID")

# Crea l'app Telegram
application = Application.builder().token(TELEGRAM_TOKEN).build()


# --- Comandi base ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != OWNER_TELEGRAM_ID:
        await update.message.reply_text("❌ Accesso non autorizzato.")
        return
    await update.message.reply_text("🤖 Ciao Angelo, sono il tuo bot AI! Connessione attiva ✅")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Puoi scrivermi qualsiasi cosa, e io risponderò!")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != OWNER_TELEGRAM_ID:
        return  # Ignora chi non è il proprietario
    text = update.message.text
    response = f"Hai scritto: {text}"
    await update.message.reply_text(response)


# --- Registra i comandi ---
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


# --- Webhook Flask ---
@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
async def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    await application.process_update(update)
    return "OK", 200


@app.route("/")
def home():
    return "Bot attivo e collegato al webhook ✅", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TELEGRAM_TOKEN,
        webhook_url=f"https://angelbot-ai.onrender.com/{TELEGRAM_TOKEN}"
    )
