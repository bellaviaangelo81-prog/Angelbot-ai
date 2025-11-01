from flask import Flask, request
import os
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from io import BytesIO
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
import asyncio
import logging
import datetime
import random

# --- CONFIGURAZIONE BASE ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

app = Flask(__name__)

# Stato utenti (in futuro → database)
user_settings = {}  # {chat_id: {"interval": "giornaliero", "symbols": ["AAPL", "TSLA"]}}

# --- FUNZIONI UTILI ---

def analisi_titolo(simbolo):
    """Restituisce un'analisi automatica semplificata."""
    try:
        dati = yf.Ticker(simbolo).history(period="1mo")
        if dati.empty:
            return "⚠️ Dati non disponibili per questo titolo."
        variazione = ((dati["Close"][-1] - dati["Close"][0]) / dati["Close"][0]) * 100
        direzione = "in rialzo 📈" if variazione > 0 else "in ribasso 📉"
        consiglio = (
            "potrebbe essere un buon momento per considerare un ingresso"
            if variazione < -5 else
            "sta performando bene, ma occhio a eventuali correzioni"
        )
        return f"{simbolo} è {direzione} del {variazione:.2f}%. In base al trend, {consiglio}."
    except Exception as e:
        return f"Errore nell'analisi di {simbolo}: {e}"

async def invia_notifica(context: ContextTypes.DEFAULT_TYPE, chat_id, simbolo):
    testo = analisi_titolo(simbolo)
    await context.bot.send_message(chat_id=chat_id, text=f"📢 Analisi aggiornata per {simbolo}:\n\n{testo}")

# --- COMANDI BASE ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_settings.setdefault(update.effective_chat.id, {"interval": None, "symbols": []})
    testo = (
        "💼 Benvenuto nel tuo consulente finanziario personale!\n\n"
        "Puoi usare i seguenti comandi:\n"
        "• /prezzo <simbolo> → Prezzo attuale\n"
        "• /grafico <simbolo> → Grafico mensile\n"
        "• /info <simbolo> → Info aziendali\n"
        "• /monitoraggio → Imposta frequenza e ricevi analisi automatiche\n"
    )
    await update.message.reply_text(testo)

async def prezzo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Scrivi: /prezzo <simbolo>")
        return
    simbolo = context.args[0].upper()
    try:
        info = yf.Ticker(simbolo).info
        prezzo = info.get("currentPrice") or info.get("regularMarketPrice")
        nome = info.get("shortName", simbolo)
        if prezzo:
            await update.message.reply_text(f"💰 {nome} ({simbolo})\nPrezzo attuale: {prezzo}$")
        else:
            await update.message.reply_text("Non trovo il prezzo per questo simbolo.")
    except Exception as e:
        await update.message.reply_text(f"Errore nel recupero dei dati: {e}")

async def grafico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Scrivi: /grafico <simbolo>")
        return
    simbolo = context.args[0].upper()
    try:
        dati = yf.Ticker(simbolo).history(period="1mo")
        if dati.empty:
            await update.message.reply_text("Dati non trovati per questo simbolo.")
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
        await update.message.reply_text(f"Errore nel generare il grafico: {e}")

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Scrivi: /info <simbolo>")
        return
    simbolo = context.args[0].upper()
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
        await update.message.reply_text(f"Errore nel recupero delle info: {e}")

# --- MONITORAGGIO AUTOMATICO ---

async def monitoraggio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra le opzioni di monitoraggio"""
    keyboard = [
        [InlineKeyboardButton("🕧 30 minuti", callback_data="freq_30")],
        [InlineKeyboardButton("🕐 60 minuti", callback_data="freq_60")],
        [InlineKeyboardButton("🕑 120 minuti", callback_data="freq_120")],
        [InlineKeyboardButton("🌅 Giornaliero", callback_data="freq_day")],
        [InlineKeyboardButton("📆 Settimanale", callback_data="freq_week")],
        [InlineKeyboardButton("🚫 Disattiva monitoraggio", callback_data="freq_off")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📊 Imposta la frequenza di monitoraggio:", reply_markup=reply_markup)

async def monitoraggio_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce la selezione delle frequenze"""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    user = user_settings.setdefault(chat_id, {"interval": None, "symbols": ["AAPL", "TSLA"]})
    scelta = query.data

    mapping = {
        "freq_30": ("ogni 30 minuti", 30),
        "freq_60": ("ogni 60 minuti", 60),
        "freq_120": ("ogni 120 minuti", 120),
        "freq_day": ("giornaliero", 60 * 24),
        "freq_week": ("settimanale", 60 * 24 * 7)
    }

    if scelta == "freq_off":
        user["interval"] = None
        await query.edit_message_text("🛑 Monitoraggio disattivato.")
        return

    descrizione, minuti = mapping.get(scelta, ("non impostato", None))
    user["interval"] = minuti

    await query.edit_message_text(f"✅ Monitoraggio impostato: {descrizione}.")

    # Imposta job periodico
    job_queue = context.application.job_queue
    job_name = f"monitor_{chat_id}"
    existing = job_queue.get_jobs_by_name(job_name)
    for j in existing:
        j.schedule_removal()

    async def job(context: ContextTypes.DEFAULT_TYPE):
        for simbolo in user["symbols"]:
            await invia_notifica(context, chat_id, simbolo)

    job_queue.run_repeating(job, interval=minuti * 60, name=job_name)

# --- AVVIO BOT ---
app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app_bot.add_handler(CommandHandler("start", start))
app_bot.add_handler(CommandHandler("prezzo", prezzo))
app_bot.add_handler(CommandHandler("grafico", grafico))
app_bot.add_handler(CommandHandler("info", info))
app_bot.add_handler(CommandHandler("monitoraggio", monitoraggio))
app_bot.add_handler(CallbackQueryHandler(monitoraggio_callback))

# --- FLASK ROUTES ---

@app.route('/')
def home():
    return "Bot finanziario attivo!"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        json_data = request.get_json(force=True)
        update = Update.de_json(json_data, app_bot.bot)
        asyncio.run(app_bot.process_update(update))
        return "ok", 200
    except Exception as e:
        logger.error(f"Errore nel webhook: {e}", exc_info=True)
        return "error", 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    asyncio.run(app_bot.bot.set_webhook(url=WEBHOOK_URL))
    app.run(host="0.0.0.0", port=port)
