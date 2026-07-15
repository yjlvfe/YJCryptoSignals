"""
🔄 Divergence Analyzer — RSI, MACD, OBV Divergence Detection
"""
import numpy as np
import pandas as pd
from .base import BaseStrategy, Signal


class DivergenceStrategy(BaseStrategy):
    """
    كشف التباعد (Divergence) بين السعر والمؤشرات:
    - RSI Regular Divergence (bullish/bearish)
    - RSI Hidden Divergence (trend continuation)
    - MACD Divergence
    - OBV Divergence
    - Multiple confirmation scoring
    """

    name = "Divergence"

    def analyze(self, df: pd.DataFrame) -> Signal:
        # Auto-tune disabled — using defaults
        lookback = 25
        price = float(df["close"].iloc[-1])
        close = df["close"].values
        high = df["high"].values
        low = df["low"].values
        volume = df["volume"].values

        if len(close) < 40:
            return self._neutral(price, "Not enough data (need 40+)")

        rsi = self._compute_rsi(close, 14)
        macd_line = self._compute_macd(close)
        obv = self._compute_obv(close, volume)

        # Collect all divergences
        divergences = []

        # RSI Regular
        if self._bullish_div(close[-20:], rsi[-20:]):
            divergences.append(("RSI", "BULLISH", 0.85))
        if self._bearish_div(close[-20:], rsi[-20:]):
            divergences.append(("RSI", "BEARISH", 0.85))

        # RSI Hidden
        if self._hidden_bullish_div(close[-20:], rsi[-20:]):
            divergences.append(("RSI hidden", "BULLISH", 0.7))
        if self._hidden_bearish_div(close[-20:], rsi[-20:]):
            divergences.append(("RSI hidden", "BEARISH", 0.7))

        # MACD Divergence
        if self._bullish_div(close[-30:], macd_line[-30:]):
            divergences.append(("MACD", "BULLISH", 0.8))
        if self._bearish_div(close[-30:], macd_line[-30:]):
            divergences.append(("MACD", "BEARISH", 0.8))

        # OBV Divergence
        obv_last = obv[-30:]
        if self._bullish_div(close[-30:], obv_last):
            divergences.append(("OBV", "BULLISH", 0.75))
        if self._bearish_div(close[-30:], obv_last):
            divergences.append(("OBV", "BEARISH", 0.75))

        # Count by type
        bullish_d = [d for d in divergences if d[1] == "BULLISH"]
        bearish_d = [d for d in divergences if d[1] == "BEARISH"]
        total_bullish = len(bullish_d)
        total_bearish = len(bearish_d)

        # Score strength
        if total_bullish >= 2:
            # Multiple confirmation
            avg_strength = sum(d[2] for d in bullish_d) / len(bullish_d)
            conf = min(95, 60 + total_bullish * 10)
            signals = [d[0] for d in bullish_d]
            return Signal(
                name=self.name, signal="BUY", strength=avg_strength,
                entry=round(price, 8), stop_loss=round(price * 0.95, 8),
                targets=[round(price * x, 8) for x in [1.03, 1.06, 1.10]],
                confidence=conf,
                reason=f"🔄 Bullish divergence on {', '.join(signals)} — reversal expected ↑"
            )

        if total_bearish >= 2:
            avg_strength = sum(d[2] for d in bearish_d) / len(bearish_d)
            conf = min(95, 60 + total_bearish * 10)
            signals = [d[0] for d in bearish_d]
            return Signal(
                name=self.name, signal="SELL", strength=avg_strength,
                entry=round(price, 8), stop_loss=round(price * 1.05, 8),
                targets=[round(price * x, 8) for x in [0.97, 0.94, 0.90]],
                confidence=conf,
                reason=f"🔄 Bearish divergence on {', '.join(signals)} — correction expected ↓"
            )

        if total_bullish == 1:
            return Signal(
                name=self.name, signal="BUY", strength=0.6,
                entry=round(price, 8), stop_loss=round(price * 0.96, 8),
                targets=[round(price * x, 8) for x in [1.02, 1.04, 1.07]],
                confidence=60,
                reason=f"🔄 Single bullish divergence ({bullish_d[0][0]}) — weak signal"
            )

        if total_bearish == 1:
            return Signal(
                name=self.name, signal="SELL", strength=0.6,
                entry=round(price, 8), stop_loss=round(price * 1.04, 8),
                targets=[round(price * x, 8) for x in [0.98, 0.96, 0.93]],
                confidence=60,
                reason=f"🔄 Single bearish divergence ({bearish_d[0][0]}) — weak signal"
            )

        return self._neutral(price, "No divergence detected")

    def _bullish_div(self, price, indicator):
        """Regular bullish: lower low in price, higher low in indicator"""
        if len(price) < 10 or len(indicator) < 10:
            return False
        # Find the two most recent lows in price
        p1, p2 = np.min(price[-10:-5]), np.min(price[-5:])
        i1, i2 = np.min(indicator[-10:-5]), np.min(indicator[-5:])
        return p2 < p1 and i2 > i1

    def _bearish_div(self, price, indicator):
        """Regular bearish: higher high in price, lower high in indicator"""
        if len(price) < 10 or len(indicator) < 10:
            return False
        p1, p2 = np.max(price[-10:-5]), np.max(price[-5:])
        i1, i2 = np.max(indicator[-10:-5]), np.max(indicator[-5:])
        return p2 > p1 and i2 < i1

    def _hidden_bullish_div(self, price, indicator):
        """Hidden bullish: higher low in price, lower low in indicator (trend continuation)"""
        if len(price) < 10 or len(indicator) < 10:
            return False
        p1, p2 = np.min(price[-10:-5]), np.min(price[-5:])
        i1, i2 = np.min(indicator[-10:-5]), np.min(indicator[-5:])
        return p2 > p1 and i2 < i1

    def _hidden_bearish_div(self, price, indicator):
        """Hidden bearish: lower high in price, higher high in indicator"""
        if len(price) < 10 or len(indicator) < 10:
            return False
        p1, p2 = np.max(price[-10:-5]), np.max(price[-5:])
        i1, i2 = np.max(indicator[-10:-5]), np.max(indicator[-5:])
        return p2 < p1 and i2 > i1

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

    def _compute_macd(self, prices, fast=12, slow=26):
        exp1 = self._ema(prices, fast)
        exp2 = self._ema(prices, slow)
        return exp1 - exp2

    def _ema(self, prices, period):
        result = np.zeros_like(prices)
        mult = 2 / (period + 1)
        result[:period] = np.mean(prices[:period])
        for i in range(period, len(prices)):
            result[i] = (prices[i] - result[i - 1]) * mult + result[i - 1]
        return result

    def _compute_obv(self, close, volume):
        obv = np.zeros_like(volume)
        obv[0] = volume[0]
        for i in range(1, len(close)):
            if close[i] > close[i - 1]:
                obv[i] = obv[i - 1] + volume[i]
            elif close[i] < close[i - 1]:
                obv[i] = obv[i - 1] - volume[i]
            else:
                obv[i] = obv[i - 1]
        return obv

    def _neutral(self, price, reason):
        return Signal(
            name=self.name, signal="NEUTRAL", strength=0.3,
            entry=round(price, 8), confidence=30,
            reason=f"⚪ {reason}."
        )
