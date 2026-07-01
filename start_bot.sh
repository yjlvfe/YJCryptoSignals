#!/bin/bash
# 🤖 CryptoSignal V1 — Telegram Bot (Standalone)
set -e

cd /root/projects/crypto-signal

# تنظيف lock قديم
rm -f /tmp/cryptosignal.lock

# استخدام Python من Hermes venv (فيه pandas ومكتبات المشروع)
PYTHON=/usr/local/lib/hermes-agent/venv/bin/python3

# تشغيل V1 Bot
exec "$PYTHON" -u bot/main.py >> /root/projects/crypto-signal/logs/stdout.log 2>&1
