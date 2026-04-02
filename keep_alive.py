from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "MCT Bot is Alive!"

def run_server(): # Renamed to avoid confusion
    app.run(host='0.0.0.0', port=8080)

def keep_alive(): # This is the function that starts the thread
    t = Thread(target=run_server)
    t.start()
