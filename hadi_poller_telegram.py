# hadi_poller_telegram.py
"""
Web-service compatible Hadi poller + Flask keepalive.
Run locally: python hadi_poller_telegram.py
Render Start Command: python hadi_poller_telegram.py
"""

import os
import time
import json
import hashlib
import re
import sys
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import requests
from flask import Flask, jsonify

# load local .env for testing (won't affect Render env vars)
load_dotenv()

# === Config from environment ===
HADI_API_URL = os.getenv("HADI_API_URL")
HADI_TOKEN = os.getenv("HADI_TOKEN")
HADI_RECORDS = int(os.getenv("HADI_RECORDS", "100"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))
STATE_FILE = os.getenv("STATE_FILE", "/tmp/hadi_poller_state.json")
TZ = ZoneInfo(os.getenv("TZ", "Asia/Dhaka"))

# Don't exit on missing env when running on Render; allow health endpoint to show status
if not (HADI_API_URL and HADI_TOKEN and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
    print("Warning: one or more environment variables missing. Set HADI_API_URL, HADI_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID in your environment.")

OTP_REGEX = re.compile(r"\b(\d{4,8})\b")
TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

app = Flask(__name__)

def dhaka_now_str():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S %z")

def send_telegram(number, code, time_str, original_message=None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram config missing; skipping send.")
        return
    text = (
        f"Number : <code>{number}</code>\n"
        f"Code   : <code>{code}</code>\n"
        f"Time   : <code>{time_str}</code>"
    )
    if original_message:
        text += f"\n\n<pre>{original_message}</pre>"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        resp = requests.post(f"{TG_API}/sendMessage", json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print("Telegram send failed:", e)

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {
            "last_dt": (datetime.now(TZ) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
            "seen": []
        }

def save_state(data):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print("Failed to save state:", e)

def hash_record(dt, num, msg):
    return hashlib.sha256(f"{dt}|{num}|{msg}".encode()).hexdigest()

def fetch_from_hadi(dt1, dt2):
    if not HADI_API_URL or not HADI_TOKEN:
        return []
    params = {
        "token": HADI_TOKEN,
        "dt1": dt1.strftime("%Y-%m-%d %H:%M:%S"),
        "dt2": dt2.strftime("%Y-%m-%d %H:%M:%S"),
        "records": HADI_RECORDS
    }
    try:
        r = requests.get(HADI_API_URL, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and data.get("status") == "success":
            return data.get("data", [])
        if isinstance(data, list):
            return data
    except Exception as e:
        print("Hadi fetch error:", e)
    return []

def extract_from_record(rec):
    num = rec.get("num") or rec.get("number") or rec.get("from") or ""
    msg = rec.get("message") or rec.get("msg") or rec.get("body") or ""
    dt = rec.get("dt") or datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    otp_m = OTP_REGEX.search(msg)
    otp = otp_m.group(1) if otp_m else ""
    return num, otp, dt, msg

def poller_loop():
    state = load_state()
    last_dt_str = state.get("last_dt")
    try:
        last_dt = datetime.strptime(last_dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
    except Exception:
        last_dt = datetime.now(TZ) - timedelta(minutes=1)
    seen = set(state.get("seen", []))
    print("Poller started from:", last_dt.strftime("%Y-%m-%d %H:%M:%S %z"))
    while True:
        try:
            now = datetime.now(TZ)
            records = fetch_from_hadi(last_dt, now)
            if records:
                try:
                    records = sorted(records, key=lambda r: r.get("dt", ""))
                except Exception:
                    pass
                for rec in records:
                    num, otp, dt, msg = extract_from_record(rec)
                    h = hash_record(dt, num, msg)
                    if h in seen:
                        continue
                    try:
                        parsed_dt = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
                        time_str = parsed_dt.strftime("%Y-%m-%d %H:%M:%S %z")
                    except Exception:
                        time_str = f"{dt} +0600"
                    send_telegram(num or "Unknown", otp or "", time_str, original_message=msg)
                    print("Forwarded ->", num, otp, time_str)
                    seen.add(h)
                    if len(seen) > 5000:
                        seen = set(list(seen)[-2000:])
            last_dt = now
            state = {"last_dt": last_dt.strftime("%Y-%m-%d %H:%M:%S"), "seen": list(seen)}
            save_state(state)
        except Exception as e:
            print("Error in poll loop:", e)
        time.sleep(POLL_INTERVAL)

# Flask endpoints for health / quick debug
app = Flask(__name__)

@app.route("/")
def index():
    return jsonify({"status": "ok", "message": "Hadi poller running"})

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "time": dhaka_now_str()})

def start_background_poller():
    t = threading.Thread(target=poller_loop, daemon=True)
    t.start()
    return t

if __name__ == "__main__":
    # start poller thread
    start_background_poller()
    # start Flask app (Render exposes PORT via env)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
