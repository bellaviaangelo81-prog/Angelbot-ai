# app.py
import os
import logging
import asyncio
from io import BytesIO
from datetime import datetime, timedelta

import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# Optional OpenAI import (used for "AI" answers)
try:
    import openai
except Exception:
    openai = None

# ---------------- CONFIG ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("angelbot")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # change if you prefer another model
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

if not TELEGRAM_TOKEN:
    raise RuntimeError("Imposta TELEGRAM_TOKEN nelle env vars")
if OPENAI_API_KEY and openai:
    openai.api_key = OPENAI_API_KEY

# ---------------- FLASK APP (for hosting/webhook) ----------------
app = Flask(__name__)

@app.route("/")
def home():
    return "AngelBot-AI attivo ✅"

# ---------------- TICKERS DB (principali, estendi quando vuoi) ----------------
TICKERS_BY_REGION = {
    "USA": {
        "AAPL": "Apple Inc.",
        "MSFT": "Microsoft Corporation",
        "AMZN": "Amazon.com, Inc.",
        "GOOGL": "Alphabet Inc.",
        "TSLA": "Tesla, Inc.",
        "NVDA": "NVIDIA Corporation",
        "META": "Meta Platforms, Inc.",
        "BIDU": "Baidu, Inc."
    },
    "Europa": {
        "BMPS.MI": "Banca Monte dei Paschi di Siena",
        "ISP.MI": "Intesa Sanpaolo",
        "ENI.MI": "ENI S.p.A.",
        "LUX.MI": "EssilorLuxottica",
        "RACE.MI": "Ferrari N.V."
    },
    "Asia": {
        "BABA": "Alibaba Group",
        "TCEHY": "Tencent Holdings",
        "005930.KS": "Samsung Electronics",
        "TSM": "TSMC",
        "9984.T": "SoftBank Group"
    }
}

REGION_FLAGS = {"USA": "🇺🇸", "Europa": "🇪🇺", "Asia": "🇯🇵", "Africa": "🌍", "Oceania": "🇦🇺", "America Latina": "🌎"}

# ---------------- PERSISTENCE (simple sqlite) ----------------
import sqlite3
DB_PATH = os.path.join(os.getcwd(), "angelbot.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS watchlist (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, symbol TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS settings (chat_id INTEGER PRIMARY KEY, interval_minutes INTEGER)""")
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

# ---------------- HELPERS: tickers search ----------------
def find_ticker(query):
    """Cerca simbolo per simbolo o per nome (case-insensitive). Restituisce (symbol,name) o (None,None)."""
    q = query.strip().lower()
    for region, map_ in TICKERS_BY_REGION.items():
        for sym, name in map_.items():
            if q == sym.lower() or q == name.lower() or q in name.lower():
                return sym, name
    # fallback: try raw uppercase symbol if user provided like AAPL
    up = query.strip().upper()
    for region, map_ in TICKERS_BY_REGION.items():
        if up in map_:
            return up, map_[up]
    return None, None

# ---------------- FINANCIAL DATA & PLOTTING ----------------
def get_market_data(symbol, period="1mo", interval="1d"):
    try:
        t = yf.Ticker(symbol)
        df = t.history(period=period, interval=interval)
        return df
    except Exception as e:
        logger.exception("get_market_data error")
        return None

def build_chart_image(df, symbol, days=30):
    buf = BytesIO()
    if df is None or df.empty:
        return None
    plt.figure(figsize=(8,4))
    close = df["Close"].dropna()
    close.plot(label="Close")
    if len(close) >= 7:
        close.rolling(7).mean().plot(label="SMA7")
    if len(close) >= 30:
        close.rolling(30).mean().plot(label="SMA30")
    plt.title(f"{symbol} — ultimi {days} giorni")
    plt.ylabel("Prezzo")
    plt.legend()
    plt.tight_layout()
    plt.savefig(buf, format="png")
    plt.close()
    buf.seek(0)
    return buf

def simple_numeric_analysis(df):
    """Genera un piccolo riassunto numerico (string) basato sui dati passati."""
    if df is None or df.empty:
        return "Dati insufficienti per un'analisi numerica."
    close = df["Close"].dropna()
    latest = close.iloc[-1]
    first = close.iloc[0]
    pct = (latest - first) / first * 100
    pct_7 = 0
    if len(close) >= 7:
        pct_7 = (latest - close.iloc[-7]) / close.iloc[-7] * 100
    text = f"Prezzo attuale: {latest:.2f}\nVariazione ultimi {len(close)} giorni: {pct:.2f}%\nVariazione breve (7d): {pct_7:.2f}%"
    return text

# ---------------- OPENAI WRAPPER ----------------
async def ask_openai(prompt, system="Sei un consulente finanziario esperto che risponde in italiano."):
    """Chiede ad OpenAI (se chiave presente). Restituisce la risposta testuale."""
    if not OPENAI_API_KEY or not openai:
        # fallback simulato (se openai non presente)
        return "💡 Non ho accesso all'API OpenAI in questo momento. Posso però fornire un'analisi numerica basata sui dati."
    try:
        # Use Chat Completions
        resp = openai.ChatCompletion.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500,
            temperature=0.7
        )
        text = resp["choices"][0]["message"]["content"].strip()
        return text
    except Exception as e:
        logger.exception("OpenAI request failed")
        return "Errore nella generazione della risposta AI."

# ---------------- TELEGRAM BOT SETUP ----------------
application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

# /start
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    db_execute("INSERT OR IGNORE INTO users(chat_id) VALUES(?)", (chat_id,))
    keyboard = [
        [InlineKeyboardButton("📊 Monitoraggio", callback_data="menu_monitor")],
        [InlineKeyboardButton("🔎 Cerca/aggiungi titolo", callback_data="menu_scegli")],
        [InlineKeyboardButton("📋 La mia watchlist", callback_data="menu_watchlist")],
        [InlineKeyboardButton("💬 Chat consulente (AI)", callback_data="menu_chat_ai")]
    ]
    await update.message.reply_text("Ciao — sono il tuo consulente finanziario virtuale. Scegli un'opzione:", reply_markup=InlineKeyboardMarkup(keyboard))

# /help
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Comandi:\n/start\n/analizza <SIMBOLO>\n/watchlist\n/monitoraggio\nScrivi liberamente per parlare con il consulente (AI) oppure chiedi dati su un titolo (es. 'AMZN' o 'Amazon').")

# /analizza
async def cmd_analizza(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /analizza <SIMBOLO> (es. /analizza AMZN)")
        return
    symbol = context.args[0].upper()
    df = await asyncio.get_event_loop().run_in_executor(None, get_market_data, symbol, "1mo", "1d")
    if df is None or df.empty:
        await update.message.reply_text("❌ Nessun dato disponibile per questo simbolo.")
        return
    text_num = simple_numeric_analysis(df)
    buf = await asyncio.get_event_loop().run_in_executor(None, build_chart_image, df, symbol, 30)
    # compose an AI-enhanced comment from numeric summary
    prompt = f"Ho questi dati per {symbol}:\n{text_num}\nFornisci un breve commento di consulente in italiano (2-3 frasi) basato su questi numeri."
    ai_comment = await ask_openai(prompt)
    if buf:
        await update.message.reply_photo(photo=buf, caption=f"{text_num}\n\nConsulente:\n{ai_comment}")
    else:
        await update.message.reply_text(f"{text_num}\n\nConsulente:\n{ai_comment}")

# CALLBACK MENU HANDLER
async def callback_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_monitor":
        keyboard = [
            [InlineKeyboardButton("🕧 30 minuti", callback_data="freq_30")],
            [InlineKeyboardButton("🕐 60 minuti", callback_data="freq_60")],
            [InlineKeyboardButton("🕑 120 minuti", callback_data="freq_120")],
            [InlineKeyboardButton("🌅 Giornaliero", callback_data="freq_day")],
            [InlineKeyboardButton("📆 Settimanale", callback_data="freq_week")],
            [InlineKeyboardButton("🚫 Disattiva monitoraggio", callback_data="freq_off")],
            [InlineKeyboardButton("⬅️ Indietro", callback_data="back_main")]
        ]
        await query.edit_message_text("📊 Seleziona la frequenza del monitoraggio:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "menu_scegli":
        keyboard = []
        for region, flag in REGION_FLAGS.items():
            keyboard.append([InlineKeyboardButton(f"{flag} {region}", callback_data=f"region_{region}")])
        keyboard.append([InlineKeyboardButton("🔍 Cerca per nome/simbolo", callback_data="search_prompt")])
        keyboard.append([InlineKeyboardButton("⬅️ Indietro", callback_data="back_main")])
        await query.edit_message_text("🌍 Seleziona una regione o cerca un titolo:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "menu_watchlist":
        chat_id = query.message.chat_id
        rows = db_execute("SELECT symbol FROM watchlist WHERE chat_id=?", (chat_id,), fetch=True)
        if not rows:
            await query.edit_message_text("La tua watchlist è vuota.")
            return
        keyboard = [[InlineKeyboardButton(f"Rimuovi {r[0]}", callback_data=f"rm_{r[0]}")] for r in rows]
        keyboard.append([InlineKeyboardButton("⬅️ Indietro", callback_data="back_main")])
        await query.edit_message_text("La tua watchlist (clicca per rimuovere):", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "menu_chat_ai":
        await query.edit_message_text("💬 Modalità chat AI attivata. Scrivi la tua domanda e risponderò come consulente (in italiano).")
        # set a small state in user_data
        context.user_data["chat_ai"] = True
        return

    if data.startswith("region_"):
        region = data.split("_",1)[1]
        symbols = TICKERS_BY_REGION.get(region, {})
        keyboard = [[InlineKeyboardButton(f"{sym} / {name}", callback_data=f"add_{sym}")] for sym, name in symbols.items()]
        keyboard.append([InlineKeyboardButton("⬅️ Indietro", callback_data="menu_scegli")])
        await query.edit_message_text(f"{REGION_FLAGS.get(region,'')} {region} — Titoli principali:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "search_prompt":
        context.user_data["awaiting_search"] = True
        await query.edit_message_text("🔎 Scrivi il nome o simbolo del titolo che cerchi (es. 'Amazon' o 'AMZN').")
        return

    if data.startswith("add_"):
        sym = data.split("_",1)[1]
        chat_id = query.message.chat_id
        db_execute("INSERT INTO watchlist(chat_id,symbol) SELECT ?,? WHERE NOT EXISTS(SELECT 1 FROM watchlist WHERE chat_id=? AND symbol=?)", (chat_id, sym, chat_id, sym))
        await query.edit_message_text(f"✅ {sym} aggiunto alla tua watchlist.")
        return

    if data.startswith("rm_"):
        sym = data.split("_",1)[1]
        chat_id = query.message.chat_id
        db_execute("DELETE FROM watchlist WHERE chat_id=? AND symbol=?", (chat_id, sym))
        await query.edit_message_text(f"❌ {sym} rimosso dalla tua watchlist.")
        return

    if data.startswith("freq_"):
        chat_id = query.message.chat_id
        mapping = {"freq_30":30, "freq_60":60, "freq_120":120, "freq_day":60*24, "freq_week":60*24*7}
        if data == "freq_off":
            db_execute("DELETE FROM settings WHERE chat_id=?", (chat_id,))
            # remove existing jobs by name
            job_name = f"monitor_{chat_id}"
            for job in context.job_queue.get_jobs_by_name(job_name):
                job.schedule_removal()
            await query.edit_message_text("🛑 Monitoraggio disattivato.")
            return
        minutes = mapping.get(data)
        db_execute("INSERT OR REPLACE INTO settings(chat_id,interval_minutes) VALUES(?,?)", (chat_id, minutes))
        # reschedule job
        job_name = f"monitor_{chat_id}"
        for job in context.job_queue.get_jobs_by_name(job_name):
            job.schedule_removal()

        async def monitor_job(ctx: ContextTypes.DEFAULT_TYPE):
            symbols = [r[0] for r in db_execute("SELECT symbol FROM watchlist WHERE chat_id=?", (chat_id,), fetch=True) or []]
            if not symbols:
                try:
                    await ctx.bot.send_message(chat_id=chat_id, text="La tua watchlist è vuota: usa /scegli_titoli per aggiungere titoli.")
                except Exception:
                    pass
                return
            for s in symbols:
                df = await asyncio.get_event_loop().run_in_executor(None, get_market_data, s, "7d", "1d")
                text_num = simple_numeric_analysis(df)
                buf = await asyncio.get_event_loop().run_in_executor(None, build_chart_image, df, s, 7)
                prompt = f"Ho questi numeri per {s}:\n{text_num}\nFornisci un breve commento da consulente in italiano (2-3 frasi)."
                ai_comment = await ask_openai(prompt)
                try:
                    if buf:
                        await ctx.bot.send_photo(chat_id=chat_id, photo=buf, caption=f"{text_num}\n\nConsulente:\n{ai_comment}")
                    else:
                        await ctx.bot.send_message(chat_id=chat_id, text=f"{text_num}\n\nConsulente:\n{ai_comment}")
                except Exception:
                    pass

        context.job_queue.run_repeating(monitor_job, interval=minutes*60, first=5, name=job_name)
        await query.edit_message_text(f"✅ Monitoraggio impostato ogni {minutes} minuti.")
        return

    if data == "back_main":
        keyboard = [
            [InlineKeyboardButton("📊 Monitoraggio", callback_data="menu_monitor")],
            [InlineKeyboardButton("🔎 Cerca/aggiungi titolo", callback_data="menu_scegli")],
            [InlineKeyboardButton("📋 La mia watchlist", callback_data="menu_watchlist")],
            [InlineKeyboardButton("💬 Chat consulente (AI)", callback_data="menu_chat_ai")]
        ]
        await query.edit_message_text("Torna al menu principale:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    await query.edit_message_text("Comando non gestito.")

# ---------------- MESSAGE HANDLER (search vs AI chat) ----------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    # if user in AI-mode
    if context.user_data.get("chat_ai"):
        # ask OpenAI for a human-like answer
        prompt = f"Il mio utente chiede (in italiano): {text}\nRispondi come consulente finanziario, in italiano, chiaro e sintetico."
        ai_reply = await ask_openai(prompt)
        await update.message.reply_text(ai_reply)
        return

    # if user expects a ticker search
    symbol, name = find_ticker(text)
    if symbol:
        # provide data + chart + short AI comment
        df = await asyncio.get_event_loop().run_in_executor(None, get_market_data, symbol, "1mo", "1d")
        if df is None or df.empty:
            await update.message.reply_text("❌ Nessun dato disponibile per questo titolo.")
            return
        text_num = simple_numeric_analysis(df)
        buf = await asyncio.get_event_loop().run_in_executor(None, build_chart_image, df, symbol, 30)
        prompt = f"Ho questi numeri per {symbol} ({name}):\n{text_num}\nScrivi un commento di consulente in italiano (2-3 frasi)."
        ai_comment = await ask_openai(prompt)
        if buf:
            await update.message.reply_photo(photo=buf, caption=f"{name} ({symbol})\n\n{text_num}\n\nConsulente:\n{ai_comment}")
        else:
            await update.message.reply_text(f"{name} ({symbol})\n\n{text_num}\n\nConsulente:\n{ai_comment}")
        return

    # fallback: short attempt to interpret free question with AI OR local fallback
    # if OpenAI available -> use it; else give numeric fallback hint
    if OPENAI_API_KEY and openai:
        prompt = f"Il mio utente scrive: '{text}'. Rispondi in italiano come consulente finanziario in modo chiaro e sintetico."
        ai_reply = await ask_openai(prompt)
        await update.message.reply_text(ai_reply)
    else:
        await update.message.reply_text("Non ho dati precisi per questa richiesta. Prova a chiedere un titolo (es. 'AMZN') o abilita OpenAI per risposte più articolate.")

# ---------------- WEBHOOK endpoint ----------------
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, application.bot)
        # schedule processing on the bot loop
        asyncio.run(application.process_update(update))
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("Webhook error")
        return jsonify({"ok": False, "error": str(e)}), 500

# ---------------- REGISTER HANDLERS ----------------
application.add_handler(CommandHandler("start", cmd_start))
application.add_handler(CommandHandler("help", cmd_help))
application.add_handler(CommandHandler("analizza", cmd_analizza))
application.add_handler(CallbackQueryHandler(callback_menu))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

# ---------------- STARTUP ----------------
if __name__ == "__main__":
    # try set webhook automatically if provided
    if WEBHOOK_URL:
        try:
            asyncio.run(application.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook"))
            logger.info("Webhook impostato su %s/webhook", WEBHOOK_URL)
        except Exception:
            logger.exception("Errore impostazione webhook")

    # run flask (Render expects a Flask app to serve)
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
