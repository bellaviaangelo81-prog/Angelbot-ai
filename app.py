from flask import Flask, request
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
import os
import yfinance as yf
import matplotlib.pyplot as plt
import pandas as pd
import io

app_flask = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://angelbot-ai.onrender.com")

app_telegram = Application.builder().token(TELEGRAM_TOKEN).build()

# ───────────────────────────────────────────────
# Lista titoli principali (USA, Europa, Asia)
# ───────────────────────────────────────────────
TICKERS = {
    "🇺🇸 Stati Uniti": [
        ("AAPL / Apple", "AAPL"),
        ("AMZN / Amazon", "AMZN"),
        ("MSFT / Microsoft", "MSFT"),
        ("GOOGL / Alphabet", "GOOGL"),
        ("META / Meta", "META"),
        ("TSLA / Tesla", "TSLA"),
        ("NVDA / Nvidia", "NVDA"),
    ],
    "🇪🇺 Europa": [
        ("ISP / Intesa Sanpaolo", "ISP.MI"),
        ("BMPS / Monte dei Paschi", "BMPS.MI"),
        ("ENI / ENI", "ENI.MI"),
        ("LVMH / LVMH", "MC.PA"),
        ("AIR / Airbus", "AIR.PA"),
    ],
    "🇨🇳 Asia": [
        ("BIDU / Baidu", "BIDU"),
        ("BABA / Alibaba", "BABA"),
        ("SONY / Sony", "SONY"),
        ("TSM / Taiwan Semiconductor", "TSM"),
    ]
}

# Frequenze disponibili
FREQUENZE = [
    ("🕐 30 minuti", 30),
    ("🕓 60 minuti", 60),
    ("🕕 120 minuti", 120),
    ("☀️ Giornaliero", 1440),
    ("📅 Settimanale", 10080),
    ("❌ Off", 0)
]

# Stato utente temporaneo
user_state = {}


# ───────────────────────────────────────────────
# Funzioni principali Telegram
# ───────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📈 Analisi Titoli", callback_data="analisi")],
        [InlineKeyboardButton("📊 Monitoraggio", callback_data="monitoraggio")],
        [InlineKeyboardButton("💬 Consigli automatici", callback_data="consigli")]
    ]
    await update.message.reply_text(
        "Ciao! Sono il tuo consulente AI finanziario.\n"
        "Scegli un'opzione:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def analisi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    for regione, lista in TICKERS.items():
        buttons = [InlineKeyboardButton(regione, callback_data=f"regione_{regione}")]
        keyboard.append(buttons)
    await update.callback_query.message.reply_text(
        "Scegli una regione:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def mostra_titoli(update: Update, context: ContextTypes.DEFAULT_TYPE, regione):
    titoli = TICKERS[regione]
    keyboard = [
        [InlineKeyboardButton(nome, callback_data=f"titolo_{symbol}")]
        for nome, symbol in titoli
    ]
    await update.callback_query.message.reply_text(
        f"Titoli disponibili in {regione}:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def mostra_grafico(update: Update, context: ContextTypes.DEFAULT_TYPE, symbol):
    data = yf.download(symbol, period="6mo", interval="1d")
    plt.figure()
    data["Close"].plot(title=symbol)
    plt.xlabel("Data")
    plt.ylabel("Prezzo ($)")
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    plt.close()
    await update.callback_query.message.reply_photo(buf)
    await update.callback_query.message.reply_text(
        f"📊 Analisi per {symbol}: Ultimo prezzo {round(data['Close'][-1], 2)} USD."
    )


async def monitoraggio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"freq_{minuti}")]
        for label, minuti in FREQUENZE
    ]
    await update.callback_query.message.reply_text(
        "Seleziona la frequenza di monitoraggio:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ───────────────────────────────────────────────
# Gestione callback
# ───────────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data.startswith("regione_"):
        regione = data.replace("regione_", "")
        await mostra_titoli(update, context, regione)

    elif data.startswith("titolo_"):
        symbol = data.replace("titolo_", "")
        await mostra_grafico(update, context, symbol)

    elif data == "analisi":
        await analisi(update, context)

    elif data == "monitoraggio":
        await monitoraggio(update, context)

    elif data.startswith("freq_"):
        minuti = int(data.replace("freq_", ""))
        user_state[update.effective_user.id] = minuti
        testo = (
            f"✅ Frequenza impostata su {minuti} minuti."
            if minuti > 0
            else "🔕 Monitoraggio disattivato."
        )
        await query.message.reply_text(testo)


# ───────────────────────────────────────────────
# Flask webhook
# ───────────────────────────────────────────────
@app_flask.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, app_telegram.bot)
    app_telegram.update_queue.put_nowait(update)
    return "OK", 200


# ───────────────────────────────────────────────
# Avvio bot
# ───────────────────────────────────────────────
def main():
    app_telegram.add_handler(CommandHandler("start", start))
    app_telegram.add_handler(CallbackQueryHandler(button_handler))

    app_telegram.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 10000)),
        webhook_url=f"{WEBHOOK_URL}/webhook"
    )


if __name__ == "__main__":
    main()
