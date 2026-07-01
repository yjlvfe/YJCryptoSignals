"""🦅🌍 Universal Scanner Runner — auto-flush everywhere"""
import os, sys
from pathlib import Path

# Force unbuffered output
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
os.environ['PYTHONUNBUFFERED'] = '1'

# Load .env first
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ[key.strip()] = val.strip().strip('"').strip("'")
    print("📄 .env loaded", flush=True)

keys = os.getenv("CRYPTOSIGNAL_AI_KEYS", "")
print(f"🔑 {len(keys.split(','))} AI keys • API: {os.getenv('CRYPTOSIGNAL_AI_BASE','?')} • Model: {os.getenv('CRYPTOSIGNAL_AI_MODEL','?')}", flush=True)

# Logging to stdout only (captured by background process)
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

from engine.universal_scanner import universal_scan_loop
universal_scan_loop()
