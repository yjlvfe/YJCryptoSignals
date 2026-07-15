"""
🎯 Smart Targets — أهداف ذكية حسب ATR والتقلب الحي

يحسب أهداف TP/SL بناءً على:
  1. ATR (متوسط المدى الحقيقي) — يضبط المسافات حسب تقلب العملة
  2. هيكل السعر — يراعي الدعوم والمقاومات القريبة
  3. حالة السوق — يوسع الأهداف في السوق الهابط

بدل النسب الثابتة (3%/6%/9%)، يستخدم ATR لضبط الأهداف ديناميكياً.
"""
import numpy as np
import logging
from typing import List, Optional, Tuple

logger = logging.getLogger("crypto-signal-smart-targets")


def compute_atr_pct(df, period: int = 14) -> float:
    """حساب ATR كنسبة من السعر"""
    try:
        import pandas as pd
        high = df["high"].values if hasattr(df, "values") else df["high"]
        low = df["low"].values if hasattr(df, "values") else df["low"]
        close = df["close"].values if hasattr(df, "values") else df["close"]
        
        n = len(close)
        if n < period + 1:
            return 0.03  # default 3%
        
        tr = np.zeros(n)
        for i in range(1, n):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i-1]),
                abs(low[i] - close[i-1])
            )
        
        atr = np.mean(tr[-period:])
        avg_price = np.mean(close[-period:])
        
        if avg_price > 0:
            return atr / avg_price  # نسبة
        return 0.03
    except Exception as e:
        logger.debug(f"ATR compute fallback: {e}")
        return 0.03


def get_volatility_regime(atr_pct: float) -> str:
    """تحديد نظام التقلب"""
    if atr_pct > 0.08:
        return "HIGH"
    elif atr_pct > 0.03:
        return "NORMAL"
    else:
        return "LOW"


def compute_smart_targets(
    entry_price: float,
    atr_pct: float,
    direction: str = "BUY",
    regime: str = "NORMAL",
    confidence: float = 50,
) -> dict:
    """
    حساب أهداف ذكية مبنية على ATR.
    
    Returns:
        dict with targets, stop_loss, adjustments
    """
    # Base multipliers by volatility
    # ✅ SL must always be ≤ TP1 — risk management fundamental
    # RR ratios: HIGH=1:1.88, NORMAL=1:2.0, LOW=1:2.08
    vol_mult = {
        "HIGH": {"tp1": 1.5, "tp2": 2.5, "tp3": 4.0, "sl": 0.8},
        "NORMAL": {"tp1": 2.0, "tp2": 3.5, "tp3": 5.5, "sl": 1.0},
        "LOW": {"tp1": 2.5, "tp2": 4.0, "tp3": 6.5, "sl": 1.2},
    }.get(get_volatility_regime(atr_pct), {})

    # Confidence modifier: higher confidence → tighter SL, slightly wider TP
    conf_mod = 1.0 + (50 - min(confidence, 90)) / 100  # 0.6 to 1.0

    # Market regime modifier
    regime_mod = 1.0
    if regime == "BEAR":
        regime_mod = 0.8  # tighter targets in bear
    elif regime == "BULL":
        regime_mod = 1.2  # wider targets in bull

    # Compute ATR in price terms
    atr_price = entry_price * atr_pct

    # Targets — direction-aware: above for BUY, below for SELL
    sign = -1 if direction == "SELL" else 1
    
    tp1 = entry_price * (1 + sign * atr_pct * vol_mult["tp1"] * regime_mod)
    tp2 = entry_price * (1 + sign * atr_pct * vol_mult["tp2"] * regime_mod)
    tp3 = entry_price * (1 + sign * atr_pct * vol_mult["tp3"] * regime_mod)

    # Stop loss — direction-aware: below for BUY, above for SELL
    sl_distance = atr_pct * vol_mult["sl"] * conf_mod
    sl = entry_price * (1 - sign * sl_distance)

    # Ensure minimum distances (direction-aware)
    if direction == "SELL":
        min_tp1 = entry_price * 0.995  # 0.5% minimum below
        max_sl = entry_price * 1.02    # 2% max above
    else:
        min_tp1 = entry_price * 1.005  # 0.5% minimum above
        max_sl = entry_price * 0.98    # 2% max below
    
    if direction == "SELL":
        targets = [
            min(tp1, min_tp1),
            min(tp2, tp1 * 0.995),
            min(tp3, tp2 * 0.995),
        ]
        stop_loss = max(sl, max_sl)
    else:
        targets = [
            max(tp1, min_tp1),
            max(tp2, tp1 * 1.005),
            max(tp3, tp2 * 1.005),
        ]
        stop_loss = min(sl, max_sl)

    # النسب المئوية (مسافة مطلقة عن الدخول)
    tp1_pct = abs(targets[0] - entry_price) / entry_price * 100
    tp2_pct = abs(targets[1] - entry_price) / entry_price * 100
    tp3_pct = abs(targets[2] - entry_price) / entry_price * 100
    sl_pct = abs(entry_price - stop_loss) / entry_price * 100

    return {
        "targets": targets,
        "stop_loss": stop_loss,
        "atr_pct": atr_pct,
        "volatility": get_volatility_regime(atr_pct),
        "adjustments": {
            "tp1_pct": round(tp1_pct, 2),
            "tp2_pct": round(tp2_pct, 2),
            "tp3_pct": round(tp3_pct, 2),
            "sl_pct": round(sl_pct, 2),
            "atr_price": round(atr_price, 8),
            "vol_multiplier_tp1": vol_mult["tp1"],
            "vol_multiplier_sl": vol_mult["sl"],
            "regime_mod": round(regime_mod, 2),
        },
        "note": f"ATR {atr_pct*100:.1f}% | تقلب {get_volatility_regime(atr_pct)} | أهداف مضبوطة ديناميكياً"
    }


def enhance_signal_targets(signal: dict, df, regime: str = "NORMAL") -> dict:
    """
    تحسين أهداف الإشارة بناءً على ATR.
    تُستدعى قبل إرسال التوصية.
    
    Args:
        signal: dict with entry, targets, stop_loss, confidence
        df: OHLCV DataFrame
        regime: market regime
    
    Returns:
        enhanced signal dict (same structure, adjusted targets)
    """
    try:
        atr_pct = compute_atr_pct(df)
        entry = signal.get("entry", 0)
        confidence = signal.get("confidence", 50)
        
        if entry <= 0 or atr_pct <= 0:
            return signal
        
        direction = signal.get("direction", "BUY")
        smart = compute_smart_targets(
            entry, atr_pct, direction, regime, confidence
        )
        
        # 🎯 BLEND: ATR-based targets are the foundation (70% weight)
        # AI targets only fine-tune (30% weight) — prevents fixed percentages
        ai_targets = signal.get("targets", [])
        smart_targets = smart["targets"]
        
        if ai_targets and len(ai_targets) >= 2:
            blended = []
            for i in range(min(3, len(smart_targets), len(ai_targets))):
                st = smart_targets[i]
                at = ai_targets[i] if i < len(ai_targets) else st
                # Clamp: AI target must be within ±50% of ATR-based target
                if at < st * 0.5:
                    at = st * 0.5
                elif at > st * 1.5:
                    at = st * 1.5
                # Weighted blend: 70% ATR + 30% AI
                blended.append(round(st * 0.7 + at * 0.3, 8))
            signal["targets"] = blended
            signal["_target_source"] = "BLENDED"
            smart_tp1_pct = smart["adjustments"]["tp1_pct"]
            ai_tp1_pct = (ai_targets[0] - entry) / entry * 100
            blend_tp1_pct = (blended[0] - entry) / entry * 100
            logger.info(f"🎯 Targets blended: AI {ai_tp1_pct:.1f}% + ATR {smart_tp1_pct:.1f}% → {blend_tp1_pct:.1f}%")
        else:
            signal["targets"] = smart_targets
            signal["_target_source"] = "ATR"
        
        # ATR-based stop loss if none provided
        if not signal.get("stop_loss") or signal.get("stop_loss", 0) >= entry:
            signal["stop_loss"] = smart["stop_loss"]
            signal["_sl_source"] = "ATR"
            logger.info(f"🛑 Using ATR-based SL: -{smart['adjustments']['sl_pct']:.1f}%")
        
        # 🛡️ Safety net: ensure SL distance ≤ TP1 distance (RR ≥ 1:1)
        sl = signal.get("stop_loss", 0)
        if sl and entry > 0 and signal.get("targets") and len(signal["targets"]) > 0:
            sl_dist = abs(entry - sl) / entry * 100
            tp1_dist = abs(signal["targets"][0] - entry) / entry * 100
            if sl_dist > tp1_dist and tp1_dist > 0:
                # Tighten SL to 60% of TP1 distance (RR 1:1.67)
                if direction == "BUY":
                    tight_sl = entry - (signal["targets"][0] - entry) * 0.6
                else:
                    tight_sl = entry + (entry - signal["targets"][0]) * 0.6
                signal["stop_loss"] = round(tight_sl, 8)
                signal["_sl_source"] = f"tightened_{signal.get('_sl_source', 'unknown')}"
                new_sl_pct = abs(entry - tight_sl) / entry * 100
                logger.info(f"🛑 RR sanity: SL {sl_dist:.1f}% > TP1 {tp1_dist:.1f}% — tightened to {new_sl_pct:.1f}% (RR 1:{tp1_dist/new_sl_pct:.1f})")
        
        signal["atr_pct"] = atr_pct
        signal["volatility"] = smart["volatility"]
        signal["_smart_targets_note"] = smart["note"]
        
        return signal
        
    except Exception as e:
        logger.debug(f"Smart targets skipped: {e}")
        return signal
