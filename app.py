from flask import Flask, request
import os
import asyncio
import logging
from io import BytesIO
from datetime import datetime
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes
)
import random

# --- CONFIGURAZIONE BASE ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
app = Flask(__name__)

# --- LOGGING ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- APP TELEGRAM ---
bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

# Variabili globali
user_preferences = {}
default_interval = 60  # minuti

# --- FUNZIONI DI ANALISI ---
def genera_suggerimento():
    """Analisi base per suggerire un titolo interessante"""
    titoli = ["AAPL", "MSFT", "TSLA", "AMZN", "GOOGL", "NVDA", "META"]
    simbolo = random.choice(titoli)
    ticker = yf.Ticker(simbolo)
    dati = ticker.history(period="1mo")

    if dati.empty:
        return "Nessun dato disponibile per oggi."

    variazione = ((dati["Close"][-1] - dati["Close"][0]) / dati["Close"][0]) * 100
    nome = ticker.info.get("shortName", simbolo)
    if variazione > 0:
        return f"📈 {nome} ({simbolo}) è in crescita del {variazione:.2f}% questo mese. Potrebbe essere un buon momento per approfondire."
    else:
        return f"📉 {nome} ({simbolo}) è in calo del {abs(variazione):.2f}% nell’ultimo mese. Potrebbe convenire attendere un'inversione di trend."

def analisi_titolo(simbolo):
    """Analisi semplice di un titolo"""
    try:
        simbolo = simbolo.upper()
        t = yf.Ticker(simbolo)
        dati = t.history(period="1mo")
        if dati.empty:
            return "Dati non trovati per questo simbolo."
        variazione = ((dati["Close"][-1] - dati["Close"][0]) / dati["Close"][0]) * 100
        prezzo = dati["Close"][-1]
        nome = t.info.get("shortName", simbolo)
        return f"📊 {nome} ({simbolo})\nPrezzo attuale: {prezzo:.2f}$\nAndamento mese: {variazione:.2f}%"
    except Exception as e:
        return f"Errore nell’analisi: {e}"

# --- GESTIONE COMANDI ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📈 Analizza titolo", callback_data="analisi_titolo")],
        [InlineKeyboardButton("💡 Suggerimento del giorno", callback_data="suggerimento")],
        [InlineKeyboardButton("🌍 Mercati globali", callback_data="mercati")],
        [InlineKeyboardButton("⏰ Imposta frequenza aggiornamenti", callback_data="frequenza")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Ciao! Sono il tuo consulente finanziario digitale 🤖\nScegli un’opzione dal menu:",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "suggerimento":
        testo = genera_suggerimento()
        await query.edit_message_text(testo)

    elif query.data == "analisi_titolo":
        await query.edit_message_text("Scrivi /analizza <simbolo> (es: /analizza AAPL) per ottenere un’analisi.")

    elif query.data == "mercati":
        text = (
            "🌍 Seleziona una regione:\n\n"
            "🇺🇸 Stati Uniti\n🇪🇺 Europa\n🇯🇵 Asia\n🌍 Altri mercati in arrivo."
        )
        await query.edit_message_text(text)

    elif query.data == "frequenza":
        keyboard = [
            [InlineKeyboardButton("⏱️ 15 minuti", callback_data="freq_15")],
            [InlineKeyboardButton("🕐 1 ora", callback_data="freq_60")],
            [InlineKeyboardButton("🕔 5 ore", callback_data="freq_300")],
            [InlineKeyboardButton("📅 Giornaliero", callback_data="freq_1440")]
        ]
        await query.edit_message_text(
            "Ogni quanto vuoi ricevere aggiornamenti automatici?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("freq_"):
        minuti = int(query.data.split("_")[1])
        user_preferences[query.from_user.id] = minuti
        await query.edit_message_text(f"Frequenza impostata a ogni {minuti} minuti ✅")

async def analizza(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usa: /analizza <simbolo> (es: /analizza TSLA)")
        return
    simbolo = context.args[0]
    testo = analisi_titolo(simbolo)
    await update.message.reply_text(testo)

async def invia_aggiornamenti():
    """Invia suggerimenti periodici agli utenti"""
    while True:
        for user_id, minuti in user_preferences.items():
            suggerimento = genera_suggerimento()
            try:
                await bot_app.bot.send_message(chat_id=user_id, text=f"🔔 Aggiornamento automatico:\n{suggerimento}")
            except Exception as e:
                logger.error(f"Errore nell’invio a {user_id}: {e}")
        await asyncio.sleep(default_interval * 60)

# --- FLASK ROUTES ---
@app.route('/')
def home():
    return "Bot consulente finanziario attivo su Render! ✅"

@app.route('/webhook', methods=['POST'])
def webhook():
    """Gestione aggiornamenti Telegram"""
    try:
        json_data = request.get_json(force=True)
        update = Update.de_json(json_data, bot_app.bot)
        asyncio.run(bot_app.process_update(update))
        return "ok", 200
    except Exception as e:
        logger.error(f"Errore webhook: {e}")
        return "error", 500

# --- HANDLERS ---
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("analizza", analizza))
bot_app.add_handler(CallbackQueryHandler(button_handler))

# --- AVVIO ---
if __name__ == "__main__":
    logger.info("Avvio bot consulente finanziario...")
    if WEBHOOK_URL:
        asyncio.run(bot_app.bot.set_webhook(url=WEBHOOK_URL + "/webhook"))
    asyncio.get_event_loop().create_task(invia_aggiornamenti())
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
