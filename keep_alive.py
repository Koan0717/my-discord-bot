import os
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting Flask server on port {port}...", flush=True)
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    print("keep_alive called! Starting thread...", flush=True)
    t = Thread(target=run)
    t.start()
