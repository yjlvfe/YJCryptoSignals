#!/usr/bin/env python3
"""
🤖 CryptoSignal Bot — Entry Point
v2 Split: config → handlers → trading → main (this file)
"""
import sys, os, time, fcntl
from pathlib import Path

# 🔧 Load .env FIRST — before project imports so config.py sees BOT_TOKEN
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

# ⛔ File lock — single-instance guard
_lock_file = None

def _acquire_lock():
    global _lock_file
    _lock_file = open('/tmp/cryptosignal.lock', 'w')
    try:
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_file.write(str(os.getpid()))
        _lock_file.flush()
        return True
    except (IOError, OSError):
        print("Bot already running — exiting")
        return False

# ─── Ensure project root is on path (for direct execution: python3 bot/main.py) ───
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# ─── Imports (after lock guard) ───
from bot.config import *
from bot.handlers import *
from bot.trading import *

import logging
logger = logging.getLogger("crypto-signal-bot")

# ─── Entry Point ───
def main():
    """Start the bot: init commands, then enter scheduler loop."""
    logger.info("🤖 CryptoSignal Bot starting...")
    
    # Initialize Telegram commands
    try:
        init_all_commands()
    except Exception as e:
        logger.error(f"Command initialization failed: {e}")
    
    # Start Telegram message polling
    start_polling()
    
    # Start the trading scheduler (runs forever)
    scheduler_loop()

if __name__ == "__main__":
    if not _acquire_lock():
        sys.exit(0)
    
    if "--once" in sys.argv:
        import requests
        bot_info = requests.get(f"{API_BASE}/getMe").json()
        logger.info(f"Bot: {bot_info}")
        subs = load_subscribers()
        logger.info(f"Subscribers: {subs}")
    else:
        main()
