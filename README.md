# Angelbot-ai 🤖📈

Bot Telegram per assistenza finanziaria, costruito con **python-telegram-bot v20+** e Flask.

## 🌟 Funzionalità

- **Prezzo azioni**: Ottieni il prezzo corrente di qualsiasi azione
- **Grafici**: Visualizza l'andamento mensile delle azioni
- **Informazioni aziendali**: Dettagli su settore, paese e capitalizzazione

## 📋 Prerequisiti

- Python 3.9 o superiore
- Account Telegram e un bot token (da [@BotFather](https://t.me/botfather))
- Account per il deploy (es. Render, Heroku, o server proprio)

## 🚀 Installazione

### 1. Clona il repository

```bash
git clone https://github.com/bellaviaangelo81-prog/Angelbot-ai.git
cd Angelbot-ai
```

### 2. Installa le dipendenze

```bash
pip install -r requirements.txt
```

### 3. Configura le variabili d'ambiente

Crea un file `.env` o imposta le seguenti variabili d'ambiente:

```bash
TELEGRAM_TOKEN=your_bot_token_here
WEBHOOK_URL=https://your-app-url.com/webhook
PORT=5000
```

**Nota**: Il `TELEGRAM_TOKEN` è obbligatorio. Il `WEBHOOK_URL` è necessario solo in modalità webhook (production).

## 🎯 Avvio del Bot

### Modalità Development (Locale)

Per testare il bot localmente con Flask:

```bash
python server.py
```

Il server sarà disponibile su `http://localhost:5000`

### Modalità Production (Webhook)

Il bot è configurato per funzionare con webhook su piattaforme di hosting come Render:

1. Deploy il codice su Render (o altra piattaforma)
2. Imposta le variabili d'ambiente nel dashboard
3. L'applicazione si avvierà automaticamente con gunicorn (vedi `Procfile`)

```bash
gunicorn server:app
```

## 📚 Comandi Bot

- `/start` - Messaggio di benvenuto e lista comandi
- `/prezzo <simbolo>` - Mostra il prezzo attuale (es. `/prezzo TSLA`)
- `/grafico <simbolo>` - Mostra il grafico dell'ultimo mese (es. `/grafico AAPL`)
- `/info <simbolo>` - Informazioni sull'azienda (settore, paese, capitalizzazione)

## 🏗️ Architettura

Il progetto utilizza **python-telegram-bot v20+** con le seguenti best practice:

### ApplicationBuilder Pattern

```python
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Inizializzazione con ApplicationBuilder (v20+)
app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
```

### Handler Asincroni

Tutti gli handler sono funzioni async compatibili con la nuova API:

```python
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Benvenuto!")
```

### Gestione Webhook

Il bot utilizza un pattern corretto per gestire webhook in modo asincrono:

```python
@app.route('/webhook', methods=['POST'])
def webhook():
    # Lazy initialization on first request
    _ensure_bot_initialized()

    async def process():
        json_data = request.get_json(force=True)
        update = Update.de_json(json_data, app_bot.bot)
        await app_bot.process_update(update)

    asyncio.run(process())
    return "ok", 200
```

### Inizializzazione Applicazione

L'applicazione utilizza un'inizializzazione lazy (al primo webhook) per compatibilità con server WSGI come gunicorn:

```python
bot_initialized = False

def _ensure_bot_initialized():
    global _bot_initialized
    if not _bot_initialized:
        async def init():
            await app_bot.initialize()
            webhook_url = os.getenv("WEBHOOK_URL")
            if webhook_url:
                await app_bot.bot.set_webhook(url=webhook_url)

        asyncio.run(init())
        _bot_initialized = True
```

## 📦 Dipendenze

- `flask==3.1.2` - Web framework per webhook
- `python-telegram-bot==20.6` - Libreria Telegram Bot API v20+
- `gunicorn==21.2.0` - WSGI server per production
- `yfinance` - Dati finanziari
- `matplotlib` - Generazione grafici
- `openai>=1.0.0` - Integrazioni AI (future)
- `requests==2.31.0` - HTTP client
- `schedule` - Task scheduling (future)

## 🔧 Struttura File

```
Angelbot-ai/
├── server.py          # Applicazione principale (bot + Flask)
├── requirements.txt   # Dipendenze Python
├── Procfile          # Configurazione per Render/Heroku
├── README.md         # Documentazione
└── .gitignore        # File da ignorare in git
```

## 🆕 Migrazione da Versioni Precedenti

Se stai aggiornando da python-telegram-bot v13.x o precedenti:

### ❌ API Obsolete (NON usare)

```python
# VECCHIO - Non più supportato
from telegram.ext import Updater

updater = Updater(token=TOKEN)
dispatcher = updater.dispatcher
updater.start_polling()
```

### ✅ Nuove API (v20+)

```python
# NUOVO - Versione corretta
from telegram.ext import ApplicationBuilder

app = ApplicationBuilder().token(TOKEN).build()
# Usa app.run_polling() o webhook
```

### Principali Cambiamenti

1. **Updater rimosso** → Usa `ApplicationBuilder`
2. **Dispatcher rimosso** → Usa `Application` direttamente
3. **Tutti gli handler devono essere async** → Aggiungi `async`/`await`
4. **CallbackContext** → Usa `ContextTypes.DEFAULT_TYPE`
5. **Inizializzazione richiesta** → Chiama `await app.initialize()`

## 🐛 Troubleshooting

### Errore: "Module 'telegram.ext' has no attribute 'Updater'"

Assicurati di usare `python-telegram-bot>=20.0` e di aver rimosso tutti i riferimenti a `Updater`.

### Il bot non risponde ai comandi

**Causa principale:** Il webhook non è configurato correttamente.

**Soluzione:**

1. **Verifica la variabile WEBHOOK_URL** - Deve includere il path `/webhook`:
   ```bash
   # ✓ CORRETTO
   WEBHOOK_URL=https://your-app-url.onrender.com/webhook
   
   # ✗ SBAGLIATO (manca /webhook)
   WEBHOOK_URL=https://your-app-url.onrender.com
   ```

2. **Controlla lo stato del webhook** - Visita `https://your-app-url.onrender.com/status` per vedere:
   - Se il bot è inizializzato
   - L'URL del webhook configurato
   - Eventuali errori di Telegram
   - Numero di aggiornamenti in coda

3. **Verifica i log** - Controlla i log dell'applicazione su Render:
   - Cerca messaggi come "✓ Webhook configured"
   - Controlla se ci sono errori durante l'inizializzazione
   - Verifica che gli aggiornamenti vengano ricevuti ("Received update")

4. **Requisiti Telegram:**
   - L'URL deve essere HTTPS (Render lo fornisce automaticamente)
   - Il server deve essere raggiungibile pubblicamente
   - Il token del bot deve essere valido

5. **Test manuale del webhook:**
   ```bash
   # Controlla info webhook via Telegram API
   curl https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo
   ```

### Webhook non riceve aggiornamenti

1. Verifica che `WEBHOOK_URL` sia impostato correttamente (vedi sopra)
2. Assicurati che l'URL sia HTTPS (richiesto da Telegram)
3. Controlla che il server sia raggiungibile pubblicamente
4. Usa l'endpoint `/status` per diagnosticare problemi

### Errori con asyncio

Assicurati che tutti gli handler siano dichiarati come `async` e che usi `await` per chiamate asincrone.

## 📄 Licenza

Questo progetto è open source.

## 👤 Autore

**bellaviaangelo81-prog**

## 🤝 Contribuire

Contributi, issues e feature requests sono benvenuti!

---
