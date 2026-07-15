"""
🏗️ Market Structure -- HH/HL, LH/LL, CHoCH, BOS
"""
import numpy as np
import pandas as pd
from .base import BaseStrategy, Signal


class MarketStructureStrategy(BaseStrategy):
    """
    تحليل هيكل السوق الكلاسيكي:
    - HH (Higher High) + HL (Higher Low) = Uptrend
    - LH (Lower High) + LL (Lower Low) = Downtrend
    - CHoCH (Change of Character) = انعكاس الاتجاه
    - BOS (Break of Structure) = استمرار الاتجاه
    - Internal structure breaks for entries
    """

    name = "Market Structure"

    def analyze(self, df) -> Signal:
        # Auto-tune disabled — using defaults
        lookback = 30
        price = float(df["close"].iloc[-1])
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values

        # استخراج القمم والقيعان
        highs_peaks = self._find_peaks(high, window=4)
        lows_valleys = self._find_valleys(low, window=4)

        if len(highs_peaks) < 3 or len(lows_valleys) < 3:
            return self._neutral(price, "Not enough structure points")

        # تحديد الاتجاه من آخر 4 نقاط
        trend = self._determine_trend(highs_peaks, lows_valleys)

        # كشف تغيير الشخصية (CHoCH)
        choch = self._detect_choch(highs_peaks, lows_valleys)

        # كشف كسر الهيكل (BOS)
        bos = self._detect_bos(highs_peaks, lows_valleys, price)

        # قوة الهيكل
        structure_strength = self._score_structure(highs_peaks, lows_valleys, trend)

        # بناء الإشارة
        bullish_signals = []
        bearish_signals = []

        if trend == "UP":
            bullish_signals.append(f"HH/HL structure intact")
            # CHoCH هابط في اتجاه صاعد = ضعف محتمل
            if choch == "DOWN":
                bearish_signals.append(f"CHoCH down detected -- trend weakening")
            if bos == "UP":
                bullish_signals.append(f"BOS up -- trend continuation ✓")
        elif trend == "DOWN":
            bearish_signals.append(f"LH/LL structure intact")
            if choch == "UP":
                bullish_signals.append(f"CHoCH up detected -- potential reversal")
            if bos == "DOWN":
                bearish_signals.append(f"BOS down -- bearish continuation ✓")
        else:
            # Range
            pass

        # إشارة تداول
        if trend == "UP" and len(bullish_signals) >= 1 and "weak" not in str(bearish_signals):
            sl = min(p["price"] for p in lows_valleys[-2:]) * 0.98 if lows_valleys else price * 0.95
            return Signal(
                name=self.name, signal="BUY", strength=0.8 if choch != "DOWN" else 0.5,
                entry=round(price, 8),
                stop_loss=round(float(sl), 8),
                targets=[round(price * x, 8) for x in [1.02, 1.04, 1.07]],
                confidence=min(90, int(structure_strength * 100)),
                reason=self._format_reason("UPTREND", bullish_signals, bearish_signals, structure_strength)
            )

        if trend == "DOWN" and len(bearish_signals) >= 1 and "weak" not in str(bullish_signals):
            sl = max(p["price"] for p in highs_peaks[-2:]) * 1.02 if highs_peaks else price * 1.05
            return Signal(
                name=self.name, signal="SELL", strength=0.8 if choch != "UP" else 0.5,
                entry=round(price, 8),
                stop_loss=round(float(sl), 8),
                targets=[round(price * x, 8) for x in [0.98, 0.96, 0.93]],
                confidence=min(90, int(structure_strength * 100)),
                reason=self._format_reason("DOWNTREND", bearish_signals, bullish_signals, structure_strength)
            )

        # CHoCH انعكاسي
        if choch == "UP" and len(highs_peaks) >= 4:
            sl = min(p["price"] for p in lows_valleys[-3:]) * 0.97
            return Signal(
                name=self.name, signal="BUY", strength=0.7,
                entry=round(price, 8),
                stop_loss=round(float(sl), 8),
                targets=[round(price * x, 8) for x in [1.03, 1.06, 1.10]],
                confidence=70,
                reason="🔄 CHoCH up -- trend reversal from downtrend to uptrend potential"
            )
        if choch == "DOWN" and len(lows_valleys) >= 4:
            sl = max(p["price"] for p in highs_peaks[-3:]) * 1.03
            return Signal(
                name=self.name, signal="SELL", strength=0.7,
                entry=round(price, 8),
                stop_loss=round(float(sl), 8),
                targets=[round(price * x, 8) for x in [0.97, 0.94, 0.90]],
                confidence=70,
                reason="🔄 CHoCH down -- trend reversal from uptrend to downtrend potential"
            )

        return self._neutral(price, f"Range structure -- {trend} with no clear entry")

    def _find_peaks(self, highs, window=4):
        peaks = []
        for i in range(window, len(highs) - window):
            if highs[i] == max(highs[i - window:i + window + 1]):
                peaks.append({"price": float(highs[i]), "i": i})
        return peaks[-10:]

    def _find_valleys(self, lows, window=4):
        valleys = []
        for i in range(window, len(lows) - window):
            if lows[i] == min(lows[i - window:i + window + 1]):
                valleys.append({"price": float(lows[i]), "i": i})
        return valleys[-10:]

    def _determine_trend(self, highs, lows):
        """تصنيف الاتجاه من آخر 3 قمم وقيعان"""
        if len(highs) < 3 or len(lows) < 3:
            return "RANGE"

        last_h = [p["price"] for p in highs[-3:]]
        last_l = [p["price"] for p in lows[-3:]]

        hh = all(last_h[i] >= last_h[i - 1] for i in range(1, len(last_h)))
        hl = all(last_l[i] >= last_l[i - 1] for i in range(1, len(last_l)))
        lh = all(last_h[i] <= last_h[i - 1] for i in range(1, len(last_h)))
        ll = all(last_l[i] <= last_l[i - 1] for i in range(1, len(last_l)))

        if hh and hl:
            return "UP"
        elif lh and ll:
            return "DOWN"
        elif hh and not hl:
            # HH with lower lows = volatile up
            return "UP"
        elif lh and not ll:
            return "DOWN"
        return "RANGE"

    def _detect_choch(self, highs, lows):
        """Change of Character -- انعكاس الاتجاه"""
        if len(highs) < 4 or len(lows) < 4:
            return None
        h3, h2, h1 = highs[-3]["price"], highs[-2]["price"], highs[-1]["price"]
        l3, l2, l1 = lows[-3]["price"], lows[-2]["price"], lows[-1]["price"]

        # من هابط إلى صاعد: قاع أعلى + قمة أعلى بعد قمة أقل
        if l2 < l1 and h2 < h1 and l1 > l3:
            return "UP"
        # من صاعد إلى هابط: قمة أقل + قاع أقل بعد قاع أعلى
        if h2 > h1 and l2 > l1 and h1 < h3:
            return "DOWN"
        return None

    def _detect_bos(self, highs, lows, price):
        """Break of Structure -- كسر الهيكل"""
        if len(highs) >= 2 and len(lows) >= 2:
            last_h = highs[-1]["price"]
            prev_h = highs[-2]["price"]
            last_l = lows[-1]["price"]
            prev_l = lows[-2]["price"]

            if price > prev_h and last_h > prev_h:
                return "UP"
            if price < prev_l and last_l < prev_l:
                return "DOWN"
        return None

    def _score_structure(self, highs, lows, trend):
        """تقييم قوة الهيكل 0-1"""
        if len(highs) < 3 or len(lows) < 3:
            return 0.3

        h_prices = [p["price"] for p in highs[-4:]]
        l_prices = [p["price"] for p in lows[-4:]]

        if trend == "UP":
            h_consistency = sum(1 for i in range(1, len(h_prices)) if h_prices[i] > h_prices[i - 1])
            l_consistency = sum(1 for i in range(1, len(l_prices)) if l_prices[i] > l_prices[i - 1])
        elif trend == "DOWN":
            h_consistency = sum(1 for i in range(1, len(h_prices)) if h_prices[i] < h_prices[i - 1])
            l_consistency = sum(1 for i in range(1, len(l_prices)) if l_prices[i] < l_prices[i - 1])
        else:
            return 0.4

        consistency = (h_consistency + l_consistency) / (max(len(h_prices) - 1, 1) + max(len(l_prices) - 1, 1))
        return min(0.95, 0.4 + consistency * 0.5)

    def _format_reason(self, trend_label, main_signals, opposing_signals, strength):
        main = "; ".join(main_signals[:2])
        opp = "; ".join(opposing_signals[:1])
        parts = [f"🏗️ {trend_label}"]
        if main:
            parts.append(f"✓ {main}")
        if opp:
            parts.append(f"⚠️ {opp}")
        parts.append(f"struct: {strength:.0%}")
        return " | ".join(parts)

    def _neutral(self, price, reason):
        return Signal(
            name=self.name, signal="NEUTRAL", strength=0.3,
            entry=round(price, 8), confidence=30,
            reason=f"⚪ {reason}."
        )
