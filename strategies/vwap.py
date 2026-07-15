"""
📏 VWAP — Volume-Weighted Average Price
Daily VWAP with standard deviation bands
"""
import numpy as np
from .base import BaseStrategy, Signal

class VWAPStrategy(BaseStrategy):
    name = "VWAP"

    def analyze(self, df) -> Signal:
        price = float(df["close"].iloc[-1])
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        volume = df["volume"].values

        lookback = min(24, len(close))  # ~1 day of 1h candles

        typical_price = (high[-lookback:] + low[-lookback:] + close[-lookback:]) / 3
        vol = volume[-lookback:]

        vwap_val = np.sum(typical_price * vol) / max(np.sum(vol), 1)

        # Standard deviation bands
        variance = np.sum(vol * (typical_price - vwap_val) ** 2) / max(np.sum(vol), 1)
        std = np.sqrt(variance) if variance > 0 else vwap_val * 0.01

        # Signal
        if price < vwap_val - std:
            # Price below -1σ → potential bounce
            sl = vwap_val - 2 * std
            return Signal(name=self.name, signal="BUY", strength=0.7,
                          entry=round(price,8), stop_loss=round(sl,8),
                          targets=[round(vwap_val,8), round(vwap_val+std,8), round(vwap_val+2*std,8)],
                          confidence=65,
                          reason=f"📏 VWAP: price below -1σ (${vwap_val:.2f}) — mean reversion")
        elif price > vwap_val + std:
            sl = vwap_val + 2 * std
            return Signal(name=self.name, signal="SELL", strength=0.6,
                          entry=round(price,8), stop_loss=round(sl,8),
                          targets=[round(vwap_val,8), round(vwap_val-std,8), round(vwap_val-2*std,8)],
                          confidence=60,
                          reason=f"📏 VWAP: price above +1σ — overextended")

        return Signal(name=self.name, signal="NEUTRAL", strength=0.3,
                      entry=round(price,8), confidence=25,
                      reason=f"⚪ VWAP: price near VWAP (${vwap_val:.2f})")
