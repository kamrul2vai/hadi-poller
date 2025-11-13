# Hadi Poller -> Telegram Forwarder

## Quick start (local)
1. Copy `.env.example` to `.env` and fill the 🔪 fields (HADI_TOKEN, TELEGRAM_BOT_TOKEN).
2. Install deps: `pip install -r requirements.txt`
3. Run: `python hadi_poller_telegram.py`

## Deploy to Render (recommended free)
1. Push repo to GitHub.
2. Create a new Worker service in Render and connect the repo.
3. In Render dashboard -> Environment -> set the following variables (do NOT commit them to GitHub):
   - HADI_API_URL
   - HADI_TOKEN (🔪)
   - HADI_RECORDS
   - TELEGRAM_BOT_TOKEN (🔪)
   - TELEGRAM_CHAT_ID
   - POLL_INTERVAL
   - STATE_FILE
   - TZ
4. Deploy.

Security: never commit real tokens to public repos.