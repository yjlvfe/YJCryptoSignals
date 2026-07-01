"""
📐 Moving Averages — Moving Averages
"""
import numpy as np
import pandas as pd
from .base import BaseStrategy, Signal


class MAStrategy(BaseStrategy):
    name = "Moving Averages"

    def analyze(self, df: pd.DataFrame) -> Signal:
        price = df["close"].iloc[-1]
        close = df["close"].values

        # Auto-tune disabled — using defaults
        ma_fast = 20
        ma_slow = 50

        # Moving averages (tuned)
        ma_f = self._sma(close, ma_fast) if len(close) >= ma_fast else None
        ma_s = self._sma(close, ma_slow) if len(close) >= ma_slow else None
        ma_7 = self._sma(close, 7) if len(close) >= 7 else None
        ma200 = self._sma(close, 200) if len(close) >= 200 else None

        c_ma7, c_ma20 = ma_7[-1], ma_f[-1]
        p_ma7, p_ma20 = ma_7[-2], ma_f[-2]

        # الذهبي / الموت التقاطعات
        golden_cross = p_ma7 <= p_ma20 and c_ma7 > c_ma20
        death_cross = p_ma7 >= p_ma20 and c_ma7 < c_ma20

        # السعر بالنسبة للمتوسطات
        above_ma7 = price > ma_7[-1]
        above_ma20 = price > ma_f[-1]
        above_ma50 = price > ma_s[-1] if ma_s is not None else True
        above_ma200 = price > ma200[-1] if ma200 is not None else True

        trend_buy_score = sum([above_ma7, above_ma20, above_ma50, above_ma200])
        trend_sell_score = 4 - trend_buy_score

        # إشارة التقاطع الذهبي
        if golden_cross and price > ma_f[-1]:
            sl = min(ma_f[-1], ma_s[-1] if ma_s is not None else ma_f[-1]) * 0.98
            return Signal(
                name=self.name, signal="BUY", strength=0.85,
                entry=round(price, 8), stop_loss=round(sl, 8),
                targets=[round(price * x, 8) for x in [1.03, 1.06, 1.10]],
                confidence=85,
                reason=f"🌟 تقاطع ذهبي! MA7 صعد فوق MA{ma_fast}. السعر فوق جميع المتوسطات."
            )

        if death_cross and price < ma_f[-1]:
            sl = max(ma_f[-1], ma_s[-1] if ma_s is not None else ma_f[-1]) * 1.02
            return Signal(
                name=self.name, signal="SELL", strength=0.85,
                entry=round(price, 8), stop_loss=round(sl, 8),
                targets=[round(price * x, 8) for x in [0.97, 0.94, 0.90]],
                confidence=85,
                reason=f"💀 تقاطع موت! MA7 نزل تحت MA{ma_fast}. السعر تحت جميع المتوسطات."
            )

        # إشارات الاتجاه القوي
        if trend_buy_score >= 3:
            sl = ma_f[-1] * 0.98
            return Signal(
                name=self.name, signal="BUY", strength=0.7,
                entry=round(price, 8), stop_loss=round(sl, 8),
                targets=[round(price * x, 8) for x in [1.02, 1.04, 1.07]],
                confidence=70,
                reason=f"📈 اتجاه صاعد قوي — السعر فوق {trend_buy_score}/4 متوسطات."
            )

        if trend_sell_score >= 3:
            sl = ma_f[-1] * 1.02
            return Signal(
                name=self.name, signal="SELL", strength=0.7,
                entry=round(price, 8), stop_loss=round(sl, 8),
                targets=[round(price * x, 8) for x in [0.98, 0.96, 0.93]],
                confidence=70,
                reason=f"📉 اتجاه هابط قوي — السعر تحت {trend_sell_score}/4 متوسطات."
            )

        return Signal(
            name=self.name, signal="NEUTRAL", strength=0.4,
            entry=round(price, 8), confidence=40,
            reason=f"⚪ المتوسطات متشابكة — السعر يخترق بينها. سوق جانبي."
        )

    def _sma(self, prices, period):
        result = np.zeros_like(prices)
        for i in range(len(prices)):
            if i < period:
                result[i] = np.mean(prices[:i + 1])
            else:
                result[i] = np.mean(prices[i - period + 1:i + 1])
        return result
