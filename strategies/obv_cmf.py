"""
📊 OBV + CMF — On-Balance Volume + Chaikin Money Flow
Volume-based momentum indicators
"""
import numpy as np
from .base import BaseStrategy, Signal

class OBVCMFStrategy(BaseStrategy):
    name = "OBV + CMF"

    def analyze(self, df) -> Signal:
        price = float(df["close"].iloc[-1])
        close = df["close"].values
        high = df["high"].values
        low = df["low"].values
        volume = df["volume"].values

        # ─── OBV (On-Balance Volume) ───
        obv = np.zeros(len(close))
        for i in range(1, len(close)):
            if close[i] > close[i-1]:
                obv[i] = obv[i-1] + volume[i]
            elif close[i] < close[i-1]:
                obv[i] = obv[i-1] - volume[i]
            else:
                obv[i] = obv[i-1]

        # OBV trend
        obv_slope = obv[-1] - obv[-20] if len(obv) >= 20 else 0
        obv_signal = "BULLISH" if obv_slope > 0 else "BEARISH"

        # ─── CMF (Chaikin Money Flow) ───
        cmf_period = 20
        mf_multiplier = np.zeros(len(close))
        mf_volume = np.zeros(len(close))
        for i in range(len(close)):
            if high[i] > low[i]:
                mf_multiplier[i] = ((close[i] - low[i]) - (high[i] - close[i])) / (high[i] - low[i])
            mf_volume[i] = mf_multiplier[i] * volume[i]

        cmf = np.zeros(len(close))
        for i in range(cmf_period, len(close)):
            cmf[i] = np.sum(mf_volume[i-cmf_period:i]) / max(np.sum(volume[i-cmf_period:i]), 1)

        current_cmf = cmf[-1]

        # ─── Combined Signal ───
        buy_score = 0
        sell_score = 0

        # OBV divergence: price down, OBV flat/up = accumulation
        price_20_ago = close[-20] if len(close) >= 20 else close[0]
        price_down = price < price_20_ago * 0.97
        if price_down and obv_signal == "BULLISH":
            buy_score += 2
            reason = "OBV bullish divergence (accumulation)"

        # CMF signals
        if current_cmf > 0.05:
            buy_score += 2
            reason = reason + " | CMF positive" if 'reason' in dir() else "CMF positive"
        elif current_cmf < -0.05:
            sell_score += 2
            reason = "CMF negative (distribution)"

        if buy_score > sell_score:
            sl = price * 0.96
            return Signal(name=self.name, signal="BUY", strength=0.75,
                          entry=round(price,8), stop_loss=round(sl,8),
                          targets=[round(price*x,8) for x in [1.03,1.05,1.08]],
                          confidence=min(90, buy_score*25),
                          reason=f"📊 {reason}")
        elif sell_score > buy_score:
            sl = price * 1.04
            return Signal(name=self.name, signal="SELL", strength=0.7,
                          entry=round(price,8), stop_loss=round(sl,8),
                          targets=[round(price*x,8) for x in [0.97,0.95,0.92]],
                          confidence=min(90, sell_score*25),
                          reason=f"📊 {reason}")

        return Signal(name=self.name, signal="NEUTRAL", strength=0.3,
                      entry=round(price,8), confidence=20,
                      reason=f"⚪ OBV {obv_signal} | CMF={current_cmf:.3f}")
