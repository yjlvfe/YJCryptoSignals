"""
🌊 Market Regime Detection — تصنيف حالة السوق
"""
import numpy as np
import warnings
import logging
from pathlib import Path
import json
import time

# Suppress numpy division warnings
warnings.filterwarnings('ignore', category=RuntimeWarning)

logger = logging.getLogger("crypto-signal-regime")

REGIME_FILE = Path("/root/.crypto-signal-bot/market_regime.json")


def detect_regime(df_btc, df_alt=None) -> dict:
    """
    تحليل حالة السوق من بيانات BTC (والعملة البديلة اختياري).
    
    Returns:
        {
            "regime": "BULL" | "BEAR" | "RANGING" | "VOLATILE",
            "confidence": 0-100,
            "btc_trend": "UP" | "DOWN" | "SIDEWAYS",
            "btc_volatility": float,  # نسبة مئوية
            "btc_strength": 0-100,
            "alt_correlation": float | None,  # ارتباط العملة مع BTC
            "recommended_exposure": 0-100,    # نسبة المخاطرة الموصى بها
            "entry_filter": "AGGRESSIVE" | "NORMAL" | "CONSERVATIVE" | "NO_ENTRY",
        }
    """
    close = df_btc["close"].values
    high = df_btc["high"].values
    low = df_btc["low"].values
    
    if len(close) < 50:
        return _default_regime()
    
    # ─── ① BTC Trend ───
    ma20 = np.mean(close[-20:])
    ma50 = np.mean(close[-50:]) if len(close) >= 50 else ma20
    current = close[-1]
    NOISE_THRESHOLD = 0.02  # 2% — down from 3% to catch more trends
    
    # 24h change
    btc_change_24h = ((close[-1] - close[-24]) / close[-24] * 100) if len(close) >= 24 else 0
    
    # Percentage distance from MAs
    dist_from_ma20 = (current - ma20) / ma20 if ma20 > 0 else 0
    dist_from_ma50 = (current - ma50) / ma50 if ma50 > 0 else 0
    
    # Short-term momentum (5-period)
    momentum_5 = (close[-1] - close[-6]) / close[-6] if len(close) >= 6 else 0
    
    if (current > ma20 and current > ma50 and ma20 > ma50
        and dist_from_ma20 > NOISE_THRESHOLD):
        btc_trend = "UP"
        trend_strength = min(100, (current - ma50) / ma50 * 100 * 5)
    elif (current < ma20 and current < ma50 and ma20 < ma50
          and abs(dist_from_ma20) > NOISE_THRESHOLD):
        btc_trend = "DOWN"
        trend_strength = min(100, (ma50 - current) / ma50 * 100 * 5)
    elif abs(dist_from_ma20) <= NOISE_THRESHOLD and abs(momentum_5) > 0.01:
        # 🟠 Secondary: strong momentum even if price hasn't crossed MAs yet
        if momentum_5 > 0.01:
            btc_trend = "UP"
            trend_strength = min(60, 30 + abs(momentum_5) * 500)
        else:
            btc_trend = "DOWN"
            trend_strength = min(60, 30 + abs(momentum_5) * 500)
    else:
        btc_trend = "SIDEWAYS"
        trend_strength = 30
    
    # ─── ② Volatility (ATR-based) ───
    atr = _compute_atr(high, low, close, 14)
    atr_pct = (atr[-1] / close[-1]) * 100 if close[-1] > 0 else 0
    
    if atr_pct > 8:
        volatility = "VERY_HIGH"
        vol_score = 90
    elif atr_pct > 5:
        volatility = "HIGH"
        vol_score = 70
    elif atr_pct > 3:
        volatility = "MODERATE"
        vol_score = 50
    elif atr_pct > 1.5:
        volatility = "LOW"
        vol_score = 30
    else:
        volatility = "VERY_LOW"
        vol_score = 15
    
    # ─── ③ BTC Strength Score (0-100) ───
    # حساب RSI بسيط
    rsi = _compute_rsi_simple(close, 14)
    rsi_val = rsi[-1] if len(rsi) > 0 else 50
    
    # قوة الاتجاه: ADX مبسط
    adx_simple = _compute_adx_simple(high, low, close, 14)
    adx_val = min(adx_simple[-1], 60) if len(adx_simple) > 0 else 20
    
    # تجميع القوة
    if btc_trend == "UP":
        btc_strength = min(100, trend_strength * 0.5 + adx_val * 0.5 + (rsi_val - 30) * 0.3)
    elif btc_trend == "DOWN":
        btc_strength = min(100, trend_strength * 0.5 + adx_val * 0.5 + (70 - rsi_val) * 0.3)
    else:
        btc_strength = min(60, adx_val * 0.8)
    
    # ─── ④ Correlation with BTC (if alt data provided) ───
    alt_correlation = None
    if df_alt is not None and len(df_alt) >= 30:
        alt_close = df_alt["close"].values[-30:]
        btc_close_slice = close[-30:]
        if len(alt_close) == len(btc_close_slice):
            alt_returns = np.diff(alt_close) / alt_close[:-1]
            btc_returns = np.diff(btc_close_slice) / btc_close_slice[:-1]
            if len(alt_returns) > 0 and np.std(btc_returns) > 0:
                corr = np.corrcoef(alt_returns, btc_returns)[0, 1]
                alt_correlation = round(float(corr), 3) if not np.isnan(corr) else None
    
    # ─── ⑤ Regime Classification ───
    if btc_trend == "UP" and atr_pct < 5:
        regime = "BULL"
        confidence = min(95, btc_strength)
        entry_filter = "AGGRESSIVE"
        exposure = min(90, btc_strength + 10)
    elif btc_trend == "DOWN" and atr_pct < 5:
        regime = "BEAR"
        confidence = min(95, btc_strength)
        entry_filter = "CONSERVATIVE"
        exposure = max(10, 50 - btc_strength // 2)
    elif btc_trend == "UP" and atr_pct >= 5:
        regime = "VOLATILE"
        confidence = min(80, btc_strength)
        entry_filter = "NORMAL"
        exposure = min(70, btc_strength)
    elif btc_trend == "DOWN" and atr_pct >= 5:
        regime = "VOLATILE"
        confidence = min(70, btc_strength)
        entry_filter = "NO_ENTRY"
        exposure = max(5, 20 - btc_strength // 3)
    else:
        regime = "RANGING"
        confidence = 40
        entry_filter = "AGGRESSIVE"  # Lower thresholds to find signals in quiet market
        exposure = 40
    
    regime_data = {
        "regime": regime,
        "confidence": round(confidence, 1),
        "btc_trend": btc_trend,
        "btc_change": round(btc_change_24h, 2),
        "btc_volatility": round(atr_pct, 1),
        "btc_strength": round(btc_strength, 1),
        "alt_correlation": alt_correlation,
        "recommended_exposure": round(exposure, 1),
        "entry_filter": entry_filter,
        "checked_at": time.time(),
    }
    
    # حفظ للتتبع
    try:
        REGIME_FILE.parent.mkdir(parents=True, exist_ok=True)
        REGIME_FILE.write_text(json.dumps(regime_data, indent=2))
    except Exception as e:
        logger.debug(f"Regime save failed: {e}")
    
    return regime_data


def get_cached_regime() -> dict:
    """استرجاع آخر تحليل للسوق"""
    try:
        if REGIME_FILE.exists():
            return json.loads(REGIME_FILE.read_text())
    except Exception as e:
        logger.debug(f"Regime detection failed, using defaults: {e}")
        return defaults
    return _default_regime()


def get_min_strength_for_regime(regime_data: dict) -> tuple:
    """
    🎯 Master YJ thresholds — confidence-driven, regime-aware.
    High success rate: AI confidence is the dominant filter.
    Returns (min_strength, min_confidence)
    
    Self-tuning: these are BASE thresholds — self_learning_v2 can
    tighten them per-symbol based on historical win/loss data.
    """
    regime = (regime_data or {}).get("regime", "RANGING")
    
    # ─── Master YJ's thresholds ───
    # Confidence ≥ 45: AI must be very sure (dominant filter)
    # Strength ≥ 35: TA signals must be solid
    if regime == "BEAR":
        base_str, base_conf = (30, 40)   # Relaxed: signals bot catches dips in bear
    elif regime == "BULL":
        base_str, base_conf = (25, 30)   # More permissive: trend is your friend
    else:  # RANGING
        base_str, base_conf = (25, 35)   # Relaxed: catch signals in ranging market
    
    # 🧠 Self-learning adjustment
    try:
        from engine.self_learning_v2 import get_adaptive_thresholds
        return get_adaptive_thresholds(base_str, base_conf)
    except Exception:
        return (base_str, base_conf)


def _compute_atr(high, low, close, period=14):
    """حساب ATR"""
    n = len(close)
    tr = np.zeros(n)
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i-1])
        lc = abs(low[i] - close[i-1])
        tr[i] = max(hl, hc, lc)
    
    atr = np.zeros(n)
    atr[period-1] = np.mean(tr[:period])
    for i in range(period, n):
        atr[i] = (atr[i-1] * (period-1) + tr[i]) / period
    return atr


def _compute_rsi_simple(prices, period=14):
    """RSI سريع"""
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    rsi = np.zeros(len(prices))
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    
    if avg_loss > 0:
        rsi[period-1] = 100 - 100/(1 + avg_gain/avg_loss)
    else:
        rsi[period-1] = 100
    
    for i in range(period, len(prices)):
        avg_gain = (avg_gain * (period-1) + gains[i-1]) / period
        avg_loss = (avg_loss * (period-1) + losses[i-1]) / period
        if avg_loss > 0:
            rsi[i] = 100 - 100/(1 + avg_gain/avg_loss)
        else:
            rsi[i] = 100
    
    return rsi


def _compute_adx_simple(high, low, close, period=14):
    """ADX سريع"""
    n = len(close)
    tr = np.zeros(n)
    up = np.zeros(n)
    down = np.zeros(n)
    
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i-1])
        lc = abs(low[i] - close[i-1])
        tr[i] = max(hl, hc, lc)
        up[i] = max(0, high[i] - high[i-1])
        down[i] = max(0, low[i-1] - low[i])
    
    atr = _wilder_smooth(tr, period)
    up_s = _wilder_smooth(up, period)
    down_s = _wilder_smooth(down, period)
    
    di_plus = np.where(atr > 0, 100 * up_s / atr, 0)
    di_minus = np.where(atr > 0, 100 * down_s / atr, 0)
    
    di_sum = di_plus + di_minus
    dx = np.where(di_sum > 0, 100 * abs(di_plus - di_minus) / di_sum, 0)
    adx = _wilder_smooth(dx, period)
    
    return adx


def _wilder_smooth(values, period):
    n = len(values)
    result = np.zeros(n)
    if n > period:
        result[period-1] = np.mean(values[:period])
    for i in range(period, n):
        result[i] = (result[i-1] * (period-1) + values[i]) / period
    return result


def _default_regime():
    return {
        "regime": "RANGING",
        "confidence": 40,  # 🟠 Up from 30 — more neutral than pessimistic
        "btc_trend": "SIDEWAYS",
        "btc_change": 0,
        "btc_volatility": 3.0,
        "btc_strength": 40,  # 🟠 Up from 30
        "alt_correlation": None,
        "recommended_exposure": 50,  # 🟠 Up from 40
        "entry_filter": "NORMAL",
        "checked_at": time.time(),
    }
