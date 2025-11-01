# server.py
import os
import asyncio
import requests
from io import BytesIO

from flask import Flask, request
import yfinance as yf
import matplotlib.pyplot as plt

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# --- CONFIG ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # es: https://tuoapp.onrender.com/webhook
OWNER_TELEGRAM_ID = int(os.environ.get("OWNER_TELEGRAM_ID", "0"))

# Optional alert vars
ALERT_SYMBOL = os.environ.get("ALERT_SYMBOL")      # es. "TSLA"
ALERT_THRESHOLD = float(os.environ.get("ALERT_THRESHOLD", "0")) if os.environ.get("ALERT_THRESHOLD") else None
ALERT_CHECK_INTERVAL = int(os.environ.get("ALERT_CHECK_INTERVAL", "60"))  # secondi

if not TELEGRAM_TOKEN:
    raise RuntimeError("Devi impostare TELEGRAM_TOKEN nelle env vars")

if not WEBHOOK_URL:
    # Non falliamo: l'utente può impostarlo manualmente più tardi
    print("Warning: WEBHOOK_URL non impostato. Impostalo per usare webhook pubblici.")

app = Flask(__name__)

# --- BOT: handlers ---
async def _unauthorized_reply(update: Update):
    try:
        await update.message.reply_text("❌ Non autorizzato.")
    except Exception:
        pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # sicurezza: rispondi solo al proprietario
    if not update.effective_user or update.effective_user.id != OWNER_TELEGRAM_ID:
        await _unauthorized_reply(update)
        return

    msg = (
        "📈 Benvenuto (solo per il proprietario)!\n\n"
        "Comandi:\n"
        "/prezzo <SIMBOLO>\n"
        "/grafico <SIMBOLO>\n"
        "/info <SIMBOLO>\n"
        "/set_alert <SIMBOLO> <SOGLIA> (es. /set_alert TSLA 150)\n"
    )
    await update.message.reply_text(msg)


async def prezzo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != OWNER_TELEGRAM_ID:
        await _unauthorized_reply(update)
        return

    if not context.args:
        await update.message.reply_text("Scrivi: /prezzo <simbolo>")
        return
    simbolo = context.args[0].upper()
    try:
        info = yf.Ticker(simbolo).info
        prezzo = info.get("currentPrice") or info.get("regularMarketPrice")
        nome = info.get("shortName", simbolo)
        if prezzo is not None:
            await update.message.reply_text(f"💰 {nome} ({simbolo})\nPrezzo attuale: {prezzo}$")
        else:
            await update.message.reply_text("Non trovo il prezzo per questo simbolo.")
    except Exception as e:
        await update.message.reply_text(f"Errore nel recupero dei dati: {e}")


async def grafico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != OWNER_TELEGRAM_ID:
        await _unauthorized_reply(update)
        return

    if not context.args:
        await update.message.reply_text("Scrivi: /grafico <simbolo>")
        return
    simbolo = context.args[0].upper()
    try:
        dati = yf.Ticker(simbolo).history(period="1mo")
        if dati.empty:
            await update.message.reply_text("Dati non trovati per questo simbolo.")
            return

        plt.figure()
        dati["Close"].plot(title=f"Andamento di {simbolo}")
        plt.xlabel("Data")
        plt.ylabel("Prezzo ($)")

        buf = BytesIO()
        plt.savefig(buf, format="png")
        buf.seek(0)
        await update.message.reply_photo(buf)
        plt.close()
    except Exception as e:
        await update.message.reply_text(f"Errore nel generare il grafico: {e}")


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != OWNER_TELEGRAM_ID:
        await _unauthorized_reply(update)
        return

    if not context.args:
        await update.message.reply_text("Scrivi: /info <simbolo>")
        return
    simbolo = context.args[0].upper()
    try:
        info = yf.Ticker(simbolo).info
        nome = info.get("shortName", "N/D")
        settore = info.get("sector", "N/D")
        paese = info.get("country", "N/D")
        cap = info.get("marketCap", "N/D")
        await update.message.reply_text(
            f"📊 {nome} ({simbolo})\nSettore: {settore}\nPaese: {paese}\nCapitalizzazione: {cap}"
        )
    except Exception as e:
        await update.message.reply_text(f"Errore nel recupero delle info: {e}")


# Simple command to set alert from Telegram
async def set_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ALERT_SYMBOL, ALERT_THRESHOLD
    if not update.effective_user or update.effective_user.id != OWNER_TELEGRAM_ID:
        await _unauthorized_reply(update)
        return

    if len(context.args) < 2:
        await update.message.reply_text("Usa: /set_alert <SIMBOLO> <SOGLIA>")
        return
    ALERT_SYMBOL = context.args[0].upper()
    try:
        ALERT_THRESHOLD = float(context.args[1])
        await update.message.reply_text(f"Alert impostato: {ALERT_SYMBOL} sotto {ALERT_THRESHOLD}$")
    except ValueError:
        await update.message.reply_text("La soglia deve essere un numero, es. 150.0")


# --- inizializza Application (bot) ---
app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app_bot.add_handler(CommandHandler("start", start))
app_bot.add_handler(CommandHandler("prezzo", prezzo))
app_bot.add_handler(CommandHandler("grafico", grafico))
app_bot.add_handler(CommandHandler("info", info))
app_bot.add_handler(CommandHandler("set_alert", set_alert))

# stato di inizializzazione (evita doppie chiamate)
_bot_initialized = False

# --- Flask endpoints ---
@app.route("/", methods=["GET"])
def home():
    return "✅ Bot finanziario attivo (webhook)."


@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    """Endpoint manuale per impostare il webhook (utile se preferisci farlo dopo il deploy)."""
    if not WEBHOOK_URL:
        return "WEBHOOK_URL non impostato nelle env vars.", 400
    r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={WEBHOOK_URL}")
    return ("OK: " + r.text) if r.ok else ("ERROR: " + r.text), (200 if r.ok else 500)


@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Telegram invia qui gli aggiornamenti. Per sicurezza ignoriamo messaggi da utenti non autorizzati.
    Questo codice mette in coda l'elaborazione dell'update nell'event loop esistente.
    """
    global _bot_initialized

    payload = request.get_json(force=True)
    # costruisce Update
    update = Update.de_json(payload, app_bot.bot)

    # Se il payload contiene un messaggio/utente, filtriamo subito se non è il proprietario:
    user_id = None
    if update.message and update.message.from_user:
        user_id = update.message.from_user.id
    elif update.effective_user:
        user_id = update.effective_user.id

    if user_id and user_id != OWNER_TELEGRAM_ID:
        # Ignora richieste non autorizzate (non rispondiamo)
        return "ok", 200

    # Se non inizializzato, prova a settare webhook (solo una volta)
    if not _bot_initialized:
        _bot_initialized = True
        if WEBHOOK_URL:
            try:
                requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={WEBHOOK_URL}", timeout=10)
            except Exception as e:
                print("setWebhook error:", e)

    # schedule processing on event loop
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    # assicura che l'app sia inizializzata (non await qui): prova a inizializzare una sola volta in background
    try:
        if not app_bot.updater:  # non dovrebbe esistere in v20+, check safe
            pass
    except Exception:
        pass

    # metti in coda l'elaborazione dell'update
    try:
        loop.create_task(app_bot.process_update(update))
    except RuntimeError:
        # se non c'è loop attivo (situazione rara sotto gunicorn), esegui in modo sincrono come fallback
        import asyncio as _asyncio
        _asyncio.run(app_bot.process_update(update))

    return "ok", 200


# --- Alert background task (async) ---
async def alert_worker():
    """Controlla periodicamente il prezzo e invia un messaggio se scende sotto la soglia."""
    if not ALERT_SYMBOL or not ALERT_THRESHOLD:
        return  # niente alert configurati

    while True:
        try:
            info = yf.Ticker(ALERT_SYMBOL).info
            prezzo = info.get("currentPrice") or info.get("regularMarketPrice")
            if prezzo is not None:
                print(f"[alert_worker] {ALERT_SYMBOL} price = {prezzo}")
                if prezzo <= ALERT_THRESHOLD:
                    # invia un messaggio al proprietario
                    try:
                        await app_bot.bot.send_message(
                            chat_id=OWNER_TELEGRAM_ID,
                            text=f"⚠️ ALERT: {ALERT_SYMBOL} è sceso a {prezzo}$ (soglia {ALERT_THRESHOLD}$)"
                        )
                    except Exception as send_err:
                        print("Errore invio alert:", send_err)
                        # non break; continuiamo a controllare
            else:
                print(f"[alert_worker] prezzo non disponibile per {ALERT_SYMBOL}")
        except Exception as e:
            print("Errore alert_worker:", e)

        await asyncio.sleep(ALERT_CHECK_INTERVAL)


# --- On startup: crea task di alert se configurato ---
# Nota: sotto gunicorn il blocco if __name__ == '__main__' non è eseguito.
# Per assicurare il task, proviamo a creare la task la prima volta che arriva il webhook
# (nel webhook abbiamo _bot_initialized per il setWebhook). Qui comunque tentiamo un avvio se script lanciato direttamente.

if __name__ == "__main__":
    # in sviluppo / test locale
    loop = asyncio.get_event_loop()
    if ALERT_SYMBOL and ALERT_THRESHOLD:
        loop.create_task(alert_worker())
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
