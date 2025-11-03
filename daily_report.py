import requests
import random
import datetime

# === CONFIGURAZIONE ===
BOT_TOKEN = "INSERISCI_IL_TUO_TOKEN_QUI"
CHAT_ID = "1122092272"

# Lista titoli per esempio (puoi ampliarla liberamente)
stocks = {
    "AAPL": "Apple",
    "TSLA": "Tesla",
    "MSFT": "Microsoft",
    "AMZN": "Amazon",
    "NVDA": "Nvidia",
    "GOOGL": "Alphabet",
    "NFLX": "Netflix",
    "META": "Meta Platforms",
    "BABA": "Alibaba",
    "RACE": "Ferrari",
    "ENI.MI": "ENI",
    "BMW.DE": "BMW"
}

# Simulazione di dati d’analisi (in futuro potrai collegare API reali)
signals = ["📈 Rialzo probabile", "📉 Ribasso probabile", "😐 Laterale", "🔥 Ipercomprato", "🧊 Ipervenduto"]
advice = [
    "Consiglio: attendere conferma tecnica prima dell'acquisto.",
    "Consiglio: possibile opportunità di ingresso a breve.",
    "Consiglio: monitorare il volume degli scambi.",
    "Consiglio: fase di correzione in corso.",
    "Consiglio: attenzione a resistenze chiave."
]

# === CREAZIONE DEL REPORT ===
today = datetime.date.today().strftime("%d/%m/%Y")
report_lines = [f"📊 Report giornaliero titoli – {today}\n"]

for symbol, name in stocks.items():
    trend = random.choice(signals)
    tip = random.choice(advice)
    report_lines.append(f"🔹 {name} ({symbol})\n{trend}\n{tip}\n")

message = "\n".join(report_lines)

# === INVIO SU TELEGRAM ===
url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
params = {
    "chat_id": CHAT_ID,
    "text": message
}

response = requests.get(url, params=params)

if response.status_code == 200:
    print("✅ Report inviato correttamente su Telegram.")
else:
    print(f"⚠️ Errore: {response.text}")
