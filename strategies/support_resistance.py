"""
📈 Support & Resistance — Support & Resistance Strategy
"""
import numpy as np
import pandas as pd
from .base import BaseStrategy, Signal


class SupportResistanceStrategy(BaseStrategy):
    name = "Support & Resistance"

    def analyze(self, df: pd.DataFrame) -> Signal:
        price = df["close"].iloc[-1]
        # Auto-tune disabled — using defaults
        sr_win = 5
        support, resistance = self.get_pivot_points(df, window=sr_win)

        # مناطق Support & Resistance الإضافية باستخدام مستويات 20/50/80
        high = df["high"].iloc[-20:].max()
        low = df["low"].iloc[-20:].min()
        range_ = high - low
        levels = {
            "R3": high,
            "R2": low + range_ * 0.786,
            "R1": low + range_ * 0.618,
            "P": low + range_ * 0.5,
            "S1": low + range_ * 0.382,
            "S2": low + range_ * 0.236,
            "S3": low,
        }

        # تحديد الإشارة بناءً على قرب السعر من الدعم/المقاومة
        dist_to_support = abs(price - support) / price * 100 if support > 0 else 99
        dist_to_resistance = abs(price - resistance) / price * 100 if resistance > 0 else 99

        if dist_to_support < 2.0 and price > support * 0.98:
            # السعر قرب الدعم → شراء
            sl = support * 0.97  # 3% تحت الدعم
            targets = [
                round((price + resistance) / 2, 8),  # T1: منتصف الطريق
                round(resistance, 8),                 # T2: المقاومة
                round(resistance * 1.05, 8),          # T3: فوق المقاومة
            ]
            confidence = max(0, 70 - dist_to_support * 10)
            return Signal(
                name=self.name, signal="BUY", strength=0.8,
                entry=round(price, 8), stop_loss=round(sl, 8),
                targets=targets, confidence=min(95, confidence),
                reason=f"💰 السعر قرب منطقة الدعم ({support:.4f}). مسافة {dist_to_support:.1f}% فقط."
            )

        elif dist_to_resistance < 2.0 and price < resistance * 1.02:
            # السعر قرب المقاومة → بيع
            sl = resistance * 1.03  # 3% فوق المقاومة
            targets = [
                round((price + support) / 2, 8),
                round(support, 8),
                round(support * 0.95, 8),
            ]
            confidence = max(0, 70 - dist_to_resistance * 10)
            return Signal(
                name=self.name, signal="SELL", strength=0.8,
                entry=round(price, 8), stop_loss=round(sl, 8),
                targets=targets, confidence=min(95, confidence),
                reason=f"📉 السعر قرب منطقة المقاومة ({resistance:.4f}). مسافة {dist_to_resistance:.1f}%."
            )

        return Signal(
            name=self.name, signal="NEUTRAL", strength=0.3,
            entry=round(price, 8), confidence=30,
            reason=f"↔️ السعر بين الدعم ({support:.4f}) والمقاومة ({resistance:.4f}) — في المنطقة الآمنة."
        )
