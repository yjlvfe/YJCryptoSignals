"""
📊 Advanced Volume Analysis — CVD + Volume Profile
"""
import numpy as np
import pandas as pd

def compute_cvd(df: pd.DataFrame) -> np.ndarray:
    """
    Cumulative Volume Delta (CVD).
    الفرق التراكمي بين حجم الشراء وحجم البيع.
    CVD صاعد = ضغط شرائي. CVD هابط = ضغط بيعي.
    """
    close = df["close"].values
    volume = df["volume"].values
    high = df["high"].values
    low = df["low"].values
    
    cvd = np.zeros(len(close))
    
    for i in range(1, len(close)):
        # تقدير حجم الشراء/البيع من موقع الإغلاق في الشمعة
        if high[i] > low[i]:
            buy_pct = (close[i] - low[i]) / (high[i] - low[i])
        else:
            buy_pct = 0.5
        
        buy_vol = volume[i] * buy_pct
        sell_vol = volume[i] * (1 - buy_pct)
        
        delta = buy_vol - sell_vol
        cvd[i] = cvd[i-1] + delta
    
    return cvd


def analyze_cvd_signal(cvd: np.ndarray, price: np.ndarray, lookback: int = 20) -> dict:
    """
    تحليل CVD لإشارات التداول.
    Returns: {"signal": "BUY"/"SELL"/"NEUTRAL", "strength": 0-1, "reason": str}
    """
    if len(cvd) < lookback:
        return {"signal": "NEUTRAL", "strength": 0, "reason": "Insufficient CVD data"}
    
    recent_cvd = cvd[-lookback:]
    recent_price = price[-lookback:]
    
    # اتجاه CVD
    cvd_change = (cvd[-1] - cvd[-lookback]) / max(abs(cvd[-lookback]), 1)
    
    # تباعد CVD عن السعر
    price_change = (price[-1] - price[-lookback]) / max(abs(price[-lookback]), 1e-10)
    
    # CVD divergence: سعر هابط + CVD صاعد = شراء قوي
    if price_change < -0.02 and cvd_change > 0.05:
        return {
            "signal": "BUY", "strength": 0.85,
            "reason": f"CVD bullish divergence — price down {price_change*100:.1f}% but volume buying"
        }
    
    # CVD divergence: سعر صاعد + CVD هابط = بيع
    if price_change > 0.02 and cvd_change < -0.05:
        return {
            "signal": "SELL", "strength": 0.85,
            "reason": f"CVD bearish divergence — price up {price_change*100:.1f}% but volume selling"
        }
    
    # CVD اتجاه قوي
    if cvd_change > 0.1:
        return {"signal": "BUY", "strength": 0.6,
                "reason": f"Strong CVD uptrend ({cvd_change*100:.1f}%)"}
    elif cvd_change < -0.1:
        return {"signal": "SELL", "strength": 0.6,
                "reason": f"Strong CVD downtrend ({cvd_change*100:.1f}%)"}
    
    return {"signal": "NEUTRAL", "strength": 0.2, "reason": "CVD neutral"}


def compute_volume_profile(df: pd.DataFrame, bins: int = 30) -> dict:
    """
    Volume Profile (VPVR) — مناطق السيولة.
    Returns: {"poc": float, "value_area_high": float, "value_area_low": float}
    """
    high = df["high"].values[-100:]
    low = df["low"].values[-100:]
    close = df["close"].values[-100:]
    volume = df["volume"].values[-100:]
    
    price_range = np.linspace(np.min(low), np.max(high), bins)
    vol_profile = np.zeros(bins)
    
    for i in range(len(close)):
        for j in range(bins - 1):
            # كم من الشمعة يغطي هذا المستوى
            candle_low = low[i]
            candle_high = high[i]
            level_low = price_range[j]
            level_high = price_range[j+1]
            
            overlap = max(0, min(candle_high, level_high) - max(candle_low, level_low))
            if candle_high > candle_low:
                vol_profile[j] += volume[i] * (overlap / (candle_high - candle_low))
    
    # POC = Point of Control (أعلى حجم)
    poc_idx = np.argmax(vol_profile)
    poc = price_range[poc_idx]
    
    # Value Area = 70% من الحجم
    total_vol = np.sum(vol_profile)
    cumsum = 0
    va_high_idx = poc_idx
    va_low_idx = poc_idx
    
    max_iter = bins * 2  # Safety: prevent infinite loop
    iteration = 0
    while cumsum < total_vol * 0.7 and iteration < max_iter:
        iteration += 1
        up_idx = min(va_high_idx + 1, bins - 1)
        down_idx = max(va_low_idx - 1, 0)
        up_vol = vol_profile[up_idx] if up_idx > va_high_idx else 0
        down_vol = vol_profile[down_idx] if down_idx < va_low_idx else 0
        
        # Break if both sides exhausted
        if up_vol == 0 and down_vol == 0:
            break
        
        if up_vol > down_vol:
            va_high_idx = up_idx
            cumsum += up_vol
        else:
            va_low_idx = down_idx
            cumsum += down_vol
    
    return {
        "poc": round(float(poc), 8),
        "value_area_high": round(float(price_range[va_high_idx]), 8),
        "value_area_low": round(float(price_range[va_low_idx]), 8),
    }
