#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# app.py — AngelBot AI (bot Telegram + Flask webhook)
# Funzionalità:
# - menu interattivo per regioni/titoli
# - ricerca per nome/simbolo
# - watchlist per utente (sqlite)
# - monitoraggio con frequenze (30m, 60m, 120m, giornaliero, settimanale, off)
# - analisi testuale + grafico generato con matplotlib
# - messaggi in italiano

import os
import logging
import sqlite3
import asyncio
from io import BytesIO
from datetime import datetime

import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# ----------------- CONFIG -----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("angelbot")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # es: https://angelbot-ai.onrender.com
OWNER_ID = int(os.getenv("OWNER_ID", "0"))  # opzionale: tuo id telegram

if not TELEGRAM_TOKEN:
    raise RuntimeError("Devi impostare TELEGRAM_TOKEN nelle env vars")

app = Flask(__name__)

# ----------------- DB (sqlite) -----------------
DB_PATH = os.path.join(os.getcwd(), "angelbot.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        chat_id INTEGER PRIMARY KEY
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS watchlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        symbol TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        chat_id INTEGER PRIMARY KEY,
        interval_minutes INTEGER
    )""")
    conn.commit()
    conn.close()

def db_execute(query, params=(), fetch=False):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(query, params)
    if fetch:
        rows = cur.fetchall()
        conn.close()
        return rows
    conn.commit()
    conn.close()
    return None

init_db()

# ----------------- TICKERS DB (per region) -----------------
TICKERS_BY_REGION = {
    "USA": {
        "AAPL": "Apple Inc.",
        "MSFT": "Microsoft Corporation",
        "AMZN": "Amazon.com, Inc.",
        "GOOGL": "Alphabet Inc.",
        "TSLA": "Tesla, Inc.",
        "NVDA": "NVIDIA Corporation",
        "META": "Meta Platforms, Inc.",
        "BRK-B": "Berkshire Hathaway",
        "JPM": "JPMorgan Chase & Co.",
        "XOM": "Exxon Mobil Corporation",
        "BIDU": "Baidu Inc."
    },
    "Europa": {
        "BMPS.MI": "Banca Monte dei Paschi di Siena",
        "ISP.MI": "Intesa Sanpaolo",
        "ENI.MI": "ENI S.p.A.",
        "LUX.MI": "EssilorLuxottica",
        "RACE.MI": "Ferrari N.V.",
        "BMW.DE": "BMW AG",
        "VOW3.DE": "Volkswagen AG",
        "AIR.PA": "Airbus SE",
        "SAN.PA": "Sanofi",
        "AZN.L": "AstraZeneca"
    },
    "Asia": {
        "SONY": "Sony Group Corporation",
        "7203.T": "Toyota Motor Corporation",
        "BABA": "Alibaba Group Holding Ltd",
        "BIDU": "Baidu, Inc.",
        "TCEHY": "Tencent Holdings Ltd",
        "005930.KS": "Samsung Electronics",
        "TSM": "Taiwan Semiconductor Manufacturing Company",
        "9984.T": "SoftBank Group Corp.",
        "1211.HK": "BYD Company Limited"
    },
    "Africa": {},
    "Oceania": {},
    "America Latina": {}
}

REGION_FLAGS = {
    "USA": "🇺🇸",
    "Europa": "🇪🇺",
    "Asia": "🇯🇵",
    "Africa": "🌍",
    "Oceania": "🇦🇺",
    "America Latina": "🌎"
}

# ----------------- Helper functions -----------------
def add_user_if_missing(chat_id: int):
    db_execute("INSERT OR IGNORE INTO users(chat_id) VALUES(?)", (chat_id,))

def add_symbol(chat_id: int, symbol: str):
    add_user_if_missing(chat_id)
    db_execute("INSERT INTO watchlist(chat_id,symbol) SELECT ?,? WHERE NOT EXISTS(SELECT 1 FROM watchlist WHERE chat_id=? AND symbol=?)",
               (chat_id, symbol, chat_id, symbol))

def remove_symbol(chat_id: int, symbol: str):
    db_execute("DELETE FROM watchlist WHERE chat_id=? AND symbol=?", (chat_id, symbol))

def get_watchlist(chat_id: int):
    rows = db_execute("SELECT symbol FROM watchlist WHERE chat_id=?", (chat_id,), fetch=True)
    return [r[0] for r in rows] if rows else []

def set_interval(chat_id: int, minutes: int or None):
    add_user_if_missing(chat_id)
    if minutes is None:
        db_execute("DELETE FROM settings WHERE chat_id=?", (chat_id,))
    else:
        db_execute("INSERT OR REPLACE INTO settings(chat_id,interval_minutes) VALUES(?,?)", (chat_id, minutes))

def get_interval(chat_id: int):
    rows = db_execute("SELECT interval_minutes FROM settings WHERE chat_id=?", (chat_id,), fetch=True)
    return rows[0][0] if rows else None

# ----------------- Analysis & plotting -----------------
def safe_ticker_info(ticker):
    try:
        return ticker.info or {}
    except Exception:
        return {}

def generate_consultant_analysis(symbol: str, days: int = 30):
    """
    Returns (text_analysis, png_buffer)
    - text is in Italian, consultant tone
    - png_buffer is BytesIO of the plot (last `days`)
    """
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=f"{max(days,7)}d")
        info = safe_ticker_info(ticker)
        name = info.get("shortName", symbol)
        if df is None or df.empty:
            text = f"⚠️ Non sono disponibili dati storici per {symbol}."
            return text, None

        close = df["Close"].dropna()
        latest = close.iloc[-1]
        first = close.iloc[0]
        pct_change = (latest - first) / first * 100
        window = min(7, len(close))
        pct_7 = (latest - close.iloc[-window]) / close.iloc[-window] * 100 if len(close) >= window else 0
        sma7 = close.rolling(window=7).mean().iloc[-1] if len(close) >= 7 else None
        sma30 = close.rolling(window=30).mean().iloc[-1] if len(close) >= 30 else None

        parts = [f"📊 Analisi per {name} ({symbol})", f"Prezzo attuale: {latest:.2f}$"]
        parts.append(f"Variazione ultimi {len(close)} giorni: {pct_change:.2f}%")
        parts.append(f"Variazione breve (ultimi {window} giorni): {pct_7:.2f}%")

        if sma30 and latest > sma30:
            parts.append("Trend di medio periodo: rialzista.")
        elif sma30 and latest < sma30:
            parts.append("Trend di medio periodo: ribassista.")
        else:
            parts.append("Trend: neutro / dati insufficienti per giudizio netto.")

        if pct_7 <= -10:
            advice = "Il titolo ha accusato una correzione significativa: potrebbe rappresentare un'opportunità, valuta rischio e fondamentali."
            sentiment = "📉 sconsigliato a ingresso aggressivo"
        elif pct_7 <= -5:
            advice = "Correzione moderata: valutare ingresso frazionato se i fondamentali reggono."
            sentiment = "⚖️ neutro / opportunità"
        elif pct_7 >= 10:
            advice = "Forte salita recente: attenzione a possibili ritracciamenti."
            sentiment = "📈 possibile momentum ma con rischio"
        else:
            advice = "Situazione stabile: osservare livelli chiave e i volumi."
            sentiment = "⚖️ neutro"

        parts.append(f"Consulente: {advice}")
        parts.append(f"Sentiment sintetico: {sentiment}")

        text = "\n".join(parts)

        plt.figure(figsize=(10,4))
        ax = plt.gca()
        close.plot(ax=ax, label="Close")
        if len(close) >= 7:
            close.rolling(7).mean().plot(ax=ax, label="SMA7")
        if len(close) >= 30:
            close.rolling(30).mean().plot(ax=ax, label="SMA30")
        ax.set_title(f"{symbol} — ultimi {days} giorni")
        ax.set_ylabel("Prezzo")
        ax.legend()
        buf = BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format="png")
        plt.close()
        buf.seek(0)
        return text, buf

    except Exception as e:
        logger.exception("generate_consultant_analysis error")
        return f"Errore nella generazione dell'analisi per {symbol}: {e}", None

# ----------------- Telegram bot & Handlers -----------------
application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

# Start
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    add_user_if_missing(chat_id)
    keyboard = [
        [InlineKeyboardButton("📊 Monitoraggio", callback_data="menu_monitor")],
        [InlineKeyboardButton("🔎 Scegli/cerchi titoli", callback_data="menu_scegli")],
        [InlineKeyboardButton("📋 La mia watchlist", callback_data="menu_watchlist")],
        [InlineKeyboardButton("ℹ️ Info /help", callback_data="menu_help")]
    ]
    reply = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Ciao — sono il tuo consulente finanziario virtuale. Scegli un'opzione:", reply_markup=reply
    )

# Help
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Comandi rapidi:\n"
        "/start — menu principale\n"
        "/scegli_titoli — aggiungi titoli (ricerca)\n"
        "/watchlist — mostra titoli che segui\n"
        "/monitoraggio — imposta frequenza monitoraggio\n"
        "/analizza <SIMBOLO> — analisi testuale + grafico immediato\n"
    )

# Analizza manuale
async def cmd_analizza(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /analizza <SIMBOLO> (es. /analizza AMZN)")
        return
    symbol = context.args[0].upper()
    text, buf = await asyncio.get_event_loop().run_in_executor(None, generate_consultant_analysis, symbol, 30)
    if buf:
        await update.message.reply_photo(photo=buf, caption=text)
    else:
        await update.message.reply_text(text)

# Show watchlist
async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    symbols = get_watchlist(chat_id)
    if not symbols:
        await update.message.reply_text("La tua watchlist è vuota. Aggiungi titoli con /scegli_titoli")
        return
    await update.message.reply_text("I tuoi titoli:\n" + "\n".join(symbols))

# Menu callback
async def callback_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_monitor" or data == "monitor_from_start":
        keyboard = [
            [InlineKeyboardButton("🕧 30 minuti", callback_data="freq_30")],
            [InlineKeyboardButton("🕐 60 minuti", callback_data="freq_60")],
            [InlineKeyboardButton("🕑 120 minuti", callback_data="freq_120")],
            [InlineKeyboardButton("🌅 Giornaliero", callback_data="freq_day")],
            [InlineKeyboardButton("📆 Settimanale", callback_data="freq_week")],
            [InlineKeyboardButton("🚫 Disattiva monitoraggio", callback_data="freq_off")],
            [InlineKeyboardButton("⬅️ Indietro", callback_data="back_main")]
        ]
        await query.edit_message_text("📊 Seleziona la frequenza del monitoraggio (verranno inviati analisi + grafico per ogni titolo della tua watchlist):", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "menu_scegli":
        keyboard = []
        for region, flag in [("USA","🇺🇸"),("Europa","🇪🇺"),("Asia","🇯🇵"),("Africa","🌍"),("Oceania","🇦🇺"),("America Latina","🌎")]:
            keyboard.append([InlineKeyboardButton(f"{flag} {region}", callback_data=f"region_{region}")])
        keyboard.append([InlineKeyboardButton("🔍 Cerca per nome/simbolo", callback_data="search_prompt")])
        keyboard.append([InlineKeyboardButton("⬅️ Indietro", callback_data="back_main")])
        await query.edit_message_text("🌍 Seleziona una regione o cerca un titolo:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # Show watchlist
    if data == "menu_watchlist":
        chat_id = query.message.chat_id
        symbols = get_watchlist(chat_id)
        if not symbols:
            await query.edit_message_text("La tua watchlist è vuota.")
            return
        keyboard = []
        for s in symbols:
            keyboard.append([InlineKeyboardButton(f"Rimuovi {s}", callback_data=f"rm_{s}")])
        keyboard.append([InlineKeyboardButton("⬅️ Indietro", callback_data="back_main")])
        await query.edit_message_text("La tua watchlist (clicca per rimuovere):", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "menu_help":
        await query.edit_message_text("Usa /analizza <SIMBOLO> per un'analisi rapida. Usa /scegli_titoli per aggiungere titoli. Usa /monitoraggio per attivare notifiche.")
        return

    if data == "back_main":
        keyboard = [
            [InlineKeyboardButton("📊 Monitoraggio", callback_data="menu_monitor")],
            [InlineKeyboardButton("🔎 Scegli/cerchi titoli", callback_data="menu_scegli")],
            [InlineKeyboardButton("📋 La mia watchlist", callback_data="menu_watchlist")],
            [InlineKeyboardButton("ℹ️ Info /help", callback_data="menu_help")]
        ]
        await query.edit_message_text("Torna al menu principale:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("region_"):
        region = data.split("_",1)[1]
        symbols = []
        for sym, info in TICKERS_BY_REGION.items():
            pass  # placeholder for clarity (we'll use mapping below)
        # collect symbols for region
        region_symbols = TICKERS_BY_REGION.get(region, {})
        keyboard = []
        for sym, name in region_symbols.items():
            keyboard.append([InlineKeyboardButton(f"{sym} / {name}", callback_data=f"add_{sym}")])
        keyboard.append([InlineKeyboardButton("⬅️ Indietro", callback_data="menu_scegli")])
        if not keyboard:
            keyboard = [[InlineKeyboardButton("⬅️ Indietro", callback_data="menu_scegli")]]
        await query.edit_message_text(f"{REGION_FLAGS.get(region,'')} {region} — Titoli principali:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "search_prompt":
        chat_id = query.message.chat_id
        # set in-memory state for next message
        # we will handle search via MessageHandler and check context.user_data
        context.user_data["awaiting_search"] = True
        await query.edit_message_text("🔎 Scrivi il nome o simbolo del titolo che cerchi (es. 'Amazon' o 'AMZN').")
        return

    if data.startswith("add_"):
        sym = data.split("_",1)[1]
        chat_id = query.message.chat_id
        add_symbol(chat_id, sym)
        await query.edit_message_text(f"✅ {sym} aggiunto alla tua watchlist.")
        return

    if data.startswith("rm_"):
        sym = data.split("_",1)[1]
        chat_id = query.message.chat_id
        remove_symbol(chat_id, sym)
        await query.edit_message_text(f"❌ {sym} rimosso dalla tua watchlist.")
        return

    if data.startswith("freq_"):
        chat_id = query.message.chat_id
        mapping = {
            "freq_30": 30,
            "freq_60": 60,
            "freq_120": 120,
            "freq_day": 60*24,
            "freq_week": 60*24*7
        }
        if data == "freq_off":
            set_interval(chat_id, None)
            # remove job if exists
            job_name = f"monitor_{chat_id}"
            for job in context.job_queue.get_jobs_by_name(job_name):
                job.schedule_removal()
            await query.edit_message_text("🛑 Monitoraggio disattivato.")
            return

        minutes = mapping.get(data)
        set_interval(chat_id, minutes)
        # reschedule job: remove existing
        job_name = f"monitor_{chat_id}"
        for job in context.job_queue.get_jobs_by_name(job_name):
            job.schedule_removal()

        async def monitor_job(ctx: ContextTypes.DEFAULT_TYPE):
            symbols = get_watchlist(chat_id)
            if not symbols:
                try:
                    await ctx.bot.send_message(chat_id=chat_id, text="La tua watchlist è vuota: usa /scegli_titoli per aggiungere titoli.")
                except Exception:
                    pass
                return
            for s in symbols:
                text, buf = await asyncio.get_event_loop().run_in_executor(None, generate_consultant_analysis, s, 30)
                try:
                    if buf:
                        await ctx.bot.send_photo(chat_id=chat_id, photo=buf, caption=text)
                    else:
                        await ctx.bot.send_message(chat_id=chat_id, text=text)
                except Exception:
                    pass

        context.job_queue.run_repeating(monitor_job, interval=minutes*60, first=5, name=job_name)
        await query.edit_message_text(f"✅ Monitoraggio impostato ogni {minutes} minuti. Ti invierò analisi + grafico per ogni titolo della tua watchlist.")
        return

    await query.edit_message_text("Comando non gestito.")

# Search message handler
async def handle_search_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # triggered when user wrote after selecting search prompt
    if not context.user_data.get("awaiting_search"):
        return
    query = update.message.text.strip().lower()
    context.user_data["awaiting_search"] = False
    results = []
    for region, mapping in TICKERS_BY_REGION.items():
        for sym, name in mapping.items():
            if query in sym.lower() or query in name.lower():
                results.append((region, sym, name))
    if not results:
        try:
            yf_res = yf.utils.get_json("https://query2.finance.yahoo.com/v1/finance/search?q=" + query)
            quotes = yf_res.get("quotes", [])[:6]
            for q in quotes:
                sym = q.get("symbol")
                name = q.get("shortname") or q.get("longname") or q.get("symbol")
                results.append(("Unknown", sym, name))
        except Exception:
            pass

    if not results:
        await update.message.reply_text("Nessun titolo trovato — prova un'altra ricerca.")
        return

    keyboard = []
    for region, sym, name in results[:10]:
        keyboard.append([InlineKeyboardButton(f"{sym} / {name}", callback_data=f"add_{sym}")])
    await update.message.reply_text("Seleziona il titolo da aggiungere:", reply_markup=InlineKeyboardMarkup(keyboard))

# Register handlers
application.add_handler(CommandHandler("start", cmd_start))
application.add_handler(CommandHandler("help", cmd_help))
application.add_handler(CommandHandler("analizza", cmd_analizza))
application.add_handler(CommandHandler("watchlist", cmd_watchlist))
application.add_handler(CommandHandler("scegli_titoli", lambda u,c: callback_menu(u,c)))
application.add_handler(CommandHandler("monitoraggio", lambda u,c: callback_menu(u,c)))
application.add_handler(CallbackQueryHandler(callback_menu))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search_message))

# Flask webhook endpoints
@app.route("/")
def home():
    return "✅ AngelBot-AI: servizio attivo"

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, application.bot)
        asyncio.run(application.process_update(update))
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("webhook error")
        return jsonify({"ok": False, "error": str(e)}), 500

# ----------------- Startup -----------------
if __name__ == "__main__":
    # set webhook if provided
    if WEBHOOK_URL:
        try:
            asyncio.run(application.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook"))
            logger.info("Webhook impostato su %s/webhook", WEBHOOK_URL)
        except Exception:
            logger.exception("Errore impostazione webhook")
    # run flask
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
