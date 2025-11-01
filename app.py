from flask import Flask, request
import os
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from io import BytesIO
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import asyncio
import logging
import openai
import datetime

# --- CONFIGURAZIONE BASE ---
TELEGRAM_TOKEN = "8497761155:AAGE6mYNuXrYY6tav8IxsurnOgBG90cJ2_0"
WEBHOOK_URL = "https://angelbot-ai.onrender.com/webhook"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # Inserisci la tua chiave OpenAI su Render
openai.api_key = OPENAI_API_KEY

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BOT TELEGRAM ---
app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

# Mappa per salvare le preferenze di monitoraggio per ogni utente
user_settings = {}

# --- COMANDI BASE ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 Prezzo", callback_data="prezzo")],
        [InlineKeyboardButton("📈 Grafico", callback_data="grafico")],
        [InlineKeyboardButton("ℹ️ Info", callback_data="info")],
        [InlineKeyboardButton("🧠 Analisi AI", callback_data="analisi_ai")],
        [InlineKeyboardButton("⏱️ Monitoraggio", callback_data="monitoraggio")]
    ]
    await update.message.reply_text(
        "👋 Benvenuto nel tuo assistente finanziario AI!\n\nScegli un’opzione:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --- FUNZIONI FINANZIARIE ---
async def mostra_prezzo(update: Update, context: ContextTypes.DEFAULT_TYPE, simbolo):
    try:
        ticker = yf.Ticker(simbolo)
        info = ticker.info
        prezzo = info.get("currentPrice") or info.get("regularMarketPrice")
        nome = info.get("shortName", simbolo)
        if prezzo:
            await update.message.reply_text(f"💰 {nome} ({simbolo})\nPrezzo attuale: {prezzo}$")
        else:
            await update.message.reply_text("Nessun dato disponibile.")
    except Exception as e:
        await update.message.reply_text(f"Errore: {e}")

async def mostra_grafico(update: Update, context: ContextTypes.DEFAULT_TYPE, simbolo):
    try:
        dati = yf.Ticker(simbolo).history(period="1mo")
        if dati.empty:
            await update.message.reply_text("Dati non trovati.")
            return
        plt.figure()
        dati["Close"].plot(title=f"Andamento di {simbolo}")
        plt.xlabel("Data")
        plt.ylabel("Prezzo ($)")
        buf = BytesIO()
        plt.savefig(buf, format="png")
        buf.seek(0)
        await update.message.reply_photo(buf)
        plt.close()
    except Exception as e:
        await update.message.reply_text(f"Errore: {e}")

async def mostra_info(update: Update, context: ContextTypes.DEFAULT_TYPE, simbolo):
    try:
        info = yf.Ticker(simbolo).info
        nome = info.get("shortName", "N/D")
        settore = info.get("sector", "N/D")
        paese = info.get("country", "N/D")
        cap = info.get("marketCap", "N/D")
        await update.message.reply_text(
            f"📊 {nome} ({simbolo})\nSettore: {settore}\nPaese: {paese}\nCapitalizzazione: {cap}"
        )
    except Exception as e:
        await update.message.reply_text(f"Errore: {e}")

# --- ANALISI INTELLIGENTE ---
async def analisi_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Scrivimi il simbolo o chiedi un consiglio (es. 'Cosa ne pensi di Amazon?').")

async def ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    testo = update.message.text
    try:
        risposta = openai.ChatCompletion.create(
            model="gpt-5",
            messages=[
                {"role": "system", "content": "Sei un consulente finanziario esperto e rispondi in italiano, in modo realistico e prudente."},
                {"role": "user", "content": testo}
            ]
        )
        risposta_testo = risposta.choices[0].message.content
        await update.message.reply_text(risposta_testo)
    except Exception as e:
        await update.message.reply_text(f"Errore AI: {e}")

# --- MONITORAGGIO ---
async def monitoraggio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("⏰ 30 minuti", callback_data="m_30")],
        [InlineKeyboardButton("🕐 1 ora", callback_data="m_60")],
        [InlineKeyboardButton("🕑 2 ore", callback_data="m_120")],
        [InlineKeyboardButton("🌅 Giornaliero", callback_data="m_day")],
        [InlineKeyboardButton("🗓️ Settimanale", callback_data="m_week")],
        [InlineKeyboardButton("🔕 Off", callback_data="m_off")]
    ]
    await update.message.reply_text("Imposta la frequenza di monitoraggio:", reply_markup=InlineKeyboardMarkup(keyboard))

async def gestisci_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data.startswith("m_"):
        user_settings[query.from_user.id] = data
        await query.edit_message_text(f"✅ Frequenza impostata su: {data[2:]}")
        return

    if data == "prezzo":
        await query.edit_message_text("Scrivi il simbolo per conoscere il prezzo (es. AAPL, AMZN).")
    elif data == "grafico":
        await query.edit_message_text("Scrivi il simbolo per vedere il grafico (es. TSLA, MSFT).")
    elif data == "info":
        await query.edit_message_text("Scrivi il simbolo per ottenere info (es. META, BIDU).")
    elif data == "analisi_ai":
        await analisi_ai(query, context)
    elif data == "monitoraggio":
        await monitoraggio(query, context)

# --- HANDLER MESSAGGI ---
app_bot.add_handler(CommandHandler("start", start))
app_bot.add_handler(CallbackQueryHandler(gestisci_callback))
app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ai_chat))

# --- FLASK ROUTES ---
@app.route("/")
def home():
    return "✅ AngelBot AI attivo su Render."

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        json_data = request.get_json(force=True)
        update = Update.de_json(json_data, app_bot.bot)
        asyncio.run(app_bot.process_update(update))
        return "ok", 200
    except Exception as e:
        logger.error(f"Errore webhook: {e}", exc_info=True)
        return "error", 500

# --- AVVIO ---
if __name__ == "__main__":
    asyncio.run(app_bot.bot.set_webhook(WEBHOOK_URL))
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
