# Setup Guide per AngelBot-AI

Questa guida ti aiuterà a configurare il bot Telegram con tutte le funzionalità interattive.

## Prerequisiti

1. **Token del Bot Telegram**
   - Crea un bot su Telegram usando [@BotFather](https://t.me/botfather)
   - Salva il token che ricevi

2. **Chiave API OpenAI**
   - Registrati su [OpenAI](https://platform.openai.com/)
   - Genera una API key

3. **URL Pubblico**
   - Serve un URL pubblico accessibile (es: Heroku, Railway, render.com)
   - L'URL deve essere HTTPS

## Configurazione

### 1. Variabili d'Ambiente

Imposta queste variabili d'ambiente nel tuo servizio di hosting:

```bash
TELEGRAM_TOKEN=il_tuo_token_telegram
OPENAI_API_KEY=la_tua_chiave_openai
TELEGRAM_SECRET_TOKEN=un_token_segreto_opzionale  # Opzionale ma consigliato
PORT=5000  # Opzionale, default 5000
LOG_LEVEL=INFO  # Opzionale, default INFO
```

### 2. Configura il Webhook

Dopo aver deployato il bot, devi configurare il webhook con Telegram.

**Metodo 1: Usando curl (Raccomandato)**

```bash
curl -X POST "https://api.telegram.org/bot<IL_TUO_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://il-tuo-dominio.com/webhook",
    "allowed_updates": ["message", "callback_query"],
    "drop_pending_updates": true,
    "secret_token": "il_tuo_secret_token_opzionale"
  }'
```

**Metodo 2: Usando il browser**

Vai a questo URL sostituendo `<IL_TUO_TOKEN>` e `<IL_TUO_URL>`:

```
https://api.telegram.org/bot<IL_TUO_TOKEN>/setWebhook?url=<IL_TUO_URL>/webhook&allowed_updates=["message","callback_query"]&drop_pending_updates=true
```

Esempio:
```
https://api.telegram.org/bot123456789:ABC-DEF/setWebhook?url=https://mio-bot.herokuapp.com/webhook&allowed_updates=["message","callback_query"]&drop_pending_updates=true
```

### 3. Verifica il Webhook

Controlla che il webhook sia configurato correttamente:

```bash
curl "https://api.telegram.org/bot<IL_TUO_TOKEN>/getWebhookInfo"
```

Dovresti vedere:
- `url`: Il tuo URL webhook
- `has_custom_certificate`: false
- `pending_update_count`: 0
- `allowed_updates`: ["message", "callback_query"]

## Test del Bot

1. **Apri il bot su Telegram**
   - Cerca il tuo bot usando il nome che hai scelto
   - Clicca "Start" o scrivi `/start`

2. **Verifica i pulsanti**
   - Dovresti vedere un messaggio di benvenuto con pulsanti interattivi
   - I pulsanti dovrebbero includere:
     - 💰 Prezzi Crypto
     - 📈 Azioni
     - 📊 Mercato Crypto
     - 🔔 Alert Prezzo
     - 📈 Monitora Variazioni
     - 📋 Il Mio Status
     - ❓ Aiuto

3. **Test dei comandi**
   - `/menu` - Mostra il menu con pulsanti
   - `/help` - Mostra l'aiuto
   - `/price BTC` - Controlla il prezzo del Bitcoin
   - `/stock AAPL` - Controlla il prezzo delle azioni Apple

## Risoluzione Problemi

### I pulsanti non appaiono

**Causa**: Il webhook non è configurato correttamente o non include "callback_query" negli updates.

**Soluzione**:
1. Verifica che il webhook sia attivo:
   ```bash
   curl "https://api.telegram.org/bot<IL_TUO_TOKEN>/getWebhookInfo"
   ```

2. Assicurati che `allowed_updates` includa `["message", "callback_query"]`

3. Se necessario, cancella e riconfigura il webhook:
   ```bash
   curl -X POST "https://api.telegram.org/bot<IL_TUO_TOKEN>/deleteWebhook?drop_pending_updates=true"
   ```
   
   Poi riconfigura come descritto sopra.

### Il bot non risponde

**Causa**: Il webhook potrebbe non essere raggiungibile o le variabili d'ambiente non sono configurate.

**Soluzione**:
1. Controlla i log del server per errori
2. Verifica che l'URL pubblico sia accessibile: `curl https://il-tuo-dominio.com/`
3. Verifica le variabili d'ambiente

### Errori API

**Causa**: Token o chiavi API non valide.

**Soluzione**:
1. Verifica che `TELEGRAM_TOKEN` sia corretto
2. Verifica che `OPENAI_API_KEY` sia valida
3. Controlla i log per messaggi di errore specifici

### "Application exited early" su Render

**Causa**: Le variabili d'ambiente non sono configurate, causando l'uscita del server all'avvio.

**Soluzione**:
1. Vai su Render Dashboard → Il tuo servizio → Environment
2. Aggiungi queste variabili:
   - `TELEGRAM_TOKEN` = il tuo token
   - `OPENAI_API_KEY` = la tua chiave
   - `TELEGRAM_SECRET_TOKEN` = un token segreto (opzionale)
3. Clicca "Save Changes"
4. Il servizio si riavvierà automaticamente

**Verifica nei log**:
- Se vedi "Missing required environment variables", le variabili non sono impostate
- Se il server parte correttamente, vedrai "Running on http://0.0.0.0:..."

## Deploy su Render

1. **Crea un nuovo Web Service**:
   - Vai su [Render Dashboard](https://dashboard.render.com/)
   - Clicca "New +" → "Web Service"
   - Connetti il tuo repository GitHub

2. **Configura il servizio**:
   - **Name**: `angelbot-ai` (o un nome a tua scelta)
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn server:app` (o `python server.py`)
   - **Plan**: Free

3. **Aggiungi variabili d'ambiente** (IMPORTANTE):
   - `TELEGRAM_TOKEN` = il tuo token da BotFather
   - `OPENAI_API_KEY` = la tua chiave OpenAI
   - `TELEGRAM_SECRET_TOKEN` = un token segreto (opzionale ma consigliato)

4. **Deploy**:
   - Clicca "Create Web Service"
   - Attendi il completamento del build

5. **Configura il webhook**:
   ```bash
   curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
     -H "Content-Type: application/json" \
     -d '{
       "url": "https://tuo-servizio.onrender.com/webhook",
       "allowed_updates": ["message", "callback_query"],
       "drop_pending_updates": true
     }'
   ```

**Nota**: Render fornisce automaticamente la variabile `PORT`, non serve configurarla.

## Deploy su Heroku

1. **Crea un'app Heroku**:
   ```bash
   heroku create nome-tuo-bot
   ```

2. **Configura le variabili d'ambiente**:
   ```bash
   heroku config:set TELEGRAM_TOKEN=il_tuo_token
   heroku config:set OPENAI_API_KEY=la_tua_chiave
   heroku config:set TELEGRAM_SECRET_TOKEN=un_token_segreto
   ```

3. **Deploy**:
   ```bash
   git push heroku main
   ```

4. **Configura il webhook** usando l'URL di Heroku:
   ```
   https://nome-tuo-bot.herokuapp.com/webhook
   ```

## Supporto

Per ulteriore assistenza:
- Controlla i log del server
- Verifica la configurazione del webhook
- Assicurati che tutte le variabili d'ambiente siano impostate correttamente
