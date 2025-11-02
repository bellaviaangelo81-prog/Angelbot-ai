# notifiche.py
import os
import json
import time
import threading
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Any

import requests
import yfinance as yf
import pandas as pd

logger = logging.getLogger("angelbot.notifiche")
logger.setLevel(logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
DATA_FILE = "users.json"
GOOGLE_SHEETS_KEY = os.getenv("GOOGLE_SHEETS_KEY")
SHEET_ID = os.getenv("SHEET_ID")

# default check cadence in seconds for loop internal (will sleep small steps)
LOOP_SLEEP = 20

# Try Google Sheets
gc = None
sheet = None
if GOOGLE_SHEETS_KEY and SHEET_ID:
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds_dict = json.loads(GOOGLE_SHEETS_KEY)
        creds = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(SHEET_ID)
        logger.info("notifiche.py: Google Sheets connected")
    except Exception:
        logger.exception("notifiche.py: Google Sheets init failed")

def load_user_data() -> Dict[str, Any]:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logger.exception("load_user_data failed")
    return {}

def save_user_data(data: Dict[str, Any]):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.exception("save_user_data failed")

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

def telegram_send_photo(chat_id: str, image_buf, caption: str = ""):
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

def get_price(ticker: str):
    try:
        t = yf.Ticker(ticker)
        df = t.history(period="1d", interval="1d")
        if df is None or df.empty:
            return None
        return float(df["Close"].iloc[-1])
    except Exception:
        logger.exception("get_price error")
        return None

def build_small_chart(ticker: str, minutes: int = 60):
    # build a small intraday chart if possible (fallback to 1d)
    try:
        # try 1d with 5m interval if supported
        t = yf.Ticker(ticker)
        df = t.history(period="2d", interval="15m")
        if df is None or df.empty:
            df = t.history(period="7d", interval="1d")
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import io
        buf = io.BytesIO()
        plt.figure(figsize=(6,3))
        if "Close" in df:
            plt.plot(df.index, df["Close"], marker="o")
        plt.title(f"{ticker} - ultimo periodo")
        plt.tight_layout()
        plt.grid(True)
        plt.savefig(buf, format="png")
        plt.close()
        buf.seek(0)
        return buf
    except Exception:
        logger.exception("build_small_chart error")
        return None

def read_notifications_sheet():
    """
    If sheet contains a tab named 'Notifiche', read rows into a list of dicts.
    Expected columns: Simbolo, Nome, Variazione%, Intervallo(minuti), Ultimo Prezzo, Ultima Notifica
    """
    rows = []
    try:
        if sheet:
            try:
                ws = sheet.worksheet("Notifiche")
            except Exception:
                # if no Notifiche sheet, return empty
                return rows
            rows = ws.get_all_records()
    except Exception:
        logger.exception("read_notifications_sheet error")
    return rows

def update_notifications_sheet_row(ticker: str, last_price: float, last_notif_ts: str):
    try:
        if sheet:
            ws = sheet.worksheet("Notifiche")
            all_rows = ws.get_all_records()
            # find row index
            for idx, r in enumerate(all_rows, start=2):  # 1-based, header row is 1
                if str(r.get("Simbolo") or r.get("Symbol") or "").strip().upper() == ticker.upper():
                    # update Ultimo Prezzo and Ultima Notifica
                    ws.update_cell(idx, 5, str(round(last_price,2)))  # column 5 = Ultimo Prezzo (as per spec)
                    ws.update_cell(idx, 6, last_notif_ts)
                    return True
    except Exception:
        logger.exception("update_notifications_sheet_row error")
    return False

def monitor_loop(check_timezone: ZoneInfo = ZoneInfo("Europe/Rome")):
    """
    Background loop: checks user_data notifications + sheet notifications, sends messages when condition met.
    """
    logger.info("notifiche: monitor_loop avviato (timezone=%s)", str(check_timezone))
    while True:
        now = datetime.now(check_timezone)
        users = load_user_data()
        # 1) Notifications per users.json (per-user notifications)
        for chat_id, u in users.items():
            try:
                notifications = u.get("notifications", {})
                for ticker, cfg in list(notifications.items()):
                    pct = float(cfg.get("pct", 5.0))
                    interval = int(cfg.get("interval_min", u.get("notification_interval_default", 15)))
                    both = bool(cfg.get("both", True))
                    last_notif_ts = cfg.get("last_notif_ts", 0)
                    # check time since last notif for this ticker
                    if last_notif_ts:
                        last_dt = datetime.fromtimestamp(int(last_notif_ts), check_timezone)
                        if (now - last_dt) < timedelta(minutes=interval):
                            continue  # skip until interval elapsed
                    # get current price and compare with "baseline"
                    baseline = cfg.get("baseline_price")
                    price = get_price(ticker)
                    if price is None:
                        continue
                    # if baseline is missing, set baseline and continue (no immediate notification)
                    if not baseline:
                        cfg["baseline_price"] = price
                        users[chat_id]["notifications"][ticker] = cfg
                        save_user_data(users)
                        continue
                    # compute pct change relative to baseline
                    change = (price - float(baseline)) / float(baseline) * 100.0
                    if both:
                        triggered = abs(change) >= pct
                    else:
                        # if both False, assume only decreases? But default both True; handle only >pct or <-pct via cfg
                        direction = cfg.get("direction", "both")
                        if direction == "up":
                            triggered = change >= pct
                        elif direction == "down":
                            triggered = change <= -pct
                        else:
                            triggered = abs(change) >= pct
                    if triggered:
                        # send notification
                        arrow = "▲" if change > 0 else "▼"
                        caption = (f"🔔 <b>Notifica</b>\n{ticker}\nPrezzo precedente di riferimento: {baseline:.2f}$\n"
                                   f"Prezzo attuale: {price:.2f}$\nVariazione: {arrow} {change:.2f}% (soglia {pct}%)")
                        # attach a small chart
                        chart = build_small_chart(ticker)
                        if chart:
                            telegram_send_photo(chat_id, chart, caption=caption)
                        else:
                            telegram_send_message(chat_id, caption)
                        # update last notification timestamp and baseline (to avoid repeated alerts)
                        cfg["last_notif_ts"] = int(now.timestamp())
                        cfg["baseline_price"] = price
                        users[chat_id]["notifications"][ticker] = cfg
                        save_user_data(users)
                        # also update notifications sheet if present
                        try:
                            update_notifications_sheet_row(ticker, price, now.strftime("%Y-%m-%d %H:%M:%S"))
                        except Exception:
                            pass
            except Exception:
                logger.exception("Error processing user notifications for %s", chat_id)

        # 2) Notifications from 'Notifiche' sheet (global)
        sheet_rows = read_notifications_sheet()
        for row in sheet_rows:
            try:
                ticker = str(row.get("Simbolo") or row.get("Symbol") or "").strip().upper()
                if not ticker:
                    continue
                pct = float(row.get("Variazione%", row.get("Variazione", 5.0)))
                interval = int(row.get("Intervallo(minuti)", row.get("Intervallo", 60) or 60))
                last_notif = row.get("Ultima Notifica") or row.get("UltimaNotifica") or ""
                last_notif_dt = None
                if last_notif:
                    try:
                        last_notif_dt = datetime.fromisoformat(last_notif)
                    except Exception:
                        try:
                            last_notif_dt = datetime.strptime(last_notif, "%Y-%m-%d %H:%M:%S")
                        except Exception:
                            last_notif_dt = None
                # get price and baseline (Ultimo Prezzo column)
                last_price_sheet = None
                try:
                    last_price_sheet = float(row.get("Ultimo Prezzo") or row.get("UltimoPrezzo") or 0)
                except Exception:
                    last_price_sheet = None
                price = get_price(ticker)
                if price is None:
                    continue
                # If no last_price_sheet, write current and skip
                if not last_price_sheet or last_price_sheet == 0:
                    # update sheet
                    update_notifications_sheet_row(ticker, price, "")
                    continue
                # check time interval
                if last_notif_dt:
                    if (now - last_notif_dt) < timedelta(minutes=interval):
                        continue
                # compute change
                change = (price - last_price_sheet) / last_price_sheet * 100.0
                if abs(change) >= pct:
                    # find users who care: all users with ticker in favorites or if sheet is global send to CHAT_ID_PERSONALE if set
                    # for safety, send to CHAT_ID_PERSONALE if present, and also to users who have ticker in favorites
                    # Load users
                    users = load_user_data()
                    # notify personal chat id
                    recipients = []
                    personal_chat = os.getenv("CHAT_ID_PERSONALE")
                    if personal_chat:
                        recipients.append(personal_chat)
                    # check users favorites
                    for cid, u in users.items():
                        if ticker in (u.get("favorites") or []):
                            recipients.append(cid)
                    # unique
                    recipients = list(dict.fromkeys(recipients))
                    arrow = "▲" if change > 0 else "▼"
                    caption = (f"🔔 <b>Notifica Foglio</b>\n{ticker}\nPrezzo precedente su sheet: {last_price_sheet:.2f}$\n"
                               f"Prezzo attuale: {price:.2f}$\nVariazione: {arrow} {change:.2f}% (soglia {pct}%)")
                    chart = build_small_chart(ticker)
                    for rchat in recipients:
                        if chart:
                            telegram_send_photo(rchat, chart, caption=caption)
                        else:
                            telegram_send_message(rchat, caption)
                    # update the sheet last price and ultima notifica
                    update_notifications_sheet_row(ticker, price, now.strftime("%Y-%m-%d %H:%M:%S"))
            except Exception:
                logger.exception("Error processing sheet notification row: %s", row)

        # sleep small amount (outer loop)
        time.sleep(LOOP_SLEEP)

# Public entrypoint
_monitor_thread = None

def start_background(check_timezone=ZoneInfo("Europe/Rome")):
    global _monitor_thread
    if _monitor_thread and _monitor_thread.is_alive():
        logger.info("notifiche: background already running")
        return
    _monitor_thread = threading.Thread(target=monitor_loop, args=(check_timezone,), daemon=True)
    _monitor_thread.start()
    logger.info("notifiche: background thread started")
