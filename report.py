import yfinance as yf
import matplotlib.pyplot as plt
import base64, io, time, datetime, os, threading, requests
from openai import OpenAI

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID_PERSONALE = os.getenv("CHAT_ID_PERSONALE")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})

def genera_grafico(symbol, giorni=7):
    stock = yf.Ticker(symbol)
    data = stock.history(period=f"{giorni}d")
    plt.figure()
    plt.plot(data.index, data['Close'], marker='o')
    plt.title(f"Andamento {symbol} - ultimi {giorni} giorni")
    plt.xlabel("Data")
    plt.ylabel("Prezzo ($)")
    plt.grid(True)
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    plt.close()
    return buf

def genera_report_giornaliero(chat_id=None):
    indici = {
        "S&P 500": "^GSPC",
        "NASDAQ": "^IXIC",
        "EURO STOXX 50": "^STOXX50E",
        "NIKKEI 225": "^N225"
    }

    report = "🌍 <b>Report Globale Mercati</b>\n\n"
    for nome, symbol in indici.items():
        stock = yf.Ticker(symbol)
        info = stock.info
        prezzo = info.get("regularMarketPrice", None)
        delta = info.get("regularMarketChangePercent", 0)
        tendenza = "📈" if delta > 0 else "📉"
        report += f"{nome}: {prezzo}$ ({round(delta, 2)}%) {tendenza}\n"

    azioni = ["AAPL", "AMZN", "TSLA", "MSFT", "NVDA", "GOOGL"]
    variazioni = []
    for s in azioni:
        try:
            info = yf.Ticker(s).info
            variazioni.append((s, info.get("shortName", s), info.get("regularMarketChangePercent", 0)))
        except:
            continue

    variazioni.sort(key=lambda x: x[2], reverse=True)
    top3 = variazioni[:3]
    worst3 = variazioni[-3:]

    report += "\n🏆 <b>Migliori titoli</b>\n"
    for s, nome, v in top3:
        report += f"• {nome} ({s}): {round(v, 2)}%\n"

    report += "\n⚠️ <b>Peggiori titoli</b>\n"
    for s, nome, v in worst3:
        report += f"• {nome} ({s}): {round(v, 2)}%\n"

    analisi = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Agisci come analista finanziario esperto."},
            {"role": "user", "content": f"Analizza il seguente report:\n{report}"}
        ]
    ).choices[0].message.content.strip()

    report += f"\n🧠 <b>Analisi GPT:</b>\n{analisi}"

    send_message(chat_id or CHAT_ID_PERSONALE, report)

    grafico = genera_grafico("^GSPC")
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
        data={"chat_id": chat_id or CHAT_ID_PERSONALE},
        files={"photo": grafico}
    )

def avvia_report_programmato():
    while True:
        ora = datetime.datetime.now()
        if ora.hour == 9 and ora.minute == 0:
            genera_report_giornaliero()
            time.sleep(60)
        time.sleep(30)
