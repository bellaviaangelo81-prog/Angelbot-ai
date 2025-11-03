# bot.py — AngelBot (YahooFinance + Telegram + OpenAI on demand)
# Funzionalità: menu categorie, ricerca simbolo/nome, grafici, analisi tecnica,
# preferiti per utente, notifiche periodiche, report giornaliero, AI su richiesta.

import os
import io
import json
import time
import threading
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# OpenAI (opzionale)
try:
    import openai
except Exception:
    openai = None

# ---------- CONFIG ----------
logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger("angelbot")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")  # obbligatorio
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # opzionale
if OPENAI_API_KEY and openai:
    openai.api_key = OPENAI_API_KEY

TZ = ZoneInfo("Europe/Rome")
DATA_FILE = "users.json"
CHECK_INTERVAL_MIN = int(os.getenv("CHECK_INTERVAL_MIN", "60"))  # default check ogni 60 minuti
NOTIF_PCT_DEFAULT = float(os.getenv("NOTIF_PCT_DEFAULT", "2.0"))
DAILY_REPORT_HOUR = int(os.getenv("DAILY_REPORT_HOUR", "9"))

BASE_TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
WEBHOOK_PATH = "/webhook"

# ---------- persistence ----------
def load_users():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            LOG.exception("Errore load_users")
    return {}

def save_users(u):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(u, f, ensure_ascii=False, indent=2)
    except Exception:
        LOG.exception("Errore save_users")

# ---------- telegram helpers ----------
def telegram_call(method, payload=None, files=None):
    url = f"{BASE_TELEGRAM_API}/{method}"
    try:
        if files:
            r = requests.post(url, data=payload, files=files, timeout=30)
        else:
            r = requests.post(url, json=payload, timeout=20)
        if not r.ok:
            LOG.warning("Telegram %s failed: %s", method, r.text)
        return r
    except Exception:
        LOG.exception("telegram_call exception")
        return None

def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return telegram_call("sendMessage", payload)

def send_photo_bytes(chat_id, img_bytes, caption=""):
    data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
    files = {"photo": ("chart.png", img_bytes)}
    return telegram_call("sendPhoto", payload=data, files=files)

def answer_callback(callback_id, text="", show_alert=False):
    return telegram_call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text, "show_alert": show_alert})

def set_commands():
    cmds = [
        {"command":"start","description":"Avvia AngelBot"},
        {"command":"help","description":"Guida rapida"},
        {"command":"analizza","description":"Analizza /analizza TICKER"},
        {"command":"watch","description":"/watch TICKER aggiungi ai preferiti"},
        {"command":"unwatch","description":"/unwatch TICKER rimuovi preferito"},
        {"command":"list","description":"Mostra preferiti"},
        {"command":"report","description":"Invia report giornaliero"}
    ]
    try:
        telegram_call("setMyCommands", {"commands": json.dumps(cmds)})
    except Exception:
        LOG.exception("set_commands failed")

# ---------- categories ----------
CATEGORIES = {
    "USA": ["AAPL","MSFT","AMZN","GOOG","TSLA","NVDA"],
    "EUROPA": ["SAP.DE","ASML.AS","AIR.PA","SAN.PA"],
    "ASIA": ["9988.HK","0700.HK","BABA","0700.SS"],
    "AFRICA": ["NPN.JO","SBK.JO"],
    "CRYPTO": ["BTC-USD","ETH-USD"],
    "FX": ["EURUSD=X","GBPUSD=X"]
}

# ---------- search (Yahoo) ----------
def search_ticker(query, limit=8):
    url = "https://query1.finance.yahoo.com/v1/finance/search"
    try:
        r = requests.get(url, params={"q": query, "quotesCount": limit, "newsCount": 0}, timeout=8)
        if r.ok:
            j = r.json()
            res = []
            for item in j.get("quotes", [])[:limit]:
                sym = item.get("symbol")
                name = item.get("shortname") or item.get("longname") or item.get("name") or ""
                if sym:
                    res.append({"symbol": sym, "name": name})
            return res
    except Exception:
        LOG.exception("search_ticker error")
    # fallback: assume query as symbol
    return [{"symbol": query.upper(), "name": query}]

# ---------- finance helpers & indicators ----------
def fetch_history(symbol, period="6mo", interval="1d"):
    try:
        t = yf.Ticker(symbol)
        df = t.history(period=period, interval=interval, actions=False)
        if df is None or df.empty:
            return None
        return df
    except Exception:
        LOG.exception("fetch_history %s failed", symbol)
        return None

def get_last_price(symbol):
    df = fetch_history(symbol, period="2d", interval="1d")
    if df is None or df.empty:
        return None
    return float(df["Close"].iloc[-1])

def sma(series, window):
    return series.rolling(window=window, min_periods=1).mean()

def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.rolling(period, min_periods=1).mean()
    ma_down = down.rolling(period, min_periods=1).mean()
    rs = ma_up / (ma_down + 1e-9)
    return 100 - (100 / (1 + rs))

def macd(series):
    macd_line = ema(series, 12) - ema(series, 26)
    signal = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal
    return macd_line, signal, hist

def fundamental_summary(symbol):
    try:
        t = yf.Ticker(symbol)
        info = t.info if hasattr(t, "info") else {}
        return {
            "pe": info.get("trailingPE") or info.get("forwardPE"),
            "eps": info.get("trailingEps"),
            "marketcap": info.get("marketCap"),
            "sector": info.get("sector"),
            "dividend_yield": info.get("dividendYield")
        }
    except Exception:
        LOG.exception("fundamental_summary fail for %s", symbol)
        return {}

def detect_trend(df):
    close = df["Close"]
    ma50 = float(sma(close, 50).iloc[-1]) if len(close) >= 5 else float(sma(close, max(1,len(close))).iloc[-1])
    ma200 = float(sma(close, 200).iloc[-1]) if len(close) >= 50 else float(sma(close, max(1,len(close))).iloc[-1])
    trend = "neutrale"
    if ma50 > ma200 * 1.01:
        trend = "rialzista"
    elif ma50 < ma200 * 0.99:
        trend = "ribassista"
    return {"ma50": ma50, "ma200": ma200, "trend": trend}

def build_chart_bytes(symbol, period="3mo"):
    df = fetch_history(symbol, period=period, interval="1d")
    if df is None or df.empty:
        return None
    try:
        fig, ax = plt.subplots(figsize=(8,4))
        ax.plot(df.index, df["Close"], label="Close", linewidth=1.6)
        if len(df) >= 5:
            ax.plot(df.index, sma(df["Close"],50), label="SMA50", linestyle="--", linewidth=1)
        if len(df) >= 50:
            ax.plot(df.index, sma(df["Close"],200), label="SMA200", linestyle="--", linewidth=1)
        ax.set_title(f"{symbol.upper()} — {period}")
        ax.set_xlabel("Data")
        ax.set_ylabel("Prezzo")
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.legend(loc="upper left", fontsize="small")
        buf = io.BytesIO()
        fig.tight_layout()
        fig.savefig(buf, format="png")
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()
    except Exception:
        LOG.exception("build_chart_bytes fail for %s", symbol)
        return None

# ---------- AI commentary (on demand) ----------
def ai_commentary(symbol, fundamentals, technical, recent_pct):
    prompt = (
        f"Sei un analista finanziario che parla italiano. Commenta in modo sintetico {symbol} "
        f"con queste informazioni: trend {technical.get('trend')}, SMA50 {technical.get('ma50'):.2f}, SMA200 {technical.get('ma200'):.2f}, "
        f"variazione recente {recent_pct:.2f}%, fondamentali P/E={fundamentals.get('pe')}, EPS={fundamentals.get('eps')}."
        "Forni 3 punti: situazione, rischio principale, indicatore da monitorare. Termina con frase indicativa (non consulenza)."
    )
    if openai and OPENAI_API_KEY:
        try:
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[{"role":"system","content":"Sei un analista finanziario esperto."},
                          {"role":"user","content":prompt}],
                max_tokens=300, temperature=0.3
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            LOG.exception("openai failed in ai_commentary")
    # fallback
    return f"{symbol.upper()} trend {technical.get('trend')}. Variazione recent {recent_pct:.2f}%. Monitorare SMA50/SMA200 e RSI."

# ---------- keyboards ----------
MAIN_KEYBOARD = {"keyboard":[[{"text":"💬 Chat AI"},{"text":"🔍 Cerca"}],[{"text":"📂 Categorie"},{"text":"⭐ Preferiti"}],[{"text":"📊 Analisi"},{"text":"🧾 Report Giornaliero"}],[{"text":"🏠 Menu principale"}]], "resize_keyboard": True}
CATEGORIES_KB = {"keyboard":[[{"text":"🇺🇸 USA"},{"text":"🇪🇺 Europa"}],[{"text":"🇨🇳 Asia"},{"text":"🌍 Africa"}],[{"text":"💹 Crypto"},{"text":"💱 Valute"}],[{"text":"🏠 Menu principale"}]], "resize_keyboard": True}
def inline_ai_button(symbol):
    return {"inline_keyboard":[[{"text":"🧠 Analisi AI","callback_data":f"AI|{symbol.upper()}"}]]}

def inline_search_results(results):
    kb = {"inline_keyboard":[]}
    for item in results:
        sym = item.get("symbol")
        name = item.get("name") or ""
        kb["inline_keyboard"].append([{"text":f"{sym} — {name[:30]}", "callback_data":f"SEL|{sym}"}])
    return kb

# ---------- analysis formatting ----------
def format_analysis(symbol):
    df = fetch_history(symbol, period="6mo", interval="1d")
    if df is None or df.empty:
        return None
    close = df["Close"]
    latest = float(close.iloc[-1])
    first = float(close.iloc[0])
    pct_6m = (latest - first) / first * 100.0
    tech = detect_trend(df)
    macd_line, signal_line, hist = macd(close)
    rsi_val = float(rsi(close).iloc[-1]) if len(close) >= 14 else None
    fundamentals = fundamental_summary(symbol)
    signals = []
    if rsi_val is not None:
        if rsi_val < 30:
            signals.append("IPERVENDUTO (RSI<30)")
        elif rsi_val > 70:
            signals.append("IPERCOMPRATO (RSI>70)")
    vol7 = float(close.pct_change().rolling(7).std().iloc[-1]) * 100 if len(close) >= 7 else 0.0
    vol30 = float(close.pct_change().rolling(30).std().iloc[-1]) * 100 if len(close) >= 30 else 0.0
    return {
        "symbol": symbol.upper(),
        "latest": latest,
        "pct_6m": pct_6m,
        "rsi": rsi_val,
        "macd_hist": float(hist.iloc[-1]) if len(hist)>0 else None,
        "vol7_pct": vol7,
        "vol30_pct": vol30,
        "fundamentals": fundamentals,
        "technical": tech,
        "signals": signals
    }

def build_analysis_message(summary):
    s = summary
    lines = [f"📊 <b>Analisi per {s['symbol']}</b>"]
    lines.append(f"- Prezzo attuale: <b>{s['latest']:.2f}$</b>")
    lines.append(f"- Variazione 6m: {s['pct_6m']:+.2f}%")
    if s.get("rsi") is not None:
        lines.append(f"- RSI(14): {s['rsi']:.2f}")
    lines.append(f"- Trend tecnico: <b>{s['technical']['trend']}</b> (SMA50={s['technical']['ma50']:.2f}, SMA200={s['technical']['ma200']:.2f})")
    lines.append(f"- Volatilità 7d: {s['vol7_pct']:.2f}% — 30d: {s['vol30_pct']:.2f}%")
    if s.get("signals"):
        lines.append("- Segnali: " + ", ".join(s["signals"]))
    f = s.get("fundamentals", {})
    if f:
        lines.append(f"- Fondamentali: P/E={f.get('pe')}, EPS={f.get('eps')}, MarketCap={f.get('marketcap')}")
    lines.append("\n<i>Nota: informazione di carattere informativo, non consulenza finanziaria.</i>")
    return "\n".join(lines)

# ---------- background notify & daily report ----------
def notify_loop():
    LOG.info("Notify loop avviato, interval min: %s", CHECK_INTERVAL_MIN)
    last_prices = {}
    while True:
        users = load_users()
        for chat_id, u in list(users.items()):
            if chat_id.startswith("_"):  # internal keys
                continue
            favs = u.get("favorites", [])
            notifs = u.get("notifications", {})
            for sym in favs:
                try:
                    price = get_last_price(sym)
                    if price is None:
                        continue
                    key = f"{chat_id}:{sym}"
                    prev = last_prices.get(key)
                    cfg = notifs.get(sym, {})
                    pct_thr = float(cfg.get("pct", NOTIF_PCT_DEFAULT))
                    baseline = cfg.get("baseline", prev or price)
                    if baseline is None:
                        cfg["baseline"] = price
                        notifs[sym] = cfg
                        users[chat_id]["notifications"] = notifs
                        save_users(users)
                        continue
                    change = (price - float(baseline)) / float(baseline) * 100.0
                    send_flag = False
                    if abs(change) >= pct_thr:
                        last_ts = cfg.get("last_notif_ts", 0)
                        if last_ts:
                            last_dt = datetime.fromtimestamp(int(last_ts), TZ)
                            if (datetime.now(TZ) - last_dt) < timedelta(minutes=CHECK_INTERVAL_MIN):
                                send_flag = False
                            else:
                                send_flag = True
                        else:
                            send_flag = True
                    if send_flag:
                        arrow = "▲" if change > 0 else "▼"
                        caption = (f"🔔 <b>Notifica</b>\n{sym}\nPrezzo riferimento: {baseline:.2f}$\nPrezzo attuale: {price:.2f}$\nVariazione: {arrow} {change:.2f}% (soglia {pct_thr}%)")
                        img = build_chart_bytes(sym, period="1mo")
                        if img:
                            send_photo_bytes(chat_id, img, caption)
                        else:
                            send_message(chat_id, caption)
                        cfg["last_notif_ts"] = int(time.time())
                        cfg["baseline"] = price
                        notifs[sym] = cfg
                        users[chat_id]["notifications"] = notifs
                        save_users(users)
                    last_prices[key] = price
                except Exception:
                    LOG.exception("notify error for %s %s", chat_id, sym)
        # daily report once per day at hour
        now = datetime.now(TZ)
        if now.hour == DAILY_REPORT_HOUR and now.minute < 2:
            users_all = load_users()
            last_daily = users_all.get("_last_daily_ts", 0)
            if not last_daily or (datetime.now(TZ) - datetime.fromtimestamp(int(last_daily), TZ)) > timedelta(hours=20):
                for cid in list(users_all.keys()):
                    if cid.startswith("_"):
                        continue
                    try:
                        send_daily_report_to_user(cid)
                    except Exception:
                        LOG.exception("daily report fail for %s", cid)
                users_all["_last_daily_ts"] = int(time.time())
                save_users(users_all)
        time.sleep(CHECK_INTERVAL_MIN * 60)

def send_daily_report_to_user(chat_id):
    users = load_users()
    u = users.get(chat_id, {})
    favs = u.get("favorites", [])
    header = f"🗞️ <b>Report giornaliero</b> — {datetime.now(TZ).strftime('%d/%m %H:%M')}\n"
    if not favs:
        send_message(chat_id, header + "Nessun preferito. Aggiungine con /watch TICKER")
        return
    scored = []
    for s in favs:
        try:
            summ = format_analysis(s)
            if summ is None:
                continue
            score = 0.0
            if summ.get("rsi") is not None:
                if summ["rsi"] < 35: score += 1.5
                elif summ["rsi"] > 70: score -= 1.5
            if summ["technical"]["trend"] == "rialzista": score += 1.2
            elif summ["technical"]["trend"] == "ribassista": score -= 1.2
            score += (summ.get("pct_6m",0)/100.0)
            scored.append((s, score, summ))
        except Exception:
            LOG.exception("score fail for %s", s)
    scored.sort(key=lambda x: x[1], reverse=True)
    lines = [header]
    for sym, score, summ in scored[:8]:
        status = ""
        if summ.get("signals"):
            status = " — " + ", ".join(summ["signals"])
        lines.append(f"• <b>{sym}</b>: {summ['latest']:.2f}$; trend {summ['technical']['trend']}{status}")
    send_message(chat_id, "\n".join(lines))
    # optional AI short commentary for top 3 if enabled
    if OPENAI_API_KEY and openai and u.get("daily_ai", True):
        top3 = scored[:3]
        if top3:
            prompt = "Sei un analista. Dai un commento sintetico e prudente per questi titoli:\n"
            for sym, score, summ in top3:
                prompt += f"{sym}: price {summ['latest']:.2f}, trend {summ['technical']['trend']}, RSI {summ.get('rsi')}\n"
            try:
                resp = openai.ChatCompletion.create(
                    model="gpt-4o-mini",
                    messages=[{"role":"system","content":"Sei un analista finanziario esperto."},{"role":"user","content":prompt}],
                    max_tokens=220, temperature=0.35
                )
                comment = resp.choices[0].message.content.strip()
                send_message(chat_id, "🧠 <b>Commento AI giornaliero</b>:\n" + comment)
            except Exception:
                LOG.exception("openai daily failed")

# ---------- Flask webhook ----------
from flask import Flask, request, jsonify
app = Flask(__name__)

@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    if not data:
        return jsonify({"ok": False})
    # handle callback_query first (inline buttons)
    if "callback_query" in data:
        cq = data["callback_query"]
        cb_id = cq.get("id")
        cb_data = cq.get("data", "")
        msg = cq.get("message", {}) or {}
        chat = msg.get("chat", {}) or {}
        chat_id = str(chat.get("id"))
        # ack
        answer_callback(cb_id, text="Elaboro...", show_alert=False)
        if cb_data.startswith("AI|"):
            _, sym = cb_data.split("|",1)
            try:
                df = fetch_history(sym, period="6mo", interval="1d")
                if not df:
                    send_message(chat_id, f"⚠️ Dati non disponibili per {sym}")
                else:
                    close = df["Close"]
                    recent_pct = (float(close.iloc[-1]) - float(close.iloc[0])) / float(close.iloc[0]) * 100.0
                    technical = detect_trend(df)
                    fundamentals = fundamental_summary(sym)
                    commentary = ai_commentary(sym, fundamentals, technical, recent_pct)
                    send_message(chat_id, f"🧠 <b>Analisi AI — {sym}</b>\n\n{commentary}")
            except Exception:
                LOG.exception("AI callback failed")
                send_message(chat_id, "Errore generando analisi AI.")
        elif cb_data.startswith("SEL|"):
            _, sym = cb_data.split("|",1)
            try:
                summ = format_analysis(sym)
                if not summ:
                    send_message(chat_id, f"Dati non disponibili per {sym}")
                else:
                    send_message(chat_id, build_analysis_message(summ), reply_markup=inline_ai_button(sym))
                    img = build_chart_bytes(sym, period="3mo")
                    if img:
                        send_photo_bytes(chat_id, img, f"Grafico {sym}")
            except Exception:
                LOG.exception("SEL callback")
                send_message(chat_id, "Errore nella selezione.")
        return jsonify({"ok": True})

    # normal message handling
    message = data.get("message") or {}
    if not message:
        return jsonify({"ok": True})
    chat = message.get("chat", {})
    chat_id = str(chat.get("id"))
    text = (message.get("text") or "").strip()
    if not text:
        return jsonify({"ok": True})
    LOG.info("Msg from %s: %s", chat_id, text)
    users = load_users()
    if chat_id not in users:
        users[chat_id] = {"favorites": [], "notifications": {}, "mode": None, "context": [], "daily_ai": True}
        save_users(users)

    # commands
    if text.startswith("/start") or text == "🏠 Menu principale":
        send_message(chat_id, "👋 Ciao — sono AngelBot. Usa i pulsanti o digita simbolo/nome.", reply_markup=MAIN_KEYBOARD)
        return jsonify({"ok": True})
    if text.startswith("/help"):
        send_message(chat_id, "Aiuto: /analizza TICKER, /watch TICKER, /unwatch TICKER, /list, oppure usa i pulsanti.")
        return jsonify({"ok": True})
    if text.startswith("/analizza"):
        parts = text.split()
        if len(parts) >= 2:
            sym = parts[1].upper()
            summ = format_analysis(sym)
            if not summ:
                send_message(chat_id, "Dati non disponibili per " + sym)
            else:
                send_message(chat_id, build_analysis_message(summ), reply_markup=inline_ai_button(sym))
                img = build_chart_bytes(sym, period="6mo")
                if img:
                    send_photo_bytes(chat_id, img, f"Grafico {sym}")
        else:
            send_message(chat_id, "Uso: /analizza TICKER")
        return jsonify({"ok": True})
    if text.startswith("/watch"):
        parts = text.split()
        if len(parts) >= 2:
            sym = parts[1].upper()
            users[chat_id].setdefault("favorites", [])
            if sym not in users[chat_id]["favorites"]:
                users[chat_id]["favorites"].append(sym)
                users[chat_id].setdefault("notifications", {})
                users[chat_id]["notifications"][sym] = {"pct": NOTIF_PCT_DEFAULT, "baseline": None, "last_notif_ts": 0}
                save_users(users)
                send_message(chat_id, f"✅ {sym} aggiunto ai preferiti.")
            else:
                send_message(chat_id, f"{sym} è già nei preferiti.")
        else:
            send_message(chat_id, "Uso: /watch TICKER")
        return jsonify({"ok": True})
    if text.startswith("/unwatch"):
        parts = text.split()
        if len(parts) >= 2:
            sym = parts[1].upper()
            if sym in users[chat_id].get("favorites", []):
                users[chat_id]["favorites"].remove(sym)
                users[chat_id].get("notifications", {}).pop(sym, None)
                save_users(users)
                send_message(chat_id, f"🗑️ {sym} rimosso dai preferiti.")
            else:
                send_message(chat_id, f"{sym} non è nei preferiti.")
        else:
            send_message(chat_id, "Uso: /unwatch TICKER")
        return jsonify({"ok": True})
    if text.startswith("/list"):
        favs = users[chat_id].get("favorites", [])
        send_message(chat_id, "Preferiti:\n" + ("\n".join(favs) if favs else "Nessuno"))
        return jsonify({"ok": True})
    if text.startswith("/notify"):
        parts = text.split()
        if len(parts) >= 3:
            sym = parts[1].upper()
            try:
                pct = float(parts[2])
                users[chat_id].setdefault("notifications", {})
                users[chat_id]["notifications"].setdefault(sym, {})["pct"] = pct
                save_users(users)
                send_message(chat_id, f"Soglia notifiche per {sym} impostata a {pct}%")
            except Exception:
                send_message(chat_id, "Formato soglia non valido.")
        else:
            send_message(chat_id, "Uso: /notify TICKER PCT")
        return jsonify({"ok": True})
    if text in ["📂 Categorie","📂 Categorie mercati","🔍 Categorie"]:
        send_message(chat_id, "Scegli categoria:", reply_markup=CATEGORIES_KB)
        return jsonify({"ok": True})
    if text in ["🇺🇸 USA","🇪🇺 Europa","🇨🇳 Asia","🌍 Africa","💹 Crypto","💱 Valute"]:
        mapping = {"🇺🇸 USA":"USA","🇪🇺 Europa":"EUROPA","🇨🇳 Asia":"ASIA","🌍 Africa":"AFRICA","💹 Crypto":"CRYPTO","💱 Valute":"FX"}
        cat = mapping.get(text)
        syms = CATEGORIES.get(cat, [])
        if not syms:
            send_message(chat_id, "Nessun simbolo in questa categoria.")
        else:
            res = [{"symbol":s,"name":""} for s in syms]
            send_message(chat_id, f"Simboli in {cat}:")
            kb = inline_search_results(res)
            send_message(chat_id, "Scegli per analizzare:", reply_markup=kb)
        return jsonify({"ok": True})
    if text in ["🔍 Cerca","🔎 Ricerca simbolo/nome"]:
        users[chat_id]["mode"] = "search"
        save_users(users)
        send_message(chat_id, "🔎 Scrivi simbolo o nome (es. AAPL o Apple).")
        return jsonify({"ok": True})
    if text == "💬 Chat AI":
        users[chat_id]["mode"] = "chat"
        save_users(users)
        send_message(chat_id, "🧠 Modalità Chat AI attiva. Parla pure.")
        return jsonify({"ok": True})
    if text in ["📊 Analisi","🔍 Analisi"]:
        users[chat_id]["mode"] = "analysis_prompt"
        save_users(users)
        send_message(chat_id, "🔍 Inserisci il ticker da analizzare (es. AAPL) o usa /analizza TICKER")
        return jsonify({"ok": True})
    if text in ["🧾 Report Giornaliero","🧾 Report","/report"]:
        send_daily_report_to_user(chat_id)
        return jsonify({"ok": True})

    # modes
    mode = users[chat_id].get("mode")
    if mode == "search":
        q = text.strip()
        results = search_ticker(q, limit=6)
        users[chat_id]["mode"] = None
        save_users(users)
        if not results:
            send_message(chat_id, "Nessun risultato. Riprova con nome o simbolo diverso.")
        else:
            kb = inline_search_results(results)
            send_message(chat_id, f"Risultati per <b>{q}</b>:", reply_markup=kb)
        return jsonify({"ok": True})
    if mode == "chat":
        # context simple
        ctx = users[chat_id].setdefault("context", [])
        ctx.append({"role":"user","content":text,"ts":int(time.time())})
        users[chat_id]["context"] = ctx[-12:]
        save_users(users)
        reply = None
        if openai and OPENAI_API_KEY:
            try:
                messages = [{"role":"system","content":"Sei AngelBot, analista finanziario che risponde in italiano in modo chiaro e prudente."}]
                messages += [{"role":m["role"], "content":m["content"]} for m in users[chat_id]["context"]]
                resp = openai.ChatCompletion.create(model="gpt-4o-mini", messages=messages, max_tokens=300, temperature=0.3)
                reply = resp.choices[0].message.content.strip()
            except Exception:
                LOG.exception("openai chat fail")
        if not reply:
            reply = "Ricevuto. Posso fare analisi con /analizza TICKER o ricerca con 🔍 Cerca."
        ctx.append({"role":"assistant","content":reply,"ts":int(time.time())})
        users[chat_id]["context"] = ctx[-12:]
        save_users(users)
        send_message(chat_id, reply)
        return jsonify({"ok": True})
    if mode == "analysis_prompt":
        sym = text.strip().upper().split()[0]
        users[chat_id]["mode"] = None
        save_users(users)
        summ = format_analysis(sym)
        if not summ:
            send_message(chat_id, "Dati non disponibili per " + sym)
        else:
            send_message(chat_id, build_analysis_message(summ), reply_markup=inline_ai_button(sym))
            img = build_chart_bytes(sym, period="6mo")
            if img:
                send_photo_bytes(chat_id, img, f"Grafico {sym}")
        return jsonify({"ok": True})

    # final heuristics: if user types ticker-like or name
    if (len(text) <= 6 and text.isupper()) or any(ch.isdigit() for ch in text):
        sym = text.upper().split()[0]
        summ = format_analysis(sym)
        if summ:
            send_message(chat_id, build_analysis_message(summ), reply_markup=inline_ai_button(sym))
            img = build_chart_bytes(sym, period="3mo")
            if img:
                send_photo_bytes(chat_id, img, f"Grafico {sym}")
        else:
            results = search_ticker(text, limit=6)
            if results:
                kb = inline_search_results(results)
                send_message(chat_id, "Forse intendevi:", reply_markup=kb)
            else:
                send_message(chat_id, "Simbolo non trovato.")
        return jsonify({"ok": True})
    # otherwise search by name:
    results = search_ticker(text, limit=6)
    if results:
        kb = inline_search_results(results)
        send_message(chat_id, f"Risultati per <b>{text}</b>:", reply_markup=kb)
    else:
        send_message(chat_id, "Nessun risultato. Prova con simbolo o nome differente.")
    return jsonify({"ok": True})

@app.route("/")
def home():
    try:
        set_commands()
    except Exception:
        pass
    return "AngelBot attivo 🚀"

# ---------- start background worker ----------
def start_workers():
    t = threading.Thread(target=notify_loop, daemon=True)
    t.start()
    LOG.info("Worker notifiche avviato")

if __name__ == "__main__":
    start_workers()
    # run with Flask (Render gestisce gunicorn)
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
