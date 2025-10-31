from flask import Flask, request, jsonify

app = Flask(__name__)
from flask import request, jsonify

@app.route('/messaggio', methods=['POST'])
def ricevi_messaggio():
    dati = request.get_json()
    utente = dati.get("utente", "Sconosciuto")
    testo = dati.get("testo", "")
    print(f"📩 Messaggio da {utente}: {testo}")
    return jsonify({"risposta": f"Ciao {utente}, ho ricevuto: {testo}!"})
@app.route('/')
def home():
    return jsonify({"messaggio": "Server attivo su Render!"})

@app.route('/saluta')
def saluta():
    nome = request.args.get('nome', 'amico')
    return jsonify({"messaggio": f"Ciao, {nome}, dal server Render!"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
