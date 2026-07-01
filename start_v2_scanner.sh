#!/bin/bash
# 🦅🌍 CryptoSignal V2 — Universal AI Scanner (Standalone)
# يجري run_scanner.py كعملية مستقلة عن V1 Bot
set -e

cd /root/projects/crypto-signal

# تنظيف أي lock قديم
rm -f /tmp/cryptosignal-scanner.lock
rm -f /tmp/cryptosignal-v2.lock

# استخدام Python من Hermes venv (فيه pandas ومكتبات المشروع)
PYTHON=/usr/local/lib/hermes-agent/venv/bin/python3

# تشغيل V2 Scanner
exec "$PYTHON" -u run_scanner.py >> /root/projects/crypto-signal/logs/v2_scanner.log 2>&1
