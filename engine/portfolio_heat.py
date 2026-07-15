"""
🌡️ Portfolio Heat — aggregate risk tracking.
"""
import time
import json
import logging
from pathlib import Path

logger = logging.getLogger("crypto-signal-heat")

HEAT_FILE = Path("/root/.crypto-signal-bot/portfolio_heat.json")

MAX_TOTAL_HEAT = 15.0
MAX_DRAWDOWN_HEAT = 20.0


def load_heat() -> dict:
    try:
        if HEAT_FILE.exists():
            return json.loads(HEAT_FILE.read_text())
    except Exception as e:
        logger.error(f"Compute failure: {e}", exc_info=True)
        return 0  # compute failure
    return {"total_open_risk": 0.0, "unrealized_pnl": 0.0, "last_updated": time.time()}


def save_heat(data: dict):
    try:
        HEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        data["last_updated"] = time.time()
        HEAT_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Heat save failed: {e}")


def compute_portfolio_heat(active_trades: list, portfolio_value: float = 1000.0) -> dict:
    if not active_trades:
        return {"total_heat": 0.0, "unrealized_pnl_pct": 0.0, "blocked": False, "reason": ""}

    active = [t for t in active_trades if t.get("status") == "active"]
    if not active:
        return {"total_heat": 0.0, "unrealized_pnl_pct": 0.0, "blocked": False, "reason": ""}

    allocation = min(20.0, 100.0 / max(len(active), 1))
    total_heat = 0.0
    total_unrealized = 0.0

    for t in active:
        entry = t.get("entry_price", 0)
        sl = t.get("stop_loss", entry * 0.95)
        cp = t.get("current_price", entry)
        if entry > 0:
            sl_pct = 2.0 if t.get("entry_type") is None else abs(entry - sl) / entry * 100
            total_heat += allocation * sl_pct / 100
            total_unrealized += (cp - entry) / entry * 100 * (allocation / 100)

    blocked = total_heat > MAX_TOTAL_HEAT or total_unrealized < -MAX_DRAWDOWN_HEAT
    reason = []
    if total_heat > MAX_TOTAL_HEAT:
        reason.append(f"Heat {total_heat:.1f}% > {MAX_TOTAL_HEAT}%")
    if total_unrealized < -MAX_DRAWDOWN_HEAT:
        reason.append(f"Drawdown {abs(total_unrealized):.1f}% > {MAX_DRAWDOWN_HEAT}%")

    return {
        "unrealized_pnl_pct": round(total_unrealized, 2),
        "blocked": blocked,
        "reason": " | ".join(reason) if reason else "",
        "active_trade_count": len(active),
    }


LIFECYCLE_FILE = Path("/root/.crypto-signal-bot/trade_lifecycle.json")


def track_trade_lifecycle(trade: dict, is_closed: bool = False):
    try:
        lifecycle = []
        if LIFECYCLE_FILE.exists():
            lifecycle = json.loads(LIFECYCLE_FILE.read_text())
    except Exception as e:
        logger.error(f"Compute failure: {e}", exc_info=True)
        return 0  # compute failure

    sym = trade.get("symbol", "").replace("USDT", "")
    entry = trade.get("entry_price", 0)
    existing = next((lc for lc in lifecycle if lc.get("symbol") == sym and lc.get("status") == "active"), None)

    if existing is None and not is_closed:
        lifecycle.append({
            "symbol": sym, "entry_price": entry,
            "entry_time": trade.get("added_at", time.time()),
            "highest_price": entry, "lowest_price": entry,
            "mfe_pct": 0.0, "mae_pct": 0.0,
            "current_price": entry, "status": "active",
            "final_pnl": trade.get("pnl_pct", 0),
        })
    elif existing and not is_closed:
        cp = trade.get("current_price", entry)
        if cp > existing["highest_price"]:
            existing["highest_price"] = cp
            if entry > 0:
                existing["mfe_pct"] = round((cp - entry) / entry * 100, 2)
        if cp < existing["lowest_price"]:
            existing["lowest_price"] = cp
            if entry > 0:
                existing["mae_pct"] = round((entry - cp) / entry * 100, 2)
        existing["current_price"] = cp
    elif existing and is_closed:
        existing["status"] = "closed"
        existing["close_time"] = time.time()
        existing["final_pnl"] = trade.get("pnl_pct", 0)

    try:
        LIFECYCLE_FILE.parent.mkdir(parents=True, exist_ok=True)
        LIFECYCLE_FILE.write_text(json.dumps(lifecycle, indent=2))
    except Exception as e:
        logger.error(f"Lifecycle save failed: {e}")
