from flask import Flask, request
import os
import yfinance as yf
import matplotlib
matplotlib.use('Agg')  # Usa backend non-GUI per i server
import matplotlib.pyplot as plt
from io import BytesIO
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import asyncio
import logging

# --- LOGGING ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- CONFIGURAZIONE ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
app = Flask(__name__)

# --- BOT TELEGRAM ---
app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()


# --- COMANDI DEL BOT ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📈 Benvenuto nel tuo assistente finanziario!\n\n"
        "Comandi disponibili:\n"
        "• /prezzo <simbolo> → Prezzo attuale (es. /prezzo TSLA)\n"
        "• /grafico <simbolo> → Grafico dell’ultimo mese (es. /grafico AAPL)\n"
        "• /info <simbolo> → Info sull’azienda"
    )
    await update.message.reply_text(msg)


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


# --- REGISTRA COMANDI ---
app_bot.add_handler(CommandHandler("start", start))
app_bot.add_handler(CommandHandler("prezzo", prezzo))
app_bot.add_handler(CommandHandler("grafico", grafico))
app_bot.add_handler(CommandHandler("info", info))

_bot_initialized = False


def _ensure_bot_initialized():
    """Inizializza il bot e configura il webhook"""
    global _bot_initialized
    if not _bot_initialized:
        async def init():
            try:
                await app_bot.initialize()
                if WEBHOOK_URL:
                    await app_bot.bot.set_webhook(url=WEBHOOK_URL)
                    logger.info(f"✓ Webhook configurato: {WEBHOOK_URL}")
                else:
                    logger.warning("⚠ Variabile WEBHOOK_URL mancante")
            except Exception as e:
                logger.error(f"Errore inizializzazione bot: {e}", exc_info=True)
                raise

        asyncio.run(init())
        _bot_initialized = True
        logger.info("Bot inizializzato correttamente")


# --- FLASK ROUTES ---
@app.route('/')
def home():
    return "✅ Bot finanziario attivo su Render!"


@app.route('/status')
def status():
    """Verifica stato bot e webhook"""
    try:
        _ensure_bot_initialized()
        webhook_info = asyncio.run(app_bot.bot.get_webhook_info())
        return {
            "status": "ok",
            "bot_initialized": _bot_initialized,
            "webhook_url": webhook_info.url,
            "pending_updates": webhook_info.pending_update_count,
            "last_error_message": webhook_info.last_error_message
        }, 200
    except Exception as e:
        logger.error(f"Errore nel recupero stato: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}, 500


@app.route('/webhook', methods=['POST'])
def webhook():
    """Gestisce gli aggiornamenti Telegram via webhook"""
    try:
        _ensure_bot_initialized()

        async def process():
            json_data = request.get_json(force=True)
            logger.info(f"Ricevuto update: {json_data}")
            update = Update.de_json(json_data, app_bot.bot)
            await app_bot.process_update(update)

        asyncio.run(process())
        return "ok", 200
    except Exception as e:
        logger.error(f"Errore durante il webhook: {e}", exc_info=True)
        return "error", 500


if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
