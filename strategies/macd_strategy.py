"""
📉 MACD — مؤشر التقارب والتباعد
"""
import numpy as np
from .base import BaseStrategy, Signal


class MACDStrategy(BaseStrategy):
    name = "MACD"

    def analyze(self, df) -> Signal:
        price = df["close"].iloc[-1]
        close = df["close"].values

        # MACD params — auto_tune disabled, using defaults
        macd_fast = 12
        macd_slow = 26
        macd_signal_period = 9
        
        macd_line, signal_line, histogram = self._compute_macd(close, macd_fast, macd_slow, macd_signal_period)

        current_macd = macd_line[-1]
        current_signal = signal_line[-1]
        current_hist = histogram[-1]
        prev_hist = histogram[-2] if len(histogram) > 1 else 0

        # التقاطع
        macd_cross_up = macd_line[-2] <= signal_line[-2] and macd_line[-1] > signal_line[-1]
        macd_cross_down = macd_line[-2] >= signal_line[-2] and macd_line[-1] < signal_line[-1]

        # الهيستوجرام يتزايد/يتناقص
        hist_increasing = current_hist > prev_hist
        hist_zero_cross_up = prev_hist <= 0 < current_hist
        hist_zero_cross_down = prev_hist >= 0 > current_hist

        # ═══════════════════════════════════
        # BUY SIGNALS
        # ═══════════════════════════════════
        if macd_cross_up and current_macd < 0 and hist_increasing:
            # تقاطع تحت الصفر → شراء قوي
            sl = price * 0.95
            return Signal(
                name=self.name, signal="BUY", strength=0.9,
                entry=round(price, 8), stop_loss=round(sl, 8),
                targets=[round(price * x, 8) for x in [1.04, 1.07, 1.12]],
                confidence=90,
                reason=f"🚀 MACD تقاطع صعودي تحت الصفر! إشارة شراء قوية."
            )

        if macd_cross_up and current_macd > 0:
            sl = price * 0.96
            return Signal(
                name=self.name, signal="BUY", strength=0.75,
                entry=round(price, 8), stop_loss=round(sl, 8),
                targets=[round(price * x, 8) for x in [1.03, 1.05, 1.08]],
                confidence=75,
                reason=f"🟢 MACD تقاطع صعودي فوق الصفر — استمرار صعود."
            )

        if hist_zero_cross_up:
            sl = price * 0.96
            return Signal(
                name=self.name, signal="BUY", strength=0.6,
                entry=round(price, 8), stop_loss=round(sl, 8),
                targets=[round(price * x, 8) for x in [1.02, 1.04, 1.06]],
                confidence=60,
                reason=f"🟢 هيستوجرام MACD عبر فوق الصفر — بداية زخم صاعد."
            )

        # ═══════════════════════════════════
        # SELL SIGNALS
        # ═══════════════════════════════════
        if macd_cross_down and current_macd > 0 and not hist_increasing:
            sl = price * 1.05
            return Signal(
                name=self.name, signal="SELL", strength=0.9,
                entry=round(price, 8), stop_loss=round(sl, 8),
                targets=[round(price * x, 8) for x in [0.96, 0.93, 0.88]],
                confidence=90,
                reason=f"🔻 MACD تقاطع هابط فوق الصفر! إشارة بيع قوية."
            )

        if macd_cross_down and current_macd < 0:
            sl = price * 1.04
            return Signal(
                name=self.name, signal="SELL", strength=0.75,
                entry=round(price, 8), stop_loss=round(sl, 8),
                targets=[round(price * x, 8) for x in [0.97, 0.95, 0.92]],
                confidence=75,
                reason=f"🔴 MACD تقاطع هابط تحت الصفر — استمرار هبوط."
            )

        if hist_zero_cross_down:
            sl = price * 1.04
            return Signal(
                name=self.name, signal="SELL", strength=0.6,
                entry=round(price, 8), stop_loss=round(sl, 8),
                targets=[round(price * x, 8) for x in [0.98, 0.96, 0.94]],
                confidence=60,
                reason=f"🔴 هيستوجرام MACD عبر تحت الصفر — بداية زخم هابط."
            )

        # ═══════════════════════════════════
        # NEUTRAL
        # ═══════════════════════════════════
        direction = "صاعد" if current_macd > current_signal else "هابط"
        return Signal(
            name=self.name, signal="NEUTRAL", strength=0.3,
            entry=round(price, 8), confidence=30,
            reason=f"⚪ MACD في منطقة محايدة. الزخم {direction}. لا إشارة واضحة."
        )

    def _compute_macd(self, prices, fast=12, slow=26, signal=9):
        """حساب MACD يدوي (بدون مكتبات إضافية)"""
        exp1 = self._ema(prices, fast)
        exp2 = self._ema(prices, slow)
        macd_line = exp1 - exp2
        signal_line = self._ema(macd_line, signal)
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def _ema(self, prices, period):
        result = np.zeros_like(prices)
        multiplier = 2 / (period + 1)
        result[:period] = np.mean(prices[:period])
        for i in range(period, len(prices)):
            result[i] = (prices[i] - result[i - 1]) * multiplier + result[i - 1]
        return result
