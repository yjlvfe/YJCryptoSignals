"""
🎯 استراتيجيات التحليل — Base + كل المدارس
"""
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd


@dataclass
class Signal:
    """نتيجة تحليل مدرسة واحدة"""
    name: str
    signal: str  # BUY / SELL / NEUTRAL
    strength: float  # 0.0 → 1.0
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    targets: list = field(default_factory=list)  # [t1, t2, t3]
    reason: str = ""
    confidence: float = 0.0  # 0-100


class BaseStrategy:
    """Base class for all analysis strategies"""
    name = "base"

    def analyze(self, df: pd.DataFrame) -> Signal:
        raise NotImplementedError

    def detect_trend(self, df: pd.DataFrame) -> str:
        """اتجاه السوق العام"""
        ma20 = df["close"].rolling(20).mean().iloc[-1]
        ma50 = df["close"].rolling(50).mean().iloc[-1] if len(df) >= 50 else ma20
        current = df["close"].iloc[-1]
        prev = df["close"].iloc[-2] if len(df) > 1 else current

        if current > ma20 and current > ma50 and current > prev:
            return "UP"
        elif current < ma20 and current < ma50 and current < prev:
            return "DOWN"
        return "SIDEWAYS"

    def get_pivot_points(self, df: pd.DataFrame, window: int = 5) -> tuple:
        """حساب نقاط القمة والقاع المحلية"""
        highs = df["high"].values
        lows = df["low"].values

        pivot_highs = []
        pivot_lows = []

        for i in range(window, len(df) - window):
            if all(highs[i] >= highs[i - j] and highs[i] >= highs[i + j] for j in range(1, window + 1)):
                pivot_highs.append((i, highs[i]))
            if all(lows[i] <= lows[i - j] and lows[i] <= lows[i + j] for j in range(1, window + 1)):
                pivot_lows.append((i, lows[i]))

        support = np.median([p[1] for p in pivot_lows[-5:]]) if pivot_lows else df["low"].min()
        resistance = np.median([p[1] for p in pivot_highs[-5:]]) if pivot_highs else df["high"].max()

        return support, resistance
