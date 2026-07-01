"""
📊 RSI — مؤشر القوة النسبية
"""
import numpy as np
import pandas as pd
from .base import BaseStrategy, Signal


class RSIStrategy(BaseStrategy):
    name = "RSI"

    def analyze(self, df: pd.DataFrame) -> Signal:
        price = df["close"].iloc[-1]
        close = df["close"].values

        # RSI period — auto_tune disabled, using defaults
        rsi_period = 14
        rsi_oversold = 30
        rsi_overbought = 70
        
        rsi = self._compute_rsi(close, rsi_period)
        current_rsi = rsi[-1]

        # RSI 7 (أسرع)
        rsi_fast = self._compute_rsi(close, 7)
        fast_rsi = rsi_fast[-1]

        # كشف التباعد (Divergence)
        bullish_div = self._detect_bullish_div(close, rsi)
        bearish_div = self._detect_bearish_div(close, rsi)

        # تحديد الإشارة
        if current_rsi < rsi_oversold and bullish_div:
            # ذروة بيع + تباعد صاعد → شراء قوي
            sl = price * 0.95
            targets = self._calculate_targets(price, 1.05, 1.08, 1.12)
            return Signal(
                name=self.name, signal="BUY", strength=0.9,
                entry=round(price, 8), stop_loss=round(sl, 8),
                targets=targets, confidence=90,
                reason=f"🟢 RSI={current_rsi:.1f} في ذروة البيع + تباعد صاعد! انعكاس وشيك."
            )

        elif current_rsi < rsi_oversold:
            sl = price * 0.95
            targets = self._calculate_targets(price, 1.03, 1.05, 1.08)
            return Signal(
                name=self.name, signal="BUY", strength=0.7,
                entry=round(price, 8), stop_loss=round(sl, 8),
                targets=targets, confidence=75,
                reason=f"🟡 RSI={current_rsi:.1f} في منطقة البيع (تحت 35). فرصة شراء."
            )

        elif current_rsi > rsi_overbought and bearish_div:
            sl = price * 1.05
            targets = self._calculate_targets(price, 0.95, 0.92, 0.88)
            return Signal(
                name=self.name, signal="SELL", strength=0.9,
                entry=round(price, 8), stop_loss=round(sl, 8),
                targets=targets, confidence=90,
                reason=f"🔴 RSI={current_rsi:.1f} ذروة شراء + تباعد هابط! تصحيح وشيك."
            )

        elif current_rsi > rsi_overbought:
            sl = price * 1.05
            targets = self._calculate_targets(price, 0.97, 0.95, 0.92)
            return Signal(
                name=self.name, signal="SELL", strength=0.7,
                entry=round(price, 8), stop_loss=round(sl, 8),
                targets=targets, confidence=70,
                reason=f"🟠 RSI={current_rsi:.1f} في منطقة الشراء (فوق 65). احتمال تصحيح."
            )

        return Signal(
            name=self.name, signal="NEUTRAL", strength=0.4,
            entry=round(price, 8), confidence=40,
            reason=f"⚪ RSI={current_rsi:.1f} منطقة طبيعية. لا توجد إشارة واضحة."
        )

    def _compute_rsi(self, prices, period=14):
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        rsi = np.zeros(len(prices))
        rsi[:period] = 100 - (100 / (1 + rs)) if avg_loss > 0 else 100
        for i in range(period, len(prices)):
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
            rs = avg_gain / avg_loss if avg_loss > 0 else 100
            rsi[i] = 100 - (100 / (1 + rs))
        return rsi

    def _detect_bullish_div(self, prices, rsi):
        """تباعد صاعد: قاع منخفض في السعر ↔ قاع مرتفع في RSI"""
        if len(prices) < 30:
            return False
        p1, p2 = prices[-20], prices[-5]
        r1, r2 = rsi[-20], rsi[-5]
        return p2 < p1 and r2 > r1

    def _detect_bearish_div(self, prices, rsi):
        """تباعد هابط: قمة مرتفعة في السعر ↔ قمة منخفضة في RSI"""
        if len(prices) < 30:
            return False
        p1, p2 = prices[-20], prices[-5]
        r1, r2 = rsi[-20], rsi[-5]
        return p2 > p1 and r2 < r1

    def _calculate_targets(self, price, t1_pct, t2_pct, t3_pct):
        return [round(price * t1_pct, 8), round(price * t2_pct, 8), round(price * t3_pct, 8)]
