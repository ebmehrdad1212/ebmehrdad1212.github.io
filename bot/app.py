from flask import Flask, render_template, jsonify, request
import asyncio
from main import run_bot, log_messages
import threading
import time
from datetime import datetime
import json

app = Flask(__name__)
bot_running = False
bot_thread = None

def load_config():
    with open('bot/config.json', 'r', encoding='utf-8') as f:
        return json.load(f)

config = load_config()

def start_bot():
    global bot_running
    bot_running = True
    try:
        while bot_running:
            current_hour = datetime.now().hour
            if current_hour in config['peak_hours']:
                asyncio.run(run_bot())
            time.sleep(60)  # هر دقیقه چک کن
    except Exception as e:
        log_messages.append(f"خطا در اجرای بات: {str(e)}")
    finally:
        bot_running = False

@app.route('/')
def index():
    return render_template('index.html', bot_running=bot_running)

@app.route('/logs')
def get_logs():
    return jsonify(log_messages)

@app.route('/start', methods=['POST'])
def start():
    global bot_thread
    if not bot_running:
        bot_thread = threading.Thread(target=start_bot)
        bot_thread.daemon = True
        bot_thread.start()
        return jsonify({'status': 'started'})
    return jsonify({'status': 'already running'})

@app.route('/stop', methods=['POST'])
def stop():
    global bot_running
    if bot_running:
        bot_running = False
        log_messages.append("بات متوقف شد.")
        return jsonify({'status': 'stopped'})
    return jsonify({'status': 'not running'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)