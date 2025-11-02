#!/usr/bin/env python3
# app.py — AngelBot AI (complete)
# - Save settings to data.json (persistence)
# - Monitor user watchlists in-memory + persistent
# - Frequencies: 30m, 1h, 6h, 1d, 1w
# - Threshold percent customizable per user
# - yfinance for data, matplotlib for charts
# - OpenAI integration (modern SDK or legacy fallback)
# - Telegram via HTTP API (webhook)

import os
import json
import time
import threading
import logging
from io import BytesIO
from datetime import datetime, timedelta

import requests
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from flask import Flask, request, jsonify

# ---------------- config & logging ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("angelbot")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://your-domain/path
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_TOKEN:
    raise RuntimeError("Devi impostare TELEGRAM_TOKEN nelle env vars")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

DATA_FILE = os.path.join(os.getcwd(), "data.json")

# ---------------- OpenAI client (modern + fallback) ----------------
USE_MODERN_OPENAI = False
client_modern = None
client_legacy = None
if OPENAI_API_KEY:
    try:
        # modern SDK
        from openai import OpenAI
        client_modern = OpenAI(api_key=OPENAI_API_KEY)
        USE_MODERN_OPENAI = True
        logger.info("OpenAI: using modern SDK")
    except Exception:
        import openai
        openai.api_key = OPENAI_API_KEY
        client_legacy = openai
        USE_MODERN_OPENAI = False
        logger.info("OpenAI: using legacy client")

def ask_openai(prompt, system="Sei un consulente finanziario esperto che risponde in italiano, prudente e chiaro."):
    """Sync call returning string. Uses modern SDK if available, else legacy."""
    if not OPENAI_API_KEY:
        return "⚠️ OpenAI non configurato. Imposta OPENAI_API_KEY per risposte AI."
    try:
        if USE_MODERN_OPENAI and client_modern:
            resp = client_modern.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.7
            )
            # try multiple access patterns for compat
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
                max_tokens=500,
                temperature=0.7
            )
            return resp['choices'][0]['message']['content'].strip()
    except Exception as e:
        logger.exception("OpenAI request failed")
        return f"Errore OpenAI: {e}"

# ---------------- persistence ----------------
default_data = {
    # chat_id (str) -> {
    #   "watchlist": { symbol: baseline_price or None },
    #   "frequency_min": int or None,
    #   "threshold_pct": float,
    #   "active": bool,
    #   "chat_ai": bool,
    #   "last_check_ts": float
    # }
}

def load_data():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                # keys were strings already — ensure floats for threshold
                for k, v in d.items():
                    if "threshold_pct" in v:
                        v["threshold_pct"] = float(v.get("threshold_pct", 5.0))
                logger.info("Loaded data.json")
                return d
    except Exception:
        logger.exception("Failed to load data.json")
    return {}

def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(user_data, f, ensure_ascii=False, indent=2)
        logger.debug("Saved data.json")
    except Exception:
        logger.exception("Failed to save data.json")

user_data = load_data()

def ensure_user(chat_id):
    key = str(chat_id)
    if key not in user_data:
        user_data[key] = {
            "watchlist": {},
            "frequency_min": None,
            "threshold_pct": 5.0,
            "active": False,
            "chat_ai": False,
            "last_check_ts": 0
        }
        save_data()
    return user_data[key]

# ---------------- finance helpers ----------------
def get_current_price(symbol):
    try:
        t = yf.Ticker(symbol)
        df = t.history(period="1d", interval="1d")
        if df is None or df.empty:
            return None
        return float(df["Close"].iloc[-1])
    except Exception:
        logger.exception("get_current_price %s", symbol)
        return None

def download_history(symbol, period="1mo", interval="1d"):
    try:
        return yf.Ticker(symbol).history(period=period, interval=interval)
    except Exception:
        logger.exception("download_history %s", symbol)
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

# ---------------- telegram helpers ----------------
def send_message(chat_id, text, reply_markup=None):
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

def send_photo(chat_id, image_buf, caption=""):
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
        logger.warning("WEBHOOK_URL not set")
        return False
    url = f"{TELEGRAM_API}/setWebhook?url={WEBHOOK_URL}/webhook"
    try:
        r = requests.get(url, timeout=15)
        logger.info("setWebhook response: %s", r.text)
        return r.ok
    except Exception:
        logger.exception("setWebhook error")
        return False

# ---------------- monitoring / alerts ----------------
def check_and_notify_user(chat_id_str):
    u = ensure_user(chat_id_str)
    if not u.get("active"):
        return
    threshold = float(u.get("threshold_pct", 5.0))
    to_notify = []
    for symbol, baseline in list(u["watchlist"].items()):
        if baseline is None:
            # try set baseline now
            current = get_current_price(symbol)
            if current is None:
                continue
            user_data[chat_id_str]["watchlist"][symbol] = current
            save_data()
            continue
        current = get_current_price(symbol)
        if current is None:
            continue
        pct = (current - baseline) / baseline * 100
        if abs(pct) >= threshold:
            to_notify.append((symbol, baseline, current, pct))
            # update baseline to current to avoid repeated alerts
            user_data[chat_id_str]["watchlist"][symbol] = current
            save_data()
    for symbol, base, curr, pct in to_notify:
        arrow = "▲" if pct > 0 else "▼"
        text = (f"🔔 <b>Alert monitoraggio</b>\n"
                f"{symbol}\n"
                f"Prezzo precedente: {base:.2f}$\n"
                f"Prezzo attuale: {curr:.2f}$\n"
                f"Variazione: {arrow} {pct:.2f}% (soglia {threshold:.2f}%)")
        send_message(chat_id_str, text)

def monitor_loop():
    logger.info("Monitor thread started")
    while True:
        now = time.time()
        for chat_id_str, u in list(user_data.items()):
            freq = u.get("frequency_min")
            if not u.get("active") or not freq:
                continue
            last = u.get("last_check_ts", 0)
            if now - last >= freq * 60:
                logger.info("Checking user %s", chat_id_str)
                try:
                    check_and_notify_user(chat_id_str)
                    user_data[chat_id_str]["last_check_ts"] = now
                    save_data()
                except Exception:
                    logger.exception("Error checking user %s", chat_id_str)
        time.sleep(20)

# start monitor thread
monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
monitor_thread.start()

# ---------------- keyboards ----------------
def freq_keyboard():
    return {
        "inline_keyboard": [
            [{"text":"30 minuti","callback_data":"freq|30"}],
            [{"text":"1 ora","callback_data":"freq|60"}],
            [{"text":"6 ore","callback_data":"freq|360"}],
            [{"text":"1 giorno","callback_data":"freq|1440"}],
            [{"text":"1 settimana","callback_data":"freq|10080"}],
            [{"text":"Disattiva","callback_data":"freq|0"}],
        ]
    }

def threshold_keyboard():
    kb = {"inline_keyboard": []}
    for p in [1.0, 3.0, 5.0, 10.0, 20.0]:
        kb["inline_keyboard"].append([{"text":f"{p}%", "callback_data":f"th|{p}"}])
    kb["inline_keyboard"].append([{"text":"Personalizzata", "callback_data":"th|custom"}])
    return kb

def watchlist_keyboard(chat_id_str):
    u = ensure_user(chat_id_str)
    kb = {"inline_keyboard": []}
    for symbol in u["watchlist"].keys():
        kb["inline_keyboard"].append([{"text":f"Rimuovi {symbol}", "callback_data":f"rm|{symbol}"}])
    kb["inline_keyboard"].append([{"text":"Aggiungi simbolo", "callback_data":"add_symbol"}])
    kb["inline_keyboard"].append([{"text":"Indietro", "callback_data":"menu"}])
    return kb

# ---------------- flask app + webhook ----------------
app = Flask(__name__)

@app.route("/")
def root():
    return "AngelBot AI attivo"

@app.route("/set_webhook", methods=["GET"])
def route_set_webhook():
    ok = set_webhook()
    return ("Webhook impostato" if ok else "Errore set webhook"), (200 if ok else 500)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    logger.debug("update: %s", data)

    # messages
    if "message" in data:
        msg = data["message"]
        chat_id = str(msg["chat"]["id"])
        text = msg.get("text", "").strip()
        ensure_user(chat_id)

        # handle awaiting custom flows
        u = user_data[chat_id]
        if u.get("awaiting_add"):
            symbol = text.upper().strip()
            price = get_current_price(symbol)
            u["watchlist"][symbol] = price
            u["awaiting_add"] = False
            save_data()
            if price:
                send_message(chat_id, f"Aggiunto {symbol} con baseline {price:.2f}$")
            else:
                send_message(chat_id, f"Aggiunto {symbol}. Baseline non disponibile ora.")
            return jsonify(ok=True)

        if u.get("awaiting_threshold"):
            try:
                val = float(text)
                u["threshold_pct"] = val
                u["awaiting_threshold"] = False
                save_data()
                send_message(chat_id, f"Soglia impostata su {val:.2f}%")
            except Exception:
                send_message(chat_id, "Valore non valido. Scrivi un numero come 3 o 7.5")
            return jsonify(ok=True)

        # commands
        if text.startswith("/start"):
            send_message(chat_id, ("Ciao — sono il tuo consulente finanziario.\n"
                                   "Usa i comandi o premi i pulsanti.\n"
                                   "Comandi utili:\n"
                                   "/add <SIMBOLO>\n"
                                   "/rm <SIMBOLO>\n"
                                   "/watchlist\n"
                                   "/freq\n"
                                   "/th\n"
                                   "/grafico <SIMBOLO>\n"
                                   "/analizza <SIMBOLO>\n"
                                   "/ai <DOMANDA>\n"
                                   "/startmonitor /stopmonitor"))
            return jsonify(ok=True)

        if text.startswith("/add "):
            symbol = text.split(maxsplit=1)[1].strip().upper()
            price = get_current_price(symbol)
            user_data[chat_id]["watchlist"][symbol] = price
            save_data()
            if price:
                send_message(chat_id, f"Aggiunto {symbol} con baseline {price:.2f}$")
            else:
                send_message(chat_id, f"Aggiunto {symbol}. Baseline non disponibile ora.")
            return jsonify(ok=True)

        if text.startswith("/rm "):
            symbol = text.split(maxsplit=1)[1].strip().upper()
            removed = user_data[chat_id]["watchlist"].pop(symbol, None)
            save_data()
            if removed is None:
                send_message(chat_id, f"{symbol} non era nella tua watchlist.")
            else:
                send_message(chat_id, f"Rimosso {symbol} dalla tua watchlist.")
            return jsonify(ok=True)

        if text.startswith("/watchlist"):
            items = user_data[chat_id]["watchlist"]
            if not items:
                send_message(chat_id, "La tua watchlist è vuota. Aggiungi con /add <SIMBOLO>")
            else:
                lines = [f"{s} — baseline: {('N/D' if b is None else f'{b:.2f}$')}" for s,b in items.items()]
                send_message(chat_id, "La tua watchlist:\n" + "\n".join(lines), reply_markup=watchlist_keyboard(chat_id))
            return jsonify(ok=True)

        if text.startswith("/freq"):
            send_message(chat_id, "Scegli frequenza di monitoraggio:", reply_markup=freq_keyboard())
            return jsonify(ok=True)

        if text.startswith("/th"):
            send_message(chat_id, "Scegli soglia percentuale:", reply_markup=threshold_keyboard())
            return jsonify(ok=True)

        if text.startswith("/startmonitor"):
            user_data[chat_id]["active"] = True
            user_data[chat_id]["frequency_min"] = user_data[chat_id].get("frequency_min") or 60
            user_data[chat_id]["last_check_ts"] = 0
            save_data()
            send_message(chat_id, "Monitoraggio avviato.")
            return jsonify(ok=True)

        if text.startswith("/stopmonitor"):
            user_data[chat_id]["active"] = False
            save_data()
            send_message(chat_id, "Monitoraggio fermato.")
            return jsonify(ok=True)

        if text.startswith("/grafico "):
            symbol = text.split(maxsplit=1)[1].strip().upper()
            buf = build_chart([symbol], days=7)
            if buf:
                send_photo(chat_id, buf, caption=f"Grafico ultimi 7 giorni per {symbol}")
            else:
                send_message(chat_id, f"Impossibile generare grafico per {symbol}.")
            return jsonify(ok=True)

        if text.startswith("/analizza "):
            symbol = text.split(maxsplit=1)[1].strip().upper()
            df = download_history(symbol, period="1mo", interval="1d")
            if df is None or df.empty:
                send_message(chat_id, f"Nessun dato per {symbol}.")
                return jsonify(ok=True)
            latest = df["Close"].iloc[-1]
            change_pct = (latest - df["Close"].iloc[0]) / df["Close"].iloc[0] * 100
            numeric = f"Prezzo attuale: {latest:.2f}$\nVariazione ultimo mese: {change_pct:.2f}%"
            prompt = f"Ho questi dati per {symbol}: {numeric}. Scrivi 2-3 frasi di analisi in italiano come un consulente."
            ai = ask_openai(prompt)
            buf = build_chart([symbol], days=30)
            if buf:
                send_photo(chat_id, buf, caption=f"{symbol}\n\n{numeric}\n\nConsulente:\n{ai}")
            else:
                send_message(chat_id, f"{symbol}\n\n{numeric}\n\nConsulente:\n{ai}")
            return jsonify(ok=True)

        if text.startswith("/ai "):
            question = text.split(maxsplit=1)[1].strip()
            answer = ask_openai(question)
            send_message(chat_id, answer)
            return jsonify(ok=True)

        # fallback: conversational mode if chat_ai true
        if user_data[chat_id].get("chat_ai"):
            ans = ask_openai(text)
            send_message(chat_id, ans)
            return jsonify(ok=True)

        # naive ticker detection
        token = text.strip().upper()
        if token and (len(token) <= 6 and token.isalpha() or "." in token or token.isalnum()):
            price = get_current_price(token)
            if price is not None:
                send_message(chat_id, f"{token} — prezzo attuale: {price:.2f}$\nUsa /analizza {token} per più info.")
                return jsonify(ok=True)

        send_message(chat_id, "Non riconosco il comando. Usa /start per la lista comandi.")
        return jsonify(ok=True)

    # callback_query handling (inline buttons)
    if "callback_query" in data:
        cq = data["callback_query"]
        chat_id = str(cq["message"]["chat"]["id"])
        payload = cq["data"]
        ensure_user(chat_id)

        if payload.startswith("freq|"):
            minutes = int(payload.split("|",1)[1])
            if minutes == 0:
                user_data[chat_id]["frequency_min"] = None
                user_data[chat_id]["active"] = False
                send_message(chat_id, "Monitoraggio disattivato.")
            else:
                user_data[chat_id]["frequency_min"] = minutes
                user_data[chat_id]["active"] = True
                user_data[chat_id]["last_check_ts"] = 0
                send_message(chat_id, f"Monitoraggio impostato ogni {minutes} minuti.")
            save_data()
            return jsonify(ok=True)

        if payload.startswith("th|"):
            val = payload.split("|",1)[1]
            if val == "custom":
                user_data[chat_id]["awaiting_threshold"] = True
                send_message(chat_id, "Scrivi la soglia percentuale desiderata (es. 7.5):")
            else:
                pct = float(val)
                user_data[chat_id]["threshold_pct"] = pct
                save_data()
                send_message(chat_id, f"Soglia impostata su {pct:.2f}%")
            return jsonify(ok=True)

        if payload.startswith("rm|"):
            sym = payload.split("|",1)[1]
            removed = user_data[chat_id]["watchlist"].pop(sym, None)
            save_data()
            if removed is None:
                send_message(chat_id, f"{sym} non era nella watchlist.")
            else:
                send_message(chat_id, f"{sym} rimosso.")
            return jsonify(ok=True)

        if payload == "add_symbol":
            user_data[chat_id]["awaiting_add"] = True
            send_message(chat_id, "Scrivi il simbolo da aggiungere (es. AAPL):")
            save_data()
            return jsonify(ok=True)

        if payload == "menu":
            send_message(chat_id, "Menu principale: usa /start")
            return jsonify(ok=True)

    return jsonify(ok=True)

# ---------------- start-up helper ----------------
if __name__ == "__main__":
    # try set webhook automatically if WEBHOOK_URL provided
    if WEBHOOK_URL:
        ok = set_webhook()
        if not ok:
            logger.warning("Could not set webhook automatically; set it manually via Telegram API.")
    port = int(os.getenv("PORT", 5000))
    logger.info("Starting Flask on port %s", port)
    app.run(host="0.0.0.0", port=port)
