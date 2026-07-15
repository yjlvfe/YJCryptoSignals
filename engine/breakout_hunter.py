"""
🎯 Breakout Hunter — 3 Real-time Detection Patterns
محور ٣: صياد الاختراقات — يلتقط الفرصة قبل ما تتحقق

Patterns:
  1. BB Squeeze     — Bollinger Bands tightening (volatility contraction → explosion)
  2. Volume Breakout — Volume 4x avg + big candle → confirmed breakout
  3. S/R Retest      — Price bouncing off support/resistance + volume confirmation
"""
import numpy as np
import pandas as pd
import logging
from typing import List, Tuple, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("crypto-signal-breakout")

# ═══════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════

@dataclass
class BBSqueezeSignal:
    """Bollinger Band squeeze — volatility contraction before explosion."""
    detected: bool = False
    squeeze_duration: int = 0          # how many candles in squeeze
    bb_width: float = 0.0              # current BB width %
    bb_width_min: float = 0.0          # minimum BB width in lookback
    squeeze_ratio: float = 0.0         # current_width / min_width (close to 1 = squeezing)
    expected_direction: str = "NEUTRAL" # "UP" / "DOWN" — which way it might break
    breakout_imminent: bool = False    # squeeze + volume starting to rise
    confidence: float = 0.0
    reason: str = ""


@dataclass
class VolumeBreakoutSignal:
    """Volume spike + large candle = confirmed breakout."""
    detected: bool = False
    direction: str = "NEUTRAL"         # "UP" / "DOWN"
    volume_ratio: float = 1.0          # current vol / avg vol
    candle_size_pct: float = 0.0       # candle body size as % of price
    breakout_level: float = 0.0        # price level being broken
    level_type: str = ""               # "resistance" / "support"
    confidence: float = 0.0
    reason: str = ""


@dataclass
class SRRetestSignal:
    """Support/Resistance retest with volume confirmation."""
    detected: bool = False
    direction: str = "NEUTRAL"         # "BOUNCE_UP" / "BOUNCE_DOWN" / "BREAK_UP" / "BREAK_DOWN"
    level_price: float = 0.0           # the S/R level
    level_type: str = ""               # "support" / "resistance"
    retest_count: int = 0              # how many times tested
    volume_on_retest: float = 0.0      # volume ratio during retest
    confidence: float = 0.0
    reason: str = ""


# ═══════════════════════════════════════
# 1. Bollinger Band Squeeze
# ═══════════════════════════════════════

def detect_bb_squeeze(df: pd.DataFrame, bb_period: int = 20,
                      bb_std: float = 2.0, min_squeeze_bars: int = 3,
                      width_percentile: float = 10.0) -> BBSqueezeSignal:
    """
    Detect Bollinger Band squeeze — the calm before the storm.
    
    A squeeze occurs when BB width is in the lowest X% of its recent range.
    This signals an imminent breakout (direction determined by other factors).
    
    Args:
        df: OHLCV DataFrame
        bb_period: BB lookback (default 20)
        bb_std: standard deviations (default 2.0)
        min_squeeze_bars: minimum candles in squeeze to confirm
        width_percentile: width must be below this percentile
        
    Returns:
        BBSqueezeSignal
    """
    close = df["close"].values
    n = len(close)
    
    if n < bb_period + 20:
        return BBSqueezeSignal(reason=f"Need > {bb_period+20} candles, have {n}")
    
    # Compute Bollinger Bands
    sma = np.convolve(close, np.ones(bb_period)/bb_period, mode='valid')
    sma = np.concatenate([np.full(bb_period-1, np.nan), sma])
    
    bb_widths = []
    for i in range(bb_period-1, n):
        window = close[i-bb_period+1:i+1]
        std = np.std(window)
        middle = np.mean(window)
        upper = middle + bb_std * std
        lower = middle - bb_std * std
        width_pct = (upper - lower) / middle * 100
        bb_widths.append(width_pct)
    
    # Lookback window for percentile calculation
    lookback = min(100, len(bb_widths))
    recent_widths = bb_widths[-lookback:]
    current_width = recent_widths[-1]
    width_min = np.min(recent_widths)
    
    # Check if in squeeze (width near minimum)
    if width_min <= 0:
        return BBSqueezeSignal(reason="Zero BB width")
    
    squeeze_ratio = current_width / width_min
    
    # Count consecutive bars in squeeze zone
    threshold = np.percentile(recent_widths, width_percentile)
    squeeze_bars = 0
    for w in reversed(recent_widths):
        if w <= threshold * 1.05:  # 5% tolerance
            squeeze_bars += 1
        else:
            break
    
    is_squeezing = squeeze_bars >= min_squeeze_bars and squeeze_ratio < 1.5
    
    if not is_squeezing:
        return BBSqueezeSignal(
            bb_width=round(current_width, 2),
            bb_width_min=round(width_min, 2),
            squeeze_ratio=round(squeeze_ratio, 2),
            squeeze_duration=squeeze_bars,
            reason=f"لا انضغاط: BB عرض={current_width:.1f}%، نسبة={squeeze_ratio:.1f}x"
        )
    
    # Determine expected direction from recent price action
    recent_close = close[-10:]
    half = len(recent_close) // 2
    price_trend = "UP" if np.mean(recent_close[-half:]) > np.mean(recent_close[:half]) else "DOWN"
    
    # Check if breakout is imminent (volume starting to rise in squeeze)
    volume = df["volume"].values
    recent_vol = volume[-5:]
    older_vol = volume[-10:-5]
    vol_rising = np.mean(recent_vol) > np.mean(older_vol) * 1.1 if len(older_vol) > 0 else False
    
    breakout_imminent = is_squeezing and vol_rising
    
    confidence = 0.4
    if squeeze_bars >= 5:
        confidence += 0.15
    if vol_rising:
        confidence += 0.15
    if squeeze_ratio < 1.1:
        confidence += 0.1
    
    reason_parts = [f"انضغاط Bollinger: {squeeze_bars} شموع"]
    if vol_rising:
        reason_parts.append("حجم يرتفع")
    if breakout_imminent:
        reason_parts.append("⚠️ انفجار وشيك")
    
    return BBSqueezeSignal(
        detected=True,
        squeeze_duration=squeeze_bars,
        bb_width=round(current_width, 2),
        bb_width_min=round(width_min, 2),
        squeeze_ratio=round(squeeze_ratio, 2),
        expected_direction=price_trend,
        breakout_imminent=breakout_imminent,
        confidence=round(min(1.0, confidence), 2),
        reason=" | ".join(reason_parts)
    )


# ═══════════════════════════════════════
# 2. Volume Breakout
# ═══════════════════════════════════════

def detect_volume_breakout(df: pd.DataFrame, vol_multiplier: float = 4.0,
                           min_candle_pct: float = 2.0,
                           lookback: int = 50) -> VolumeBreakoutSignal:
    """
    Detect volume-confirmed breakouts.
    
    A breakout = volume spike + large candle body breaking a key level.
    Looks for break above recent resistance or below recent support.
    
    Args:
        df: OHLCV DataFrame
        vol_multiplier: volume must be > N × average
        min_candle_pct: minimum candle body size as % of price
        lookback: candles for average volume and S/R levels
        
    Returns:
        VolumeBreakoutSignal
    """
    close = df["close"].values
    volume = df["volume"].values
    high = df["high"].values
    low = df["low"].values
    open_p = df["open"].values
    n = len(close)
    
    if n < lookback:
        return VolumeBreakoutSignal(reason=f"Need > {lookback} candles, have {n}")
    
    # Check last 3 candles for breakout
    best = VolumeBreakoutSignal()
    
    # Find recent resistance and support
    recent_high = np.max(high[-lookback:-3])  # exclude last 3 candles
    recent_low = np.min(low[-lookback:-3])
    
    avg_vol = np.mean(volume[-lookback:-1])
    if avg_vol <= 0:
        return VolumeBreakoutSignal(reason="Zero average volume")
    
    for i in range(n-3, n):
        vol_ratio = volume[i] / avg_vol
        
        if vol_ratio < vol_multiplier:
            continue
        
        # Candle body size
        body_pct = abs(close[i] - open_p[i]) / close[i] * 100
        
        if body_pct < min_candle_pct:
            continue
        
        # Check if breaking a level
        is_bullish = close[i] > open_p[i]
        
        if is_bullish and high[i] > recent_high:
            direction = "UP"
            breakout_level = recent_high
            level_type = "resistance"
            conf = min(1.0, 0.5 + (vol_ratio - vol_multiplier) / 5 + body_pct / 10)
        elif not is_bullish and low[i] < recent_low:
            direction = "DOWN"
            breakout_level = recent_low
            level_type = "support"
            conf = min(1.0, 0.5 + (vol_ratio - vol_multiplier) / 5 + body_pct / 10)
        else:
            continue
        
        if conf > best.confidence:
            best = VolumeBreakoutSignal(
                detected=True,
                direction=direction,
                volume_ratio=round(vol_ratio, 1),
                candle_size_pct=round(body_pct, 2),
                breakout_level=round(breakout_level, 6),
                level_type=level_type,
                confidence=round(conf, 2),
                reason=f"اختراق {direction}: حجم {vol_ratio:.1f}x + شمعة {body_pct:.1f}% {level_type}"
            )
    
    if not best.detected:
        best.reason = "لا اختراقات حجمية حديثة"
    
    return best


# ═══════════════════════════════════════
# 3. Support/Resistance Retest
# ═══════════════════════════════════════

def find_key_levels(df: pd.DataFrame, lookback: int = 50,
                    min_touches: int = 2, tolerance_pct: float = 0.5) -> List[float]:
    """
    Find key support and resistance levels using swing points.
    
    Returns list of price levels sorted by importance (number of touches).
    """
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(close)
    
    if n < 20:
        return []
    
    # Find swing highs and lows
    swings = []
    window = min(20, n // 3)
    
    for i in range(window, n - window):
        # Swing high
        if high[i] == np.max(high[i-window:i+window+1]):
            swings.append(("HIGH", high[i]))
        # Swing low
        if low[i] == np.min(low[i-window:i+window+1]):
            swings.append(("LOW", low[i]))
    
    if not swings:
        return []
    
    # Cluster nearby levels
    levels = []
    used = set()
    
    for i, (stype, price) in enumerate(swings):
        if i in used:
            continue
        
        cluster = [price]
        used.add(i)
        
        for j, (stype2, price2) in enumerate(swings):
            if j in used:
                continue
            if abs(price2 - price) / price * 100 < tolerance_pct:
                cluster.append(price2)
                used.add(j)
        
        if len(cluster) >= min_touches:
            levels.append(np.mean(cluster))
    
    return sorted(levels)


def detect_sr_retest(df: pd.DataFrame, lookback: int = 50,
                     vol_threshold: float = 1.2,
                     bounce_tolerance: float = 1.0) -> SRRetestSignal:
    """
    Detect price retesting key S/R levels with volume confirmation.
    
    A successful retest = price approaches a level, touches it, and bounces
    with increased volume.
    
    Args:
        df: OHLCV DataFrame
        lookback: candles for level detection
        vol_threshold: volume must be > N × average on retest
        bounce_tolerance: max % distance from level to count as touch
        
    Returns:
        SRRetestSignal
    """
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    volume = df["volume"].values
    n = len(close)
    
    if n < lookback:
        return SRRetestSignal(reason=f"Need > {lookback} candles, have {n}")
    
    # Find key levels
    levels = find_key_levels(df, lookback=lookback)
    
    if not levels:
        return SRRetestSignal(reason="لا مستويات دعم/مقاومة واضحة")
    
    current_price = close[-1]
    avg_vol = np.mean(volume[-20:]) if n >= 20 else np.mean(volume)
    prev_close = close[-2] if n >= 2 else current_price
    
    best = SRRetestSignal()
    
    for level in levels:
        dist_pct = abs(current_price - level) / current_price * 100
        
        # Check if price is near this level
        if dist_pct > bounce_tolerance:
            continue
        
        # Determine level type relative to current price
        if level < current_price:
            level_type = "support"
        else:
            level_type = "resistance"
        
        # Check recent touches of this level
        touches = 0
        for i in range(max(0, n-20), n-1):
            candle_touch = (low[i] <= level * 1.005 and high[i] >= level * 0.995)
            if candle_touch:
                touches += 1
        
        if touches < 1:
            continue
        
        # Check volume on retest
        vol_ratio = volume[-1] / avg_vol if avg_vol > 0 else 1.0
        
        # Determine bounce direction
        if level_type == "support":
            # Price near support — did it bounce up?
            if close[-1] > prev_close and low[-1] <= level * 1.01:
                direction = "BOUNCE_UP"
                conf = min(1.0, 0.5 + touches * 0.1 + min(vol_ratio, 3) * 0.1)
                reason = f"ارتداد من دعم ${level:.4f}: {touches} لمسات، حجم {vol_ratio:.1f}x"
            elif close[-1] < prev_close and low[-1] < level * 0.99:
                direction = "BREAK_DOWN"
                conf = min(1.0, 0.4 + touches * 0.05 + min(vol_ratio, 3) * 0.1)
                reason = f"كسر دعم ${level:.4f}: {touches} لمسات، حجم {vol_ratio:.1f}x"
            else:
                continue
        else:  # resistance
            if close[-1] < prev_close and high[-1] >= level * 0.99:
                direction = "BOUNCE_DOWN"
                conf = min(1.0, 0.5 + touches * 0.1 + min(vol_ratio, 3) * 0.1)
                reason = f"ارتداد من مقاومة ${level:.4f}: {touches} لمسات، حجم {vol_ratio:.1f}x"
            elif close[-1] > prev_close and high[-1] > level * 1.01:
                direction = "BREAK_UP"
                conf = min(1.0, 0.4 + touches * 0.05 + min(vol_ratio, 3) * 0.1)
                reason = f"اختراق مقاومة ${level:.4f}: {touches} لمسات، حجم {vol_ratio:.1f}x"
            else:
                continue
        
        if conf > best.confidence:
            best = SRRetestSignal(
                detected=True,
                direction=direction,
                level_price=round(level, 6),
                level_type=level_type,
                retest_count=touches,
                volume_on_retest=round(vol_ratio, 2),
                confidence=round(conf, 2),
                reason=reason
            )
    
    if not best.detected:
        best.reason = "لا ارتدادات حديثة من مستويات رئيسية"
    
    return best


# ═══════════════════════════════════════
# 4. Unified Breakout Report
# ═══════════════════════════════════════

def hunt_breakouts(df: pd.DataFrame, symbol: str = "") -> dict:
    """
    Run all 3 breakout detectors and return unified report.
    
    Args:
        df: OHLCV DataFrame (≥50 candles, recommended on 1h or 4h)
        symbol: for reporting
        
    Returns:
        dict with all detectors + summary
    """
    if len(df) < 50:
        return {
            "status": "insufficient_data",
            "message": f"Need ≥50 candles, got {len(df)}",
            "squeeze": None, "volume_breakout": None, "sr_retest": None,
            "alerts": [], "breakout_score": 0,
        }
    
    squeeze = detect_bb_squeeze(df)
    vol_break = detect_volume_breakout(df)
    sr_retest = detect_sr_retest(df)
    
    alerts = []
    breakout_score = 30  # baseline
    
    if squeeze.detected:
        alerts.append(f"🔵 {squeeze.reason}")
        breakout_score += 15 if squeeze.breakout_imminent else 8
    
    if vol_break.detected:
        emoji = "🟢" if vol_break.direction == "UP" else "🔴"
        alerts.append(f"{emoji} {vol_break.reason}")
        breakout_score += 20
    
    if sr_retest.detected:
        if "BOUNCE" in sr_retest.direction:
            emoji = "🟢" if "UP" in sr_retest.direction else "🔴"
            breakout_score += 15
        else:
            emoji = "⚡"
            breakout_score += 10
        alerts.append(f"{emoji} {sr_retest.reason}")
    
    # Clamp
    breakout_score = max(0, min(100, breakout_score))
    
    return {
        "symbol": symbol,
        "breakout_score": breakout_score,
        "squeeze": {
            "detected": squeeze.detected,
            "duration": squeeze.squeeze_duration,
            "imminent": squeeze.breakout_imminent,
            "expected_dir": squeeze.expected_direction,
            "confidence": squeeze.confidence,
            "reason": squeeze.reason,
        },
        "volume_breakout": {
            "detected": vol_break.detected,
            "direction": vol_break.direction,
            "volume_ratio": vol_break.volume_ratio,
            "candle_size_pct": vol_break.candle_size_pct,
            "confidence": vol_break.confidence,
            "reason": vol_break.reason,
        },
        "sr_retest": {
            "detected": sr_retest.detected,
            "direction": sr_retest.direction,
            "level": sr_retest.level_price,
            "level_type": sr_retest.level_type,
            "retest_count": sr_retest.retest_count,
            "confidence": sr_retest.confidence,
            "reason": sr_retest.reason,
        },
        "alerts": alerts,
    }


def format_breakout_summary(report: dict) -> str:
    """Format breakout report as compact Arabic summary."""
    if report.get("status") == "insufficient_data":
        return f"⚠️ بيانات اختراق غير كافية: {report.get('message', '')}"
    
    score = report.get("breakout_score", 0)
    symbol = report.get("symbol", "")
    alerts = report.get("alerts", [])
    
    lines = [f"🎯 **اختراقات {symbol}**: {score}/100"]
    
    if alerts:
        for a in alerts:
            lines.append(f"  {a}")
    else:
        lines.append("  لا إشارات اختراق حالياً")
    
    return "\n".join(lines)
