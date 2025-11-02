import os
import io
import json
import time
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

import requests
import yfinance as yf
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# OpenAI (modern or legacy)
USE_MODERN_OPENAI = False
client_modern = None
client_legacy = None
try:
    from openai import OpenAI
    USE_MODERN_OPENAI = True
except Exception:
    try:
        import openai as _openai
        client_legacy = _openai
    except Exception:
        client_legacy = None

logger = logging.getLogger("angelbot.report")
logger.setLevel(logging.INFO)

# Environment
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEETS_KEY = os.getenv("GOOGLE_SHEETS_KEY")
SHEET_ID = os.getenv("SHEET_ID")
TZ_ITALY = ZoneInfo("Europe/Rome")
DATA_FILE = "users.json"

# init OpenAI client if possible
if OPENAI_API_KEY:
    try:
        if USE_MODERN_OPENAI:
            client_modern = OpenAI(api_key=OPENAI_API_KEY)
        else:
            import openai as _openai
            _openai.api_key = OPENAI_API_KEY
            client_legacy = _openai
    except Exception as e:
        logger.exception("OpenAI init failed: %s", e)

# Google Sheets helper (optional)
gc = None
sheet = None
try:
    if GOOGLE_SHEETS_KEY and SHEET_ID:
        import gspread
        from google.oauth2.service_account import Credentials
        creds_dict = json.loads(GOOGLE_SHEETS_KEY)
        creds = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(SHEET_ID)
        logger.info("report.py: Google Sheets connected")
except Exception:
    logger.info("report.py: Google Sheets not connected or missing credentials")

def load_user_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logger.exception("load_user_data failed")
    return {}

def telegram_send_message(chat_id: str, text: str, reply_markup: dict = None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(f"{TELEGRAM_API_BASE}/sendMessage", json=payload, timeout=15)
        if not r.ok:
            logger.warning("sendMessage failed: %s", r.text)
        return r
    except Exception:
        logger.exception("sendMessage exception")
        return None

def telegram_send_photo(chat_id: str, image_buf: io.BytesIO, caption: str = ""):
    try:
        files = {"photo": ("chart.png", image_buf.getvalue())}
        data = {"chat_id": chat_id, "caption": caption}
        r = requests.post(f"{TELEGRAM_API_BASE}/sendPhoto", files=files, data=data, timeout=30)
        if not r.ok:
            logger.warning("sendPhoto failed: %s", r.text)
        return r
    except Exception:
        logger.exception("sendPhoto exception")
        return None

# ---------------- Finance helpers ----------------
def get_current_price(ticker: str) -> Optional[float]:
    try:
        t = yf.Ticker(ticker)
        df = t.history(period="1d", interval="1d")
        if df is None or df.empty:
            return None
        return float(df["Close"].iloc[-1])
    except Exception:
        logger.exception("get_current_price error for %s", ticker)
        return None

def get_history_df(ticker: str, period: str = "1mo", interval: str = "1d") -> Optional[pd.DataFrame]:
    try:
        t = yf.Ticker(ticker)
        df = t.history(period=period, interval=interval)
        if df is None or df.empty:
            return None
        return df
    except Exception:
        logger.exception("get_history_df error for %s", ticker)
        return None

def build_chart_image(ticker: str, days: int = 7) -> Optional[io.BytesIO]:
    df = get_history_df(ticker, period=f"{max(days,7)}d", interval="1d")
    if df is None or df.empty: 
        return None
    buf = io.BytesIO()
    try:
        plt.figure(figsize=(8,4))
        plt.plot(df.index, df["Close"], marker="o")
        plt.title(f"{ticker} - ultimi {days} giorni")
        plt.xlabel("Data")
        plt.ylabel("Prezzo ($)")
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(buf, format="png")
        plt.close()
        buf.seek(0)
        return buf
    except Exception:
        logger.exception("build_chart_image error")
        return None

# ---------------- OpenAI small wrapper for analysis ----------------
def ask_openai_text(prompt: str, max_tokens: int = 300, temperature: float = 0.3) -> str:
    if not (client_modern or client_legacy):
        return "⚠️ OpenAI non configurato. Imposta OPENAI_API_KEY per avere analisi AI."
    messages = [{"role":"system", "content": "Sei un analista finanziario esperto che risponde in italiano in modo chiaro e prudente."},
                {"role":"user", "content": prompt}]
    try:
        if client_modern:
            resp = client_modern.chat.completions.create(model="gpt-4o-mini", messages=messages, max_tokens=max_tokens, temperature=temperature)
            try:
                return resp.choices[0].message.content.strip()
            except Exception:
                return resp['choices'][0]['message']['content'].strip()
        else:
            resp = client_legacy.ChatCompletion.create(model="gpt-3.5-turbo", messages=messages, max_tokens=max_tokens, temperature=temperature)
            return resp['choices'][0]['message']['content'].strip()
    except Exception:
        logger.exception("ask_openai_text failed")
        return "Errore durante richiesta OpenAI."

# ---------------- Public functions called by app.py ----------------
def send_price_for_chat(chat_id: str, ticker: str):
    price = get_current_price(ticker)
    if price is None:
        telegram_send_message(chat_id, f"⚠️ Prezzo non disponibile per <b>{ticker}</b>.")
        return
    # Try to extract name from yfinance info
    try:
        info = yf.Ticker(ticker).info
        name = info.get("shortName") or ticker
    except Exception:
        name = ticker
    # small percent change
    pct = info.get("regularMarketChangePercent") if isinstance(info, dict) else None
    pct_str = f" ({pct:.2f}%)" if pct is not None else ""
    telegram_send_message(chat_id, f"💱 <b>{name}</b> ({ticker})\nPrezzo attuale: <b>{price:.2f}$</b>{pct_str}")

def send_chart_for_chat(chat_id: str, ticker: str, days: int = 7):
    buf = build_chart_image(ticker, days=days)
    if buf:
        telegram_send_photo(chat_id, buf, caption=f"📈 Grafico ultimi {days} giorni — {ticker}")
    else:
        telegram_send_message(chat_id, f"⚠️ Impossibile generare grafico per {ticker}.")

def send_analysis_for_chat(chat_id: str, ticker: str):
    # Build simple numeric summary and request AI comment
    df = get_history_df(ticker, period="6mo", interval="1d")
    if df is None or df.empty:
        telegram_send_message(chat_id, f"⚠️ Dati insufficienti per analisi di {ticker}.")
        return
    latest = float(df["Close"].iloc[-1])
    first = float(df["Close"].iloc[0])
    pct_6m = (latest - first) / first * 100
    sma50 = df["Close"].rolling(window=50, min_periods=1).mean().iloc[-1]
    sma200 = df["Close"].rolling(window=200, min_periods=1).mean().iloc[-1]
    prompt = (
        f"Ho questi dati per {ticker}:\n"
        f"- Prezzo attuale: {latest:.2f}\n"
        f"- Variazione 6 mesi: {pct_6m:.2f}%\n"
        f"- SMA50: {sma50:.2f}\n"
        f"- SMA200: {sma200:.2f}\n"
        "Fornisci 3 osservazioni sintetiche in italiano (tono consulente), "
        "poi un suggerimento breve su quale metrica guardare per decidere."
    )
    ai_comment = ask_openai_text(prompt, max_tokens=300)
    # send chart + text
    buf = build_chart_image(ticker, days=90)
    caption = f"🧾 Analisi sintetica per {ticker}:\n{ai_comment}"
    if buf:
        telegram_send_photo(chat_id, buf, caption=caption)
    else:
        telegram_send_message(chat_id, caption)

def send_portfolio(chat_id: str):
    # try to read portfolio from Google Sheets (sheet named 'Portafoglio' or first sheet)
    msg = ""
    if sheet:
        try:
            try:
                ws = sheet.worksheet("Portafoglio")
            except Exception:
                ws = sheet.sheet1
            rows = ws.get_all_records()
            if not rows:
                telegram_send_message(chat_id, "📘 Il foglio portafoglio è vuoto.")
                return
            total_value = 0.0
            lines = []
            for r in rows:
                t = r.get("Ticker") or r.get("ticker") or r.get("Symbol")
                qty = float(r.get("Quantità") or r.get("Qty") or r.get("Quantity") or 0)
                avg = float(r.get("Prezzo medio") or r.get("AvgPrice") or r.get("Avg") or 0)
                price = get_current_price(t) or 0.0
                value = qty * price
                total_value += value
                lines.append(f"{t}: qty {qty} — prezzo {price:.2f}$ — valore {value:.2f}$")
            header = f"💼 Portafoglio (valore totale stimato: {total_value:.2f}$)\n"
            telegram_send_message(chat_id, header + "\n".join(lines))
            return
        except Exception:
            logger.exception("send_portfolio: errore lettura sheet")
    # fallback: try users.json file
    users = load_user_data()
    u = users.get(str(chat_id), {})
    portfolio = u.get("portfolio", [])
    if not portfolio:
        telegram_send_message(chat_id, "💼 Portafoglio vuoto. Aggiungi con il foglio Google o /add (funzione).")
        return
    lines = []
    total_value = 0.0
    for it in portfolio:
        t = it.get("ticker")
        qty = float(it.get("qty", 0))
        price = get_current_price(t) or 0.0
        val = qty * price
        total_value += val
        lines.append(f"{t}: qty {qty} — prezzo {price:.2f}$ — valore {val:.2f}$")
    telegram_send_message(chat_id, f"💼 Portafoglio (totale ~ {total_value:.2f}$)\n" + "\n".join(lines))

def genera_report_giornaliero(chat_id=None):
    """
    Funzione che genera un report giornaliero. Se chat_id è fornito,
    invia il report alla chat Telegram, altrimenti lo salva/logga.
    """
    # Esempio di report basato sul portafoglio degli utenti
    users = load_user_data()
    report_lines = []
    for uid, udata in users.items():
        nome = udata.get("name", f"ID {uid}")
        portfolio = udata.get("portfolio", [])
        total_value = 0.0
        for it in portfolio:
            t = it.get("ticker")
            qty = float(it.get("qty", 0))
            price = get_current_price(t) or 0.0
            val = qty * price
            total_value += val
        report_lines.append(f"• {nome}: valore totale portafoglio stimato {total_value:.2f}$")
    testo_report = "🗞️ <b>Report giornaliero portafogli utenti:</b>\n" + "\n".join(report_lines)
    # Se il report è richiesto da una chat Telegram, invia il report lì
    if chat_id:
        telegram_send_message(chat_id, testo_report)
    else:
        logger.info(testo_report)
    return testo_report

if __name__ == "__main__":
    print("report.py module — import into app.py")
