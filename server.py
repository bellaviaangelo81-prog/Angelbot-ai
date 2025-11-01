from flask import Flask, request
import os
import yfinance as yf
import matplotlib.pyplot as plt
from io import BytesIO
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import asyncio

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

# Shared event loop for async operations
_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)

# Initialize bot application (required in v20+)
async def _init_bot():
    """Initialize the bot application for webhook mode"""
    await app_bot.initialize()
    webhook_url = os.getenv("WEBHOOK_URL")
    if webhook_url:
        await app_bot.bot.set_webhook(url=webhook_url)
        print(f"✓ Webhook configured: {webhook_url}")
    else:
        print("⚠ WEBHOOK_URL not set - bot will not receive updates")

# Run bot initialization at startup (only if not already running)
if not app_bot.running:
    _loop.run_until_complete(_init_bot())

# --- FLASK WEBHOOK ---
@app.route('/')
def home():
    return "Bot finanziario attivo su Render!"

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook updates from Telegram"""
    async def process():
        json_data = request.get_json(force=True)
        update = Update.de_json(json_data, app_bot.bot)
        await app_bot.process_update(update)
    
    # Use the shared event loop
    _loop.run_until_complete(process())
    return "ok", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
