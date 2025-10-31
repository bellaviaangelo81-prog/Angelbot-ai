# AngelBot-AI 🤖

Assistente di trading avanzato per Telegram con supporto per criptovalute e mercati azionari globali.

## 🌟 Funzionalità

### 💰 Criptovalute
- Prezzi in tempo reale (Bitcoin, Ethereum, Solana, BNB, XRP, ADA, ecc.)
- Riepilogo mercato con variazioni 24h
- Alert personalizzati

### 📈 Azioni Internazionali
Organizzate per continente per facilitare la ricerca:
- 🇺🇸 **Stati Uniti**: Apple, Microsoft, Google, Amazon, Tesla, NVIDIA, Meta, JPMorgan
- 🇪🇺 **Europa**: SAP, ASML, Novo Nordisk, LVMH, Siemens, L'Oréal  
- 🌏 **Asia**: TSMC, Alibaba, Sony, Toyota, Samsung, TCS

### 🔔 Alert e Monitoraggio
- Alert di prezzo personalizzati
- Monitoraggio variazioni in tempo reale
- Notifiche automatiche

### 🎯 Interfaccia Interattiva
- Menu con pulsanti per navigazione facile
- Nessuna necessità di ricordare comandi
- Ottimizzato per mobile

### 🌐 AI con Accesso Web
- GPT-4o con capacità di navigazione web in tempo reale
- Risposte aggiornate sui mercati
- Analisi tecnica e fondamentale

## 🚀 Quick Start

### 1. Prerequisiti
- Token bot Telegram (da [@BotFather](https://t.me/botfather))
- Chiave API OpenAI
- Servizio hosting con URL pubblico HTTPS

### 2. Installazione

```bash
# Clona il repository
git clone https://github.com/bellaviaangelo81-prog/Angelbot-ai.git
cd Angelbot-ai

# Installa dipendenze
pip install -r requirements.txt
```

### 3. Configurazione

Imposta le variabili d'ambiente:

```bash
export TELEGRAM_TOKEN="il_tuo_token"
export OPENAI_API_KEY="la_tua_chiave"
export TELEGRAM_SECRET_TOKEN="token_segreto_opzionale"
```

### 4. Avvia il Bot

```bash
python server.py
```

### 5. Configura il Webhook

**IMPORTANTE**: Per vedere i pulsanti interattivi, devi configurare il webhook con Telegram:

```bash
curl -X POST "https://api.telegram.org/bot<IL_TUO_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://il-tuo-dominio.com/webhook",
    "allowed_updates": ["message", "callback_query"],
    "drop_pending_updates": true
  }'
```

**📚 Guida Completa**: Vedi [SETUP.md](SETUP.md) per istruzioni dettagliate.

## 💡 Comandi

### Criptovalute
- `/price BTC` - Prezzo Bitcoin
- `/mercato` - Riepilogo mercato crypto

### Azioni
- `/stock AAPL` - Prezzo azione Apple
- `/menu` - Menu interattivo con pulsanti (organizzato per continente)

### Alert e Monitoraggio  
- `/alert BTC below 50000` - Imposta alert
- `/alerts` - Visualizza alert attivi
- `/monitora BTC,ETH,SOL 5` - Monitora variazioni >5%
- `/status` - Visualizza il tuo status

### Generale
- `/start` - Avvia il bot
- `/help` - Mostra aiuto
- `/menu` - Mostra menu con pulsanti

## 🔧 Deploy

### Heroku

```bash
heroku create nome-tuo-bot
heroku config:set TELEGRAM_TOKEN=xxx
heroku config:set OPENAI_API_KEY=xxx
git push heroku main
```

Poi configura il webhook con l'URL di Heroku.

### Render

```bash
# 1. Crea nuovo Web Service su Render
# 2. Connetti il repository
# 3. Configura:
#    Build Command: pip install -r requirements.txt
#    Start Command: gunicorn server:app
# 4. Aggiungi variabili d'ambiente:
TELEGRAM_TOKEN=xxx
OPENAI_API_KEY=xxx
TELEGRAM_SECRET_TOKEN=xxx
# 5. Deploy
```

Poi configura il webhook con l'URL Render (es: `https://tuo-servizio.onrender.com/webhook`).

**Importante**: Se vedi "Application exited early", assicurati che le variabili d'ambiente siano configurate correttamente.

### Railway

1. Connetti il repository
2. Imposta le variabili d'ambiente
3. Deploy
4. Configura il webhook con l'URL pubblico

## 📊 Architettura

- **Flask**: Server web per webhook Telegram
- **OpenAI GPT-4o**: AI con accesso web per risposte intelligenti
- **Binance API**: Prezzi crypto in tempo reale
- **Yahoo Finance API**: Prezzi azioni internazionali
- **CoinGecko API**: Backup per prezzi crypto
- **Threading**: Monitoraggio prezzi in background

## 🛡️ Sicurezza

- Validazione token webhook opzionale
- Retry con backoff esponenziale
- Timeout su tutte le chiamate di rete
- Gestione errori completa
- Logging strutturato

## 📝 Note

- Per vedere i **pulsanti interattivi**, è essenziale configurare il webhook con `allowed_updates: ["message", "callback_query"]`
- Il bot richiede un URL pubblico HTTPS per il webhook
- I prezzi sono in tempo reale ma possono avere un leggero ritardo

## 🐛 Risoluzione Problemi

**I pulsanti non appaiono?**
1. Verifica che il webhook sia configurato: `curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"`
2. Assicurati che `allowed_updates` includa `"callback_query"`
3. Vedi [SETUP.md](SETUP.md) per la guida completa

## 📄 Licenza

Questo progetto è open source.

## 🤝 Contributi

I contributi sono benvenuti! Apri un issue o una pull request.
