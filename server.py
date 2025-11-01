# server.py
import os
import logging
import sqlite3
import json
import asyncio
from io import BytesIO
from functools import partial
from typing import Optional

import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import requests

from flask import Flask, request, jsonify

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# -------------------------
# Config & logging
# -------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("angelbot")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g. https://angelbot-ai.onrender.com
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", None)

if not TELEGRAM_TOKEN:
    raise RuntimeError("Devi impostare TELEGRAM_TOKEN nelle environment variables")

app = Flask(__name__)

# -------------------------
# Persistence (SQLite)
# -------------------------
DB_PATH = os.path.join(os.getcwd(), "angelbot.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        threshold REAL NOT NULL,
        direction TEXT NOT NULL, -- 'below' or 'above'
        chat_id INTEGER
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS portfolio (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        symbol TEXT,
        quantity REAL,
        avg_price REAL
    )
    """)
    conn.commit()
    conn.close()

init_db()

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

# -------------------------
# Telegram bot (Application)
# -------------------------
application = Application.builder().token(TELEGRAM_TOKEN).build()
_bot_initialized = False

async def ensure_initialized():
    global _bot_initialized
    if _bot_initialized:
        return
    try:
        await application.initialize()
        if WEBHOOK_URL:
            # set webhook to WEBHOOK_URL + /webhook
            await application.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
            logger.info(f"Webhook impostato su {WEBHOOK_URL}/webhook")
        else:
            logger.warning("WEBHOOK_URL non impostato; webhook non verrà impostato automaticamente")
        _bot_initialized = True
    except Exception as e:
        logger.exception("Errore inizializzazione bot")
        raise

# -------------------------
# Utilities (non-blocking wrappers)
# -------------------------
loop = asyncio.get_event_loop()

def run_blocking(func, *args, **kwargs):
    return loop.run_in_executor(None, partial(func, *args, **kwargs))

# -------------------------
# Finance helpers
# -------------------------
def get_price_sync(symbol: str) -> Optional[float]:
    t = yf.Ticker(symbol)
    info = t.info
    return info.get("currentPrice") or info.get("regularMarketPrice")

def get_history_sync(symbol: str, period="1mo"):
    t = yf.Ticker(symbol)
    return t.history(period=period)

async def get_price(symbol):
    return await run_blocking(get_price_sync, symbol)

async def get_history(symbol, period="1mo"):
    return await run_blocking(get_history_sync, symbol, period)

def plot_history(dframe: pd.DataFrame, symbol: str) -> BytesIO:
    plt.figure(figsize=(8,4))
    dframe["Close"].plot(title=f"{symbol} - last month")
    plt.xlabel("Date")
    plt.ylabel("Price")
    buf = BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png")
    buf.seek(0)
    plt.close()
    return buf

# -------------------------
# AI helper (OpenAI)
# -------------------------
def openai_query(prompt: str) -> Optional[str]:
    if not OPENAI_API_KEY:
        return None
    try:
        # Use OpenAI simple completion for example (adjust to your API)
        import openai
        openai.api_key = OPENAI_API_KEY
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",  # replace with available model in your account
            messages=[{"role":"user","content":prompt}],
            max_tokens=400
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.exception("OpenAI error")
        return None

# -------------------------
# Commands
# -------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None:
        return
    text = ("Ciao! Sono AngelBot-AI 🤖\n"
            "Comandi principali:\n"
            "/prezzo <SIMBOLO>\n"
            "/grafico <SIMBOLO>\n"
            "/info <SIMBOLO>\n"
            "/set_alert <SIMBOLO> <soglia> <below|above>\n"
            "/list_alerts\n"
            "/remove_alert <id>\n"
            "/portfolio add <SIMBOLO> <qty> <avg_price>\n"
            "/portfolio list\n"
            "/ai <domanda>  (richiede OPENAI_API_KEY)\n")
    await update.message.reply_text(text)

async def cmd_prezzo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usa: /prezzo <SIMBOLO>")
        return
    symbol = context.args[0].upper()
    try:
        price = await get_price(symbol)
        if price is None:
            await update.message.reply_text("Prezzo non disponibile.")
        else:
            await update.message.reply_text(f"{symbol}: {price}$")
    except Exception as e:
        logger.exception("prezzo error")
        await update.message.reply_text("Errore nel recupero prezzo.")

async def cmd_grafico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usa: /grafico <SIMBOLO>")
        return
    symbol = context.args[0].upper()
    try:
        df = await run_blocking(get_history_sync, symbol, "1mo")
        if df.empty:
            await update.message.reply_text("Dati non trovati per questo simbolo.")
            return
        buf = await run_blocking(plot_history, df, symbol)
        await update.message.reply_photo(buf)
    except Exception as e:
        logger.exception("grafico error")
        await update.message.reply_text("Errore generazione grafico.")

async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usa: /info <SIMBOLO>")
        return
    symbol = context.args[0].upper()
    try:
        info = await run_blocking(lambda s: yf.Ticker(s).info, symbol)
        name = info.get("shortName", symbol)
        sector = info.get("sector", "N/D")
        country = info.get("country", "N/D")
        cap = info.get("marketCap", "N/D")
        await update.message.reply_text(f"📊 {name} ({symbol})\nSettore: {sector}\nPaese: {country}\nMarketCap: {cap}")
    except Exception:
        await update.message.reply_text("Errore nel recupero delle info.")

# Alerts: add/list/remove
async def cmd_set_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text("Usa: /set_alert <SIMBOLO> <soglia> <below|above>")
        return
    symbol = context.args[0].upper()
    try:
        threshold = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Soglia non valida")
        return
    direction = context.args[2].lower()
    if direction not in ("below","above"):
        await update.message.reply_text("Direction deve essere 'below' o 'above'")
        return
    chat_id = update.effective_chat.id
    db_execute("INSERT INTO alerts(symbol,threshold,direction,chat_id) VALUES(?,?,?,?)",
               (symbol, threshold, direction, chat_id))
    await update.message.reply_text(f"Alert impostato: {symbol} {direction} {threshold}$")

async def cmd_list_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db_execute("SELECT id,symbol,threshold,direction FROM alerts WHERE chat_id=?",(update.effective_chat.id,), fetch=True)
    if not rows:
        await update.message.reply_text("Nessun alert impostato.")
        return
    text = "\n".join([f"{r[0]} - {r[1]} {r[3]} {r[2]}$" for r in rows])
    await update.message.reply_text(text)

async def cmd_remove_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usa: /remove_alert <id>")
        return
    try:
        aid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Id non valido")
        return
    db_execute("DELETE FROM alerts WHERE id=? AND chat_id=?", (aid, update.effective_chat.id))
    await update.message.reply_text("Alert rimosso (se esisteva).")

# Portfolio
async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usa: /portfolio add <SIMBOLO> <qty> <avg_price>  oppure /portfolio list")
        return
    sub = context.args[0].lower()
    if sub == "add" and len(context.args) >= 4:
        symbol = context.args[1].upper()
        try:
            qty = float(context.args[2])
            avg = float(context.args[3])
        except ValueError:
            await update.message.reply_text("qty o avg_price non validi")
            return
        db_execute("INSERT INTO portfolio(chat_id,symbol,quantity,avg_price) VALUES(?,?,?,?)",
                   (update.effective_chat.id, symbol, qty, avg))
        await update.message.reply_text("Posizione aggiunta.")
    elif sub == "list":
        rows = db_execute("SELECT symbol,quantity,avg_price FROM portfolio WHERE chat_id=?", (update.effective_chat.id,), fetch=True)
        if not rows:
            await update.message.reply_text("Portafoglio vuoto.")
            return
        lines = []
        for r in rows:
            lines.append(f"{r[0]} — qty: {r[1]} — avg: {r[2]}$")
        await update.message.reply_text("\n".join(lines))
    else:
        await update.message.reply_text("Comando portfolio non riconosciuto.")

# AI command
async def cmd_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not OPENAI_API_KEY:
        await update.message.reply_text("OpenAI non configurato.")
        return
    prompt = " ".join(context.args) if context.args else (update.message.reply_text("Usa: /ai <domanda>") or "")
    if not prompt:
        return
    await update.message.reply_text("Sto chiamando l'AI... attendi.")
    resp = await run_blocking(openai_query, prompt)
    if resp:
        await update.message.reply_text(resp)
    else:
        await update.message.reply_text("Errore o nessuna risposta da OpenAI.")

# Simple echo (dev)
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # optional: restrict to owner
    if update.effective_user and update.effective_user.id != OWNER_ID:
        return
    if update.message and update.message.text:
        await update.message.reply_text("Hai detto: " + update.message.text)

# Register handlers
application.add_handler(CommandHandler("start", cmd_start))
application.add_handler(CommandHandler("prezzo", cmd_prezzo))
application.add_handler(CommandHandler("grafico", cmd_grafico))
application.add_handler(CommandHandler("info", cmd_info))
application.add_handler(CommandHandler("set_alert", cmd_set_alert))
application.add_handler(CommandHandler("list_alerts", cmd_list_alerts))
application.add_handler(CommandHandler("remove_alert", cmd_remove_alert))
application.add_handler(CommandHandler("portfolio", cmd_portfolio))
application.add_handler(CommandHandler("ai", cmd_ai))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

# -------------------------
# Background tasks (alerts)
# -------------------------
ALERT_POLL_INTERVAL = int(os.getenv("ALERT_CHECK_INTERVAL", "60"))  # seconds

async def alert_worker():
    logger.info("Alert worker started")
    while True:
        try:
            rows = db_execute("SELECT id,symbol,threshold,direction,chat_id FROM alerts", fetch=True)
            if rows:
                for r in rows:
                    aid, sym, thr, dirc, chat_id = r
                    price = await get_price(sym)
                    if price is None:
                        continue
                    if dirc == "below" and price <= thr:
                        await application.bot.send_message(chat_id=chat_id, text=f"⚠️ ALERT: {sym} è sceso a {price}$ (soglia {thr})")
                        # optionally delete one-shot alert
                        # db_execute("DELETE FROM alerts WHERE id=?", (aid,))
                    if dirc == "above" and price >= thr:
                        await application.bot.send_message(chat_id=chat_id, text=f"⚠️ ALERT: {sym} è salito a {price}$ (soglia {thr})")
            await asyncio.sleep(ALERT_POLL_INTERVAL)
        except Exception:
            logger.exception("alert_worker errore, riprovo tra poco")
            await asyncio.sleep(10)

# -------------------------
# Flask webhook endpoints
# -------------------------
@app.route("/")
def home():
    return "✅ AngelBot-AI attivo!"

@app.route("/status")
def status():
    try:
        initialized = _bot_initialized
        return jsonify({"status":"running","bot_initialized": initialized}), 200
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        # ensure initialized
        asyncio.run(ensure_initialized())
        json_data = request.get_json(force=True)
        logger.info("Update ricevuto: %s", json_data)
        update = Update.de_json(json_data, application.bot)
        asyncio.run(application.process_update(update))
        return "ok", 200
    except Exception as e:
        logger.exception("Errore webhook")
        return "error", 500

# -------------------------
# Startup block (only when run directly)
# -------------------------
if __name__ == "__main__":
    # start background tasks and flask server (dev)
    # create background task for alerts
    loop = asyncio.get_event_loop()
    # ensure bot init lazy
    loop.run_until_complete(ensure_initialized())
    loop.create_task(alert_worker())
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
