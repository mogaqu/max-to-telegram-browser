import threading
from flask import Flask

app = Flask(__name__)

@app.route("/")
def health():
    return "OK", 200

@app.route("/ping")
def ping():
    return "pong", 200

def start_server():
    app.run(host="0.0.0.0", port=10000)

def run_in_background():
    t = threading.Thread(target=start_server, daemon=True)
    t.start()