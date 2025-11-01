import os
import logging
from flask import Flask
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)
import yfinance as yf

# --- CONFIGURAZIONE ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# --- FLASK APP PER RENDER ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot AI Finanziario attivo ✅"

# --- BOT TELEGRAM ---
logging.basicConfig(level=logging.INFO)

# Dizionario titoli per regione
STOCKS = {
    "🇺🇸 Stati Uniti": {
        "AAPL / Apple": "AAPL",
        "MSFT / Microsoft": "MSFT",
        "AMZN / Amazon": "AMZN",
        "GOOG / Alphabet": "GOOG",
        "TSLA / Tesla": "TSLA",
        "META / Meta Platforms": "META"
    },
    "🇪🇺 Europa": {
        "ISP / Intesa Sanpaolo": "ISP.MI",
        "BMPS / Monte dei Paschi di Siena": "BMPS.MI",
        "ENI / Eni": "ENI.MI",
        "LUX / Luxottica": "LUX.MI",
        "RACE / Ferrari": "RACE.MI"
    },
    "🇨🇳 Asia": {
        "BIDU / Baidu": "BIDU",
        "BABA / Alibaba": "BABA",
        "TSM / Taiwan Semiconductor": "TSM",
        "SONY / Sony": "SONY",
        "NTDOY / Nintendo": "NTDOY"
    }
}

FREQUENZE = {
    "30 minuti": 30,
    "60 minuti": 60,
    "120 minuti": 120,
    "Giornaliero": 1440,
    "Settimanale": 10080,
    "Off": 0
}

# --- FUNZIONE DATI FINANZIARI ---
def get_stock_data(symbol):
    try:
        stock = yf.Ticker(symbol)
        info = stock.info
        price = info.get("regularMarketPrice")
        prev = info.get("regularMarketPreviousClose")
        if not price or not prev:
            return None
        change = ((price - prev) / prev) * 100
        trend = "📈" if change > 0 else "📉"
        suggestion = "Consigliato l’acquisto ✅" if change > 0 else "Meglio attendere ⏳"
        return f"💼 {symbol}\n💰 Prezzo attuale: {price}$\n📊 Variazione: {change:.2f}% {trend}\n💡 {suggestion}"
    except Exception as e:
        logging.error(f"Errore dati per {symbol}: {e}")
        return None

# --- HANDLER ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 Controlla titoli", callback_data="controlla_titoli")],
        [InlineKeyboardButton("🕓 Imposta monitoraggio", callback_data="imposta_monitoraggio")]
    ]
    await update.message.reply_text(
        "Benvenuto nel tuo assistente finanziario AI! 💹",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def menu_principale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "controlla_titoli":
        region_buttons = [[InlineKeyboardButton(region, callback_data=f"regione_{region}")] for region in STOCKS.keys()]
        await query.message.reply_text("Seleziona una regione:", reply_markup=InlineKeyboardMarkup(region_buttons))

    elif query.data == "imposta_monitoraggio":
        freq_buttons = [[InlineKeyboardButton(name, callback_data=f"freq_{value}")] for name, value in FREQUENZE.items()]
        await query.message.reply_text("Imposta la frequenza di monitoraggio:", reply_markup=InlineKeyboardMarkup(freq_buttons))

async def seleziona_titolo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    regione = query.data.replace("regione_", "")
    stocks = STOCKS.get(regione, {})
    titolo_buttons = [[InlineKeyboardButton(nome, callback_data=f"titolo_{simbolo}")] for nome, simbolo in stocks.items()]
    await query.message.reply_text("Scegli un titolo da analizzare:", reply_markup=InlineKeyboardMarkup(titolo_buttons))

async def analizza_titolo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    symbol = query.data.replace("titolo_", "")
    data = get_stock_data(symbol)
    if data:
        await query.message.reply_text(data)
    else:
        await query.message.reply_text("❌ Nessun dato disponibile per questo titolo.")

async def imposta_frequenza(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    freq_value = query.data.replace("freq_", "")
    await query.message.reply_text(f"🔔 Frequenza di monitoraggio impostata su {freq_value} minuti.")

# --- AVVIO BOT ---
if __name__ == "__main__":
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(menu_principale, pattern="^controlla_titoli|imposta_monitoraggio$"))
    application.add_handler(CallbackQueryHandler(seleziona_titolo, pattern="^regione_"))
    application.add_handler(CallbackQueryHandler(analizza_titolo, pattern="^titolo_"))
    application.add_handler(CallbackQueryHandler(imposta_frequenza, pattern="^freq_"))

    # Avvio bot
    application.run_polling()
