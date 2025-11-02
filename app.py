import os
import logging
import yfinance as yf
import matplotlib.pyplot as plt
import io
import schedule
import time
import threading
from flask import Flask, request
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    CallbackQueryHandler,
)
from openai import OpenAI

# === CONFIG ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)
app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === REGIONI E TITOLI ===
REGIONS = {
    "🇺🇸 Stati Uniti": ["AAPL / Apple", "MSFT / Microsoft", "AMZN / Amazon", "GOOGL / Alphabet", "META / Meta", "TSLA / Tesla"],
    "🇪🇺 Europa": ["ISP / Intesa Sanpaolo", "BMPS / Monte dei Paschi", "ENI / ENI", "LUX / Luxottica", "AIR / Airbus"],
    "🇨🇳 Asia": ["BIDU / Baidu", "TCEHY / Tencent", "BABA / Alibaba", "SONY / Sony"],
}

# === FREQUENZE MONITORAGGIO ===
FREQUENCIES = {
    "Ogni 30 minuti": 30,
    "Ogni ora": 60,
    "Ogni 6 ore": 360,
    "Giornaliero": 1440,
    "Settimanale": 10080,
    "Off": None
}

user_settings = {}  # {user_id: {"region": str, "symbol": str, "frequency": int}}

# === FUNZIONE CHAT AI ===
def chat_with_ai(message):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Sei un consulente finanziario AI esperto che parla in modo chiaro e realistico in italiano."},
                {"role": "user", "content": message},
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Errore nel contatto con l'AI: {e}"

# === FUNZIONE ANALISI TITOLI ===
def analyze_stock(symbol):
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1mo")

        if hist.empty:
            return None, "❌ Nessun dato disponibile per questo titolo."

        last_price = hist["Close"].iloc[-1]
        change = ((hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0]) * 100

        plt.figure(figsize=(6, 3))
        plt.plot(hist.index, hist["Close"], label=f"{symbol}", linewidth=2)
        plt.title(f"Andamento di {symbol}")
        plt.xlabel("Data")
        plt.ylabel("Prezzo ($)")
        plt.legend()

        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        buf.seek(0)
        plt.close()

        trend = "📈 in crescita" if change > 0 else "📉 in calo"
        analysis = f"{symbol} è {trend} ({change:.2f}%) nell’ultimo mese.\nPrezzo attuale: ${last_price:.2f}"

        return buf, analysis
    except Exception as e:
        return None, f"Errore durante l'analisi: {e}"

# === GESTIONE TELEGRAM ===
async def start(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("📊 Controlla titoli", callback_data="check_stocks")],
        [InlineKeyboardButton("💬 Parla con l'AI", callback_data="chat_ai")],
        [InlineKeyboardButton("⏱ Monitoraggio", callback_data="monitor")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Benvenuto nel tuo assistente finanziario AI! 💹", reply_markup=reply_markup)

async def button(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    if query.data == "check_stocks":
        keyboard = [[InlineKeyboardButton(region, callback_data=f"region_{region}")] for region in REGIONS]
        await query.message.reply_text("Seleziona una regione:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("region_"):
        region = query.data.split("_", 1)[1]
        keyboard = [
            [InlineKeyboardButton(symbol, callback_data=f"stock_{symbol.split('/')[0].strip()}")]
            for symbol in REGIONS[region]
        ]
        await query.message.reply_text("Scegli un titolo da analizzare:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("stock_"):
        symbol = query.data.split("_", 1)[1]
        buf, analysis = analyze_stock(symbol)
        if buf:
            await query.message.reply_photo(buf, caption=analysis)
        else:
            await query.message.reply_text(analysis)

    elif query.data == "chat_ai":
        await query.message.reply_text("Scrivimi una domanda o una richiesta finanziaria, e ti risponderò come consulente AI.")

    elif query.data == "monitor":
        keyboard = [[InlineKeyboardButton(name, callback_data=f"freq_{minutes}")] for name, minutes in FREQUENCIES.items()]
        await query.message.reply_text("Scegli la frequenza di monitoraggio:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("freq_"):
        user_id = query.from_user.id
        minutes = query.data.split("_", 1)[1]
        user_settings[user_id] = {"frequency": None if minutes == "None" else int(minutes)}
        await query.message.reply_text(f"⏱ Monitoraggio impostato su: {minutes} minuti.")

async def handle_message(update: Update, context: CallbackContext):
    text = update.message.text
    response = chat_with_ai(text)
    await update.message.reply_text(response)

# === FLASK ===
@app.route("/")
def index():
    return "Bot AI operativo!"

# === AVVIO ===
def start_bot():
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.run_polling()

threading.Thread(target=start_bot).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
