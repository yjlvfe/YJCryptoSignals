#!/usr/bin/env python3
"""
🏥 CryptoSignal Unified Health Monitor — v5.0 (Phase 5.5)
كل 30 دقيقة: فحص + إصلاح تلقائي + تقرير تيليجرام
Expires after 14 days from first run.

Phase 5.5 additions:
  - Error state tracking (active vs historical)
  - Severity decay (15m→WARNING, 1h→INFO, 6h→RESOLVED)
  - Runtime heartbeat validation (prioritizes live health)
  - Health confidence scoring (CRITICAL/WARNING/INFO/HEALTHY)
  - Monitor loop protection (cooldowns, repair caps)
  - Health metrics dashboard (cycles/hr, signals/day, memory trend)
"""
import sys, json, time, subprocess, os, re, traceback, requests, logging
from pathlib import Path
from datetime import datetime, date, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

# Ensure project root is in path for engine imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ═══════════════ CONFIG ═══════════════
PROJECT_DIR = Path("/root/projects/crypto-signal")
DATA_DIR = Path("/root/.crypto-signal-bot")
LOG_FILE = Path("/var/log/crypto-signal.log")
TRADES_FILE = DATA_DIR / "trades.json"
OI_CACHE_FILE = DATA_DIR / "oi_cache.json"
FIX_HISTORY_FILE = DATA_DIR / "fix_history.json"
MONITOR_START_FILE = PROJECT_DIR / "monitor_start.txt"
SCRIPTS_DIR = PROJECT_DIR / "strategies"
STRATEGIES_DIR = PROJECT_DIR / "strategies"

# ═══════════════ BOT CONFIG (local bot — NOT signal bot) ═══════════════
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    logger.warning("⚠️ BOT_TOKEN not set — health monitor will not send Telegram messages")
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
OWNER_ID = 528864559

EXPIRY_DAYS = 14

# ═══════════════ PHASE 5.5 STATE FILES ═══════════════
LOG_POSITION_FILE = DATA_DIR / "last_log_position.json"
ERROR_STATE_FILE = DATA_DIR / "error_state.json"
DASHBOARD_FILE = DATA_DIR / "dashboard.json"
COOLDOWN_FILE = DATA_DIR / "repair_cooldowns.json"
MONITOR_STATE_FILE = DATA_DIR / "monitor_state.json"

# ═══════════════ PHASE 5 FILES ═══════════════
POSITION_SIZING_FILE = PROJECT_DIR / "engine" / "position_sizing_v2.py"
PORTFOLIO_HEAT_FILE = PROJECT_DIR / "engine" / "portfolio_heat.py"
TRADE_LIFECYCLE_FILE = DATA_DIR / "trade_lifecycle.json"

# ═══════════════ DECAY CONFIG ═══════════════
DECAY_SCHEDULE = {
    "active":    timedelta(minutes=0),   # 0-15m since last seen
    "warning":   timedelta(minutes=15),  # 15m-1h
    "info":      timedelta(hours=1),     # 1h-6h
    "resolved":  timedelta(hours=6),     # >6h → archived
}

# ═══════════════ LOOP PROTECTION ═══════════════
MAX_REPAIR_ATTEMPTS = 3       # max attempts per error key
REPAIR_COOLDOWN_MINUTES = 30  # wait between repair attempts for same error
TELEGRAM_COOLDOWN_MINUTES = 5 # min time between Telegram reports (default)
TELEGRAM_COOLDOWN_HEALTHY = 60  # if HEALTHY, only report every 60 min

# ═══════════════ RUNTIME HEARTBEAT WEIGHTS ═══════════════
# Runtime signals are weighted HIGHER than static log errors
HEARTBEAT_WEIGHT = 3  # heartbeat failures count 3x vs log errors
LOG_ERROR_WEIGHT = 1  # each log error counts as 1

# ═══════════════ 11 CORE STRATEGIES (Phase 2) ═══════════════
STRATEGIES = {
    "smc.py": "SMCStrategy",
    "market_structure.py": "MarketStructureStrategy",
    "macd_strategy.py": "MACDStrategy",
    "rsi_strategy.py": "RSIStrategy",
    "atr_analyzer.py": "ATRStrategy",
    "moving_average.py": "MAStrategy",
    "cvd_strategy.py": "CVDStrategy",
    "obv_cmf.py": "OBVCMFStrategy",
    "vwap.py": "VWAPStrategy",
    "support_resistance.py": "SupportResistanceStrategy",
    "divergence.py": "DivergenceStrategy",
}

# Engine modules to verify
ENGINE_MODULES = [
    "sentiment",
    "weights",
    "regime",
    "analyzer",
    "scanner",
    "multi_analyzer",
]

# ═══════════════ EXPIRY CHECK ═══════════════
def check_expiry():
    """إذا مر 14 يوم من أول تشغيل → توقف تلقائياً"""
    if MONITOR_START_FILE.exists():
        try:
            start_str = MONITOR_START_FILE.read_text().strip()
            start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            start_date = date.today()
            MONITOR_START_FILE.write_text(str(date.today()))
    else:
        MONITOR_START_FILE.write_text(str(date.today()))
        start_date = date.today()

    if date.today() > start_date + timedelta(days=EXPIRY_DAYS):
        msg = f"⏰ انتهت مدة المراقبة ({EXPIRY_DAYS} يوم من {start_date}). المراقب يتوقف."
        send_telegram(msg)
        print(msg)
        sys.exit(0)

    return start_date


# ═══════════════ HELPERS ═══════════════
def load_json(path, default=None):
    try:
        if Path(path).exists():
            return json.loads(Path(path).read_text())
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        pass
    return default if default is not None else {}


def save_json(path, data):
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"  ⚠️ Failed to save {path}: {e}")


def sh(cmd, timeout=15):
    """Run shell command, return (stdout, returncode)"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=str(PROJECT_DIR))
        return r.stdout.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "TIMEOUT", -1
    except Exception as e:
        return str(e), -1


def send_telegram(text):
    """Send report via Telegram bot API"""
    try:
        max_len = 4000
        if len(text) > max_len:
            parts = [text[i:i+max_len] for i in range(0, len(text), max_len)]
            for part in parts:
                requests.post(f"{API_BASE}/sendMessage", json={
                    "chat_id": OWNER_ID,
                    "text": part,
                    "parse_mode": "HTML"
                }, timeout=10)
        else:
            requests.post(f"{API_BASE}/sendMessage", json={
                "chat_id": OWNER_ID,
                "text": text,
                "parse_mode": "HTML"
            }, timeout=10)
    except Exception as e:
        print(f"  ⚠️ Telegram send failed: {e}")


def find_bot_pids():
    """Find all bot main.py processes (real project bot, not Hermes sandbox)"""
    out, code = sh("pgrep -af 'bot/main.py' 2>/dev/null")
    if code != 0 or not out:
        return []
    pids = []
    for line in out.splitlines():
        parts = line.strip().split()
        if parts:
            try:
                pid = int(parts[0])
                if "hermes" in line.lower() or "sandbox" in line.lower():
                    continue
                pids.append(pid)
            except Exception as e:
                logger.error(f"Error: {e}", exc_info=True)
                pass
    return pids


# ═══════════════ ERROR STATE TRACKING (Phase 5.5) ═══════════════
def load_error_state():
    """Load persistent error state with decay tracking"""
    default = {"errors": {}, "last_decay": None, "report_count": 0, "last_report_ts": None}
    return load_json(ERROR_STATE_FILE, default=default)


def save_error_state(state):
    """Save error state"""
    save_json(ERROR_STATE_FILE, state)


def error_key_from_msg(msg):
    """Generate stable error key from message"""
    # Strip timestamps, numbers, and normalize
    cleaned = re.sub(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[.,]\d+', '', msg)
    cleaned = re.sub(r'0x[0-9a-fA-F]+', 'HEX', cleaned)
    cleaned = re.sub(r'\d+\.\d+%', 'PCT%', cleaned)
    cleaned = re.sub(r'\d+', 'N', cleaned)
    key = re.sub(r'[^a-zA-Z0-9_ -]', '', cleaned).strip()
    # Truncate to first 60 chars + hash for uniqueness
    if len(key) > 60:
        import hashlib
        h = hashlib.md5(key.encode()).hexdigest()[:8]
        key = key[:50] + "_" + h
    return key or "unknown_error"


def register_error(error_msg, subsystem="unknown", severity="warning"):
    """Register or update an error in the state tracker"""
    state = load_error_state()
    error_key = error_key_from_msg(error_msg)
    now = datetime.now().isoformat()

    if error_key in state["errors"]:
        entry = state["errors"][error_key]
        entry["last_seen"] = now
        entry["recurrence_count"] = entry.get("recurrence_count", 0) + 1
        # 🔧 Update severity if reclassified (e.g., warning→info)
        if entry.get("severity") != severity:
            entry["severity"] = severity
        # If was resolved but recurred → reactivate
        if entry.get("status") == "resolved":
            entry["status"] = "active"
            entry["resolution_time"] = None
    else:
        state["errors"][error_key] = {
            "first_seen": now,
            "last_seen": now,
            "recurrence_count": 1,
            "status": "active",
            "severity": severity,
            "subsystem": subsystem,
            "message": error_msg[:200],
            "resolution_time": None,
            "repair_attempts": 0,
        }

    save_error_state(state)
    return error_key


def apply_decay():
    """Apply severity decay to all tracked errors. Returns summary counts."""
    state = load_error_state()
    now = datetime.now()
    decayed = {"active": 0, "warning": 0, "info": 0, "resolved": 0}

    for error_key, entry in state["errors"].items():
        try:
            last_seen = datetime.fromisoformat(entry["last_seen"])
            age = now - last_seen

            if age > DECAY_SCHEDULE["resolved"]:
                if entry["status"] != "resolved":
                    entry["status"] = "resolved"
                    entry["resolution_time"] = now.isoformat()
            elif age > DECAY_SCHEDULE["info"]:
                entry["status"] = "info"
            elif age > DECAY_SCHEDULE["warning"]:
                entry["status"] = "warning"
            else:
                entry["status"] = "active"

            decayed[entry["status"]] += 1
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            entry["status"] = "resolved"
            decayed["resolved"] += 1

    state["last_decay"] = now.isoformat()
    save_error_state(state)
    return decayed


def get_active_errors():
    """Get errors that are currently active (not decayed)"""
    state = load_error_state()
    active = {}
    for key, entry in state["errors"].items():
        if entry.get("status") in ("active", "warning"):
            active[key] = entry
    return active


def get_error_age(error_key):
    """Get age of error since first seen"""
    state = load_error_state()
    entry = state["errors"].get(error_key)
    if not entry:
        return None
    try:
        first = datetime.fromisoformat(entry["first_seen"])
        return datetime.now() - first
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return None


# ═══════════════ RUNTIME HEARTBEAT (Phase 5.5) ═══════════════
def check_runtime_heartbeat():
    """
    Validate live runtime health — prioritized over static logs.
    Returns (errors, signals) where signals = dict of healthy indicators.
    """
    errors = []
    signals = {
        "bot_alive": False,
        "cycles_active": False,
        "polling_active": False,
        "telegram_ok": False,
        "trades_updating": False,
        "memory_stable": False,
        "no_recent_tracebacks": False,
    }

    # ─── Bot process check ───
    pids = find_bot_pids()
    if pids:
        signals["bot_alive"] = True
        # Check memory stability
        for pid in pids:
            out, code = sh(f"ps -p {pid} -o rss --no-headers 2>/dev/null")
            if out:
                try:
                    # Robust: extract first number from output
                    match = re.search(r'\d+', out)
                    if match:
                        mem_kb = int(match.group())
                        signals["memory_stable"] = mem_kb < 2_000_000  # <2GB
                    else:
                        signals["memory_stable"] = True  # assume OK if unparseable
                except Exception as e:
                    logger.error(f"Error: {e}", exc_info=True)
                    signals["memory_stable"] = True  # assume OK on parse failure
            else:
                signals["memory_stable"] = True  # assume OK if ps returns empty (PID may have died)
    else:
        errors.append("❤️ RUNTIME: Bot not running")

    # ─── Cycle activity check (from log) ───
    if LOG_FILE.exists():
        try:
            # Check last 2 hours for cycle activity
            two_hours_ago = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
            out, code = sh(f"grep -c 'Cycle #' {LOG_FILE} 2>/dev/null || echo 0")
            if out:
                try:
                    cycle_count = int(out.strip())
                    signals["cycles_active"] = cycle_count > 0
                except Exception as e:
                    logger.error(f"Error: {e}", exc_info=True)
                    pass

            out, code = sh(f"grep -c 'Polling for commands' {LOG_FILE} 2>/dev/null || echo 0")
            if out:
                try:
                    polling_count = int(out.strip())
                    signals["polling_active"] = polling_count > 0
                except Exception as e:
                    logger.error(f"Error: {e}", exc_info=True)
                    pass
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            pass
    else:
        if signals["bot_alive"]:
            signals["cycles_active"] = True
            signals["polling_active"] = True

    # ─── Trades updating check ───
    if TRADE_LIFECYCLE_FILE.exists():
        try:
            mtime = TRADE_LIFECYCLE_FILE.stat().st_mtime
            age_sec = time.time() - mtime
            signals["trades_updating"] = age_sec < 3600  # <1 hour
            if age_sec > 7200:
                errors.append(f"❤️ RUNTIME: trade_lifecycle.json stale ({age_sec/3600:.1f}h)")
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            pass
    else:
        errors.append("❤️ RUNTIME: trade_lifecycle.json missing")

    # ─── Recent traceback check ───
    if LOG_FILE.exists():
        try:
            out, code = sh(f"tac {LOG_FILE} 2>/dev/null | head -500 | grep -c 'Traceback' || echo 0")
            if out:
                try:
                    tb_count = int(out.strip())
                    signals["no_recent_tracebacks"] = tb_count == 0
                    if tb_count > 0:
                        errors.append(f"❤️ RUNTIME: {tb_count} recent tracebacks in log tail")
                except Exception as e:
                    logger.error(f"Error: {e}", exc_info=True)
                    signals["no_recent_tracebacks"] = True
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            signals["no_recent_tracebacks"] = True

    # ─── Telegram check ───
    try:
        r = requests.get(f"{API_BASE}/getMe", timeout=5)
        signals["telegram_ok"] = r.status_code == 200 and r.json().get("ok", False)
        if not signals["telegram_ok"]:
            errors.append("❤️ RUNTIME: Telegram API not responding")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        errors.append("❤️ RUNTIME: Telegram API unreachable")

    # Compute heartbeat score (higher = more healthy)
    healthy_count = sum(1 for v in signals.values() if v)
    total_checks = len(signals)

    return errors, signals, healthy_count, total_checks


# ═══════════════ HEALTH CONFIDENCE SCORING (Phase 5.5) ═══════════════
def compute_health_score(runtime_errors, check_errors, decayed, heartbeat_healthy, heartbeat_total):
    """
    Compute confidence-weighted health status.
    Returns: (status, confidence_pct, emoji, explanation)

    Priority:
      1. Bot not running → CRITICAL (100%)
      2. Runtime heartbeat fails → CRITICAL/WARNING
      3. Active code errors (traceback/syntax/import) → CRITICAL
      4. Decayed warnings → WARNING
      5. Portfolio heat >15% → WARNING
      6. Everything clean → HEALTHY
    """
    status = "HEALTHY"
    emoji = "🟢"
    confidence = 100
    explanations = []

    # Count active errors by severity
    state = load_error_state()
    active_errors = {k: v for k, v in state["errors"].items()
                     if v.get("status") in ("active", "warning")}
    critical_active = sum(1 for v in active_errors.values()
                         if v.get("severity") == "critical")
    warning_active = sum(1 for v in active_errors.values()
                        if v.get("severity") == "warning")
    info_active = sum(1 for v in active_errors.values()
                     if v.get("severity") == "info")

    # ─── RULE 1: Bot dead = CRITICAL ───
    for err in runtime_errors + check_errors:
        if "Bot not running" in err or "MANUAL RESTART" in err:
            status = "CRITICAL"
            emoji = "🔴"
            confidence = 100
            explanations.append("Bot not running")
            return status, confidence, emoji, explanations

    # ─── RULE 2: Runtime heartbeat degradation ───
    heartbeat_pct = (heartbeat_healthy / heartbeat_total * 100) if heartbeat_total > 0 else 0
    if heartbeat_pct < 50:
        status = "CRITICAL"
        emoji = "🔴"
        confidence = 95
        explanations.append(f"Heartbeat {heartbeat_healthy}/{heartbeat_total}")
    elif heartbeat_pct < 85:
        if status != "CRITICAL":
            status = "WARNING"
            emoji = "🟡"
            confidence = max(confidence - 20, 40)
        explanations.append(f"Heartbeat {heartbeat_healthy}/{heartbeat_total}")

    # ─── RULE 3: Active critical code errors ───
    true_code_errors = [e for e in check_errors if not (
        "poll conflict" in e.lower() or
        "Phase 5: Portfolio heat" in e or
        "📝" in e  # log summary line
    )]

    has_traceback = any("Traceback" in e or "syntax error" in e.lower() or
                       "import FAILED" in e and "Phase 5" not in e
                       for e in true_code_errors)
    if has_traceback:
        status = "CRITICAL"
        emoji = "🔴"
        confidence = 90
        explanations.append("Active traceback/syntax/import error")

    # Check for real active errors (not informational)
    if critical_active > 0:
        status = "CRITICAL"
        emoji = "🔴"
        confidence = max(confidence - 10, 70)
        explanations.append(f"{critical_active} critical errors active")

    # ─── RULE 4: Warnings from decayed items ───
    if warning_active > 2 and status != "CRITICAL":
        status = "WARNING"
        emoji = "🟡"
        confidence = max(confidence - 15, 50)
        explanations.append(f"{warning_active} warning-level errors")

    # ─── RULE 5: Portfolio heat ───
    for err in check_errors:
        if "Portfolio heat" in err and "EXCEEDS" in err:
            if status != "CRITICAL":
                status = "WARNING"
                emoji = "🟡"
                confidence = max(confidence - 10, 60)
            explanations.append("Portfolio heat >15%")

    # ─── RULE 6: No issues → HEALTHY ───
    if status == "HEALTHY" and len(true_code_errors) == 0 and heartbeat_pct >= 85:
        status = "HEALTHY"
        emoji = "🟢"
        confidence = 100
        explanations.append("All systems nominal")

    # ─── Adjust confidence based on error recency ───
    for entry in active_errors.values():
        try:
            last = datetime.fromisoformat(entry["last_seen"])
            age_min = (datetime.now() - last).total_seconds() / 60
            if age_min < 15:
                confidence = max(confidence - 5, 20)
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            pass

    return status, confidence, emoji, explanations


# ═══════════════ LOOP PROTECTION (Phase 5.5) ═══════════════
def load_cooldowns():
    return load_json(COOLDOWN_FILE, default={"repairs": {}, "last_telegram_ts": None})


def save_cooldowns(data):
    save_json(COOLDOWN_FILE, data)


def can_repair(error_key):
    """Check if repair is allowed for this error (cooldown + attempt cap)"""
    cooldowns = load_cooldowns()
    now = datetime.now()

    # Check state for total attempts
    state = load_error_state()
    entry = state["errors"].get(error_key, {})
    attempts = entry.get("repair_attempts", 0)
    if attempts >= MAX_REPAIR_ATTEMPTS:
        return False, f"Max attempts ({MAX_REPAIR_ATTEMPTS}) reached"

    # Check cooldown
    repair_info = cooldowns["repairs"].get(error_key)
    if repair_info:
        try:
            last_attempt = datetime.fromisoformat(repair_info["last_attempt"])
            if now - last_attempt < timedelta(minutes=REPAIR_COOLDOWN_MINUTES):
                remaining = REPAIR_COOLDOWN_MINUTES - int((now - last_attempt).total_seconds() / 60)
                return False, f"Cooldown ({remaining}m remaining)"
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            pass

    return True, "OK"


def record_repair_attempt(error_key, success):
    """Record a repair attempt"""
    cooldowns = load_cooldowns()
    now = datetime.now().isoformat()

    cooldowns["repairs"][error_key] = {
        "last_attempt": now,
        "success": success,
    }

    # Update error state counter
    state = load_error_state()
    if error_key in state["errors"]:
        state["errors"][error_key]["repair_attempts"] = \
            state["errors"][error_key].get("repair_attempts", 0) + 1
    save_error_state(state)

    save_cooldowns(cooldowns)


def should_send_telegram(status):
    """Check Telegram cooldown to prevent spam"""
    cooldowns = load_cooldowns()
    now = datetime.now()

    # For HEALTHY status, only report every HEALTHY_COOLDOWN minutes
    if status == "HEALTHY":
        cooldown_min = TELEGRAM_COOLDOWN_HEALTHY
    else:
        cooldown_min = TELEGRAM_COOLDOWN_MINUTES

    last_ts = cooldowns.get("last_telegram_ts")
    if last_ts:
        try:
            last = datetime.fromisoformat(last_ts)
            if now - last < timedelta(minutes=cooldown_min):
                remaining = cooldown_min - int((now - last).total_seconds() / 60)
                return False, f"Telegram cooldown ({remaining}m remaining)"
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            pass

    return True, "OK"


def record_telegram_sent():
    """Record Telegram send timestamp"""
    cooldowns = load_cooldowns()
    cooldowns["last_telegram_ts"] = datetime.now().isoformat()
    save_cooldowns(cooldowns)


# ═══════════════ FIX HISTORY ═══════════════
def load_fix_history():
    return load_json(FIX_HISTORY_FILE, default={"repairs": []})


def save_fix_history(history):
    save_json(FIX_HISTORY_FILE, history)


def record_fix(error_key, problem, solution, success):
    """Record fix attempt in history"""
    history = load_fix_history()
    history["repairs"].append({
        "timestamp": datetime.now().isoformat(),
        "error_key": error_key,
        "problem": problem[:300],
        "solution": solution[:300],
        "success": success,
    })
    if len(history["repairs"]) > 200:
        history["repairs"] = history["repairs"][-200:]
    save_fix_history(history)


def was_fixed_before(error_key):
    """Check if same error was already repaired"""
    history = load_fix_history()
    for repair in reversed(history.get("repairs", [])):
        if repair.get("error_key") == error_key:
            return repair
    return None


# ═══════════════ CHECKS ═══════════════

def check_1_bot_running():
    """① افحص البوت نشط أم لا — لا تعيد تشغيله أبداً"""
    errors = []
    repairs = []
    pids = find_bot_pids()

    if not pids:
        errors.append("🤖 Bot not running — MANUAL RESTART REQUIRED")
    elif len(pids) > 2:
        errors.append(f"⚠️ Duplicate bot instances: {len(pids)} processes — keeping newest, killing old")
        pids_sorted = sorted(pids)
        for pid in pids_sorted[:-1]:
            sh(f"kill {pid} 2>/dev/null")
        repairs.append(("bot/main.py", f"Killed {len(pids_sorted)-1} old duplicates", f"Keeping PID {pids_sorted[-1]}", True))

    return errors, repairs


def check_2_strategies():
    """② افحص كل الـ 28 استراتيجية"""
    errors = []
    repairs = []

    analyzer_path = PROJECT_DIR / "engine" / "analyzer.py"
    if not analyzer_path.exists():
        errors.append("engine/analyzer.py missing!")
        return errors, repairs

    analyzer_code = analyzer_path.read_text()
    connected = set()
    for cls_name in STRATEGIES.values():
        if f"{cls_name}()" in analyzer_code:
            connected.add(cls_name)

    for filename, cls_name in STRATEGIES.items():
        strat_path = STRATEGIES_DIR / filename
        if not strat_path.exists():
            errors.append(f"Strategy file missing: {filename}")
            continue

        out, code = sh(f'python3 -m py_compile "{strat_path}" 2>&1', timeout=5)
        if code != 0:
            errors.append(f"{filename}: syntax error — {out[:150]}")

        if cls_name not in connected:
            errors.append(f"{filename}: {cls_name} NOT in ALL_STRATEGIES")
            prev = was_fixed_before(f"missing-{cls_name}")
            if not prev or not prev.get("success"):
                try:
                    old = "    VPVRStrategy(),\n]"
                    new = f"    VPVRStrategy(),\n    {cls_name}(),\n]"
                    if old in analyzer_code:
                        new_code = analyzer_code.replace(old, new)
                        analyzer_path.write_text(new_code)
                        repairs.append((filename, f"{cls_name} not in ALL_STRATEGIES", "Added to ALL_STRATEGIES", True))
                        record_fix(f"missing-{cls_name}", f"{cls_name} missing from ALL_STRATEGIES", "Auto-added", True)
                    else:
                        repairs.append((filename, f"{cls_name} not in ALL_STRATEGIES", "Could not auto-add (pattern mismatch)", False))
                except Exception as e:
                    repairs.append((filename, f"{cls_name} not in ALL_STRATEGIES", f"Auto-add failed: {e}", False))

    return errors, repairs


def check_3_engine():
    """③ افحص engine modules"""
    errors = []
    repairs = []

    for mod in ENGINE_MODULES:
        mod_path = PROJECT_DIR / "engine" / f"{mod}.py"
        if not mod_path.exists():
            errors.append(f"engine/{mod}.py: MISSING")
            continue

        out, code = sh(f'python3 -m py_compile "{mod_path}" 2>&1', timeout=5)
        if code != 0:
            errors.append(f"engine/{mod}.py: syntax error — {out[:150]}")

        out, code = sh(f'python3 -c "import sys; sys.path.insert(0, \'{PROJECT_DIR}\'); from engine.{mod} import *" 2>&1', timeout=5)
        if code != 0:
            err_msg = out[:200]
            errors.append(f"engine/{mod}.py: import FAILED — {err_msg}")

    return errors, repairs


def check_4_trades():
    """④ افحص trades.json — للقراءة فقط ⛔ لا يعدل شيء"""
    errors = []
    repairs = []

    trades = load_json(TRADES_FILE, default=[])
    if not trades:
        return errors, repairs

    now = time.time()

    for i, t in enumerate(trades):
        sym = t.get("symbol", f"#{i}")

        if "stop_loss" not in t or t.get("stop_loss") is None:
            errors.append(f"⛔ trades.json: {sym} missing stop_loss — NEEDS MANUAL FIX")
        if "alert_state" not in t:
            errors.append(f"⛔ trades.json: {sym} missing alert_state — NEEDS MANUAL FIX")
        if "entry_price" not in t and "entry" not in t:
            errors.append(f"⛔ trades.json: {sym} missing entry price — NEEDS MANUAL FIX")

        if t.get("status") == "active":
            created = t.get("added_at", t.get("created_at", 0))
            if created and (now - created) > 30 * 86400:
                errors.append(f"🧟 trades.json: {sym} ZOMBIE (active >30 days) — NEEDS MANUAL REVIEW")

    return errors, repairs


def check_5_oi_cache():
    """⑤ افحص oi_cache.json"""
    errors = []
    repairs = []

    if not OI_CACHE_FILE.exists():
        errors.append("oi_cache.json MISSING")
        save_json(OI_CACHE_FILE, {})
        repairs.append(("oi_cache.json", "File missing", "Created empty {}", True))
    else:
        try:
            data = load_json(OI_CACHE_FILE)
            if not isinstance(data, dict):
                errors.append("oi_cache.json corrupted (not a dict)")
                save_json(OI_CACHE_FILE, {})
                repairs.append(("oi_cache.json", "Corrupted", "Reset to {}", True))
            else:
                latest_ts = 0
                for sym, info in data.items():
                    if isinstance(info, dict):
                        ts = info.get("timestamp", 0)
                        if ts > latest_ts:
                            latest_ts = ts
                if latest_ts > 0 and (time.time() - latest_ts) > 7200:
                    errors.append(f"oi_cache.json STALE (last update {(time.time()-latest_ts)/3600:.1f}h ago)")
        except Exception as e:
            errors.append(f"oi_cache.json: read error — {e}")

    return errors, repairs


def check_6_logs():
    """⑥ افحص اللوجز: byte-offset tracking + error state integration"""
    errors = []
    repairs = []

    if not LOG_FILE.exists():
        register_error("Log file missing", subsystem="logs", severity="warning")
        errors.append(f"Log file missing: {LOG_FILE}")
        return errors, repairs

    try:
        pos_data = load_json(LOG_POSITION_FILE, default={"offset": 0})
        last_offset = pos_data.get("offset", 0)
        file_size = LOG_FILE.stat().st_size

        if last_offset > file_size:
            last_offset = 0

        if last_offset >= file_size:
            return errors, repairs

        new_errors = []
        with open(LOG_FILE, "rb") as f:
            f.seek(last_offset)
            if last_offset > 0:
                f.readline()
            for raw_line in f:
                try:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                except Exception as e:
                    logger.error(f"Error: {e}", exc_info=True)
                    continue

                if "ERROR" not in line and "CRITICAL" not in line and "Traceback" not in line:
                    continue

                # ⛔ SKIP noise
                if "poll conflict" in line.lower() and "Persistent" in line:
                    continue
                if "healthy providers failed" in line and "forcing retry" in line.lower():
                    continue

                new_errors.append(line[-300:])

            new_offset = f.tell()
            save_json(LOG_POSITION_FILE, {"offset": new_offset, "last_check": datetime.now().isoformat()})

        if new_errors:
            unique = list(dict.fromkeys(new_errors))
            for err in unique:
                # Determine severity based on content
                severity = "warning"
                if "Traceback" in err or "CRITICAL" in err:
                    severity = "critical"
                elif "syntax error" in err.lower() or "import FAILED" in err:
                    severity = "critical"
                elif "ZOMBIE" in err or "MANUAL RESTART" in err:
                    severity = "critical"

                # Register in error state
                register_error(err, subsystem="logs", severity=severity)

            errors.append(f"📝 {len(unique)} new log lines scanned")

        # Save monitor state
        state = {"last_check_time": datetime.now().isoformat(), "errors_found": len(new_errors)}
        save_json(MONITOR_STATE_FILE, state)

    except Exception as e:
        register_error(f"Log read error: {e}", subsystem="logs", severity="warning")
        errors.append(f"Log read error: {e}")

    return errors, repairs


def check_7_auto_tune():
    """⑦ فحص auto_tune + weights — معطل بعد حذف Phase 5.x"""
    return [], []


def check_8_phase5():
    """⑧ فحص Phase 5: Position Sizing + Portfolio Heat + Trade Lifecycle"""
    errors = []
    repairs = []

    # 8a: position_sizing.py
    if not POSITION_SIZING_FILE.exists():
        errors.append("Phase 5: engine/position_sizing.py MISSING")
    else:
        out, code = sh(f'python3 -m py_compile "{POSITION_SIZING_FILE}" 2>&1', timeout=5)
        if code != 0:
            errors.append(f"Phase 5: position_sizing.py syntax error — {out[:150]}")
        else:
            out, code = sh(
                f'python3 -c "import sys; sys.path.insert(0, \'{PROJECT_DIR}\'); from engine.position_sizing_v2 import compute_position_size" 2>&1',
                timeout=5
            )
            if code != 0:
                errors.append(f"Phase 5: position_sizing.py import FAILED — {out[:200]}")

    # 8b: portfolio_heat.py
    if not PORTFOLIO_HEAT_FILE.exists():
        errors.append("Phase 5: engine/portfolio_heat.py MISSING")
    else:
        out, code = sh(f'python3 -m py_compile "{PORTFOLIO_HEAT_FILE}" 2>&1', timeout=5)
        if code != 0:
            errors.append(f"Phase 5: portfolio_heat.py syntax error — {out[:150]}")
        else:
            out, code = sh(
                f'python3 -c "import sys; sys.path.insert(0, \'{PROJECT_DIR}\'); from engine.portfolio_heat import compute_portfolio_heat" 2>&1',
                timeout=5
            )
            if code != 0:
                errors.append(f"Phase 5: portfolio_heat.py import FAILED — {out[:200]}")

    # 8c: trade_lifecycle.json
    if not TRADE_LIFECYCLE_FILE.exists():
        errors.append("Phase 5: trade_lifecycle.json MISSING")
    else:
        try:
            lifecycle_data = load_json(TRADE_LIFECYCLE_FILE, default=[])
            if not lifecycle_data or (isinstance(lifecycle_data, list) and len(lifecycle_data) == 0):
                errors.append("Phase 5: trade_lifecycle.json empty — no trades tracked")
            else:
                now = time.time()
                latest_ts = 0
                if isinstance(lifecycle_data, list):
                    for entry in lifecycle_data:
                        ts = entry.get("last_updated", entry.get("timestamp", 0))
                        if isinstance(ts, (int, float)) and ts > latest_ts:
                            latest_ts = ts
                else:
                    for sym, entry in lifecycle_data.items():
                        ts = entry.get("last_updated", entry.get("timestamp", 0))
                        if isinstance(ts, (int, float)) and ts > latest_ts:
                            latest_ts = ts
                if latest_ts > 0 and (now - latest_ts) > 7200:
                    errors.append(f"Phase 5: trade_lifecycle.json STALE ({int((now-latest_ts)/3600)}h since last update)")
        except Exception as e:
            errors.append(f"Phase 5: trade_lifecycle.json read error — {e}")

    # 8d: Portfolio heat (entry_type-aware)
    trades = load_json(TRADES_FILE, default=[])
    active_trades = [t for t in trades if t.get("status") == "active"]
    if active_trades:
        total_heat = 0
        for t in active_trades:
            sl = t.get("stop_loss")
            entry = t.get("entry_price") or t.get("entry")
            if entry and isinstance(entry, (int, float)):
                # ═══ entry_type-aware risk ═══
                # Legacy trades (entry_type=None) use assumed 2% risk
                if t.get("entry_type") is None:
                    risk_pct = 2.0
                elif sl and isinstance(sl, (int, float)):
                    risk_pct = abs(entry - sl) / entry * 100
                else:
                    risk_pct = 2.0  # fallback
                total_heat += risk_pct
        if total_heat > 15:
            errors.append(f"Phase 5: Portfolio heat {total_heat:.1f}% — EXCEEDS 15% CAP ⚠️")
        elif total_heat > 10:
            errors.append(f"Phase 5: Portfolio heat {total_heat:.1f}% — approaching cap")

    # 8e: Sector caps
    if active_trades and len(active_trades) >= 2:
        try:
            out, code = sh(
                f'python3 -c "'
                f'import sys, json; sys.path.insert(0, \'{PROJECT_DIR}\'); '
                f'from engine.position_sizing_v2 import COIN_SECTORS; '
                f'print(json.dumps(COIN_SECTORS))'
                f'" 2>&1',
                timeout=5
            )
            if code == 0 and out:
                coin_sectors = json.loads(out)
                sector_counts = defaultdict(int)
                for t in active_trades:
                    sym = t.get("symbol", "")
                    base = sym.replace("USDT", "").replace("USDC", "")
                    sector = coin_sectors.get(base, coin_sectors.get(sym, "OTHER"))
                    sector_counts[sector] += 1

                for sector, count in sector_counts.items():
                    pct = count / len(active_trades) * 100
                    if pct > 25:
                        errors.append(f"Phase 5: Sector '{sector}' at {pct:.0f}% concentration — 25% cap exceeded")
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            pass

    return errors, repairs


# ═══════════════ ⑨ PHASE 5.7 — FACTOR EXPOSURE & SYSTEM SIMPLIFICATION ═══════════════
def check_9_phase57():
    """⑨ فحص Safety Walls فقط (Phase 5.x المحذوفة)"""
    errors = []
    repairs = []

    # ═══ Phase 5.x modules PURGED — only safety_walls kept ═══

    # ═══ Safety Walls ═══
    try:
        from engine.safety_walls import get_safety_summary
        safety = get_safety_summary()
        if safety.get("emergency_flattened"):
            errors.append("🛑 EMERGENCY FLATTEN ACTIVE")
        if safety.get("consecutive_losses", 0) >= 3:
            errors.append(f"{safety['consecutive_losses']} consecutive losses ⚠️")
        daily_pnl = safety.get("daily_pnl_pct", 0)
        if daily_pnl < -5:
            errors.append(f"Daily P&L {daily_pnl:.1f}% — approaching cap")
    except Exception as e:
        errors.append(f"Safety: import/exec error — {e}")

    return errors, repairs


# ═══════════════ AUTO-REPAIR ═══════════════
def attempt_repair(error_msg, error_key):
    """Try to auto-repair based on error pattern (with loop protection)"""
    prev = was_fixed_before(error_key)

    if prev and prev.get("success"):
        return ("auto-repair", error_msg[:100], "DEEPER FIX NEEDED — recurring after previous repair", False)

    # Duplicate bot instances
    if "duplicate" in error_msg.lower() or "poll conflict" in error_msg.lower():
        pids = find_bot_pids()
        if len(pids) > 3:
            pids_sorted = sorted(pids)
            for pid in pids_sorted[:-1]:
                sh(f"kill {pid} 2>/dev/null")
            return ("bot/main.py", "Duplicate bot instances", f"Killed {len(pids_sorted)-1} old instances", True)

    # Strategy syntax error
    if "SyntaxError" in error_msg or "syntax error" in error_msg:
        return ("auto-repair", error_msg[:100], "Syntax error — needs manual review", False)

    # Import error
    if "import" in error_msg.lower() and ("FAILED" in error_msg or "ModuleNotFoundError" in error_msg):
        return ("auto-repair", error_msg[:100], "Import error — needs manual review", False)

    return ("auto-repair", error_msg[:100], "No auto-repair pattern matched", False)


# ═══════════════ DASHBOARD (Phase 5.5) ═══════════════
def update_dashboard(decayed, heartbeat_healthy, heartbeat_total, status_info, errors_all):
    """Update health metrics dashboard"""
    state = load_error_state()
    decay_counts = decayed

    # Compute metrics
    active_count = decay_counts.get("active", 0)
    warning_count = decay_counts.get("warning", 0)
    info_count = decay_counts.get("info", 0)
    resolved_count = decay_counts.get("resolved", 0)

    # Get bot runtime info
    pids = find_bot_pids()
    bot_uptime = None
    bot_mem = None
    if pids:
        out, code = sh(f"ps -p {pids[0]} -o etimes=,rss= 2>/dev/null")
        if code == 0 and out:
            parts = out.strip().split()
            if len(parts) >= 1:
                bot_uptime = int(parts[0])  # seconds
            if len(parts) >= 2:
                bot_mem = int(parts[1])  # KB

    dashboard = {
        "updated": datetime.now().isoformat(),
        "bot": {
            "running": len(pids) > 0,
            "pid": pids[0] if pids else None,
            "uptime_seconds": bot_uptime,
            "memory_kb": bot_mem,
        },
        "errors": {
            "active": active_count,
            "warning": warning_count,
            "info": info_count,
            "resolved": resolved_count,
            "total_tracked": len(state.get("errors", {})),
        },
        "heartbeat": {
            "healthy": heartbeat_healthy,
            "total": heartbeat_total,
            "pct": round(heartbeat_healthy / heartbeat_total * 100, 1) if heartbeat_total > 0 else 0,
        },
        "status": status_info,
        "checks_total": len(errors_all),
    }

    # Load existing dashboard and append history
    existing = load_json(DASHBOARD_FILE, default={"history": []})
    history = existing.get("history", [])
    history.append({
        "timestamp": datetime.now().isoformat(),
        "status": status_info[0],
        "confidence": status_info[1],
        "active_errors": active_count,
        "heartbeat_pct": dashboard["heartbeat"]["pct"],
    })
    # Keep last 500 entries (~10 days)
    if len(history) > 500:
        history = history[-500:]
    existing["history"] = history
    existing["current"] = dashboard

    save_json(DASHBOARD_FILE, existing)
    return dashboard


# ═══════════════ MAIN ═══════════════
def main():
    now = datetime.now()
    start_date = check_expiry()
    day_num = (date.today() - start_date).days + 1

    errors_all = []
    repairs_all = []

    print(f"🏥 Health Monitor v5.0 — {now.strftime('%Y-%m-%d %H:%M')} — Day {day_num}/{EXPIRY_DAYS}")
    print("=" * 60)

    # ─── ① Bot status ───
    print("\n① Checking bot status...")
    errs, reps = check_1_bot_running()
    errors_all.extend(errs)
    repairs_all.extend(reps)
    for e in errs:
        print(f"  ❌ {e}")
    for r in reps:
        print(f"  🔧 {r[0]} → {r[2]} → {'✅' if r[3] else '❌'}")

    # ─── ② Strategies ───
    print("\n② Checking 28 strategies...")
    errs, reps = check_2_strategies()
    errors_all.extend(errs)
    repairs_all.extend(reps)
    for e in errs[:5]:
        print(f"  ❌ {e}")
    if len(errs) > 5:
        print(f"  ... and {len(errs)-5} more strategy errors")
    for r in reps:
        print(f"  🔧 {r[0]} → {r[2]} → {'✅' if r[3] else '❌'}")

    # ─── ③ Engine ───
    print("\n③ Checking engine modules...")
    errs, reps = check_3_engine()
    errors_all.extend(errs)
    repairs_all.extend(reps)
    for e in errs:
        print(f"  ❌ {e}")

    # ─── ④ Trades ───
    print("\n④ Checking trades.json...")
    errs, reps = check_4_trades()
    errors_all.extend(errs)
    repairs_all.extend(reps)
    for e in errs:
        print(f"  ❌ {e}")
    for r in reps:
        print(f"  🔧 {r[0]} → {r[2]} → {'✅' if r[3] else '❌'}")

    # ─── ⑤ OI Cache ───
    print("\n⑤ Checking oi_cache.json...")
    errs, reps = check_5_oi_cache()
    errors_all.extend(errs)
    repairs_all.extend(reps)
    for e in errs:
        print(f"  ❌ {e}")
    for r in reps:
        print(f"  🔧 {r[0]} → {r[2]} → {'✅' if r[3] else '❌'}")

    # ─── ⑥ Logs ───
    print("\n⑥ Checking logs...")
    errs, reps = check_6_logs()
    errors_all.extend(errs)
    repairs_all.extend(reps)
    for e in errs[:3]:
        print(f"  ❌ {e}")

    # ─── ⑦ Auto-tune ───
    print("\n⑦ Checking auto-tune & weights...")
    errs, reps = check_7_auto_tune()
    errors_all.extend(errs)
    repairs_all.extend(reps)
    for e in errs:
        print(f"  ❌ {e}")

    # ─── ⑧ Phase 5 ───
    print("\n⑧ Checking Phase 5 (Position Sizing + Portfolio Heat)...")
    errs, reps = check_8_phase5()
    errors_all.extend(errs)
    repairs_all.extend(reps)
    for e in errs:
        print(f"  ❌ {e}")

    # ─── ⑨ Safety Walls ───
    print("\n⑨ Checking Safety Walls...")
    errs, reps = check_9_phase57()
    errors_all.extend(errs)
    repairs_all.extend(reps)
    for e in errs[:5]:
        print(f"  ❌ {e}")

    # ═══════════════ PHASE 5.5 SYSTEMS ═══════════════

    # ─── Register all check errors in error state ───
    print("\n⑩ Registering errors + applying decay...")
    for err in errors_all:
        if "poll conflict" in err.lower():
            continue
        # Determine subsystem
        if "bot" in err.lower() or "MANUAL RESTART" in err:
            subsystem = "bot"
        elif "Strategy" in err or "strategy" in err.lower() or "ALL_STRATEGIES" in err:
            subsystem = "strategy"
        elif "engine/" in err or "import FAILED" in err:
            subsystem = "engine"
        elif "trades.json" in err:
            subsystem = "trades"
        elif "Phase 5" in err:
            subsystem = "phase5"
        elif "RUNTIME" in err or "❤️" in err:
            subsystem = "runtime"
        else:
            subsystem = "other"

        severity = "warning"
        if "syntax error" in err.lower() or "import FAILED" in err or "MISSING" in err:
            severity = "critical"
        elif "Traceback" in err:
            severity = "critical"
        elif "ZOMBIE" in err or "MANUAL RESTART" in err:
            severity = "critical"
        # Phase 5.x removed — no special downgrades needed

        register_error(err, subsystem=subsystem, severity=severity)

    # ─── Apply decay ───
    decayed = apply_decay()
    print(f"   Errors: {decayed['active']} active, {decayed['warning']} warning, "
          f"{decayed['info']} info, {decayed['resolved']} resolved")

    # ─── Runtime heartbeat ───
    print("\n⑪ Checking runtime heartbeat...")
    runtime_errs, signals, heartbeat_healthy, heartbeat_total = check_runtime_heartbeat()
    errors_all.extend(runtime_errs)
    for e in runtime_errs:
        print(f"  ❌ {e}")
    for sig, val in signals.items():
        icon = "✅" if val else "❌"
        print(f"  {icon} {sig}: {val}")
    print(f"   Heartbeat: {heartbeat_healthy}/{heartbeat_total} healthy")

    # ─── Auto-repairs with loop protection ───
    print("\n⑫ Attempting auto-repairs (with cooldown)...")
    extra_repairs = []
    for err in errors_all:
        if "poll conflict" in err.lower():
            continue
        error_key = error_key_from_msg(err)
        prev_attempts = [r for r in load_fix_history().get("repairs", [])
                         if r.get("error_key") == error_key]
        if len(prev_attempts) >= 3 and not any(r.get("success") for r in prev_attempts):
            print(f"  ⛔ Skipping '{error_key[:40]}' — failed {len(prev_attempts)} times already")
            continue

        can, reason = can_repair(error_key)
        if not can:
            print(f"  ⏸️ Skipping '{error_key[:40]}' — {reason}")
            continue

        if not was_fixed_before(error_key) or not was_fixed_before(error_key).get("success"):
            file_, problem, solution, ok = attempt_repair(err, error_key)
            if solution != "No auto-repair pattern matched":
                extra_repairs.append((file_, problem, solution, ok))
                record_fix(error_key, problem, solution, ok)
                record_repair_attempt(error_key, ok)
    repairs_all.extend(extra_repairs)
    for r in extra_repairs:
        print(f"  🔧 {r[0]} → {r[2]} → {'✅' if r[3] else '❌'}")

    if not extra_repairs:
        print("   No repairs needed or all in cooldown.")

    # ─── Health confidence scoring ───
    print("\n⑬ Computing health confidence...")
    status, confidence, emoji, explanations = compute_health_score(
        runtime_errs, errors_all, decayed, heartbeat_healthy, heartbeat_total
    )
    print(f"   Status: {emoji} {status} ({confidence}% confidence)")
    for expl in explanations:
        print(f"   → {expl}")

    # ─── Update dashboard ───
    update_dashboard(decayed, heartbeat_healthy, heartbeat_total,
                     (status, confidence, emoji), errors_all)

    # ═══════════════ BUILD REPORT ═══════════════
    total_errors = len(errors_all)
    total_repairs = len(repairs_all)
    successful_repairs = sum(1 for r in repairs_all if r[3])

    # Get error state summary
    state = load_error_state()
    active_errors_list = [v for v in state["errors"].values()
                          if v.get("status") in ("active", "warning")]

    # Check if we should send Telegram (cooldown)
    should_send, cooldown_reason = should_send_telegram(status)
    if not should_send:
        print(f"\n⏸️ Telegram suppressed: {cooldown_reason}")
        print(f"\n{'='*60}")
        print(f"🏥 Health check complete: {emoji} {status} ({confidence}%)")
        sys.exit(0)

    # Build report
    report = f"""🔍 <b>فحص صحي — {now.strftime('%Y-%m-%d %H:%M')}</b>
📅 اليوم {day_num}/{EXPIRY_DAYS} | 📊 v5.0 Phase 5.5

<b>الحالة:</b> {emoji} {status} — ثقة {confidence}%

"""

    # Heartbeat summary
    report += "━━━ ❤️ <b>النبض الحي</b> ━━━\n"
    for sig, val in signals.items():
        icon = "✅" if val else "❌"
        label = {
            "bot_alive": "البوت شغال",
            "cycles_active": "الدورات نشطة",
            "polling_active": "الاستقبال نشط",
            "telegram_ok": "تيليجرام متصل",
            "trades_updating": "الصفقات تتحدث",
            "memory_stable": "الذاكرة مستقرة",
            "no_recent_tracebacks": "لا أخطاء حديثة",
        }.get(sig, sig)
        report += f"{icon} {label}\n"
    report += f"❤️ النبض: {heartbeat_healthy}/{heartbeat_total}\n\n"

    # Error decay summary
    report += f"━━━ 🐛 <b>الأخطاء</b> ━━━\n"
    report += f"🔴 نشطة: {decayed['active']} | 🟡 تحذير: {decayed['warning']}"
    report += f" | 🔵 معلومات: {decayed['info']} | ✅ محلولة: {decayed['resolved']}\n"

    if active_errors_list:
        report += "🔴 <b>نشطة حالياً:</b>\n"
        for entry in sorted(active_errors_list, key=lambda x: x.get("first_seen", ""), reverse=True)[:5]:
            try:
                age = datetime.now() - datetime.fromisoformat(entry["first_seen"])
                age_str = f"{int(age.total_seconds()/3600)}س" if age.total_seconds() > 3600 else f"{int(age.total_seconds()/60)}د"
            except Exception as e:
                logger.error(f"Error: {e}", exc_info=True)
                age_str = "?"
            sev = entry.get("severity", "?")
            msg = entry.get("message", "")[:100]
            report += f"  [{sev}] {msg} ({age_str})\n"
    report += "\n"

    if total_repairs > 0:
        report += f"━━━ 🔧 <b>الإصلاحات</b> ━━━\n"
        report += f"المحاولات: {total_repairs} | الناجحة: {successful_repairs}\n"
        for file_, problem, solution, ok in repairs_all[:5]:
            icon = "✅" if ok else "❌"
            report += f"{icon} [{file_[:30]}] → {problem[:60]}\n"
        report += "\n"

    if len(errors_all) > 0 and total_errors > 0:
        report += f"━━━ 📋 <b>ملاحظات ({total_errors})</b> ━━━\n"
        unique_errors = list(dict.fromkeys(errors_all))
        for err in unique_errors[:8]:
            report += f"  • {err[:180]}\n"
        if len(unique_errors) > 8:
            report += f"  ... و {len(unique_errors)-8} ملاحظة أخرى\n"
        report += "\n"

    # Dashboard metrics
    if TRADE_LIFECYCLE_FILE.exists():
        try:
            trades = load_json(TRADES_FILE, default=[])
            active_trades_count = sum(1 for t in trades if t.get("status") == "active")
            report += f"━━━ 📊 <b>مؤشرات سريعة</b> ━━━\n"
            report += f"📈 صفقات نشطة: {active_trades_count}\n"
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            pass

    report += f"\n💡 <b>المراقبة الذكية:</b> الأخطاء تتحلل تلقائياً بعد 6 ساعات من آخر ظهور\n"
    report += f"━━━━━━━━━━━━━━━━━━━\n"
    report += f"🤖 CryptoSignal Health Monitor v5.0"

    # Send report
    print(f"\n⑭ Sending Telegram report... [{status}]")
    send_telegram(report)
    record_telegram_sent()
    print("   ✅ Report sent!")

    # Final summary
    print(f"\n{'='*60}")
    print(f"🏥 Health check complete: {emoji} {status} ({confidence}% confidence)")
    print(f"   Active errors: {decayed['active']} | Resolved: {decayed['resolved']}")
    print(f"   Repairs: {total_repairs} ({successful_repairs} successful)")
    print(f"   Heartbeat: {heartbeat_healthy}/{heartbeat_total}")
    print(f"   Monitor expires: {start_date + timedelta(days=EXPIRY_DAYS)}")

    sys.exit(0)


if __name__ == "__main__":
    main()
