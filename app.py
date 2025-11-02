#!/usr/bin/env python3
# app.py — AngelBot AI definitivo
# - persistence data.json
# - monitoraggio con soglia personalizzabile
# - frequenze: 30m,1h,6h,1d,1w
# - grafici con matplotlib
# - OpenAI (modern SDK or legacy fallback)
# - Telegram via HTTP API (webhook)

import os
import json
import time
import threading
import logging
from io import BytesIO
from datetime import datetime
from typing import Optional

import requests
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from flask import Flask, request, jsonify

# ---------------- Config & Logging ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("angelbot")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # es. https://angelbot-ai.onrender.com
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_TOKEN:
    raise RuntimeError("Imposta TELEGRAM_TOKEN nelle environment variables (env vars)")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
DATA_FILE = os.path.join(os.getcwd(), "data.json")

# ---------------- OpenAI client (modern SDK preferred, legacy fallback) ----------------
USE_MODERN_OPENAI = False
client_modern = None
client_legacy = None
if OPENAI_API_KEY:
    try:
        from openai import OpenAI
        client_modern = OpenAI(api_key=OPENAI_API_KEY)
        USE_MODERN_OPENAI = True
        logger.info("OpenAI: uso SDK moderno")
    except Exception:
        import openai
        openai.api_key = OPENAI_API_KEY
        client_legacy = openai
        USE_MODERN_OPENAI = False
        logger.info("OpenAI: uso client legacy")

def ask_openai(prompt: str, system: str = "Sei un consulente finanziario esperto che risponde in italiano in modo chiaro e prudente.") -> str:
    if not OPENAI_API_KEY:
        return "⚠️ OpenAI non configurato. Imposta OPENAI_API_KEY per avere risposte AI."
    try:
        if USE_MODERN_OPENAI and client_modern:
            resp = client_modern.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=400,
                temperature=0.6
            )
            # try common access patterns
            try:
                return resp.choices[0].message.content.strip()
            except Exception:
                return resp['choices'][0]['message']['content'].strip()
        else:
            resp = client_legacy.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=400,
                temperature=0.6
            )
            return resp['choices'][0]['message']['content'].strip()
    except Exception as e:
        logger.exception("OpenAI error")
        return f"Errore OpenAI: {e}"

# ---------------- Persistence (data.json) ----------------
DEFAULT_DATA = {}  # structure: chat_id (str) -> user settings

def load_data() -> dict:
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                logger.info("Caricato data.json")
                return d
    except Exception:
        logger.exception("Impossibile caricare data.json")
    return {}

def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(user_data, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.exception("Errore salvataggio data.json")

user_data = load_data()

def ensure_user(chat_id: str):
    if chat_id not in user_data:
        # default watchlist: expanded list with Italian + Intl tickers
        default_watch = {
            "AAPL": None, "MSFT": None, "NVDA": None, "TSLA": None, "AMZN": None, "GOOG": None, "META": None,
            "BMPS.MI": None, "ENEL.MI": None, "ENI.MI": None, "ISP.MI": None, "UCG.MI": None,
            "BIDU": None, "BABA": None
        }
        user_data[chat_id] = {
            "watchlist": default_watch.copy(),
            "frequency_min": 60,       # default 1h
            "threshold_pct": 5.0,      # default 5%
            "active": True,            # monitoring active by default as requested
            "chat_ai": True,           # chat AI active by default
            "last_check_ts": 0,
            "awaiting_add": False,
            "awaiting_threshold": False
        }
        save_data()
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
        logger.exception("get_current_price error for %s", symbol)
        return None

def download_history(symbol: str, period: str = "1mo", interval: str = "1d"):
    try:
        return yf.Ticker(symbol).history(period=period, interval=interval)
    except Exception:
        logger.exception("download_history error for %s", symbol)
        return None

def build_chart(symbols, days=7):
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
        logger.exception("build_chart error")
        return None

# ---------------- Telegram helpers ----------------
def send_message(chat_id: str, text: str, reply_markup: dict = None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=15)
        if not r.ok:
            logger.warning("send_message failed: %s", r.text)
        return r
    except Exception:
        logger.exception("send_message exception")
        return None

def send_photo(chat_id: str, image_buf: BytesIO, caption: str = ""):
    try:
        files = {"photo": ("chart.png", image_buf.getvalue())}
        data = {"chat_id": chat_id, "caption": caption}
        r = requests.post(f"{TELEGRAM_API}/sendPhoto", files=files, data=data, timeout=30)
        if not r.ok:
            logger.warning("send_photo failed: %s", r.text)
        return r
    except Exception:
        logger.exception("send_photo exception")
        return None

def set_webhook():
    if not WEBHOOK_URL:
        logger.warning("WEBHOOK_URL non impostato")
        return False
    url = f"{TELEGRAM_API}/setWebhook?url={WEBHOOK_URL}/webhook"
    try:
        r = requests.get(url, timeout=15)
        logger.info("setWebhook response: %s", r.text)
        return r.ok
    except Exception:
        logger.exception("setWebhook error")
        return False

# ---------------- Monitoring logic ----------------
FREQ_OPTIONS = {
    "30m": 30,
    "1h": 60,
    "6h": 360,
    "1d": 1440,
    "1w": 10080
}

THRESH_PRESETS = [1.0, 3.0, 5.0, 10.0, 20.0]

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
            save_data()
            continue
        cur = get_current_price(symbol)
        if cur is None:
            continue
        pct = (cur - baseline) / baseline * 100
        if abs(pct) >= threshold:
            notifications.append((symbol, baseline, cur, pct))
            # update baseline to avoid repeat alerts for same move
            user_data[chat_id_str]["watchlist"][symbol] = cur
            save_data()
    for symbol, base, curr, pct in notifications:
        arrow = "▲" if pct > 0 else "▼"
        mood = "positivo" if pct > 0 else "negativo"
        text = (f"🔔 <b>Alert monitoraggio</b>\n"
                f"{symbol}\n"
                f"Prezzo precedente: {base:.2f}$\n"
                f"Prezzo attuale: {curr:.2f}$\n"
                f"Variazione: {arrow} {pct:.2f}% ({mood}) — soglia {threshold:.2f}%\n\n"
                "Consiglio: valuta il contesto e la tua strategia. Io fornisco info, non eseguo ordini.")
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
            if now - last >= freq * 60:
                try:
                    logger.info("Controllo watchlist per %s", chat_id_str)
                    check_and_notify_user(chat_id_str)
                    user_data[chat_id_str]["last_check_ts"] = now
                    save_data()
                except Exception:
                    logger.exception("Errore durante check user %s", chat_id_str)
        time.sleep(20)

monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
monitor_thread.start()

# ---------------- Keyboards ----------------
def freq_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "30 minuti", "callback_data": "freq|30"}],
            [{"text": "1 ora", "callback_data": "freq|60"}],
            [{"text": "6 ore", "callback_data": "freq|360"}],
            [{"text": "1 giorno", "callback_data": "freq|1440"}],
            [{"text": "1 settimana", "callback_data": "freq|10080"}],
            [{"text": "Disattiva", "callback_data": "freq|0"}],
        ]
    }

def threshold_keyboard():
    kb = {"inline_keyboard": []}
    for p in THRESH_PRESETS:
        kb["inline_keyboard"].append([{"text": f"{p}%", "callback_data": f"th|{p}"}])
    kb["inline_keyboard"].append([{"text": "Personalizzata", "callback_data": "th|custom"}])
    return kb

def watchlist_keyboard(chat_id_str: str):
    u = ensure_user(chat_id_str)
    kb = {"inline_keyboard": []}
    for symbol in u["watchlist"].keys():
        kb["inline_keyboard"].append([{"text": f"Rimuovi {symbol}", "callback_data": f"rm|{symbol}"}])
    kb["inline_keyboard"].append([{"text": "Aggiungi simbolo", "callback_data": "add_symbol"}])
    kb["inline_keyboard"].append([{"text": "Indietro", "callback_data": "menu"}])
    return kb

# ---------------- Flask app & webhook ----------------
app = Flask(__name__)

@app.route("/")
def root():
    return "AngelBot AI attivo ✅"

@app.route("/set_webhook", methods=["GET"])
def route_set_webhook():
    ok = set_webhook()
    return ("Webhook impostato" if ok else "Errore set webhook"), (200 if ok else 500)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    logger.debug("update: %s", data)

    # MESSAGE
    if "message" in data:
        msg = data["message"]
        chat_id = str(msg["chat"]["id"])
        text = msg.get("text", "").strip()
        ensure_user(chat_id)
        u = user_data[chat_id]

        # handle awaiting states
        if u.get("awaiting_add"):
            symbol = text.upper().strip()
            price = get_current_price(symbol)
            u["watchlist"][symbol] = price
            u["awaiting_add"] = False
            save_data()
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
                save_data()
                send_message(chat_id, f"✅ Soglia impostata su {val:.2f}%")
            except Exception:
                send_message(chat_id, "Valore non valido. Scrivi un numero (es. 3 o 7.5).")
            return jsonify(ok=True)

        # commands
        cmd = text.split(maxsplit=1)[0].lower() if text else ""
        if cmd == "/start":
            send_message(chat_id, (
                "Ciao 👋 Sono il tuo consulente finanziario.\n"
                "Usa i comandi o i pulsanti inline.\n"
                "Comandi principali:\n"
                "/add <SIMBOLO> — aggiungi un titolo\n"
                "/rm <SIMBOLO> — rimuovi\n"
                "/watchlist — mostra la lista\n"
                "/freq — imposta frequenza\n"
                "/th — imposta soglia\n"
                "/grafico <SIMBOLO> — grafico 7 giorni\n"
                "/analizza <SIMBOLO> — analisi + commento AI\n"
                "/ai <DOMANDA> — chat con AI\n"
            ))
            return jsonify(ok=True)

        if cmd == "/add" and len(text.split()) > 1:
            symbol = text.split(maxsplit=1)[1].upper().strip()
            price = get_current_price(symbol)
            u["watchlist"][symbol] = price
            save_data()
            if price:
                send_message(chat_id, f"✅ Aggiunto {symbol} con baseline {price:.2f}$")
            else:
                send_message(chat_id, f"✅ Aggiunto {symbol}. Baseline non disponibile ora.")
            return jsonify(ok=True)

        if cmd == "/rm" and len(text.split()) > 1:
            symbol = text.split(maxsplit=1)[1].upper().strip()
            removed = u["watchlist"].pop(symbol, None)
            save_data()
            if removed is None:
                send_message(chat_id, f"{symbol} non era nella tua watchlist.")
            else:
                send_message(chat_id, f"🗑️ Rimosso {symbol} dalla tua watchlist.")
            return jsonify(ok=True)

        if cmd == "/watchlist":
            items = u["watchlist"]
            if not items:
                send_message(chat_id, "La tua watchlist è vuota. Aggiungi con /add <SIMBOLO>")
            else:
                lines = [f"{s} — baseline: {('N/D' if b is None else f'{b:.2f}$')}" for s,b in items.items()]
                send_message(chat_id, "📋 La tua watchlist:\n" + "\n".join(lines), reply_markup=watchlist_keyboard(chat_id))
            return jsonify(ok=True)

        if cmd == "/freq":
            send_message(chat_id, "⏱️ Scegli la frequenza di monitoraggio:", reply_markup=freq_keyboard())
            return jsonify(ok=True)

        if cmd == "/th":
            send_message(chat_id, "⚖️ Scegli la soglia percentuale di alert:", reply_markup=threshold_keyboard())
            return jsonify(ok=True)

        if cmd == "/startmonitor":
            u["active"] = True
            u["frequency_min"] = u.get("frequency_min") or 60
            u["last_check_ts"] = 0
            save_data()
            send_message(chat_id, "✅ Monitoraggio automatico avviato.")
            return jsonify(ok=True)

        if cmd == "/stopmonitor":
            u["active"] = False
            save_data()
            send_message(chat_id, "⏸️ Monitoraggio automatico fermato.")
            return jsonify(ok=True)

        if cmd == "/grafico" and len(text.split()) > 1:
            symbol = text.split(maxsplit=1)[1].strip().upper()
            buf = build_chart([symbol], days=7)
            if buf:
                send_photo(chat_id, buf, caption=f"📈 Grafico ultimi 7 giorni: {symbol}")
            else:
                send_message(chat_id, f"⚠️ Impossibile generare grafico per {symbol}.")
            return jsonify(ok=True)

        if cmd == "/analizza" and len(text.split()) > 1:
            symbol = text.split(maxsplit=1)[1].strip().upper()
            df = download_history(symbol, period="1mo", interval="1d")
            if df is None or df.empty:
                send_message(chat_id, f"⚠️ Nessun dato disponibile per {symbol}.")
                return jsonify(ok=True)
            latest = df["Close"].iloc[-1]
            change_pct = (latest - df["Close"].iloc[0]) / df["Close"].iloc[0] * 100
            numeric = f"Prezzo attuale: {latest:.2f}$\nVariazione ultimo mese: {change_pct:.2f}%"
            prompt = f"Ho questi dati per {symbol}: {numeric}. Fornisci 2-3 frasi di analisi in italiano, tono consulente."
            ai_comment = ask_openai(prompt)
            buf = build_chart([symbol], days=30)
            if buf:
                send_photo(chat_id, buf, caption=f"{symbol}\n\n{numeric}\n\nConsulente:\n{ai_comment}")
            else:
                send_message(chat_id, f"{symbol}\n\n{numeric}\n\nConsulente:\n{ai_comment}")
            return jsonify(ok=True)

        if cmd == "/ai" and len(text.split()) > 1:
            question = text.split(maxsplit=1)[1].strip()
            answer = ask_openai(question)
            send_message(chat_id, answer)
            return jsonify(ok=True)

        # fallback: if chat_ai active, forward to OpenAI
        if u.get("chat_ai"):
            ans = ask_openai(text)
            send_message(chat_id, ans)
            return jsonify(ok=True)

        # naive ticker detection
        token = text.strip().upper()
        if token and (len(token) <= 6 and token.isalpha() or "." in token or token.isalnum()):
            price = get_current_price(token)
            if price is not None:
                send_message(chat_id, f"📈 {token} — prezzo attuale: {price:.2f}$\nUsa /analizza {token} per più dettagli.")
                return jsonify(ok=True)

        send_message(chat_id, "❓ Non riconosco il comando. Usa /start per la guida o /ai per parlare con il consulente.")
        return jsonify(ok=True)

    # CALLBACK_QUERY (inline buttons)
    if "callback_query" in data:
        cq = data["callback_query"]
        chat_id = str(cq["message"]["chat"]["id"])
        payload = cq["data"]
        ensure_user(chat_id)
        u = user_data[chat_id]

        if payload.startswith("freq|"):
            minutes = int(payload.split("|",1)[1])
            if minutes == 0:
                u["frequency_min"] = None
                u["active"] = False
                send_message(chat_id, "⏸️ Monitoraggio disattivato.")
            else:
                u["frequency_min"] = minutes
                u["active"] = True
                u["last_check_ts"] = 0
                send_message(chat_id, f"⏱️ Monitoraggio impostato ogni {minutes} minuti.")
            save_data()
            return jsonify(ok=True)

        if payload.startswith("th|"):
            val = payload.split("|",1)[1]
            if val == "custom":
                u["awaiting_threshold"] = True
                send_message(chat_id, "✍️ Scrivi la soglia percentuale desiderata (es. 7.5):")
            else:
                pct = float(val)
                u["threshold_pct"] = pct
                save_data()
                send_message(chat_id, f"✅ Soglia impostata su {pct:.2f}%")
            return jsonify(ok=True)

        if payload.startswith("rm|"):
            sym = payload.split("|",1)[1]
            removed = u["watchlist"].pop(sym, None)
            save_data()
            if removed is None:
                send_message(chat_id, f"ℹ️ {sym} non era in watchlist.")
            else:
                send_message(chat_id, f"🗑️ {sym} rimosso dalla watchlist.")
            return jsonify(ok=True)

        if payload == "add_symbol":
            u["awaiting_add"] = True
            send_message(chat_id, "✍️ Scrivi il simbolo da aggiungere (es. AAPL):")
            save_data()
            return jsonify(ok=True)

        if payload == "menu":
            send_message(chat_id, "🔙 Menu principale. Usa /start per le opzioni.")
            return jsonify(ok=True)

    return jsonify(ok=True)

# ---------------- Startup: attempt automatic webhook set ----------------
if __name__ == "__main__":
    # try to set webhook if WEBHOOK_URL present
    if WEBHOOK_URL:
        ok = set_webhook()
        if not ok:
            logger.warning("Impossibile impostare automaticamente il webhook; imposta manualmente con Telegram API.")
    port = int(os.getenv("PORT", 5000))
    logger.info("Avvio Flask su port %s", port)
    app.run(host="0.0.0.0", port=port)
