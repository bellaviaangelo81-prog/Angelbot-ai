# Troubleshooting Guide - Angelbot-ai

## Bot non risponde (Bot not responding)

Se il bot non risponde ai comandi, segui questi passaggi per diagnosticare il problema:

### 1. Verifica lo stato del bot

Visita l'endpoint `/status` del tuo servizio:
```
https://your-app-name.onrender.com/status
```

Questo ti mostrerà:
- Se il bot è inizializzato
- L'URL del webhook configurato
- Numero di aggiornamenti in coda
- Eventuali errori da Telegram

### 2. Controlla le variabili d'ambiente

Assicurati che su Render siano impostate **entrambe** le variabili:

```bash
TELEGRAM_TOKEN=your_bot_token_here
WEBHOOK_URL=https://your-app-name.onrender.com/webhook
```

**IMPORTANTE:** 
- `TELEGRAM_TOKEN`: Ottieni il token da [@BotFather](https://t.me/botfather)
- `WEBHOOK_URL`: Deve includere `/webhook` alla fine!
  - ✓ **CORRETTO:** `https://your-app-name.onrender.com/webhook`
  - ✗ **SBAGLIATO:** `https://your-app-name.onrender.com`

### 3. Verifica i log su Render

1. Vai su Render Dashboard
2. Seleziona il tuo servizio
3. Clicca su "Logs"
4. Cerca questi messaggi:
   - `✓ Bot initialized successfully` - Il bot si è avviato
   - `✓ Webhook configured: https://...` - Il webhook è configurato
   - `Received update from Telegram` - Un messaggio è arrivato

**Se vedi errori nei log:**
- Copia l'errore completo
- Cerca l'errore su Google o Stack Overflow
- Verifica che tutte le dipendenze siano installate

### 4. Test del webhook manualmente

Usa il comando curl per verificare il webhook di Telegram:

```bash
curl https://api.telegram.org/bot<YOUR_TOKEN>/getWebhookInfo
```

Sostituisci `<YOUR_TOKEN>` con il tuo token reale.

**Risposta corretta:**
```json
{
  "ok": true,
  "result": {
    "url": "https://your-app-name.onrender.com/webhook",
    "has_custom_certificate": false,
    "pending_update_count": 0
  }
}
```

**Se l'URL è vuoto o diverso:**
Il webhook non è configurato correttamente. Verifica `WEBHOOK_URL`.

**Se `pending_update_count` è > 0:**
Ci sono messaggi in coda. Il bot non sta processando gli aggiornamenti.

### 5. Riavvia il servizio

A volte un semplice riavvio risolve il problema:

1. Vai su Render Dashboard
2. Seleziona il tuo servizio
3. Clicca su "Manual Deploy" > "Deploy latest commit"

### 6. Test locale (opzionale)

Se vuoi testare localmente:

```bash
# Installa le dipendenze
pip install -r requirements.txt

# Imposta le variabili d'ambiente
export TELEGRAM_TOKEN="your_token"
export PORT=5000

# Avvia il server
python server.py
```

**Nota:** Per testing locale, è meglio usare polling invece di webhook. Il codice attuale è ottimizzato per webhook in produzione.

### 7. Problemi comuni

#### Il bot era attivo ma ora non risponde più

**Possibili cause:**
1. **Render ha messo il servizio in sleep** - I servizi free su Render vanno in sleep dopo 15 minuti di inattività
   - **Soluzione:** Fai una richiesta a `https://your-app-name.onrender.com/health` per svegliarlo
   - **Prevenzione:** Usa un servizio come UptimeRobot per fare ping ogni 5 minuti

2. **Il webhook è scaduto o è stato resettato**
   - **Soluzione:** Riavvia il servizio su Render
   - Il webhook verrà riconfigurato automaticamente

3. **Le variabili d'ambiente sono state modificate**
   - **Soluzione:** Verifica che TELEGRAM_TOKEN e WEBHOOK_URL siano ancora corretti

4. **Telegram ha un'interruzione del servizio**
   - **Soluzione:** Controlla https://telegram.org/ o @telegram su Twitter

#### Errore "Unauthorized" nei log

Il token del bot non è valido o è scaduto.

**Soluzione:**
1. Vai su [@BotFather](https://t.me/botfather)
2. Usa il comando `/mybots`
3. Seleziona il tuo bot
4. Verifica o rigenera il token
5. Aggiorna la variabile `TELEGRAM_TOKEN` su Render

#### Errore "Bad Gateway" o "Connection timeout"

Il servizio Render non è raggiungibile o è sovraccarico.

**Soluzione:**
1. Controlla lo stato di Render: https://status.render.com/
2. Verifica i log per vedere se ci sono errori di memoria o timeout
3. Considera di aumentare le risorse del servizio (passare a piano paid)

### 8. Comandi utili per il debugging

**Controlla salute del servizio:**
```bash
curl https://your-app-name.onrender.com/health
```

**Controlla stato bot e webhook:**
```bash
curl https://your-app-name.onrender.com/status
```

**Info webhook da Telegram:**
```bash
curl https://api.telegram.org/bot<YOUR_TOKEN>/getWebhookInfo
```

**Elimina webhook (per test):**
```bash
curl https://api.telegram.org/bot<YOUR_TOKEN>/deleteWebhook
```

**Reimposta webhook manualmente:**
```bash
curl -X POST https://api.telegram.org/bot<YOUR_TOKEN>/setWebhook \
  -d "url=https://your-app-name.onrender.com/webhook"
```

### 9. Se niente funziona

1. Esporta i log completi da Render
2. Crea un issue su GitHub con:
   - Descrizione del problema
   - Log completi (rimuovi il token!)
   - Output di `/getWebhookInfo`
   - Output di `/status`
3. Verifica che il problema non sia temporaneo aspettando 5-10 minuti

## Contatti e supporto

- **Repository:** https://github.com/bellaviaangelo81-prog/Angelbot-ai
- **Telegram Bot API Docs:** https://core.telegram.org/bots/api
- **Render Docs:** https://render.com/docs
