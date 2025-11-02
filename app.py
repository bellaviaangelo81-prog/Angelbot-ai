#!/usr/bin/env python3
# app.py - AngelBot AI (versione avanzata)
# - webhook Flask (GET per debug, POST per Telegram)
# - Telegram HTTP API (no token in code)
# - OpenAI modern SDK with legacy fallback
# - yfinance, matplotlib, pandas for grafici/analisi
# - persistence: data.json + optional Google Sheets (service account JSON in env)
# - categories: USA / Europa / Asia / Africa
# - monitor automatico con soglia e frequenze, daily report
# - safe, defensive coding, lots of logging

import os
import json
import time
import logging
import threading
from io import BytesIO
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

import requests
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from flask import Flask, request, jsonify

# Optional Google Sheets
USE_SHEETS = False
try:
    import gspread
    from google.oauth2.service_account import Credentials
    USE_SHEETS = True
except Exception:
    # gspread not available -> will use local JSON persistence
    USE_SHEETS = False

# OpenAI modern SDK or legacy fallback
USE_MODERN_OPENAI = False
openai_modern_client = None
openai_legacy = None
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except Exception:
    try:
        import openai
        OPENAI_AVAILABLE = True
    except Exception:
        OPENAI_AVAILABLE = False

# ---------------- Config & Logging ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("angelbot-advanced")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEETS_KEY = os.getenv("GOOGLE_SHEETS_KEY")  # JSON string for service account
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g. https://your-app.onrender.com
PORT = int(os.getenv("PORT", 5000))

if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN non impostato! Esci.")
    raise RuntimeError("Imposta TELEGRAM_TOKEN nelle env vars")

TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

DATA_FILE = os.path.join(os.getcwd(), "data.json")

# ---------------- OpenAI init ----------------
if OPENAI_AVAILABLE and OPENAI_API_KEY:
    try:
        # try modern
        from openai import OpenAI as _OpenAIModern
        openai_modern_client = _OpenAIModern(api_key=OPENAI_API_KEY)
        USE_MODERN_OPENAI = True
        logger.info("OpenAI SDK moderno disponibile")
    except Exception:
        # fallback legacy
        import openai as _openai_legacy
        _openai_legacy.api_key = OPENAI_API_KEY
        openai_legacy = _openai_legacy
        USE_MODERN_OPENAI = False
        logger.info("Usando OpenAI legacy client")
else:
    if not OPENAI_API_KEY:
        logger.info("OPENAI_API_KEY non impostato: funzionalità AI limitate")
    else:
        logger.info("OpenAI non disponibile: import failed")

def ask_openai(prompt: str, system_prompt: str = "Sei un consulente finanziario esperto in italiano, prudente e chiaro.") -> str:
    if not OPENAI_API_KEY or not OPENAI_AVAILABLE:
        return "⚠️ OpenAI non configurato o non disponibile."
    try:
        if USE_MODERN_OPENAI and openai_modern_client:
            resp = openai_modern_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=450,
                temperature=0.6
            )
            try:
                return resp.choices[0].message.content.strip()
            except Exception:
                return str(resp)
        else:
            resp = openai_legacy.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=450,
                temperature=0.6
            )
            return resp['choices'][0]['message']['content'].strip()
    except Exception as e:
        logger.exception("Errore OpenAI")
        return f"Errore OpenAI: {e}"

# ---------------- Persistence ----------------
def load_local_data() -> Dict[str, Any]:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                logger.info("Caricato dati locali da data.json")
                return d
        except Exception:
            logger.exception("Errore caricamento data.json")
    return {}

def save_local_data(data: Dict[str, Any]):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.exception("Errore salvataggio data.json")

user_data = load_local_data()  # chat_id -> settings

# Optional Google Sheets initialization
gclient = None
sheet = None
if USE_SHEETS and GOOGLE_SHEETS_KEY:
    try:
        creds_dict = json.loads(GOOGLE_SHEETS_KEY)
        creds = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gclient = gspread.authorize(creds)
        # sheet id must be provided by you in SHEET_ID env or set it here
        SHEET_ID = os.getenv("SHEET_ID")  # optional override; else not used
        if SHEET_ID:
            sheet = gclient.open_by_key(SHEET_ID).sheet1
            logger.info("Google Sheets collegato a %s", SHEET_ID)
        else:
            logger.info("GOOGLE_SHEETS_KEY OK ma SHEET_ID non impostato; useremo sheets solo per append history se impostato")
    except Exception:
        logger.exception("Errore inizializzazione Google Sheets; useremo solo data.json")
        gclient = None
        sheet = None

# ---------------- Defaults / categories ----------------
DEFAULT_WATCHLIST = {
    "USA": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOG", "TSLA", "META"],
    "EUROPA": ["ENEL.MI", "ENI.MI", "ISP.MI", "STM.MI", "RDSA.L"],  # example
    "ASIA": ["BABA", "BIDU", "TCEHY"],
    "AFRICA": ["NPN.JO"]  # example tickers (may need exchange suffixes)
}

FREQ_OPTIONS = {"30m": 30, "1h": 60, "6h": 360, "1d": 1440, "1w": 10080}
THRESH_PRESETS = [1.0, 3.0, 5.0, 10.0, 20.0]

def ensure_user(chat_id: str) -> Dict[str, Any]:
    if chat_id not in user_data:
        user_data[chat_id] = {
            "watchlist": {t: None for t in DEFAULT_WATCHLIST["USA"]},
            "categories": {"USA": True, "EUROPA": False, "ASIA": False, "AFRICA": False},
            "frequency_min": 60,
            "threshold_pct": 5.0,
            "active": True,
            "chat_ai": True,
            "last_check_ts": 0,
            "awaiting_add": False,
            "awaiting_threshold": False,
            "history": []  # optional local history
        }
        save_local_data(user_data)
    return user_data[chat_id]

# ---------------- Finance helpers ----------------
def get_current_price(symbol: str) -> Optional[float]:
    try:
        t = yf.Ticker(symbol)
        df = t.history(period="1d", interval="1d")
        if df is None or df.empty:
            return None
        return float(df["Close"].iloc[-1])
    except Exception:
        logger.exception("Errore get_current_price per %s", symbol)
        return None

def download_history(symbol: str, period: str = "1mo", interval: str = "1d") -> Optional[pd.DataFrame]:
    try:
        df = yf.Ticker(symbol).history(period=period, interval=interval)
        return df
    except Exception:
        logger.exception("Errore download_history per %s", symbol)
        return None

def build_chart(symbols: List[str], days: int = 7) -> Optional[BytesIO]:
    buf = BytesIO()
    try:
        plt.figure(figsize=(8,4))
        plotted = False
        for s in symbols:
            df = download_history(s, period=f"{max(days,7)}d", interval="1d")
            if df is None or df.empty:
                continue
            series = df["Close"].dropna()
            if series.empty:
                continue
            plt.plot(series.index, series.values, label=s)
            plotted = True
        if not plotted:
            return None
        plt.legend()
        plt.title(f"Andamento ultimi {days} giorni")
        plt.xlabel("Data")
        plt.ylabel("Prezzo")
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(buf, format="png")
        plt.close()
        buf.seek(0)
        return buf
    except Exception:
        logger.exception("Errore build_chart")
        return None

# ---------------- Telegram helpers ----------------
def send_message(chat_id: str, text: str, reply_markup: dict = None):
    url = f"{TELEGRAM_API_BASE}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    try:
        r = requests.post(url, json=payload, timeout=15)
        if not r.ok:
            logger.warning("send_message fallita: %s", r.text)
        return r
    except Exception:
        logger.exception("send_message exception")
        return None

def send_photo(chat_id: str, image_buf: BytesIO, caption: str = ""):
    url = f"{TELEGRAM_API_BASE}/sendPhoto"
    try:
        files = {"photo": ("chart.png", image_buf.getvalue())}
        data = {"chat_id": chat_id, "caption": caption}
        r = requests.post(url, files=files, data=data, timeout=30)
        if not r.ok:
            logger.warning("send_photo fallita: %s", r.text)
        return r
    except Exception:
        logger.exception("send_photo exception")
        return None

def set_telegram_webhook():
    if not WEBHOOK_URL:
        logger.warning("WEBHOOK_URL non impostato, setWebhook saltato")
        return False
    url = f"{TELEGRAM_API_BASE}/setWebhook"
    payload = {"url": f"{WEBHOOK_URL.rstrip('/')}/webhook"}
    try:
        r = requests.post(url, json=payload, timeout=15)
        logger.info("setWebhook response: %s", r.text)
        return r.ok
    except Exception:
        logger.exception("setWebhook error")
        return False

# ---------------- Monitoring & notification logic ----------------
def append_history_to_sheets(chat_id: str, symbol: str, price: float, ts: float):
    """Appends a row to Google Sheets if configured; else write in local history for user."""
    dt = datetime.utcfromtimestamp(ts).isoformat()
    if sheet:
        try:
            sheet.append_row([chat_id, symbol, price, dt])
            return True
        except Exception:
            logger.exception("Errore append sheet")
    # fallback: store in user_data
    try:
        user_data.setdefault(chat_id, {}).setdefault("history", []).append({"ts": ts, "symbol": symbol, "price": price})
        save_local_data(user_data)
        return True
    except Exception:
        logger.exception("Errore append local history")
        return False

def check_and_notify_user(chat_id_str: str):
    u = ensure_user(chat_id_str)
    if not u.get("active"):
        return
    threshold = float(u.get("threshold_pct", 5.0))
    notifications = []
    for symbol, baseline in list(u["watchlist"].items()):
        if baseline is None:
            cur = get_current_price(symbol)
            if cur is None:
                continue
            user_data[chat_id_str]["watchlist"][symbol] = cur
            save_local_data(user_data)
            append_history_to_sheets(chat_id_str, symbol, cur, time.time())
            continue
        cur = get_current_price(symbol)
        if cur is None:
            continue
        pct = (cur - baseline) / baseline * 100
        # save snapshot always
        append_history_to_sheets(chat_id_str, symbol, cur, time.time())
        if abs(pct) >= threshold:
            notifications.append((symbol, baseline, cur, pct))
            user_data[chat_id_str]["watchlist"][symbol] = cur
            save_local_data(user_data)
    for symbol, base, curr, pct in notifications:
        arrow = "▲" if pct > 0 else "▼"
        mood = "positivo" if pct > 0 else "negativo"
        text = (f"🔔 <b>Alert monitoraggio</b>\n"
                f"{symbol}\n"
                f"Prezzo precedente: {base:.2f}$\n"
                f"Prezzo attuale: {curr:.2f}$\n"
                f"Variazione: {arrow} {pct:.2f}% ({mood}) — soglia {threshold:.2f}%\n\n"
                "Consiglio (generico): valuta la tua strategia e il contesto di mercato. Io fornisco informazioni, non eseguo ordini.")
        send_message(chat_id_str, text)

def monitor_loop():
    logger.info("Monitor thread avviato")
    while True:
        now = time.time()
        for chat_id_str, u in list(user_data.items()):
            freq = u.get("frequency_min")
            if not u.get("active") or not freq:
                continue
            last = u.get("last_check_ts", 0)
            if now - last >= (freq * 60):
                try:
                    logger.info("Controllo watchlist per %s", chat_id_str)
                    check_and_notify_user(chat_id_str)
                    user_data[chat_id_str]["last_check_ts"] = now
                    save_local_data(user_data)
                except Exception:
                    logger.exception("Errore check user %s", chat_id_str)
        time.sleep(20)

def daily_report_loop():
    logger.info("Daily report thread avviato")
    while True:
        now = datetime.utcnow()
        # run daily at 08:00 UTC (adjust as you prefer)
        target = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now > target:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        logger.info("Daily report in %.0f secondi", wait_seconds)
        time.sleep(max(60, min(wait_seconds, 24*3600)))  # sleep but wake for normal cycle
        # at wake time if it's within the window, proceed
        now2 = datetime.utcnow()
        if abs((now2 - target).total_seconds()) < 3600:  # within 1 hour from target
            for chat_id_str, u in list(user_data.items()):
                try:
                    # Build a short summary for the user's watchlist
                    lines = []
                    for s, base in u.get("watchlist", {}).items():
                        price = get_current_price(s)
                        if price is None:
                            continue
                        pct = (price - (base if base else price)) / (base if base else price) * 100 if base else 0.0
                        lines.append(f"{s}: {price:.2f}$ ({pct:+.2f}%)")
                    if not lines:
                        send_message(chat_id_str, "📅 Report giornaliero: nessun dato disponibile oggi.")
                        continue
                    summary_text = "📅 Report giornaliero — breve aggiornamento:\n" + "\n".join(lines)
                    # Optionally append AI suggestion
                    if OPENAI_API_KEY:
                        prompt = "Sei un consulente finanziario. Dato questo elenco di titoli con prezzi e variazioni, fornisci 2-3 frasi di raccomandazioni generiche e prudenziali per un investitore retail:\n" + "\n".join(lines)
                        ai_comment = ask_openai(prompt)
                        summary_text += "\n\nConsulente:\n" + ai_comment
                    send_message(chat_id_str, summary_text)
                except Exception:
                    logger.exception("Errore invio report giornaliero user %s", chat_id_str)
        # small sleep before next loop
        time.sleep(60)

# start background threads
monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
monitor_thread.start()

daily_thread = threading.Thread(target=daily_report_loop, daemon=True)
daily_thread.start()

# ---------------- Keyboards / UI ----------------
def make_categories_keyboard():
    kb = {"inline_keyboard": []}
    for region in ["USA", "EUROPA", "ASIA", "AFRICA"]:
        kb["inline_keyboard"].append([{"text": region, "callback_data": f"cat|{region}"}])
    kb["inline_keyboard"].append([{"text": "Mostra/Modifica watchlist", "callback_data": "menu_watchlist"}])
    return kb

def watchlist_keyboard(chat_id: str):
    u = ensure_user(chat_id)
    kb = {"inline_keyboard": []}
    for symbol in list(u["watchlist"].keys())[:8]:
        kb["inline_keyboard"].append([{"text": f"{symbol}", "callback_data": f"sym|{symbol}"},
                                     {"text": f"Rimuovi", "callback_data": f"rm|{symbol}"}])
    kb["inline_keyboard"].append([{"text": "Aggiungi simbolo", "callback_data": "add_symbol"}])
    kb["inline_keyboard"].append([{"text": "Impostazioni monitor", "callback_data": "settings"}])
    return kb

def freq_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "30m", "callback_data": "freq|30"}],
            [{"text": "1h", "callback_data": "freq|60"}],
            [{"text": "6h", "callback_data": "freq|360"}],
            [{"text": "1d", "callback_data": "freq|1440"}],
            [{"text": "Disattiva", "callback_data": "freq|0"}]
        ]
    }

def threshold_keyboard():
    kb = {"inline_keyboard": []}
    for p in THRESH_PRESETS:
        kb["inline_keyboard"].append([{"text": f"{p}%", "callback_data": f"th|{p}"}])
    kb["inline_keyboard"].append([{"text": "Personalizzata", "callback_data": "th|custom"}])
    return kb

# ---------------- Flask app and webhook ----------------
app = Flask(__name__)

@app.route("/", methods=["GET"])
def root():
    return "AngelBot AI attivo ✅", 200

@app.route("/set_webhook", methods=["GET"])
def route_set_webhook():
    ok = set_telegram_webhook()
    return ("Webhook impostato" if ok else "Errore set webhook"), (200 if ok else 500)

@app.route("/status", methods=["GET"])
def status():
    # Basic status for debug
    return jsonify({
        "uptime": time.time(),
        "users": len(user_data),
        "sheets": bool(sheet),
        "openai": bool(OPENAI_API_KEY),
    }), 200

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    # Accept GET (debug) and POST (Telegram)
    if request.method == "GET":
        return "Webhook attivo. Usa POST da Telegram.", 200
    try:
        data = request.get_json(force=True)
    except Exception:
        data = None
    logger.debug("Update ricevuto: %s", data)
    if not data:
        return jsonify(ok=False, error="no json"), 400

    # Handle message
    if "message" in data:
        msg = data["message"]
        chat_id = str(msg["chat"]["id"])
        text = msg.get("text", "").strip()
        logger.info("Messaggio da %s: %s", chat_id, text)
        ensure_user(chat_id)
        u = user_data[chat_id]

        # Handle awaiting states
        if u.get("awaiting_add"):
            symbol = text.upper().strip()
            price = get_current_price(symbol)
            u["watchlist"][symbol] = price
            u["awaiting_add"] = False
            save_local_data(user_data)
            if price:
                send_message(chat_id, f"✅ Aggiunto {symbol} con baseline {price:.2f}$")
            else:
                send_message(chat_id, f"✅ Aggiunto {symbol}. Baseline non disponibile ora.")
            return jsonify(ok=True)

        if u.get("awaiting_threshold"):
            try:
                val = float(text)
                u["threshold_pct"] = val
                u["awaiting_threshold"] = False
                save_local_data(user_data)
                send_message(chat_id, f"✅ Soglia impostata su {val:.2f}%")
            except Exception:
                send_message(chat_id, "Valore non valido. Scrivi un numero (es. 3 o 7.5).")
            return jsonify(ok=True)

        # commands (slash or plain)
        cmd = text.split(maxsplit=1)[0].lower() if text else ""
        arg = text.split(maxsplit=1)[1].strip() if len(text.split()) > 1 else ""

        if cmd in ("/start", "/help"):
            send_message(chat_id,
                         "Ciao 👋 Sono AngelBot! Posso darti prezzi, grafici, analisi e report.\n"
                         "Comandi principali:\n"
                         "/add <SIMBOLO>\n"
                         "/rm <SIMBOLO>\n"
                         "/watchlist\n"
                         "/categories\n"
                         "/freq\n"
                         "/th\n"
                         "/grafico <SIMBOLO>\n"
                         "/analizza <SIMBOLO>\n"
                         "/ai <domanda>\n"
                         "/daily_report\n"
                         "/status")
            return jsonify(ok=True)

        if cmd == "/categories" or text.lower() == "categorie":
            send_message(chat_id, "Scegli una regione:", reply_markup=make_categories_keyboard())
            return jsonify(ok=True)

        if cmd == "/add" and arg:
            symbol = arg.upper().strip()
            price = get_current_price(symbol)
            u["watchlist"][symbol] = price
            save_local_data(user_data)
            if price:
                send_message(chat_id, f"✅ Aggiunto {symbol} con baseline {price:.2f}$")
            else:
                send_message(chat_id, f"✅ Aggiunto {symbol}. Baseline non disponibile ora.")
            return jsonify(ok=True)

        if cmd == "/rm" and arg:
            symbol = arg.upper().strip()
            removed = u["watchlist"].pop(symbol, None)
            save_local_data(user_data)
            if removed is None:
                send_message(chat_id, f"{symbol} non era presente.")
            else:
                send_message(chat_id, f"🗑️ {symbol} rimosso.")
            return jsonify(ok=True)

        if cmd == "/watchlist":
            items = u.get("watchlist", {})
            if not items:
                send_message(chat_id, "La tua watchlist è vuota.")
            else:
                lines = [f"{s} — baseline: {('N/D' if b is None else f'{b:.2f}$')}" for s, b in items.items()]
                send_message(chat_id, "📋 La tua watchlist:\n" + "\n".join(lines), reply_markup=watchlist_keyboard(chat_id))
            return jsonify(ok=True)

        if cmd == "/freq":
            send_message(chat_id, "⏱️ Scegli la frequenza:", reply_markup=freq_keyboard())
            return jsonify(ok=True)

        if cmd == "/th":
            send_message(chat_id, "⚖️ Scegli la soglia:", reply_markup=threshold_keyboard())
            return jsonify(ok=True)

        if cmd == "/grafico" and arg:
            symbol = arg.upper().strip()
            buf = build_chart([symbol], days=7)
            if buf:
                send_photo(chat_id, buf, caption=f"📈 Grafico 7gg: {symbol}")
            else:
                send_message(chat_id, f"⚠️ Impossibile generare grafico per {symbol}.")
            return jsonify(ok=True)

        if cmd == "/analizza" and arg:
            symbol = arg.upper().strip()
            df = download_history(symbol, period="1mo", interval="1d")
            if df is None or df.empty:
                send_message(chat_id, f"⚠️ Nessun dato disponibile per {symbol}.")
                return jsonify(ok=True)
            latest = df["Close"].iloc[-1]
            change_pct = (latest - df["Close"].iloc[0]) / df["Close"].iloc[0] * 100
            numeric = f"Prezzo attuale: {latest:.2f}$\nVariazione ultimo mese: {change_pct:.2f}%"
            prompt = f"Ho questi dati per {symbol}: {numeric}. Fornisci 2-3 frasi di analisi in italiano, tono consulente (prudente)."
            ai_comment = ask_openai(prompt)
            buf = build_chart([symbol], days=30)
            if buf:
                send_photo(chat_id, buf, caption=f"{symbol}\n\n{numeric}\n\nConsulente:\n{ai_comment}")
            else:
                send_message(chat_id, f"{symbol}\n\n{numeric}\n\nConsulente:\n{ai_comment}")
            return jsonify(ok=True)

        if cmd == "/ai" and arg:
            question = arg.strip()
            answer = ask_openai(question)
            send_message(chat_id, answer)
            return jsonify(ok=True)

        if cmd == "/daily_report":
            # manual immediate daily report for this user
            try:
                lines = []
                for s, base in u.get("watchlist", {}).items():
                    price = get_current_price(s)
                    if price is None: continue
                    pct = (price - (base if base else price)) / (base if base else price) * 100 if base else 0.0
                    lines.append(f"{s}: {price:.2f}$ ({pct:+.2f}%)")
                if not lines:
                    send_message(chat_id, "Nessun dato disponibile per report.")
                else:
                    summary_text = "📅 Report:\n" + "\n".join(lines)
                    if OPENAI_API_KEY:
                        prompt = "Sei un consulente. Dai 2-3 frasi di raccomandazione dati questi titoli:\n" + "\n".join(lines)
                        summary_text += "\n\n" + ask_openai(prompt)
                    send_message(chat_id, summary_text)
            except Exception:
                logger.exception("Errore daily_report manuale")
                send_message(chat_id, "Errore generazione report.")
            return jsonify(ok=True)

        # fallback: if chat_ai active, forward to OpenAI
        if u.get("chat_ai") and text:
            ans = ask_openai(text)
            send_message(chat_id, ans)
            return jsonify(ok=True)

        # naive ticker detection
        token = text.strip().upper()
        if token and (len(token) <= 8 and (token.isalpha() or "." in token or token.isalnum())):
            price = get_current_price(token)
            if price is not None:
                send_message(chat_id, f"📈 {token} — prezzo attuale: {price:.2f}$\nUsa /analizza {token} per più dettagli.")
                return jsonify(ok=True)

        send_message(chat_id, "❓ Non riconosco il comando. Scrivi /help per la lista.")
        return jsonify(ok=True)

    # Callback query (button presses)
    if "callback_query" in data:
        cq = data["callback_query"]
        chat_id = str(cq["message"]["chat"]["id"])
        payload = cq.get("data", "")
        ensure_user(chat_id)
        u = user_data[chat_id]

        if payload.startswith("cat|"):
            region = payload.split("|", 1)[1]
            # toggle category
            u["categories"][region] = not u["categories"].get(region, False)
            # optionally populate watchlist with defaults if turning on
            if u["categories"][region]:
                for s in DEFAULT_WATCHLIST.get(region, []):
                    if s not in u["watchlist"]:
                        u["watchlist"][s] = None
            save_local_data(user_data)
            send_message(chat_id, f"Categoria {region} {'attivata' if u['categories'][region] else 'disattivata'}.")
            return jsonify(ok=True)

        if payload == "menu_watchlist":
            send_message(chat_id, "Ecco la tua watchlist:", reply_markup=watchlist_keyboard(chat_id))
            return jsonify(ok=True)

        if payload.startswith("rm|"):
            sym = payload.split("|", 1)[1]
            removed = u["watchlist"].pop(sym, None)
            save_local_data(user_data)
            send_message(chat_id, f"🗑️ {sym} rimosso.")
            return jsonify(ok=True)

        if payload == "add_symbol":
            u["awaiting_add"] = True
            save_local_data(user_data)
            send_message(chat_id, "✍️ Scrivi il simbolo da aggiungere (es. AAPL):")
            return jsonify(ok=True)

        if payload.startswith("freq|"):
            minutes = int(payload.split("|", 1)[1])
            if minutes == 0:
                u["frequency_min"] = None
                u["active"] = False
                send_message(chat_id, "⏸️ Monitoraggio disattivato.")
            else:
                u["frequency_min"] = minutes
                u["active"] = True
                u["last_check_ts"] = 0
                send_message(chat_id, f"⏱️ Monitoraggio impostato ogni {minutes} minuti.")
            save_local_data(user_data)
            return jsonify(ok=True)

        if payload.startswith("th|"):
            val = payload.split("|", 1)[1]
            if val == "custom":
                u["awaiting_threshold"] = True
                save_local_data(user_data)
                send_message(chat_id, "✍️ Scrivi la soglia percentuale desiderata (es. 7.5):")
            else:
                pct = float(val)
                u["threshold_pct"] = pct
                save_local_data(user_data)
                send_message(chat_id, f"✅ Soglia impostata su {pct:.2f}%")
            return jsonify(ok=True)

        # unknown callback
        send_message(chat_id, "Azione non riconosciuta.")
        return jsonify(ok=True)

    return jsonify(ok=True)

# ---------------- Startup: try set webhook and run Flask ----------------
if __name__ == "__main__":
    # try to set webhook automatically if WEBHOOK_URL present
    if WEBHOOK_URL:
        ok = set_telegram_webhook()
        if not ok:
            logger.warning("Impossibile impostare webhook automaticamente; imposta manualmente.")
    logger.info("Avvio Flask su port %s", PORT)
    # run app (gunicorn should be used in production)
    app.run(host="0.0.0.0", port=PORT)
