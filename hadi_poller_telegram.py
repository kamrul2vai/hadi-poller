# hadi_poller_telegram.py
"""
Hadi Poller -> Telegram forwarder
Designed to run as a Render worker/service.
"""

import os
import time
import json
import hashlib
import re
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
from dotenv import load_dotenv

# For local testing: load .env if present
load_dotenv()

# Config from environment (set these in Render dashboard as Environment Variables)
HADI_API_URL = os.getenv("HADI_API_URL")
HADI_TOKEN = os.getenv("HADI_TOKEN")
HADI_RECORDS = int(os.getenv("HADI_RECORDS", "100"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))
STATE_FILE = os.getenv("STATE_FILE", "/tmp/hadi_poller_state.json")
TZ = ZoneInfo(os.getenv("TZ", "Asia/Dhaka"))

if not HADI_API_URL or not HADI_TOKEN or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    print("ERROR: missing required env vars. Make sure HADI_API_URL, HADI_TOKEN, TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set.")
    sys.exit(1)

OTP_REGEX = re.compile(r"\b(\d{4,8})\b")
TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def dhaka_now_str():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S %z")


def send_telegram(number, code, time_str, original_message=None):
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
    resp = requests.post(f"{TG_API}/sendMessage", json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


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
    with open(STATE_FILE, "w") as f:
        json.dump(data, f)


def hash_record(dt, num, msg):
    return hashlib.sha256(f"{dt}|{num}|{msg}".encode()).hexdigest()


def fetch_from_hadi(dt1, dt2):
    params = {
        "token": HADI_TOKEN,
        "dt1": dt1.strftime("%Y-%m-%d %H:%M:%S"),
        "dt2": dt2.strftime("%Y-%m-%d %H:%M:%S"),
        "records": HADI_RECORDS
    }
    r = requests.get(HADI_API_URL, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    # If response structure is {"status":"success","data":[...]}
    if isinstance(data, dict) and data.get("status") == "success":
        return data.get("data", [])
    # If API returns an array directly
    if isinstance(data, list):
        return data
    return []


def extract_from_record(rec):
    num = rec.get("num") or rec.get("number") or rec.get("from") or ""
    msg = rec.get("message") or rec.get("msg") or rec.get("body") or ""
    dt = rec.get("dt") or datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    otp_m = OTP_REGEX.search(msg)
    otp = otp_m.group(1) if otp_m else ""
    return num, otp, dt, msg


def main_loop():
    state = load_state()
    last_dt_str = state.get("last_dt")
    try:
        last_dt = datetime.strptime(last_dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
    except Exception:
        last_dt = datetime.now(TZ) - timedelta(minutes=1)

    seen = set(state.get("seen", []))

    print("Hadi Poller Running... starting from:", last_dt.strftime("%Y-%m-%d %H:%M:%S %z"))
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
                    try:
                        send_telegram(num or "Unknown", otp or "", time_str, original_message=msg)
                        print("Forwarded ->", num, otp, time_str)
                    except Exception as e:
                        print("Telegram send failed:", e)
                    seen.add(h)
                    if len(seen) > 5000:
                        seen = set(list(seen)[-2000:])
            last_dt = now
            state = {"last_dt": last_dt.strftime("%Y-%m-%d %H:%M:%S"), "seen": list(seen)}
            save_state(state)
        except Exception as e:
            print("Error in poll loop:", e)
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main_loop()