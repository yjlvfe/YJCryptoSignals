"""
🛡️ Safety Walls + Circuit Breaker — Phase 3
Hard risk caps + time-based cooling + drawdown tracking.
"""
import json
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger("crypto-signal-safety")

SAFETY_FILE = Path("/root/.crypto-signal-bot/safety_walls.json")

# ═══════════════ HARD CAPS ═══════════════
MAX_DAILY_LOSS_PCT = 10.0          # 10% daily loss → EMERGENCY
EMERGENCY_FLATTEN_PCT = 25.0       # 25% total drawdown → EMERGENCY
MAX_SINGLE_POSITION_PCT = 100.0    # signals bot — user said DYOR
MAX_LEVERAGE_EQUIVALENT = 100.0    # signals bot — no leverage limit on signals
MAX_TRADES_PER_DAY = 100           # signals bot — publish freely

# ═══════════════ CIRCUIT BREAKER ═══════════════
MAX_CONSECUTIVE_LOSSES = 3         # 3 losses → cooling period
COOLING_HOURS = 6                  # pause trading for 6 hours
MAX_DRAWDOWN_FROM_PEAK = 20.0      # 20% from peak → EMERGENCY


def load_safety_state() -> dict:
    try:
        if SAFETY_FILE.exists():
            return json.loads(SAFETY_FILE.read_text())
    except Exception as e:
        logger.warning(f"Safety wall check failed, allowing: {e}")
        return True  # عند الشك، اسمح
    return {
        "daily_pnl": 0.0, "daily_trades": 0,
        "consecutive_losses": 0, "max_drawdown_reached": 0.0,
        "peak_equity_pnl": 0.0,     # highest cumulative P&L
        "emergency_flattened": False, "flatten_reason": "",
        "cooling_until": 0,          # timestamp when cooling ends
        "last_reset_date": str(datetime.now().date()),
    }


def save_safety_state(data: dict):
    try:
        SAFETY_FILE.parent.mkdir(parents=True, exist_ok=True)
        SAFETY_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Safety save failed: {e}")


def reset_daily_state(state: dict) -> dict:
    today = str(datetime.now().date())
    if state.get("last_reset_date") != today:
        state["daily_pnl"] = 0.0
        state["daily_trades"] = 0
        state["last_reset_date"] = today
        save_safety_state(state)
    return state


def is_cooling(state: dict) -> bool:
    """Check if circuit breaker cooling is active."""
    cooling_until = state.get("cooling_until", 0)
    if cooling_until > time.time():
        return True
    if cooling_until > 0 and cooling_until <= time.time():
        state["cooling_until"] = 0
        state["consecutive_losses"] = 0
        save_safety_state(state)
    return False


def enforce_safety_walls(active_trades: list, new_trade: dict = None, portfolio_value: float = 1000.0) -> dict:
    state = load_safety_state()
    state = reset_daily_state(state)
    blocked_by, warnings = [], []

    # ─── 0. Circuit Breaker Cooling ───
    if is_cooling(state):
        remaining = int(state["cooling_until"] - time.time())
        mins = remaining // 60
        return {"allowed": False, "blocked_by": ["CIRCUIT_BREAKER_COOLING"],
                "warnings": [f"⏸️ Circuit breaker active — cooling {mins}min remaining"],
                "daily_state": state}

    # ─── 1. Emergency flatten ───
    if state.get("emergency_flattened"):
        return {"allowed": False, "blocked_by": ["EMERGENCY_FLATTEN_ACTIVE"],
                "warnings": [f"Emergency: {state.get('flatten_reason')}"], "daily_state": state}

    # ─── 2. Daily loss cap ───
    daily_pnl = state.get("daily_pnl", 0)
    if daily_pnl < -MAX_DAILY_LOSS_PCT:
        state["emergency_flattened"] = True
        state["flatten_reason"] = f"Daily loss {abs(daily_pnl):.1f}% exceeds {MAX_DAILY_LOSS_PCT}%"
        save_safety_state(state)
        return {"allowed": False, "blocked_by": ["MAX_DAILY_LOSS"],
                "warnings": [state["flatten_reason"]], "daily_state": state}

    # ─── 3. Consecutive losses → Circuit Breaker ───
    if state.get("consecutive_losses", 0) >= MAX_CONSECUTIVE_LOSSES:
        state["cooling_until"] = time.time() + COOLING_HOURS * 3600
        state["consecutive_losses"] = 0
        save_safety_state(state)
        return {"allowed": False, "blocked_by": ["CIRCUIT_BREAKER"],
                "warnings": [f"⏸️ {MAX_CONSECUTIVE_LOSSES} consecutive losses — {COOLING_HOURS}h cooling"],
                "daily_state": state}

    # ─── 4. Max drawdown from peak ───
    total_pnl = state.get("daily_pnl", 0)
    peak = state.get("peak_equity_pnl", 0)
    if total_pnl > peak:
        state["peak_equity_pnl"] = total_pnl
        save_safety_state(state)
    drawdown_from_peak = peak - total_pnl
    if drawdown_from_peak > MAX_DRAWDOWN_FROM_PEAK:
        state["emergency_flattened"] = True
        state["flatten_reason"] = f"Drawdown {drawdown_from_peak:.1f}% from peak {peak:.1f}%"
        save_safety_state(state)
        return {"allowed": False, "blocked_by": ["MAX_DRAWDOWN"],
                "warnings": [state["flatten_reason"]], "daily_state": state}

    # ─── 5. Daily trade frequency ───
    if state.get("daily_trades", 0) >= MAX_TRADES_PER_DAY and new_trade:
        blocked_by.append("MAX_DAILY_TRADES")

    # ─── 6. Max single position ───
    if new_trade:
        ps = new_trade.get("position_size_usd", 0)
        if ps / max(portfolio_value, 1) * 100 > MAX_SINGLE_POSITION_PCT:
            blocked_by.append("MAX_SINGLE_POSITION")

    # ─── 7. Total exposure ───
    # 🔧 FIXED P001/P003: position_size is a dict, not float. Extract position_size_usd.
    total_exposure = sum(
        t.get("entry_price", 0) * (
            t.get("position_size", {}).get("position_units", 0)
            if isinstance(t.get("position_size"), dict)
            else float(t.get("position_size", 0) or 0)
        )
        for t in active_trades if t.get("status") == "active"
    ) / max(portfolio_value, 1) * 100
    if new_trade:
        total_exposure += new_trade.get("position_size_usd", 0) / portfolio_value * 100
    if total_exposure > MAX_LEVERAGE_EQUIVALENT * 100:
        blocked_by.append("MAX_LEVERAGE")

    return {"allowed": len(blocked_by) == 0, "blocked_by": blocked_by,
            "warnings": warnings, "daily_state": state}


def record_trade_result(pnl_pct: float):
    state = load_safety_state()
    state = reset_daily_state(state)
    state["daily_pnl"] = round(state.get("daily_pnl", 0) + pnl_pct, 2)
    state["daily_trades"] = state.get("daily_trades", 0) + 1

    if pnl_pct < 0:
        state["consecutive_losses"] = state.get("consecutive_losses", 0) + 1
    else:
        state["consecutive_losses"] = 0

    if state["daily_pnl"] > state.get("peak_equity_pnl", 0):
        state["peak_equity_pnl"] = state["daily_pnl"]
    if state["daily_pnl"] < -state.get("max_drawdown_reached", 0):
        state["max_drawdown_reached"] = abs(state["daily_pnl"])

    save_safety_state(state)


def clear_emergency(reason: str = "Manual override"):
    state = load_safety_state()
    state["emergency_flattened"] = False
    state["cooling_until"] = 0
    state["flatten_reason"] = f"Cleared: {reason}"
    save_safety_state(state)
    logger.warning(f"🛡️ Emergency cleared: {reason}")


def get_safety_summary() -> dict:
    state = load_safety_state()
    state = reset_daily_state(state)
    cooling = is_cooling(state)
    return {
        "emergency_flattened": state.get("emergency_flattened", False),
        "circuit_breaker_cooling": cooling,
        "cooling_remaining_sec": max(0, state.get("cooling_until", 0) - time.time()) if cooling else 0,
        "daily_pnl_pct": state.get("daily_pnl", 0),
        "daily_trades": state.get("daily_trades", 0),
        "consecutive_losses": state.get("consecutive_losses", 0),
        "peak_equity_pnl": state.get("peak_equity_pnl", 0),
        "drawdown_from_peak": state.get("peak_equity_pnl", 0) - state.get("daily_pnl", 0),
        "hard_caps": {
            "max_consecutive_losses": MAX_CONSECUTIVE_LOSSES,
            "cooling_hours": COOLING_HOURS,
            "max_daily_loss": MAX_DAILY_LOSS_PCT,
            "max_drawdown_from_peak": MAX_DRAWDOWN_FROM_PEAK,
            "emergency_flatten": EMERGENCY_FLATTEN_PCT,
        },
    }
