"""
📏 ATR Volatility Analyzer — Realistic targets, stops & duration estimates
"""
import numpy as np
from .base import BaseStrategy, Signal


class ATRStrategy(BaseStrategy):
    """
    تحليل التقلب (Volatility) باستخدام ATR:
    - Average True Range (ATR 14) للتقلب الحالي
    - Normalized ATR (% of price)
    - Realistic stop loss (1.5x ATR or 2x ATR)
    - Realistic targets (1x, 2x, 3x ATR)
    - Duration estimate based on ATR vs current range
    - Volatility regime classification
    """
    name = "ATR Volatility"

    def analyze(self, df) -> Signal:
        price = float(df["close"].iloc[-1])
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values

        if len(close) < 20:
            return self._neutral(price, "Need 20+ candles")

        # ATR params — auto_tune disabled, using defaults
        atr_period = 14
        atr_mult = 2.0

        # ATR
        tr = self._true_range(high, low, close)
        atr = float(np.mean(tr[-atr_period:]))
        atr_normalized = atr / price * 100  # % of price

        # Volatility classification
        if atr_normalized > 5:
            regime = "EXTREME"
            regime_emoji = "🔴"
        elif atr_normalized > 2.5:
            regime = "HIGH"
            regime_emoji = "🟠"
        elif atr_normalized > 1.0:
            regime = "NORMAL"
            regime_emoji = "🟡"
        else:
            regime = "LOW"
            regime_emoji = "🟢"

        # Current candle range vs ATR
        current_range = (high[-1] - low[-1]) / price * 100
        range_ratio = current_range / atr_normalized if atr_normalized > 0 else 1

        # Duration estimate (based on how many candles to reach target)
        # In a trending market with ATR = X, to move 3X we need ~3 candles
        duration_hours = self._estimate_duration(atr_normalized, len(close))

        # Trend direction from ATR perspective
        # If current candle is near the top of its ATR range → bullish momentum
        upper_atr = price + atr * 1.5
        lower_atr = price - atr * 1.5
        candle_top = price - low[-1] > high[-1] - price  # True = bullish body

        # Signals based on volatility
        bullish_signals = []
        bearish_signals = []

        # Squeeze: ATR contracting = breakout imminent
        atr_10 = float(np.mean(tr[-10:])) if len(tr) >= 10 else atr
        atr_20 = float(np.mean(tr[-20:])) if len(tr) >= 20 else atr
        atr_ratio = atr / atr_20 if atr_20 > 0 else 1

        is_squeezing = atr_ratio < 0.8
        is_expanding = atr_ratio > 1.2

        if is_squeezing:
            bullish_signals.append(f"ATR squeezing ({atr_ratio:.2f}x avg)")
            bearish_signals.append(f"ATR squeezing — breakout pending")

        if is_expanding and close[-1] > close[-2]:
            bullish_signals.append(f"ATR expanding ({atr_ratio:.2f}x) + bullish candle")
        elif is_expanding and close[-1] < close[-2]:
            bearish_signals.append(f"ATR expanding ({atr_ratio:.2f}x) + bearish candle")

        # Realistic stop and targets based on ATR
        atr_stop = atr * atr_mult
        realistic_stop_buy = price - atr_stop
        realistic_stop_sell = price + atr_stop

        targets_buy = [
            price + atr * 1.0,   # T1: 1x ATR
            price + atr * 2.0,   # T2: 2x ATR
            price + atr * 3.0,   # T3: 3x ATR
        ]
        targets_sell = [
            price - atr * 1.0,
            price - atr * 2.0,
            price - atr * 3.0,
        ]

        # Build signal
        confidence = 50
        if is_squeezing:
            confidence += 15
        if is_expanding and abs(close[-1] - close[-2]) / close[-2] > 0.01:
            confidence += 10

        # Direction preference
        if close[-1] > close[-2]:
            # Bullish bias
            confidence = min(85, confidence + 10)
            return Signal(
                name=self.name, signal="BUY", strength=0.65 if not is_squeezing else 0.75,
                entry=round(price, 8),
                stop_loss=round(float(realistic_stop_buy), 8),
                targets=[round(float(t), 8) for t in targets_buy],
                confidence=confidence,
                reason=f"📏 ATR={atr_normalized:.1f}% ({regime_emoji} {regime}) | ~{duration_hours}h | "
                       f"{'Squeeze breakout ↑' if is_squeezing else 'Expanding ↑' if is_expanding else 'Normal vol'}"
            )
        else:
            confidence = min(85, confidence + 5)
            return Signal(
                name=self.name, signal="SELL", strength=0.65 if not is_squeezing else 0.75,
                entry=round(price, 8),
                stop_loss=round(float(realistic_stop_sell), 8),
                targets=[round(float(t), 8) for t in targets_sell],
                confidence=confidence,
                reason=f"📏 ATR={atr_normalized:.1f}% ({regime_emoji} {regime}) | ~{duration_hours}h | "
                       f"{'Squeeze breakout ↓' if is_squeezing else 'Expanding ↓' if is_expanding else 'Normal vol'}"
            )

    def _true_range(self, high, low, close):
        tr = np.zeros_like(high)
        tr[0] = high[0] - low[0]
        for i in range(1, len(high)):
            tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        return tr

    def _estimate_duration(self, atr_pct, candle_count):
        """تقدير المدة الزمنية بناءً على ATR والتقلب"""
        if atr_pct > 5:
            return 2  # ساعتين
        elif atr_pct > 3:
            return 4
        elif atr_pct > 1.5:
            return 8
        elif atr_pct > 0.5:
            return 16
        return 24

    def _neutral(self, price, reason):
        return Signal(
            name=self.name, signal="NEUTRAL", strength=0.3,
            entry=round(price, 8), confidence=30,
            reason=f"⚪ {reason}."
        )
