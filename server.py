# server.py
import os
import asyncio
import requests
from io import BytesIO
from flask import Flask, request
import yfinance as yf
import matplotlib.pyplot as plt
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- CONFIG ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
OWNER_TELEGRAM_ID = int(os.environ.get("OWNER_TELEGRAM_ID", "0"))

app = Flask(__name__)

# --- BOT ---
app_bot = Application.builder().token(TELEGRAM_TOKEN).build()

async def _unauthorized(update: Update):
    if update.message:
        await update.message.reply_text("❌ Non autorizzato.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_TELEGRAM_ID:
        return await _unauthorized(update)
    msg = (
        "📈 Benvenuto nel tuo bot finanziario!\n\n"
        "Comandi:\n"
        "/prezzo <SIMBOLO>\n"
        "/grafico <SIMBOLO>\n"
        "/info <SIMBOLO>\n"
    )
    await update.message.reply_text(msg)

async def prezzo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_TELEGRAM_ID:
        return await _unauthorized(update)
    if not context.args:
        return await update.message.reply_text("Scrivi: /prezzo <SIMBOLO>")
    simbolo = context.args[0].upper()
    try:
        info = yf.Ticker(simbolo).info
        prezzo = info.get("currentPrice") or info.get("regularMarketPrice")
        nome = info.get("shortName", simbolo)
        if prezzo:
            await update.message.reply_text(f"💰 {nome} ({simbolo})\nPrezzo attuale: {prezzo}$")
        else:
            await update.message.reply_text("Non trovo il prezzo.")
    except Exception as e:
        await update.message.reply_text(f"Errore: {e}")

async def grafico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_TELEGRAM_ID:
        return await _unauthorized(update)
    if not context.args:
        return await update.message.reply_text("Scrivi: /grafico <SIMBOLO>")
    simbolo = context.args[0].upper()
    try:
        dati = yf.Ticker(simbolo).history(period="1mo")
        if dati.empty:
            return await update.message.reply_text("Nessun dato trovato.")
        plt.figure()
        dati["Close"].plot(title=f"Andamento di {simbolo}")
        buf = BytesIO()
        plt.savefig(buf, format="png")
        buf.seek(0)
        await update.message.reply_photo(buf)
        plt.close()
    except Exception as e:
        await update.message.reply_text(f"Errore: {e}")

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_TELEGRAM_ID:
        return await _unauthorized(update)
    if not context.args:
        return await update.message.reply_text("Scrivi: /info <SIMBOLO>")
    simbolo = context.args[0].upper()
    try:
        info = yf.Ticker(simbolo).info
        nome = info.get("shortName", "N/D")
        settore = info.get("sector", "N/D")
        paese = info.get("country", "N/D")
        cap = info.get("marketCap", "N/D")
        await update.message.reply_text(
            f"📊 {nome} ({simbolo})\nSettore: {settore}\nPaese: {paese}\nMarket Cap: {cap}"
        )
    except Exception as e:
        await update.message.reply_text(f"Errore: {e}")

# --- HANDLERS ---
app_bot.add_handler(CommandHandler("start", start))
app_bot.add_handler(CommandHandler("prezzo", prezzo))
app_bot.add_handler(CommandHandler("grafico", grafico))
app_bot.add_handler(CommandHandler("info", info))

# --- FLASK ---
@app.route("/")
def home():
    return "✅ AngelBot AI attivo."

@app.route("/set_webhook")
def set_webhook():
    if not WEBHOOK_URL:
        return "❌ WEBHOOK_URL non impostato", 400
    r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={WEBHOOK_URL}")
    return ("OK ✅" if r.ok else "Errore ❌") + f": {r.text}"

@app.route("/webhook", methods=["POST"])
async def webhook():
    update = Update.de_json(request.get_json(force=True), app_bot.bot)
    await app_bot.process_update(update)
    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
