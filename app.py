# app.py — AngelBot (grande analista): categorie, ricerca, AI su richiesta, preferiti, notifiche, report giornaliero
import os
import io
import json
import time
import math
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

try:
    import openai
except Exception:
    openai = None

# ---------------- CONFIG ----------------
logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger("angelbot")

BOT_TOKEN = os.getenv("BOT_TOKEN")            # REQUIRED
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # optional (for AI commentary)
if OPENAI_API_KEY and openai:
    openai.api_key = OPENAI_API_KEY

TZ = ZoneInfo("Europe/Rome")
DATA_FILE = "users.json"
CHECK_INTERVAL_MIN = int(os.getenv("CHECK_INTERVAL_MIN", "60"))
NOTIF_PCT_DEFAULT = float(os.getenv("NOTIF_PCT_DEFAULT", "2.0"))
DAILY_REPORT_HOUR = int(os.getenv("DAILY_REPORT_HOUR", "9"))

BASE_TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
WEBHOOK_PATH = "/webhook"

# ---------------- PERSISTENCE ----------------
def load_users():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            LOGGER.exception("load_users failed")
    return {}

def save_users(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        LOGGER.exception("save_users failed")

# ---------------- TELEGRAM HELPERS ----------------
def telegram_call(method: str, payload: dict = None, files: dict = None):
    url = f"{BASE_TELEGRAM_API}/{method}"
    try:
        if files:
            r = requests.post(url, data=payload, files=files, timeout=30)
        else:
            r = requests.post(url, json=payload, timeout=20)
        if not r.ok:
            LOGGER.warning("Telegram %s error: %s", method, r.text)
        return r
    except Exception:
        LOGGER.exception("telegram_call exception")
        return None

def send_message(chat_id: str, text: str, reply_markup: dict = None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return telegram_call("sendMessage", payload)

def send_photo_bytes(chat_id: str, img_bytes: bytes, caption: str = ""):
    data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
    files = {"photo": ("chart.png", img_bytes)}
    return telegram_call("sendPhoto", payload=data, files=files)

def answer_callback(callback_query_id: str, text: str = "", show_alert: bool = False):
    return telegram_call("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text, "show_alert": show_alert})

def set_my_commands():
    cmds = [
        {"command": "start", "description": "Avvia AngelBot"},
        {"command": "help", "description": "Mostra guida rapida"},
        {"command": "analizza", "description": "Analizza: /analizza TICKER"},
        {"command": "watch", "description": "Aggiungi preferito: /watch TICKER"},
        {"command": "unwatch", "description": "Rimuovi preferito: /unwatch TICKER"},
        {"command": "list", "description": "Mostra i preferiti"},
        {"command": "report", "description": "Report giornaliero"}
    ]
    try:
        telegram_call("setMyCommands", {"commands": json.dumps(cmds)})
    except Exception:
        LOGGER.exception("set_my_commands failed")

# ---------------- CATEGORIES ----------------
CATEGORIES = {
    "USA": ["AAPL", "MSFT", "AMZN", "GOOG", "TSLA", "NVDA"],
    "EUROPA": ["SAP.DE", "SAN.PA", "BN.PA", "AIR.PA", "ASML.AS"],
    "ASIA": ["9988.HK", "0700.HK", "0005.HK", "BABA", "0700.SS"],
    "AFRICA": ["NPN.JO", "SBK.JO"],  # examples; yfinance symbols vary by exchange
    "CRYPTO": ["BTC-USD", "ETH-USD", "BNB-USD"],
    "FX": ["EURUSD=X", "JPY=X", "GBPUSD=X"]
}

# ---------------- SEARCH (symbol or name) using Yahoo Search endpoint ----------------
def search_ticker(query: str, limit: int = 8):
    """Return list of matches: each is dict with 'symbol' and 'shortname'."""
    try:
        url = "https://query1.finance.yahoo.com/v1/finance/search"
        r = requests.get(url, params={"q": query, "lang": "en-US", "region": "US", "quotesCount": limit, "newsCount": 0}, timeout=10)
        if r.ok:
            j = r.json()
            res = []
            for q in j.get("quotes", []) + j.get("news", []):
                pass
            # primarily use 'quotes'
            for item in j.get("quotes", [])[:limit]:
                symbol = item.get("symbol")
                name = item.get("shortname") or item.get("longname") or item.get("name") or item.get("quoteType")
                if symbol:
                    res.append({"symbol": symbol, "name": name})
            return res
    except Exception:
        LOGGER.exception("search_ticker failed for %s", query)
    # fallback: if query looks like ticker, return it raw
    return [{"symbol": query.upper(), "name": query}]

# ---------------- FINANCE HELPERS ----------------
def fetch_history(symbol: str, period: str = "6mo", interval: str = "1d"):
    try:
        t = yf.Ticker(symbol)
        df = t.history(period=period, interval=interval, actions=False)
        if df is None or df.empty:
            return None
        return df
    except Exception:
        LOGGER.exception("fetch_history fail for %s", symbol)
        return None

def get_last_price(symbol: str):
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

def macd(series, fast=12, slow=26, signal=9):
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def fundamental_summary(symbol: str):
    try:
        t = yf.Ticker(symbol)
        info = t.info if hasattr(t, "info") else {}
        pe = info.get("trailingPE") or info.get("forwardPE")
        eps = info.get("trailingEps") or info.get("epsTrailingTwelveMonths")
        marketcap = info.get("marketCap")
        sector = info.get("sector") or info.get("industry")
        div_yield = info.get("dividendYield")
        return {"pe": pe, "eps": eps, "marketcap": marketcap, "sector": sector, "dividend_yield": div_yield}
    except Exception:
        LOGGER.exception("fundamental_summary fail %s", symbol)
        return {}

def detect_trend(df):
    close = df["Close"]
    ma50 = float(sma(close, 50).iloc[-1]) if len(close) >= 5 else float(sma(close, min(50, len(close))).iloc[-1])
    ma200 = float(sma(close, 200).iloc[-1]) if len(close) >= 50 else float(sma(close, max(1, len(close))).iloc[-1])
    trend = "neutrale"
    if ma50 > ma200 * 1.01:
        trend = "rialzista"
    elif ma50 < ma200 * 0.99:
        trend = "ribassista"
    return {"ma50": ma50, "ma200": ma200, "trend": trend}

def build_chart_bytes(symbol: str, period="3mo"):
    df = fetch_history(symbol, period=period, interval="1d")
    if df is None or df.empty:
        return None
    try:
        fig, ax = plt.subplots(figsize=(8,4))
        ax.plot(df.index, df["Close"], label="Close", linewidth=1.8)
        ax.set_title(f"{symbol.upper()} — {period}")
        ax.set_xlabel("Data")
        ax.set_ylabel("Prezzo")
        ax.grid(True, linestyle="--", alpha=0.4)
        if len(df) >= 5:
            ax.plot(df.index, sma(df["Close"], 50), label="SMA50", linestyle="--", linewidth=1)
        if len(df) >= 50:
            ax.plot(df.index, sma(df["Close"], 200), label="SMA200", linestyle="--", linewidth=1)
        ax.legend(loc="upper left", fontsize="small")
        buf = io.BytesIO()
        fig.tight_layout()
        fig.savefig(buf, format="png")
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()
    except Exception:
        LOGGER.exception("build_chart_bytes fail for %s", symbol)
        return None

# ---------------- AI COMMENTARY (on demand) ----------------
def ai_commentary(symbol: str, fundamentals: dict, technical: dict, recent_pct: float):
    prompt = (
        f"Sei un analista finanziario esperto che parla in italiano. Fornisci un commento sintetico su {symbol} "
        f"usando queste informazioni:\n- Trend: {technical.get('trend')} (SMA50={technical.get('ma50'):.2f}, SMA200={technical.get('ma200'):.2f})\n"
        f"- Variazione recente (%): {recent_pct:.2f}\n"
        f"- Fondamentali: P/E={fundamentals.get('pe')}, EPS={fundamentals.get('eps')}, MarketCap={fundamentals.get('marketcap')}\n"
        "Dai 3 punti: situazione, rischio principale, metrica da monitorare. Concludi con una breve frase indicativa (non una consulenza finanziaria)."
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
            LOGGER.exception("openai commentary failed")
    # fallback
    return (f"{symbol.upper()} trend {technical.get('trend')}. Variazione recent % {recent_pct:.2f}. "
            f"PE={fundamentals.get('pe')}, EPS={fundamentals.get('eps')}. Monitorare SMA50 vs SMA200 e volume.")

# ---------------- INLINE/KEYBOARDS ----------------
def main_keyboard():
    return {
        "keyboard": [
            [{"text":"💬 Chat AI"},{"text":"🔍 Cerca"}],
            [{"text":"🔍 Categorie"},{"text":"🔍 Ricerca simbolo/nome"}],
            [{"text":"🔍 Categorie mercati"},{"text":"🔔 Preferiti & Notifiche"}],
            [{"text":"📊 Analisi manuale"},{"text":"🧾 Report Giornaliero"}],
            [{"text":"🏠 Menu principale"}],
        ],
        "resize_keyboard": True
    }

def categories_keyboard():
    kb = {
        "keyboard": [
            [{"text":"🇺🇸 USA"}, {"text":"🇪🇺 Europa"}],
            [{"text":"🇨🇳 Asia"}, {"text":"🌍 Africa"}],
            [{"text":"💹 Crypto"}, {"text":"💱 Valute"}],
            [{"text":"🏠 Menu principale"}]
        ],
        "resize_keyboard": True
    }
    return kb

def inline_ai_button(symbol: str):
    return {"inline_keyboard":[[{"text":"🧠 Analisi AI","callback_data":f"AI_COMMENT|{symbol.upper()}"}]]}

def inline_search_results(results):
    kb = {"inline_keyboard":[]}
    for r in results:
        sym = r.get("symbol")
        name = r.get("name") or ""
        kb["inline_keyboard"].append([{"text":f"{sym} — {name[:30]}", "callback_data":f"SELECT|{sym}"}])
    return kb

# ---------------- ANALYSIS FORMATTING ----------------
def format_analysis(symbol: str):
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
    # trading signals
    signal_labels = []
    if rsi_val is not None:
        if rsi_val < 30:
            signal_labels.append("IPERVENDUTO (RSI<30)")
        elif rsi_val > 70:
            signal_labels.append("IPERCOMPRATO (RSI>70)")
    # momentum / volatility
    vol7 = float(close.pct_change().rolling(7).std().iloc[-1]) * 100 if len(close) >= 7 else 0.0
    vol30 = float(close.pct_change().rolling(30).std().iloc[-1]) * 100 if len(close) >= 30 else 0.0
    summary = {
        "symbol": symbol.upper(),
        "latest": latest,
        "pct_6m": pct_6m,
        "rsi": rsi_val,
        "macd_hist_last": float(hist.iloc[-1]) if len(hist)>0 else None,
        "vol7_pct": vol7,
        "vol30_pct": vol30,
        "fundamentals": fundamentals,
        "technical": tech,
        "signals": signal_labels
    }
    return summary

def build_analysis_message(summary: dict):
    s = summary
    lines = [f"📊 <b>Analisi per {s['symbol']}</b>"]
    lines.append(f"- Prezzo attuale: <b>{s['latest']:.2f}$</b>")
    lines.append(f"- Variazione 6mo: {s['pct_6m']:+.2f}%")
    if s.get("rsi") is not None:
        lines.append(f"- RSI(14): {s['rsi']:.2f}")
    lines.append(f"- Trend tecnico: <b>{s['technical']['trend']}</b> (SMA50={s['technical']['ma50']:.2f}, SMA200={s['technical']['ma200']:.2f})")
    lines.append(f"- Volatilità 7d: {s['vol7_pct']:.2f}% — 30d: {s['vol30_pct']:.2f}%")
    if s.get("signals"):
        lines.append("- Segnali: " + ", ".join(s["signals"]))
    # fundamentals snippet
    f = s.get("fundamentals", {})
    if f:
        lines.append(f"- Fondamentali: P/E={f.get('pe')}, EPS={f.get('eps')}, MarketCap={f.get('marketcap')}")
    # add a small disclaimer
    lines.append("\n<i>Nota: commento informativo, non consulenza finanziaria.</i>")
    return "\n".join(lines)

# ---------------- BACKGROUND: notifications and daily report ----------------
def notify_loop():
    LOGGER.info("Starting notify loop: interval %s minutes", CHECK_INTERVAL_MIN)
    last_prices = {}
    while True:
        users = load_users()
        for chat_id, u in users.items():
            try:
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
                            caption = (f"🔔 <b>Notifica</b>\n{sym}\nPrezzo di riferimento: {baseline:.2f}$\n"
                                       f"Prezzo attuale: {price:.2f}$\nVariazione: {arrow} {change:.2f}% (soglia {pct_thr}%)")
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
                        LOGGER.exception("error checking symbol %s for user %s", sym, chat_id)
            except Exception:
                LOGGER.exception("error in notify loop for user %s", chat_id)

        # daily report trigger (once per run when hour matches)
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
                        LOGGER.exception("daily report fail for %s", cid)
                users_all["_last_daily_ts"] = int(time.time())
                save_users(users_all)

        time.sleep(CHECK_INTERVAL_MIN * 60)

def send_daily_report_to_user(chat_id):
    users = load_users()
    u = users.get(chat_id, {})
    favs = u.get("favorites", [])
    lines = [f"🗞️ <b>Report giornaliero — {datetime.now(TZ).strftime('%d/%m %H:%M')}</b>\n"]
    if not favs:
        lines.append("Nessun preferito. Aggiungi con /watch TICKER")
        send_message(chat_id, "\n".join(lines))
        return
    # analyze each favorite and prepare short note (only top 3 with signals)
    scored = []
    for s in favs:
        try:
            summary = format_analysis(s)
            if summary is None:
                continue
            score = 0.0
            # simple heuristic score: positive if rsi low (buying opportunity) and trend up
            if summary.get("rsi") is not None:
                if summary["rsi"] < 35:
                    score += 1.5
                elif summary["rsi"] > 70:
                    score -= 1.5
            trend = summary["technical"]["trend"]
            if trend == "rialzista":
                score += 1.2
            elif trend == "ribassista":
                score -= 1.2
            # momentum recent
            score += (summary.get("pct_6m", 0) / 100.0)
            scored.append((s, score, summary))
        except Exception:
            LOGGER.exception("daily analysis failed for %s", s)
    # sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)
    # create report sentences and include suggestion for top ones
    for sym, score, summ in scored[:6]:
        status = []
        if summ.get("signals"):
            status.append(", ".join(summ["signals"]))
        status_line = (" — " + "; ".join(status)) if status else ""
        lines.append(f"• <b>{sym}</b>: prezzo {summ['latest']:.2f}$; trend {summ['technical']['trend']}{status_line}")
        # for top 1-2 items ask AI to produce a concise recommendation (on demand, but for daily we can auto-call AI if enabled)
    send_message(chat_id, "\n".join(lines))
    # attach AI suggestions only if OPENAI configured and user enabled ai_daily flag
    if OPENAI_API_KEY and openai:
        # if user opted-in for AI daily commentary
        if u.get("daily_ai", True):
            # build prompt with top 3
            top3 = scored[:3]
            prompt_parts = []
            for sym, score, summ in top3:
                prompt_parts.append(f"{sym}: price {summ['latest']:.2f}, trend {summ['technical']['trend']}, RSI {summ.get('rsi')}, pct6m {summ.get('pct_6m'):.2f}")
            prompt = ("Sei un analista finanziario. Dai un commento sintetico e prudente sui seguenti titoli e suggerisci brevemente "
                      "se c'è un'opportunità a breve termine (2-3 giorni). Indica anche se il titolo appare ipervenduto o ipercomprato. "
                      "Non dare consulenza, solo suggerimento):\n" + "\n".join(prompt_parts))
            try:
                resp = openai.ChatCompletion.create(
                    model="gpt-4o-mini",
                    messages=[{"role":"system","content":"Sei un analista finanziario esperto."},
                              {"role":"user","content":prompt}],
                    max_tokens=250, temperature=0.35
                )
                comment = resp.choices[0].message.content.strip()
                send_message(chat_id, "🧠 <b>Commento AI giornaliero</b>:\n" + comment)
            except Exception:
                LOGGER.exception("openai daily comment failed")

# ---------------- ROUTES / WEBHOOK ----------------
from flask import Flask, request, jsonify
app = Flask(__name__)

MAIN_KEYBOARD = {
    "keyboard": [
        [{"text":"💬 Chat AI"},{"text":"🔍 Cerca"}],
        [{"text":"📂 Categorie"},{"text":"🔎 Ricerca simbolo/nome"}],
        [{"text":"⭐ Preferiti"},{"text":"🔔 Notifiche"}],
        [{"text":"📊 Analisi manuale"},{"text":"🧾 Report Giornaliero"}],
        [{"text":"🏠 Menu principale"}],
    ],
    "resize_keyboard": True
}

@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    if not data:
        return jsonify({"ok": False})
    # handle callback_query for inline buttons (AI analysis or selection)
    if "callback_query" in data:
        cq = data["callback_query"]
        cb_id = cq.get("id")
        cb_data = cq.get("data", "")
        message = cq.get("message", {})
        chat = message.get("chat", {})
        chat_id = str(chat.get("id"))
        # acknowledge callback immediately (toast)
        answer_callback(cb_id, text="Elaboro la richiesta...", show_alert=False)
        if cb_data.startswith("AI_COMMENT|"):
            _, symbol = cb_data.split("|", 1)
            try:
                df = fetch_history(symbol, period="6mo", interval="1d")
                if df is None or df.empty:
                    send_message(chat_id, f"⚠️ Dati non disponibili per {symbol}")
                else:
                    close = df["Close"]
                    recent_pct = (float(close.iloc[-1]) - float(close.iloc[0])) / float(close.iloc[0]) * 100.0
                    technical = detect_trend(df)
                    fundamentals = fundamental_summary(symbol)
                    commentary = ai_commentary(symbol, fundamentals, technical, recent_pct)
                    send_message(chat_id, f"🧠 <b>Analisi AI — {symbol}</b>\n\n{commentary}")
            except Exception:
                LOGGER.exception("callback ai error for %s", symbol)
                send_message(chat_id, "Errore durante generazione analisi AI.")
        elif cb_data.startswith("SELECT|"):
            _, symbol = cb_data.split("|",1)
            # act as if user requested analysis on symbol
            try:
                summary = format_analysis(symbol)
                if summary:
                    msg = build_analysis_message(summary)
                    send_message(chat_id, msg, reply_markup=inline_ai_button(symbol))
                    img = build_chart_bytes(symbol, period="3mo")
                    if img:
                        send_photo_bytes(chat_id, img, f"Grafico {symbol}")
                else:
                    send_message(chat_id, f"Impossibile ottenere dati per {symbol}")
            except Exception:
                LOGGER.exception("callback select error")
                send_message(chat_id, "Errore durante selezione.")
        return jsonify({"ok": True})

    # normal message flow
    message = data.get("message") or data.get("edited_message") or {}
    if not message:
        return jsonify({"ok": True})
    chat = message.get("chat", {})
    chat_id = str(chat.get("id"))
    text = (message.get("text") or "").strip()
    if not text:
        return jsonify({"ok": True})
    LOGGER.info("Msg from %s: %s", chat_id, text)
    users = load_users()
    if chat_id not in users:
        users[chat_id] = {"favorites": [], "notifications": {}, "mode": None, "context": [], "daily_ai": True}
        save_users(users)
    # quick commands
    if text.startswith("/start") or text == "🏠 Menu principale":
        send_message(chat_id, "👋 Ciao — sono AngelBot, il tuo analista. Usa i pulsanti qui sotto.", reply_markup=MAIN_KEYBOARD)
        return jsonify({"ok": True})
    if text.startswith("/help"):
        send_message(chat_id, "Guida rapida: premi i pulsanti o usa comandi /analizza TICKER, /watch TICKER, /unwatch TICKER, /list")
        return jsonify({"ok": True})
    if text.startswith("/analizza"):
        parts = text.split()
        if len(parts) >= 2:
            symbol = parts[1].upper()
            summary = format_analysis(symbol)
            if summary:
                send_message(chat_id, build_analysis_message(summary), reply_markup=inline_ai_button(symbol))
                img = build_chart_bytes(symbol, period="6mo")
                if img:
                    send_photo_bytes(chat_id, img, f"Grafico {symbol}")
            else:
                send_message(chat_id, "Dati non disponibili per " + symbol)
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
                send_message(chat_id, f"✅ {sym} aggiunto ai preferiti e monitorato (soglia {NOTIF_PCT_DEFAULT}%)")
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
                send_message(chat_id, f"{sym} non è nei tuoi preferiti.")
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
    if text == "📂 Categorie" or text == "🔍 Categorie" or text == "🔍 Categorie mercati":
        send_message(chat_id, "Scegli una categoria:", reply_markup=categories_keyboard())
        return jsonify({"ok": True})
    # category buttons
    if text in ["🇺🇸 USA","🇪🇺 Europa","🇨🇳 Asia","🌍 Africa","💹 Crypto","💱 Valute"]:
        mapping = {
            "🇺🇸 USA":"USA","🇪🇺 Europa":"EUROPA","🇨🇳 Asia":"ASIA","🌍 Africa":"AFRICA","💹 Crypto":"CRYPTO","💱 Valute":"FX"
        }
        cat = mapping.get(text)
        syms = CATEGORIES.get(cat, [])
        if not syms:
            send_message(chat_id, "Nessun simbolo in questa categoria.")
        else:
            # send a list with inline buttons to select
            results = [{"symbol":s,"name":""} for s in syms]
            send_message(chat_id, f"Simboli in {cat}:")
            kb = inline_search_results(results)
            send_message(chat_id, "Scegli per analizzare:", reply_markup=kb)
        return jsonify({"ok": True})
    if text == "🔍 Ricerca simbolo/nome" or text == "🔍 Cerca" or text == "🔎 Ricerca simbolo/nome":
        users[chat_id]["mode"] = "search"
        save_users(users)
        send_message(chat_id, "🔎 Scrivi il simbolo o il nome del titolo che vuoi cercare (es: AAPL o Apple).")
        return jsonify({"ok": True})
    if text == "💬 Chat AI":
        set_user_mode = users[chat_id].setdefault("mode", "chat")
        save_users(users)
        send_message(chat_id, "🧠 Modalità Chat AI attiva. Scrivimi liberamente.")
        return jsonify({"ok": True})
    if text == "📊 Analisi manuale" or text == "🔍 Analisi":
        users[chat_id]["mode"] = "analysis_prompt"
        save_users(users)
        send_message(chat_id, "🔍 Inserisci il ticker da analizzare (es. AAPL) o usa /analizza TICKER")
        return jsonify({"ok": True})
    if text == "🧾 Report Giornaliero" or text == "🧾 Report":
        send_daily_report_to_user(chat_id)
        return jsonify({"ok": True})

    # handle modes: search, chat, price, chart, favorites, analysis_prompt
    mode = users[chat_id].get("mode")
    if mode == "search":
        query = text.strip()
        results = search_ticker(query, limit=6)
        if not results:
            send_message(chat_id, "Nessun risultato. Riprova con un nome diverso.")
            users[chat_id]["mode"] = None
            save_users(users)
            return jsonify({"ok": True})
        # show inline options
        kb = inline_search_results(results)
        send_message(chat_id, f"Risultati per <b>{query}</b>:", reply_markup=kb)
        users[chat_id]["mode"] = None
        save_users(users)
        return jsonify({"ok": True})
    if mode == "chat":
        # maintain simple context
        ctx = users[chat_id].setdefault("context", [])
        ctx.append({"role":"user","content":text,"ts":int(time.time())})
        users[chat_id]["context"] = ctx[-10:]
        save_users(users)
        # call openai if available
        reply = None
        if openai and OPENAI_API_KEY:
            try:
                messages = [{"role":"system","content":"Sei AngelBot, analista finanziario che risponde in italiano in modo chiaro e prudente."}]
                messages += [{"role":m["role"], "content":m["content"]} for m in users[chat_id]["context"]]
                resp = openai.ChatCompletion.create(model="gpt-4o-mini", messages=messages, max_tokens=300, temperature=0.3)
                reply = resp.choices[0].message.content.strip()
            except Exception:
                LOGGER.exception("openai chat failed")
        if not reply:
            reply = "Ricevuto. Posso fornirti analisi con /analizza TICKER o ricerca con 🔍 Cerca."
        ctx.append({"role":"assistant","content":reply,"ts":int(time.time())})
        users[chat_id]["context"] = ctx[-10:]
        save_users(users)
        send_message(chat_id, reply)
        return jsonify({"ok": True})
    if mode == "analysis_prompt":
        sym = text.strip().upper().split()[0]
        summary = format_analysis(sym)
        users[chat_id]["mode"] = None
        save_users(users)
        if summary:
            send_message(chat_id, build_analysis_message(summary), reply_markup=inline_ai_button(sym))
            img = build_chart_bytes(sym, period="6mo")
            if img:
                send_photo_bytes(chat_id, img, f"Grafico {sym}")
        else:
            send_message(chat_id, "Dati non disponibili per " + sym)
        return jsonify({"ok": True})

    # text could be direct ticker or name — attempt search and return best match
    # heuristic: if it's uppercase-like and short -> treat as symbol
    if (len(text) <= 6 and text.isupper()) or any(ch.isdigit() for ch in text):
        # treat as ticker
        sym = text.upper().split()[0]
        summary = format_analysis(sym)
        if summary:
            send_message(chat_id, build_analysis_message(summary), reply_markup=inline_ai_button(sym))
            img = build_chart_bytes(sym, period="3mo")
            if img:
                send_photo_bytes(chat_id, img, f"Grafico {sym}")
        else:
            # try search
            results = search_ticker(text, limit=6)
            if results:
                kb = inline_search_results(results)
                send_message(chat_id, "Non trovo direttamente il simbolo. Forse intendevi:", reply_markup=kb)
            else:
                send_message(chat_id, "Simbolo non trovato.")
        return jsonify({"ok": True})
    # otherwise try search by name
    results = search_ticker(text, limit=6)
    if results:
        kb = inline_search_results(results)
        send_message(chat_id, f"Risultati per <b>{text}</b>:", reply_markup=kb)
    else:
        send_message(chat_id, "Nessun risultato. Prova con simbolo o nome diverso.")
    return jsonify({"ok": True})

@app.route("/")
def home():
    # try set commands on startup (idempotent)
    try:
        set_my_commands()
    except Exception:
        pass
    return "AngelBot grande analista attivo 🚀"

# ---------------- START BACKGROUND WORKERS ----------------
def start_workers():
    t = threading.Thread(target=notify_loop, daemon=True)
    t.start()
    LOGGER.info("Notification worker started")

if __name__ == "__main__":
    start_workers()
    # use standard Flask server on Render; if you prefer waitress/gunicorn, Render handles it
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
