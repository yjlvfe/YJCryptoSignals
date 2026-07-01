"""
🕵️ Liquidity Intelligence — 4 Real-time Detectors
محور ١: مخابرات السيولة — يكشف تحركات الحيتان والسيولة قبل السعر

Detectors:
  1. Whale Detector    — حجم 3x المتوسط = دخول حوت
  2. Delta Divergence  — سعر يطلع + CVD ينزل = توزيع خفي
  3. Order Book Depth  — ذيول الشموع تكشف ضغط bid/ask
  4. Volume Climax      — قمم/قيعان حجمية = انعكاس محتمل
"""
import numpy as np
import pandas as pd
import logging
from typing import Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger("crypto-signal-liquidity")

# ═══════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════

@dataclass
class WhaleSignal:
    """Whale activity detection result."""
    detected: bool = False
    direction: str = "NEUTRAL"       # BUY / SELL
    volume_ratio: float = 1.0        # current volume / avg volume
    price_change_pct: float = 0.0    # % price move during whale candle
    candle_idx: int = -1             # which candle in the series
    confidence: float = 0.0          # 0-1
    reason: str = ""


@dataclass
class DeltaDivergence:
    """CVD-price divergence detection."""
    detected: bool = False
    divergence_type: str = ""        # "bullish_hidden" / "bearish_hidden" / "regular_bull" / "regular_bear"
    price_direction: str = ""        # "UP" / "DOWN"
    delta_direction: str = ""        # "UP" / "DOWN"
    strength: float = 0.0            # 0-1
    window: int = 20                 # candles looked back
    reason: str = ""


@dataclass
class OrderBookImbalance:
    """Estimated order book pressure from candle anatomy."""
    bid_pressure: float = 0.0        # 0-1 (higher = more buying)
    ask_pressure: float = 0.0        # 0-1 (higher = more selling)
    net_imbalance: float = 0.0       # -1 to +1 (positive = bull pressure)
    wick_ratio: float = 0.0          # top wick / bottom wick ratio
    interpretation: str = ""         # "شرائي", "بيعي", "متوازن"


@dataclass
class VolumeClimax:
    """Volume climax / exhaustion signal."""
    detected: bool = False
    climax_type: str = ""            # "buying_climax" / "selling_climax" / "none"
    volume_zscore: float = 0.0       # how many std above mean
    price_position: str = ""         # "high" / "low" / "mid"
    reversal_probability: float = 0.0 # 0-1
    reason: str = ""                 # Arabic explanation


# ═══════════════════════════════════════
# 1. Whale Detector — كاشف الحيتان
# ═══════════════════════════════════════

def detect_whale(df: pd.DataFrame, volume_multiplier: float = 3.0,
                 lookback: int = 50, min_price_move: float = 0.5) -> WhaleSignal:
    """
    Detect whale entries by volume spikes.
    
    A whale signal = volume > (multiplier × avg) AND significant price move.
    
    Args:
        df: OHLCV DataFrame
        volume_multiplier: how many times avg volume to trigger (default 3x)
        lookback: candles to average over
        min_price_move: minimum % price move to confirm
        
    Returns:
        WhaleSignal dataclass
    """
    close = df["close"].values
    volume = df["volume"].values
    high = df["high"].values
    low = df["low"].values
    open_p = df["open"].values
    
    n = len(volume)
    if n < lookback + 1:
        return WhaleSignal(reason=f"Need > {lookback} candles, have {n}")
    
    # Scan last 10 candles for whale activity
    best_signal = WhaleSignal()
    scan_start = max(0, n - 10)
    
    for i in range(scan_start, n):
        # Per-candle rolling average — excludes current candle
        l_start = max(0, i - lookback)
        l_end = i  # current candle NOT included
        if l_end - l_start < 5:
            continue
        window_vol = volume[l_start:l_end]
        avg_vol = np.mean(window_vol)
        if avg_vol <= 0:
            continue
        vol_ratio = volume[i] / avg_vol
        if vol_ratio < volume_multiplier:
            continue
        
        # Calculate price move for this candle
        if i > 0 and close[i-1] > 0:
            price_change = (close[i] - close[i-1]) / close[i-1] * 100
        else:
            price_change = (close[i] - low[i]) / max(low[i], 1e-10) * 100
        
        if abs(price_change) < min_price_move:
            continue  # volume spike but no price move = accumulation/distribution at same price
        
        # Direction from candle anatomy
        is_bullish = close[i] > open_p[i]
        is_bearish = close[i] < open_p[i]
        
        # Whale direction
        if price_change > 0 and is_bullish:
            direction = "BUY"
            conf = min(1.0, (vol_ratio - volume_multiplier) / 3 + 0.6)
        elif price_change < 0 and is_bearish:
            direction = "SELL"
            conf = min(1.0, (vol_ratio - volume_multiplier) / 3 + 0.6)
        else:
            # Price moved but candle is conflicted (e.g., bearish engulfing with volume)
            direction = "SELL" if is_bearish and price_change < 0 else "BUY" if is_bullish and price_change > 0 else "NEUTRAL"
            conf = 0.3
        
        if direction != "NEUTRAL" and conf > best_signal.confidence:
            best_signal = WhaleSignal(
                detected=True,
                direction=direction,
                volume_ratio=round(vol_ratio, 1),
                price_change_pct=round(price_change, 2),
                candle_idx=i,
                confidence=round(conf, 2),
                reason=f"حوت {direction}: حجم {vol_ratio:.1f}x المتوسط، حركة {price_change:+.2f}%"
            )
    
    return best_signal


# ═══════════════════════════════════════
# 2. Delta Divergence — تباعد CVD والسعر
# ═══════════════════════════════════════

def detect_delta_divergence(df: pd.DataFrame, cvd: np.ndarray = None,
                            lookback: int = 20) -> DeltaDivergence:
    """
    Detect CVD-price divergences (hidden distribution/accumulation).
    
    4 types:
      - Regular Bullish: price ↓ + CVD ↑ (smart money buying dip)
      - Regular Bearish:  price ↑ + CVD ↓ (smart money selling rally)
      - Hidden Bullish:   price ↑ + CVD ↑ (continuation, accumulation confirmed)
      - Hidden Bearish:   price ↓ + CVD ↓ (continuation, distribution confirmed)
    
    Args:
        df: OHLCV DataFrame
        cvd: pre-computed CVD array (if None, compute from df)
        lookback: candles to look back
        
    Returns:
        DeltaDivergence dataclass
    """
    close = df["close"].values
    volume = df["volume"].values
    high = df["high"].values
    low = df["low"].values
    n = len(close)
    
    if n < lookback + 5:
        return DeltaDivergence(reason=f"Need > {lookback} candles, have {n}")
    
    # Compute CVD if not provided
    if cvd is None:
        cvd = np.zeros(n)
        for i in range(1, n):
            if high[i] > low[i]:
                buy_pct = (close[i] - low[i]) / (high[i] - low[i])
            else:
                buy_pct = 0.5
            delta = volume[i] * (2 * buy_pct - 1)
            cvd[i] = cvd[i-1] + delta
    
    # Compare price direction vs CVD direction over lookback window
    half = lookback // 2
    
    # First half vs second half for divergence detection
    price_first = close[-lookback:-half]
    price_second = close[-half:]
    cvd_first = cvd[-lookback:-half]
    cvd_second = cvd[-half:]
    
    if len(price_first) < 2 or len(price_second) < 2:
        return DeltaDivergence(reason="Not enough data for window split")
    
    # Linear regression slopes
    def _slope(y):
        x = np.arange(len(y))
        if len(y) < 2:
            return 0.0
        return np.polyfit(x, y, 1)[0]
    
    price_slope_first = _slope(price_first)
    price_slope_second = _slope(price_second)
    cvd_slope_first = _slope(cvd_first)
    cvd_slope_second = _slope(cvd_second)
    
    # Normalize slopes relative to price
    price_norm = max(abs(np.mean(close[-lookback:])), 1e-10)
    cvd_norm = max(abs(np.mean(np.abs(cvd[-lookback:]))) if np.mean(np.abs(cvd[-lookback:])) > 0 else 1, 1e-10)
    
    price_change = (close[-1] - close[-lookback]) / abs(close[-lookback]) if close[-lookback] != 0 else 0
    cvd_change = (cvd[-1] - cvd[-lookback]) / cvd_norm
    
    result = DeltaDivergence(window=lookback)
    
    # Determine price and delta directions
    result.price_direction = "UP" if price_change > 0.01 else "DOWN" if price_change < -0.01 else "FLAT"
    result.delta_direction = "UP" if cvd_change > 0.02 else "DOWN" if cvd_change < -0.02 else "FLAT"
    
    # ─── Regular Divergences (reversal signals) ───
    if price_change < -0.02 and cvd_change > 0.05:
        result.detected = True
        result.divergence_type = "regular_bull"
        result.strength = min(1.0, abs(cvd_change) * 5)
        result.reason = f"تباعد إيجابي: السعر هابط {price_change*100:.1f}% لكن CVD صاعد — تجميع خفي"
    
    elif price_change > 0.02 and cvd_change < -0.05:
        result.detected = True
        result.divergence_type = "regular_bear"
        result.strength = min(1.0, abs(cvd_change) * 5)
        result.reason = f"تباعد سلبي: السعر صاعد {price_change*100:.1f}% لكن CVD هابط — توزيع خفي"
    
    # ─── Hidden Divergences (continuation signals) ───
    elif price_change > 0.03 and cvd_change > 0.08:
        result.detected = True
        result.divergence_type = "hidden_bull"
        result.strength = min(0.8, abs(cvd_change) * 3)
        result.reason = f"تأكيد تجميع: السعر +{price_change*100:.1f}% وCVD +{cvd_change*100:.1f}% — استمرار صاعد"
    
    elif price_change < -0.03 and cvd_change < -0.08:
        result.detected = True
        result.divergence_type = "hidden_bear"
        result.strength = min(0.8, abs(cvd_change) * 3)
        result.reason = f"تأكيد توزيع: السعر {price_change*100:.1f}% وCVD {cvd_change*100:.1f}% — استمرار هابط"
    
    else:
        result.reason = f"لا تباعد: سعر {price_change*100:.1f}% / CVD {cvd_change*100:.1f}%"
    
    return result


# ═══════════════════════════════════════
# 3. Order Book Imbalance — ضغط الدفاتر
# ═══════════════════════════════════════

def estimate_order_book_imbalance(df: pd.DataFrame, lookback: int = 10) -> OrderBookImbalance:
    """
    Estimate bid/ask pressure from candle anatomy.
    
    Uses wick ratios and body positions to infer order book:
      - Long bottom wicks + small top wicks = bid support (buying pressure)
      - Long top wicks + small bottom wicks = ask resistance (selling pressure)
      - Close near high = bulls in control
      - Close near low = bears in control
    
    Args:
        df: OHLCV DataFrame
        lookback: candles for rolling analysis
        
    Returns:
        OrderBookImbalance dataclass
    """
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    open_p = df["open"].values
    n = len(close)
    
    if n < lookback:
        return OrderBookImbalance(interpretation="بيانات غير كافية")
    
    recent_close = close[-lookback:]
    recent_high = high[-lookback:]
    recent_low = low[-lookback:]
    recent_open = open_p[-lookback:]
    
    # ─── Wick analysis ───
    top_wicks = []
    bottom_wicks = []
    body_positions = []
    
    for i in range(lookback):
        c, h, l, o = recent_close[i], recent_high[i], recent_low[i], recent_open[i]
        candle_range = h - l
        if candle_range <= 0:
            continue
        
        if c >= o:  # Bullish candle
            top_wick = (h - c) / candle_range
            bottom_wick = (o - l) / candle_range
        else:  # Bearish candle
            top_wick = (h - o) / candle_range
            bottom_wick = (c - l) / candle_range
        
        top_wicks.append(min(1.0, top_wick))
        bottom_wicks.append(min(1.0, bottom_wick))
        body_positions.append((c - l) / candle_range)
    
    if not top_wicks or not bottom_wicks:
        return OrderBookImbalance(interpretation="لا شموع صالحة للتحليل")
    
    avg_top_wick = np.mean(top_wicks)
    avg_bottom_wick = np.mean(bottom_wicks)
    avg_body_pos = np.mean(body_positions)
    
    # Wick ratio: >1 = more bottom wick (bullish), <1 = more top wick (bearish)
    wick_ratio = avg_bottom_wick / max(avg_top_wick, 0.001)
    
    # Bid pressure from bottom wicks + body position
    # Strong bottom wicks (rejection of lower prices) = bid pressure
    # Close near high = bid pressure
    bid_pressure = (avg_bottom_wick * 0.5 + avg_body_pos * 0.3 + (1 - avg_top_wick) * 0.2)
    
    # Ask pressure from top wicks + body position
    # Strong top wicks (rejection of higher prices) = ask pressure
    # Close near low = ask pressure
    ask_pressure = (avg_top_wick * 0.5 + (1 - avg_body_pos) * 0.3 + (1 - avg_bottom_wick) * 0.2)
    
    net_imbalance = bid_pressure - ask_pressure
    
    # Interpretation
    if net_imbalance > 0.3:
        interp = "شرائي قوي — ضغط bid عالي"
    elif net_imbalance > 0.1:
        interp = "شرائي — ميل للشراء"
    elif net_imbalance < -0.3:
        interp = "بيعي قوي — ضغط ask عالي"
    elif net_imbalance < -0.1:
        interp = "بيعي — ميل للبيع"
    else:
        interp = "متوازن — لا ضغط واضح"
    
    return OrderBookImbalance(
        bid_pressure=round(bid_pressure, 3),
        ask_pressure=round(ask_pressure, 3),
        net_imbalance=round(net_imbalance, 3),
        wick_ratio=round(wick_ratio, 2),
        interpretation=interp
    )


# ═══════════════════════════════════════
# 4. Volume Climax — قمم/قيعان حجمية
# ═══════════════════════════════════════

def detect_volume_climax(df: pd.DataFrame, lookback: int = 50,
                         zscore_threshold: float = 2.5) -> VolumeClimax:
    """
    Detect volume climax (potential reversal points).
    
    Buying climax: extreme volume at price high → distribution → sell-off
    Selling climax: extreme volume at price low → capitulation → reversal up
    
    Args:
        df: OHLCV DataFrame
        lookback: rolling window for mean/std
        zscore_threshold: how many std above mean to trigger
        
    Returns:
        VolumeClimax dataclass
    """
    close = df["close"].values
    volume = df["volume"].values
    high = df["high"].values
    low = df["low"].values
    n = len(volume)
    
    if n < lookback + 1:
        return VolumeClimax(reason="Not enough data")
    
    # Rolling volume z-score
    recent_vol = volume[-lookback:]
    vol_mean = np.mean(recent_vol)
    vol_std = np.std(recent_vol)
    
    if vol_std <= 0:
        return VolumeClimax(reason="Zero volume std")
    
    # Check last candle
    last_vol = volume[-1]
    vol_zscore = (last_vol - vol_mean) / vol_std
    
    if vol_zscore < zscore_threshold:
        return VolumeClimax(
            volume_zscore=round(vol_zscore, 2),
            reason=f"حجم عادي (z={vol_zscore:.1f})"
        )
    
    # Determine price position
    highest = np.max(high[-lookback:])
    lowest = np.min(low[-lookback:])
    price_range = highest - lowest
    if price_range > 0:
        price_position_pct = (close[-1] - lowest) / price_range
    else:
        price_position_pct = 0.5
    
    if price_position_pct >= 0.75:
        price_pos = "high"
    elif price_position_pct <= 0.25:
        price_pos = "low"
    else:
        price_pos = "mid"
    
    # Classify climax
    if vol_zscore >= zscore_threshold and price_pos == "high":
        # High volume at price peak → potential distribution
        # Check if candle is bearish
        is_bearish = close[-1] < df["open"].values[-1]
        reversal_prob = 0.6 if is_bearish else 0.35
        return VolumeClimax(
            detected=True,
            climax_type="buying_climax",
            volume_zscore=round(vol_zscore, 2),
            price_position=price_pos,
            reversal_probability=round(reversal_prob, 2),
            reason=f"ذروة شراء: حجم z={vol_zscore:.1f} عند قمة — احتمال توزيع {reversal_prob*100:.0f}%"
        )
    
    elif vol_zscore >= zscore_threshold and price_pos == "low":
        # High volume at price trough → potential capitulation/reversal
        is_bullish = close[-1] > df["open"].values[-1]
        reversal_prob = 0.6 if is_bullish else 0.35
        return VolumeClimax(
            detected=True,
            climax_type="selling_climax",
            volume_zscore=round(vol_zscore, 2),
            price_position=price_pos,
            reversal_probability=round(reversal_prob, 2),
            reason=f"ذروة بيع: حجم z={vol_zscore:.1f} عند قاع — احتمال ارتداد {reversal_prob*100:.0f}%"
        )
    
    else:
        return VolumeClimax(
            volume_zscore=round(vol_zscore, 2),
            price_position=price_pos,
            reason=f"حجم مرتفع (z={vol_zscore:.1f}) لكن السعر في المنتصف — غير حاسم"
        )


# ═══════════════════════════════════════
# 5. Unified Intel Report — تقرير السيولة الموحد
# ═══════════════════════════════════════

def gather_liquidity_intel(df: pd.DataFrame, cvd: np.ndarray = None,
                           symbol: str = "") -> dict:
    """
    Run all 4 detectors and return a unified liquidity report.
    
    Feed this to the AI Analyst for richer context.
    
    Args:
        df: OHLCV DataFrame (at least 50 candles)
        cvd: pre-computed CVD array (optional)
        symbol: for logging
        
    Returns:
        dict with all 4 detector results + summary
    """
    if len(df) < 50:
        return {
            "status": "insufficient_data",
            "message": f"Need ≥50 candles, got {len(df)}",
            "whale": None,
            "delta_divergence": None,
            "order_book": None,
            "volume_climax": None,
            "alerts": [],
        }
    
    # Run all detectors
    whale = detect_whale(df)
    delta = detect_delta_divergence(df, cvd=cvd)
    ob_imbalance = estimate_order_book_imbalance(df)
    climax = detect_volume_climax(df)
    
    # Collect alerts
    alerts = []
    liquidity_score = 50  # neutral baseline
    
    if whale.detected:
        alerts.append(f"🐋 {whale.reason}")
        liquidity_score += 15 if whale.direction == "BUY" else -15
    
    if delta.detected:
        prefix = "🟢" if "bull" in delta.divergence_type else "🔴"
        alerts.append(f"{prefix} {delta.reason}")
        if "bull" in delta.divergence_type:
            liquidity_score += 10
        else:
            liquidity_score -= 10
    
    if abs(ob_imbalance.net_imbalance) > 0.2:
        emoji = "🟢" if ob_imbalance.net_imbalance > 0 else "🔴"
        alerts.append(f"{emoji} دفتر: {ob_imbalance.interpretation}")
        liquidity_score += ob_imbalance.net_imbalance * 30
    
    if climax.detected:
        prefix = "🔴" if climax.climax_type == "buying_climax" else "🟢"
        alerts.append(f"{prefix} {climax.reason}")
        if climax.climax_type == "buying_climax":
            liquidity_score -= 10
        else:
            liquidity_score += 10
    
    # Clamp score
    liquidity_score = max(0, min(100, liquidity_score))
    
    # Determine overall bias
    if liquidity_score >= 65:
        bias = "BULLISH"
    elif liquidity_score <= 35:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"
    
    return {
        "symbol": symbol,
        "bias": bias,
        "liquidity_score": liquidity_score,
        "whale": {
            "detected": whale.detected,
            "direction": whale.direction,
            "volume_ratio": whale.volume_ratio,
            "confidence": whale.confidence,
            "reason": whale.reason,
        },
        "delta_divergence": {
            "detected": delta.detected,
            "type": delta.divergence_type,
            "strength": delta.strength,
            "reason": delta.reason,
        },
        "order_book": {
            "net_imbalance": ob_imbalance.net_imbalance,
            "bid_pressure": ob_imbalance.bid_pressure,
            "ask_pressure": ob_imbalance.ask_pressure,
            "interpretation": ob_imbalance.interpretation,
        },
        "volume_climax": {
            "detected": climax.detected,
            "type": climax.climax_type,
            "zscore": climax.volume_zscore,
            "reversal_probability": climax.reversal_probability,
            "reason": climax.reason,
        },
        "alerts": alerts,
    }


def format_liquidity_summary(intel: dict) -> str:
    """
    Format liquidity intel as a compact Arabic summary for Telegram.
    """
    if intel.get("status") == "insufficient_data":
        return f"⚠️ بيانات سيولة غير كافية: {intel.get('message', '')}"
    
    score = intel.get("liquidity_score", 50)
    bias = intel.get("bias", "NEUTRAL")
    alerts = intel.get("alerts", [])
    
    bias_emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⚪"}
    
    lines = [f"{bias_emoji.get(bias, '⚪')} **سيولة {intel.get('symbol', '')}**: {score}/100 ({bias})"]
    
    if alerts:
        for alert in alerts[:4]:  # max 4 alerts
            lines.append(f"  {alert}")
    else:
        lines.append("  لا توجد إشارات سيولة غير عادية")
    
    return "\n".join(lines)
