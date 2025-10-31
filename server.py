# app.py
from flask import Flask, request, jsonify

app = Flask(__name__)

# Rotta base: serve solo per testare che il server sia vivo
@app.route('/')
def home():
    return jsonify({"messaggio": "Server attivo su Render!"})

# Rotta per ricevere messaggi dal telefono o da altri client
@app.route('/messaggio', methods=['POST'])
def ricevi_messaggio():
    dati = request.get_json()
    utente = dati.get("utente", "Sconosciuto")
    testo = dati.get("testo", "")
    print(f"📩 Messaggio ricevuto da {utente}: {testo}")
    return jsonify({"risposta": f"Ciao {utente}, ho ricevuto: '{testo}'!"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
