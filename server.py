import os
import re
import logging
import json
from typing import Optional, Dict, List
from datetime import datetime
from threading import Thread
import time

from flask import Flask, request, jsonify, abort
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from openai import OpenAI

# Configure logging
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

app = Flask(__name__)

# === CONFIGURATION ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# Optional: secret token to verify Telegram webhook source (set when creating the webhook)
TELEGRAM_SECRET_TOKEN = os.getenv("TELEGRAM_SECRET_TOKEN")

# Validate required env vars early (fail fast)
_missing = []
if not TELEGRAM_TOKEN:
    _missing.append("TELEGRAM_TOKEN")
if not OPENAI_API_KEY:
    _missing.append("OPENAI_API_KEY")
if _missing:
    logger.error("Missing required environment variables: %s", ", ".join(_missing))
    raise SystemExit(1)

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
TELEGRAM_MAX_MESSAGE = 4096

# Requests session with retries and timeouts
session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retries)
session.mount("https://", adapter)
session.headers.update({"Content-Type": "application/json"})

# Characters to escape for MarkdownV2 according to Telegram docs
_MD_V2_CHARS_RE = re.compile(r"([_\*\[\]\(\)~`>#+\-=|{}.!\\])")

# Trading alert storage (in production, use a database)
price_alerts: Dict[int, List[Dict]] = {}  # {chat_id: [{"symbol": "BTC", "price": 50000, "direction": "below"}]}
price_change_subscriptions: Dict[int, Dict] = {}  # {chat_id: {"symbols": ["BTC", "ETH"], "threshold": 5.0}}
last_prices: Dict[str, float] = {}  # {symbol: last_price}


def get_crypto_price(symbol: str) -> Optional[float]:
    """Get current cryptocurrency price from CoinGecko API (free, no API key needed)."""
    try:
        # Map common symbols to CoinGecko IDs
        symbol_map = {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "USDT": "tether",
            "BNB": "binancecoin",
            "SOL": "solana",
            "XRP": "ripple",
            "ADA": "cardano",
            "DOGE": "dogecoin",
            "MATIC": "matic-network",
            "DOT": "polkadot",
        }
        
        coin_id = symbol_map.get(symbol.upper(), symbol.lower())
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
        
        response = session.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if coin_id in data and "usd" in data[coin_id]:
            return data[coin_id]["usd"]
        return None
    except Exception as e:
        logger.error(f"Error fetching price for {symbol}: {e}")
        return None


def get_market_summary() -> str:
    """Get a summary of top cryptocurrencies."""
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,binancecoin,solana,ripple&vs_currencies=usd&include_24hr_change=true"
        response = session.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        summary = "📊 *Riepilogo Mercato Crypto:*\n\n"
        
        for coin_id, coin_data in data.items():
            price = coin_data.get("usd", 0)
            change_24h = coin_data.get("usd_24h_change", 0)
            emoji = "🟢" if change_24h > 0 else "🔴"
            
            coin_name = coin_id.upper()[:3]
            summary += f"{emoji} *{coin_name}*: ${price:,.2f} ({change_24h:+.2f}%)\n"
        
        return summary
    except Exception as e:
        logger.error(f"Error fetching market summary: {e}")
        return "⚠️ Impossibile recuperare il riepilogo del mercato al momento."


def add_price_alert(chat_id: int, symbol: str, target_price: float, direction: str) -> str:
    """Add a price alert for a user."""
    if chat_id not in price_alerts:
        price_alerts[chat_id] = []
    
    alert = {
        "symbol": symbol.upper(),
        "target_price": target_price,
        "direction": direction,  # "above" or "below"
        "created_at": datetime.now().isoformat()
    }
    
    price_alerts[chat_id].append(alert)
    
    return f"✅ Alert impostato: ti avviserò quando {symbol.upper()} {'supera' if direction == 'above' else 'scende sotto'} ${target_price:,.2f}"


def get_binance_price(symbol: str) -> Optional[float]:
    """Get real-time price from Binance API."""
    try:
        # Convert symbol to Binance format (e.g., BTC -> BTCUSDT)
        binance_symbol = f"{symbol.upper()}USDT"
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={binance_symbol}"
        
        response = session.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        return float(data.get("price", 0))
    except Exception as e:
        logger.debug(f"Binance API error for {symbol}: {e}")
        return None


def get_best_price(symbol: str) -> Optional[float]:
    """Get price from best available source (Binance first, then CoinGecko)."""
    # Try Binance first (faster and more real-time)
    price = get_binance_price(symbol)
    if price:
        return price
    
    # Fallback to CoinGecko
    return get_crypto_price(symbol)


def check_price_alerts():
    """Background task to check price alerts and price change notifications."""
    while True:
        try:
            # Check fixed price alerts
            for chat_id, alerts in list(price_alerts.items()):
                for alert in alerts[:]:  # Create a copy to safely remove items
                    symbol = alert["symbol"]
                    target_price = alert["target_price"]
                    direction = alert["direction"]
                    
                    current_price = get_best_price(symbol)
                    
                    if current_price is None:
                        continue
                    
                    triggered = False
                    if direction == "below" and current_price <= target_price:
                        triggered = True
                    elif direction == "above" and current_price >= target_price:
                        triggered = True
                    
                    if triggered:
                        message = (
                            f"🚨 *Alert Prezzo Attivato!*\n\n"
                            f"*{symbol}* è {'sceso sotto' if direction == 'below' else 'salito sopra'} ${target_price:,.2f}\n"
                            f"Prezzo attuale: ${current_price:,.2f}"
                        )
                        
                        safe_message = escape_markdown_v2(message)
                        
                        try:
                            payload = {
                                "chat_id": chat_id,
                                "text": safe_message,
                                "parse_mode": "MarkdownV2",
                            }
                            session.post(TELEGRAM_URL, json=payload, timeout=3)
                            logger.info(f"Price alert sent to chat {chat_id} for {symbol}")
                        except Exception as e:
                            logger.error(f"Failed to send price alert to chat {chat_id}: {e}")
                        
                        # Remove triggered alert
                        price_alerts[chat_id].remove(alert)
            
            # Check price change subscriptions (variazione prezzi)
            for chat_id, subscription in list(price_change_subscriptions.items()):
                symbols = subscription.get("symbols", [])
                threshold = subscription.get("threshold", 5.0)
                
                for symbol in symbols:
                    current_price = get_best_price(symbol)
                    
                    if current_price is None:
                        continue
                    
                    # Check if we have a previous price
                    if symbol in last_prices:
                        last_price = last_prices[symbol]
                        change_percent = ((current_price - last_price) / last_price) * 100
                        
                        # Send notification if price changed by threshold %
                        if abs(change_percent) >= threshold:
                            emoji = "📈" if change_percent > 0 else "📉"
                            direction = "aumentato" if change_percent > 0 else "diminuito"
                            
                            message = (
                                f"{emoji} *Variazione Prezzo Rilevata!*\n\n"
                                f"*{symbol}*: ${current_price:,.2f}\n"
                                f"Variazione: {change_percent:+.2f}%\n"
                                f"Il prezzo è {direction} di oltre {threshold}%"
                            )
                            
                            safe_message = escape_markdown_v2(message)
                            
                            try:
                                payload = {
                                    "chat_id": chat_id,
                                    "text": safe_message,
                                    "parse_mode": "MarkdownV2",
                                }
                                session.post(TELEGRAM_URL, json=payload, timeout=3)
                                logger.info(f"Price change alert sent to chat {chat_id} for {symbol}: {change_percent:+.2f}%")
                            except Exception as e:
                                logger.error(f"Failed to send price change alert to chat {chat_id}: {e}")
                    
                    # Update last price
                    last_prices[symbol] = current_price
            
            # Check every 60 seconds (can be made faster if needed)
            time.sleep(60)
        except Exception as e:
            logger.error(f"Error in price alert checker: {e}")
            time.sleep(60)


def escape_markdown_v2(text: str) -> str:
    """Escape text for Telegram MarkdownV2."""
    if not text:
        return ""
    return _MD_V2_CHARS_RE.sub(r"\\\1", text)


def truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    note = "\n\n[...] (troncato)"
    return text[: max(0, limit - len(note))] + note


@app.route("/", methods=["GET"])
def home():
    return "✅ AngelBot-AI (GPT-5) è online e operativo!", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    # Optional verification of the secret token to ensure webhook source
    if TELEGRAM_SECRET_TOKEN:
        header_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if not header_token or header_token != TELEGRAM_SECRET_TOKEN:
            logger.warning("Invalid or missing secret token on webhook request")
            # Return 401 so misconfigured clients can notice, but Telegram will not retry a 401 by default
            return jsonify({"ok": False, "error": "Unauthorized"}), 401

    data = request.get_json(silent=True)
    if not data or "message" not in data:
        logger.info("Webhook received empty or non-message update: %s", data)
        # Respond 200 to acknowledge the webhook but do not process
        return jsonify({"ok": True, "note": "No message to process"}), 200

    message = data["message"]
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = message.get("text")

    if not chat_id:
        logger.warning("Message without chat id: %s", message)
        return jsonify({"ok": True, "note": "No chat id"}), 200

    if not text:
        # Non-text messages (stickers, photos, etc.)
        logger.info("Non-text message received in chat %s: %s", chat_id, message.keys())
        # Optionally notify users that only text is supported
        try:
            payload = {
                "chat_id": chat_id,
                "text": "Mi dispiace, al momento supporto solo messaggi di testo.",
            }
            session.post(TELEGRAM_URL, json=payload, timeout=3)  # Reduced timeout for faster response
        except Exception:
            logger.exception("Failed to send non-text reply to chat %s", chat_id)
        return jsonify({"ok": True}), 200

    text = text.strip()
    
    # Handle trading commands
    if text.lower().startswith("/price "):
        symbol = text[7:].strip().upper()
        price = get_crypto_price(symbol)
        if price:
            reply = f"💰 *{symbol}*: ${price:,.2f} USD"
        else:
            reply = f"❌ Non riesco a trovare il prezzo per {symbol}. Prova con: BTC, ETH, SOL, BNB, XRP, ADA, DOGE, MATIC, DOT"
        safe = escape_markdown_v2(reply)
        try:
            session.post(
                TELEGRAM_URL,
                json={
                    "chat_id": chat_id,
                    "text": safe,
                    "parse_mode": "MarkdownV2",
                },
                timeout=3,
            )
        except Exception:
            logger.exception("Failed to send price reply to chat %s", chat_id)
        return jsonify({"ok": True}), 200
    
    elif text.lower() == "/mercato":
        reply = get_market_summary()
        safe = escape_markdown_v2(reply)
        try:
            session.post(
                TELEGRAM_URL,
                json={
                    "chat_id": chat_id,
                    "text": safe,
                    "parse_mode": "MarkdownV2",
                },
                timeout=3,
            )
        except Exception:
            logger.exception("Failed to send market summary to chat %s", chat_id)
        return jsonify({"ok": True}), 200
    
    elif text.lower().startswith("/alert "):
        # Format: /alert BTC below 50000 or /alert ETH above 3000
        parts = text[7:].strip().split()
        if len(parts) >= 3:
            symbol = parts[0].upper()
            direction = parts[1].lower()
            try:
                target_price = float(parts[2])
                if direction in ["below", "sotto", "above", "sopra"]:
                    direction = "below" if direction in ["below", "sotto"] else "above"
                    reply = add_price_alert(chat_id, symbol, target_price, direction)
                else:
                    reply = "❌ Direzione non valida. Usa: 'below'/'sotto' o 'above'/'sopra'"
            except ValueError:
                reply = "❌ Prezzo non valido. Esempio: /alert BTC below 50000"
        else:
            reply = "❌ Formato: /alert SYMBOL below/above PREZZO\nEsempio: /alert BTC below 50000"
        
        safe = escape_markdown_v2(reply)
        try:
            session.post(
                TELEGRAM_URL,
                json={
                    "chat_id": chat_id,
                    "text": safe,
                    "parse_mode": "MarkdownV2",
                },
                timeout=3,
            )
        except Exception:
            logger.exception("Failed to send alert confirmation to chat %s", chat_id)
        return jsonify({"ok": True}), 200
    
    elif text.lower() == "/alerts":
        user_alerts = price_alerts.get(chat_id, [])
        if user_alerts:
            reply = "📋 *I tuoi Alert Attivi:*\n\n"
            for i, alert in enumerate(user_alerts, 1):
                reply += f"{i}. *{alert['symbol']}* {'sopra' if alert['direction'] == 'above' else 'sotto'} ${alert['target_price']:,.2f}\n"
        else:
            reply = "📋 Non hai alert attivi.\n\nUsa /alert per impostarne uno!\nEsempio: /alert BTC below 50000"
        
        safe = escape_markdown_v2(reply)
        try:
            session.post(
                TELEGRAM_URL,
                json={
                    "chat_id": chat_id,
                    "text": safe,
                    "parse_mode": "MarkdownV2",
                },
                timeout=3,
            )
        except Exception:
            logger.exception("Failed to send alerts list to chat %s", chat_id)
        return jsonify({"ok": True}), 200
    
    elif text.lower().startswith("/monitora "):
        # Format: /monitora BTC,ETH,SOL 5 (symbols and threshold %)
        parts = text[10:].strip().split()
        if len(parts) >= 1:
            symbols = parts[0].upper().split(",")
            threshold = float(parts[1]) if len(parts) > 1 else 5.0
            
            price_change_subscriptions[chat_id] = {
                "symbols": symbols,
                "threshold": threshold
            }
            
            # Initialize last prices
            for symbol in symbols:
                price = get_best_price(symbol)
                if price:
                    last_prices[symbol] = price
            
            symbols_str = ", ".join(symbols)
            reply = (
                f"✅ *Monitoraggio Prezzi Attivato!*\n\n"
                f"Simboli: {symbols_str}\n"
                f"Soglia: {threshold}%\n\n"
                f"Ti avviserò quando i prezzi variano di oltre {threshold}%"
            )
        else:
            reply = "❌ Formato: /monitora SYMBOLS SOGLIA%\nEsempio: /monitora BTC,ETH,SOL 5"
        
        safe = escape_markdown_v2(reply)
        try:
            session.post(
                TELEGRAM_URL,
                json={
                    "chat_id": chat_id,
                    "text": safe,
                    "parse_mode": "MarkdownV2",
                },
                timeout=3,
            )
        except Exception:
            logger.exception("Failed to send monitoring confirmation to chat %s", chat_id)
        return jsonify({"ok": True}), 200
    
    elif text.lower() == "/stopmonitora":
        if chat_id in price_change_subscriptions:
            del price_change_subscriptions[chat_id]
            reply = "✅ Monitoraggio prezzi disattivato."
        else:
            reply = "ℹ️ Non hai un monitoraggio attivo."
        
        safe = escape_markdown_v2(reply)
        try:
            session.post(
                TELEGRAM_URL,
                json={
                    "chat_id": chat_id,
                    "text": safe,
                    "parse_mode": "MarkdownV2",
                },
                timeout=3,
            )
        except Exception:
            logger.exception("Failed to send stop monitoring confirmation to chat %s", chat_id)
        return jsonify({"ok": True}), 200
    
    elif text.lower() == "/status":
        reply = "*📊 Il Tuo Status Trading:*\n\n"
        
        # Price alerts
        user_alerts = price_alerts.get(chat_id, [])
        reply += f"*Alert Prezzo:* {len(user_alerts)}\n"
        
        # Monitoring
        if chat_id in price_change_subscriptions:
            subscription = price_change_subscriptions[chat_id]
            symbols = ", ".join(subscription["symbols"])
            threshold = subscription["threshold"]
            reply += f"*Monitoraggio:* ✅ Attivo\n"
            reply += f"  - Simboli: {symbols}\n"
            reply += f"  - Soglia: {threshold}%\n"
        else:
            reply += "*Monitoraggio:* ❌ Non attivo\n"
        
        reply += "\n💹 Usa /help per vedere tutti i comandi!"
        
        safe = escape_markdown_v2(reply)
        try:
            session.post(
                TELEGRAM_URL,
                json={
                    "chat_id": chat_id,
                    "text": safe,
                    "parse_mode": "MarkdownV2",
                },
                timeout=3,
            )
        except Exception:
            logger.exception("Failed to send status to chat %s", chat_id)
        return jsonify({"ok": True}), 200
    
    # Handle basic commands
    elif text.lower() in ["/start", "/help", "ciao", "hello"]:
        reply = (
            "👋 Ciao! Sono *AngelBot-AI*, il tuo assistente di trading personale!\n\n"
            "💹 *Funzionalità Trading:*\n"
            "• `/price SYMBOL` - Prezzo attuale (es: /price BTC)\n"
            "• `/mercato` - Riepilogo mercato crypto\n"
            "• `/alert SYMBOL below/above PREZZO` - Imposta alert\n"
            "• `/alerts` - Visualizza i tuoi alert\n\n"
            "🌐 Posso anche rispondere a domande sul trading e analizzare i mercati in tempo reale!\n"
            "⚡ Ottimizzato per risposte veloci e precise.\n\n"
            "Scrivimi qualsiasi cosa sul trading e ti aiuterò!"
        )
        # Escape and send reply as MarkdownV2
        safe = escape_markdown_v2(reply)
        try:
            session.post(
                TELEGRAM_URL,
                json={
                    "chat_id": chat_id,
                    "text": safe,
                    "parse_mode": "MarkdownV2",
                    "disable_web_page_preview": True,
                },
                timeout=3,  # Reduced timeout for faster response
            )
        except Exception:
            logger.exception("Failed to send command reply to chat %s", chat_id)
        return jsonify({"ok": True}), 200

    # Build prompt for the model with trading assistant capabilities
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # Enhanced system prompt for trading assistant
    system_instructions = (
        f"Sei AngelBot-AI, un assistente di trading esperto con accesso al web in tempo reale. "
        f"Data e ora attuale: {current_date}. "
        f"Specializzato in:\n"
        f"- Analisi tecnica e fondamentale\n"
        f"- Criptovalute, azioni, forex\n"
        f"- Strategie di trading e gestione del rischio\n"
        f"- Notizie di mercato in tempo reale\n"
        f"- Analisi dei trend e pattern di mercato\n\n"
        f"Quando l'utente chiede informazioni sui mercati, prezzi, o analisi:\n"
        f"1. Fornisci dati aggiornati usando le tue capacità web\n"
        f"2. Analizza trend e pattern\n"
        f"3. Suggerisci strategie quando appropriato\n"
        f"4. Avverti sempre sui rischi del trading\n\n"
        f"Rispondi in italiano, in modo chiaro e professionale."
    )
    
    try:
        # Use Chat Completions API for faster response with streaming capability
        # This is more performant than the Responses API
        response = client.chat.completions.create(
            model="gpt-4o",  # Using gpt-4o for faster performance and web capabilities
            messages=[
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": text}
            ],
            temperature=0.7,
            max_tokens=1500,  # Optimized for faster responses
            timeout=20  # Reduced timeout for faster response
        )
        
        reply = response.choices[0].message.content
        
        if not reply:
            reply = "Mi dispiace, non sono riuscito a ottenere una risposta dall'AI."

    except Exception as e:
        logger.exception("Error while calling OpenAI for chat %s", chat_id)
        reply = f"⚠️ Errore con l'AI: {str(e)}"

    # Escape and truncate for Telegram MarkdownV2
    safe_reply = escape_markdown_v2(reply)
    safe_reply = truncate_text(safe_reply, TELEGRAM_MAX_MESSAGE)

    # Send reply to Telegram
    payload = {
        "chat_id": chat_id,
        "text": safe_reply,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }

    try:
        session.post(TELEGRAM_URL, json=payload, timeout=3)  # Reduced timeout for faster response
    except Exception:
        logger.exception("Failed to send reply to chat %s", chat_id)

    # Always acknowledge the webhook to Telegram with 200 to avoid retries
    return jsonify({"ok": True}), 200


if __name__ == "__main__":
    # Start price alert monitoring in background thread
    alert_thread = Thread(target=check_price_alerts, daemon=True)
    alert_thread.start()
    logger.info("Price alert monitoring started")
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
