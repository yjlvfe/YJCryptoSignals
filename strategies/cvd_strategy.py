"""
📊 CVD Strategy — Cumulative Volume Delta Signals
Uses advanced volume analysis (CVD + Volume Profile) for divergence signals.
"""
import numpy as np
import pandas as pd
from .base import BaseStrategy, Signal
from engine.volume_advanced import compute_cvd, analyze_cvd_signal, compute_volume_profile


class CVDStrategy(BaseStrategy):
    name = "Volume Analysis"

    def analyze(self, df: pd.DataFrame) -> Signal:
        # Auto-tune disabled — using defaults
        cvd_lb = 20
        price = df["close"].iloc[-1]
        close = df["close"].values

        try:
            # ① CVD analysis
            cvd = compute_cvd(df)
            cvd_result = analyze_cvd_signal(cvd, close)

            # ② Volume Profile
            try:
                vp = compute_volume_profile(df)
                poc = vp.get("poc", price)
                va_high = vp.get("value_area_high", price)
                va_low = vp.get("value_area_low", price)
            except Exception as e:
                logger.debug(f"CVD compute skipped: {e}")

            # ③ Volume trend (simple)
            volume = df["volume"].values
            avg_vol_short = np.mean(volume[-10:]) if len(volume) >= 10 else 0
            avg_vol_long = np.mean(volume[-50:]) if len(volume) >= 50 else 0
            vol_ratio = avg_vol_short / avg_vol_long if avg_vol_long > 0 else 1.0

            # ─── Build signal ───
            signal = cvd_result.get("signal", "NEUTRAL")
            strength = cvd_result.get("strength", 0.2)
            reason = cvd_result.get("reason", "")

            # Enhance with volume trend
            if vol_ratio > 1.5:
                strength = min(1.0, strength + 0.15)
                reason += " | High volume"
            elif vol_ratio < 0.5:
                strength = max(0.1, strength - 0.1)
                reason += " | Low volume"

            # POC proximity
            if price > 0:
                poc_dist = (price - poc) / price * 100
                if abs(poc_dist) < 1.0:
                    reason += f" | Near POC (${poc:.2f})"

            # Volume Profile context
            if signal == "BUY" and price < poc:
                strength = min(1.0, strength + 0.1)
                reason += " | Price below POC (bullish)"
            elif signal == "SELL" and price > poc:
                strength = min(1.0, strength + 0.1)
                reason += " | Price above POC (bearish)"

            # Determine targets/stop based on volume context
            if signal == "BUY":
                entry = price
                stop = va_low if va_low < price * 0.98 else price * 0.97
                targets = [poc, va_high, price * 1.05]
            elif signal == "SELL":
                entry = price
                stop = va_high if va_high > price * 1.02 else price * 1.03
                targets = [poc, va_low, price * 0.95]
            else:
                entry = price
                stop = None
                targets = []

            confidence = int(strength * 100)

            return Signal(
                name=self.name,
                signal=signal,
                strength=strength,
                entry=entry,
                stop_loss=stop,
                targets=targets,
                confidence=confidence,
                reason=reason
            )

        except Exception as e:
            return Signal(
                name=self.name,
                signal="NEUTRAL",
                strength=0.1,
                entry=price,
                confidence=0,
                reason=f"CVD error: {str(e)[:50]}"
            )
