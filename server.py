from flask import Flask, request
import os
import yfinance as yf
import matplotlib
matplotlib.use('Agg')  # Use non-GUI backend for server deployment
import matplotlib.pyplot as plt
from io import BytesIO
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import asyncio
import logging

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- CONFIGURAZIONE ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
app = Flask(__name__)

# --- COMANDI DEL BOT ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📈 Benvenuto nel tuo assistente finanziario!\n\n"
        "Puoi usare i seguenti comandi:\n"
        "• /prezzo <simbolo> → Mostra il prezzo attuale (es. /prezzo TSLA)\n"
        "• /grafico <simbolo> → Mostra il grafico dell’ultimo mese (es. /grafico AAPL)\n"
        "• /info <simbolo> → Mostra informazioni sull’azienda\n\n"
        "Presto arriveranno anche alert automatici e analisi AI."
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

# --- AVVIO DEL BOT ---
# Initialize the Application with proper configuration
app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

# Add command handlers
app_bot.add_handler(CommandHandler("start", start))
app_bot.add_handler(CommandHandler("prezzo", prezzo))
app_bot.add_handler(CommandHandler("grafico", grafico))
app_bot.add_handler(CommandHandler("info", info))

# Bot initialization state
_bot_initialized = False
_init_lock = False

def _ensure_bot_initialized():
    """Lazy initialization of the bot application (called on first webhook request)"""
    global _bot_initialized, _init_lock
    
    # Simple lock to prevent concurrent initialization
    if _init_lock:
        import time
        for _ in range(50):  # Wait up to 5 seconds
            if _bot_initialized:
                return
            time.sleep(0.1)
        return
    
    if not _bot_initialized:
        _init_lock = True
        try:
            async def init():
                try:
                    await app_bot.initialize()
                    webhook_url = os.getenv("WEBHOOK_URL")
                    if webhook_url:
                        await app_bot.bot.set_webhook(url=webhook_url)
                        logger.info(f"✓ Webhook configured: {webhook_url}")
                    else:
                        logger.warning("⚠ WEBHOOK_URL not set - bot will not receive updates")
                except Exception as e:
                    logger.error(f"Error initializing bot: {e}", exc_info=True)
                    raise
            
            asyncio.run(init())
            _bot_initialized = True
            logger.info("✓ Bot initialized successfully")
        finally:
            _init_lock = False

# --- FLASK WEBHOOK ---
@app.route('/')
def home():
    return "Bot finanziario attivo su Render!"

@app.route('/health')
def health():
    """Simple health check endpoint"""
    return {"status": "healthy", "service": "telegram-bot"}, 200

@app.route('/status')
def status():
    """Check bot and webhook status"""
    try:
        _ensure_bot_initialized()
        webhook_info = asyncio.run(app_bot.bot.get_webhook_info())
        return {
            "status": "ok",
            "bot_initialized": _bot_initialized,
            "webhook_url": webhook_info.url,
            "pending_updates": webhook_info.pending_update_count,
            "last_error_date": str(webhook_info.last_error_date) if webhook_info.last_error_date else None,
            "last_error_message": webhook_info.last_error_message
        }, 200
    except Exception as e:
        logger.error(f"Error getting status: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}, 500

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook updates from Telegram"""
    try:
        # Ensure bot is initialized on first request
        _ensure_bot_initialized()
        
        # Get the JSON data
        json_data = request.get_json(force=True)
        logger.info(f"Received update from Telegram")
        
        async def process():
            update = Update.de_json(json_data, app_bot.bot)
            await app_bot.process_update(update)

        # Process the update - handle event loop carefully
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is running, create a new one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            loop.run_until_complete(process())
        except RuntimeError:
            # Fallback to asyncio.run if there are issues
            asyncio.run(process())
        
        return "ok", 200
    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        return "error", 500

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
