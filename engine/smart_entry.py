"""
📍 Smart Entry — Optimal entry/stop/target computation
Uses support, order blocks, FVG, Fibonacci to find best entry.
"""
import numpy as np
import logging

logger = logging.getLogger("crypto-signal-smart-entry")


def find_nearest_supports(df, price):
    """
    Find all support levels below current price.
    Returns list of (level, source, confidence) sorted nearest first.
    """
    supports = []
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    open_p = df["open"].values
    volume = df["volume"].values

    # ─── 1. Swing Low (last 20 candles) ───
    lookback = min(20, len(close) - 2)
    for i in range(len(close) - lookback, len(close) - 2):
        if low[i] < low[i-1] and low[i] < low[i-2] and low[i] < low[i+1] and low[i] < low[i+2]:
            if low[i] < price:
                supports.append((float(low[i]), "Swing Low", 0.7))

    # ─── 2. Pivot support (SR zones) ───
    recent_high = np.max(high[-20:])
    recent_low = np.min(low[-20:])
    rng = recent_high - recent_low
    if rng > 0:
        levels = {
            "S1 (38.2%)": recent_low + rng * 0.382,
            "S2 (23.6%)": recent_low + rng * 0.236,
            "S3 (Bottom)": recent_low,
        }
        for name, lvl in levels.items():
            if lvl < price:
                supports.append((round(lvl, 8), f"Pivot {name}", 0.5))

    # ─── 3. Order Blocks (bullish OB lows) ───
    try:
        for i in range(max(1, len(close) - 30 - 3), len(close) - 3):
            if close[i] < open_p[i] and close[i+1] > open_p[i+1]:
                body_prev = abs(close[i] - open_p[i])
                body_next = abs(close[i+1] - open_p[i+1])
                if body_prev > 0 and (body_next / max(body_prev, 1e-10)) > 1.5 and close[i+1] > high[i]:
                    if low[i] < price:
                        supports.append((float(low[i]), "OB Bullish Low", 0.6))
    except Exception as e:
        logger.error(f"Compute failure: {e}", exc_info=True)
        return None  # compute failure

    # ─── 4. FVG bullish zones (gap low = support) ───
    try:
        for i in range(max(3, len(close) - 40), len(close) - 1):
            if i >= 2 and low[i] > high[i-2]:
                fvg_low = float(high[i-2])
                if fvg_low < price:
                    supports.append((fvg_low, "FVG Bullish Low", 0.5))
    except Exception as e:
        logger.error(f"Compute failure: {e}", exc_info=True)
        return None  # compute failure

    # ─── 5. Fibonacci 38.2% and 50% from last swing ───
    try:
        swing_high = np.max(high[-20:])
        swing_low = np.min(low[-20:])
        hi_idx = len(close) - 20 + np.argmax(high[-20:])
        lo_idx = len(close) - 20 + np.argmin(low[-20:])
        if lo_idx < hi_idx and swing_high > swing_low:
            rng = swing_high - swing_low
            fib_382 = swing_low + rng * 0.382
            fib_500 = swing_low + rng * 0.5
            if fib_382 < price:
                supports.append((round(fib_382, 8), "Fib 38.2%", 0.6))
            if fib_500 < price:
                supports.append((round(fib_500, 8), "Fib 50%", 0.55))
    except Exception as e:
        logger.error(f"Compute failure: {e}", exc_info=True)
        return None  # compute failure

    # ─── 6. Moving averages as dynamic support (if below price) ───
    for period, weight in [(20, 0.4), (50, 0.35), (200, 0.25)]:
        if len(close) >= period:
            ma = float(np.mean(close[-period:]))
            if ma < price:
                supports.append((round(ma, 8), f"MA{period}", weight))

    # Sort: nearest to price first, then by confidence
    supports.sort(key=lambda x: (abs(price - x[0]) / price, -x[2]))
    return supports


def compute_smart_entry(df, current_price):
    """
    Find optimal entry point.
    Returns dict: {entry, entry_type, entry_note, nearest_support}
    entry_type: "now" or "limit"
    """
    supports = find_nearest_supports(df, current_price)

    if not supports:
        # No support found — use current price
        return {
            "entry": current_price,
            "entry_type": "now",
            "entry_note": "📍 دخول فوري (لا يوجد دعم قريب)",
            "nearest_support": None,
        }

    nearest = supports[0]
    support_price = nearest[0]
    support_source = nearest[1]
    dist_pct = abs(current_price - support_price) / current_price * 100

    if dist_pct < 0.5:
        # Price is ON or very near support — enter now
        return {
            "entry": current_price,
            "entry_type": "now",
            "entry_note": f"📍 دخول فوري (السعر عند {support_source}: ${support_price:.6f})",
            "nearest_support": support_price,
        }
    elif dist_pct <= 2.0:
        # Price within 2% — enter now but note proximity
        return {
            "entry": current_price,
            "entry_type": "now",
            "entry_note": f"📍 دخول فوري (أقرب دعم {support_source}: ${support_price:.6f}، بُعد {dist_pct:.1f}%)",
            "nearest_support": support_price,
        }
    else:
        # Price far from support — place limit order at support
        # Use the highest-confidence support within 5%
        best_support = None
        for s in supports:
            s_dist = abs(current_price - s[0]) / current_price * 100
            if s_dist <= 5.0 and s[2] >= 0.5:
                best_support = s[0]
                break
        if best_support is None:
            best_support = support_price  # fallback to nearest

        return {
            "entry": best_support,
            "entry_type": "limit",
            "entry_note": f"⏳ أمر معلق عند {support_source}: ${best_support:.6f} (السعر الحالي بعيد {dist_pct:.1f}%)",
            "nearest_support": best_support,
        }


def compute_smart_stop(df, entry, current_price):
    """
    Compute stop loss capped at 2% max.
    Uses: swing low, support levels, OB low.
    Returns dict: {stop_loss, sl_pct, source}
    If SL would be >2%, returns capped SL.
    """
    supports = find_nearest_supports(df, current_price)

    # Find best stop loss below entry
    candidates = []

    # ─── 1. Swing low -0.3% ───
    lookback = min(20, len(df) - 2)
    swings = []
    low_vals = df["low"].values
    for i in range(len(low_vals) - lookback, len(low_vals) - 2):
        if low_vals[i] < low_vals[i-1] and low_vals[i] < low_vals[i-2] and low_vals[i] < low_vals[i+1] and low_vals[i] < low_vals[i+2]:
            if low_vals[i] < entry:
                swings.append(float(low_vals[i]))

    if swings:
        best_swing = min(swings, key=lambda x: entry - x if entry > x else float('inf'))
        sl = best_swing * 0.997  # -0.3% under swing low
        candidates.append((sl, "Swing Low -0.3%", 0.8))

    # ─── 2. Best support -0.2% ───
    for s_price, s_source, s_conf in supports[:5]:
        if s_price < entry:
            sl = s_price * 0.998  # -0.2% under support
            candidates.append((sl, f"{s_source} -0.2%", 0.6))

    # ─── 3. Order Block low -0.1% ───
    close = df["close"].values
    high = df["high"].values
    open_p = df["open"].values
    for i in range(max(1, len(close) - 30 - 3), len(close) - 3):
        if close[i] < open_p[i] and close[i+1] > open_p[i+1]:
            body_prev = abs(close[i] - open_p[i])
            body_next = abs(close[i+1] - open_p[i+1])
            if body_prev > 0 and (body_next / max(body_prev, 1e-10)) > 1.5:
                ob_low = float(df["low"].values[i])
                if ob_low < entry:
                    sl = ob_low * 0.999  # -0.1% under OB
                    candidates.append((sl, "OB Low -0.1%", 0.7))
                    break  # Take first recent OB

    # ─── 4. Default: 2% SL ───
    default_sl = entry * 0.98
    candidates.append((default_sl, "Default 2%", 0.3))

    # Sort by: closest to entry (tightest stop) but below entry, higher confidence
    valid = [(sl, src, conf) for sl, src, conf in candidates if sl < entry]
    valid.sort(key=lambda x: (entry - x[0], -x[2]))

    if not valid:
        best_sl = entry * 0.98
        best_source = "Default 2%"
    else:
        best_sl, best_source, _ = valid[0]

    # ─── Cap SL at 2% ───
    sl_pct = (entry - best_sl) / entry * 100
    max_sl = entry * 0.98  # 2% cap
    if best_sl < max_sl:
        best_sl = max_sl
        sl_pct = 2.0
        best_source += " (capped at 2%)"

    return {
        "stop_loss": round(best_sl, 8),
        "sl_pct": round(sl_pct, 2),
        "source": best_source,
    }


def compute_rr_check(entry, target, stop_loss):
    """
    Risk:Reward filter.
    Returns dict: {tp_pct, sl_pct, rr_ratio, passed, reason}
    """
    if entry <= 0 or stop_loss <= 0 or target <= 0:
        return {"tp_pct": 0, "sl_pct": 0, "rr_ratio": 0, "passed": False, "reason": "Invalid prices"}

    tp_distance = (target - entry) / entry * 100
    sl_distance = (entry - stop_loss) / entry * 100

    if sl_distance <= 0:
        return {"tp_pct": round(tp_distance, 2), "sl_pct": round(sl_distance, 2),
                "rr_ratio": 0, "passed": False, "reason": "SL above or at entry"}

    # ⛔ [2] Minimum SL distance — prevent noise-triggered stops (Phase 5.8)
    if sl_distance < 0.8:
        return {"tp_pct": round(tp_distance, 2), "sl_pct": round(sl_distance, 2),
                "rr_ratio": 0, "passed": False, "reason": f"SL={sl_distance:.2f}% < 0.8% min — price noise zone"}

    rr_ratio = tp_distance / sl_distance

    # Check all 3 conditions
    checks = []
    if tp_distance < 1.0:
        checks.append(f"TP={tp_distance:.1f}% < 1%")
    if sl_distance > 2.0:
        checks.append(f"SL={sl_distance:.1f}% > 2%")
    if rr_ratio < 1.5:
        checks.append(f"RR={rr_ratio:.1f} < 1.5")

    passed = len(checks) == 0
    reason = " | ".join(checks) if checks else "✅ All checks passed"

    return {
        "tp_pct": round(tp_distance, 2),
        "sl_pct": round(sl_distance, 2),
        "rr_ratio": round(rr_ratio, 1),
        "passed": passed,
        "reason": reason,
    }


def compute_cancel_level(df, entry_price, current_price):
    """
    Find the nearest resistance ABOVE entry price to use as cancel level.
    Priority: ① Resistance ② Bearish OB ③ Bearish FVG ④ Fib 61.8% ⑤ TP1 fallback
    Returns dict: {cancel_level, cancel_source}
    """
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    open_p = df["open"].values

    candidates = []

    # ─── ① Nearest Resistance from pivot SR ───
    recent_high = float(np.max(high[-20:]))
    recent_low = float(np.min(low[-20:]))
    rng = recent_high - recent_low
    if rng > 0:
        levels = {
            "R1 (61.8%)": recent_low + rng * 0.618,
            "R2 (78.6%)": recent_low + rng * 0.786,
            "R3 (Top)": recent_high,
        }
        for name, lvl in levels.items():
            if lvl > entry_price:
                candidates.append((lvl, "resistance", f"Pivot {name}"))

    # ─── ② Bearish Order Blocks (OB high = resistance) ───
    try:
        for i in range(max(1, len(close) - 30 - 3), len(close) - 3):
            if close[i] > open_p[i] and close[i+1] < open_p[i+1]:
                body_prev = abs(close[i] - open_p[i])
                body_next = abs(close[i+1] - open_p[i+1])
                if body_prev > 0 and (body_next / max(body_prev, 1e-10)) > 1.5 and close[i+1] < low[i]:
                    ob_high = float(high[i])
                    if ob_high > entry_price:
                        candidates.append((ob_high, "ob", "Bearish OB High"))
    except Exception as e:
        logger.error(f"Compute failure: {e}", exc_info=True)
        return None  # compute failure

    # ─── ③ Bearish FVG (gap high = resistance) ───
    try:
        for i in range(max(3, len(close) - 40), len(close) - 1):
            if i >= 2 and high[i] < low[i-2]:
                fvg_high = float(low[i-2])
                if fvg_high > entry_price:
                    candidates.append((fvg_high, "fvg", "Bearish FVG High"))
    except Exception as e:
        logger.error(f"Compute failure: {e}", exc_info=True)
        return None  # compute failure

    # ─── ④ Fibonacci 61.8% from last down wave ───
    try:
        swing_high = float(np.max(high[-20:]))
        swing_low = float(np.min(low[-20:]))
        hi_idx = len(close) - 20 + np.argmax(high[-20:])
        lo_idx = len(close) - 20 + np.argmin(low[-20:])
        if hi_idx < lo_idx and swing_high > swing_low:
            rng = swing_high - swing_low
            fib_618 = swing_high - rng * 0.618
            if fib_618 > entry_price:
                candidates.append((round(fib_618, 8), "fib61.8", "Fib 61.8%"))
    except Exception as e:
        logger.error(f"Compute failure: {e}", exc_info=True)
        return None  # compute failure

    # ─── Sort: nearest above entry first ───
    candidates.sort(key=lambda x: x[0])
    
    # 🆕 Minimum cancel distance: at least 3% above entry (5% for micro-caps)
    min_dist_pct = 5.0 if entry_price < 0.01 else 3.0 if entry_price < 1.0 else 2.0
    
    if candidates:
        # Filter: only use levels at least min_dist_pct% above entry
        valid = [(lvl, src, name) for lvl, src, name in candidates 
                 if (lvl - entry_price) / entry_price * 100 >= min_dist_pct]
        
        if valid:
            best = valid[0]  # nearest valid resistance
            return {
                "cancel_level": round(best[0], 8),
                "cancel_source": best[1],
            }
        # If no level meets minimum distance, use the farthest available
        elif candidates:
            best = candidates[-1]  # farthest resistance
            dist = (best[0] - entry_price) / entry_price * 100
            if dist >= 1.5:  # at least somewhat meaningful
                return {
                    "cancel_level": round(best[0], 8),
                    "cancel_source": best[1],
                }

    # ─── ⑤ Fallback: TP1 as cancel level ───
    tp1 = entry_price * 1.03  # default 3% above
    return {
        "cancel_level": round(tp1, 8),
        "cancel_source": "tp1",
    }
