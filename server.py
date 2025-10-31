from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"messaggio": "Server attivo su Render!"})

@app.route('/saluta')
def saluta():
    nome = request.args.get('nome', 'amico')
    return jsonify({"messaggio": f"Ciao, {nome}, dal server Render!"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
