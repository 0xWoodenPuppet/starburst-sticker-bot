from flask import Flask

app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Bot is alive!"

def run_web():
    app_web.run(host="0.0.0.0", port=3000)
