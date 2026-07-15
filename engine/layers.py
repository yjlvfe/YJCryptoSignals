"""
🧠 Signal Layer Analysis — DISABLED (Phase 5.x purge)
Always returns neutral. Kept for import compatibility.
"""
import logging

logger = logging.getLogger("crypto-signal-layers")


def analyze_all_layers(symbol: str, df_4h, df_1d=None) -> dict:
    """Disabled — all layers neutral, no agreement."""
    return {
        "layers": {},
        "agreement": "0/0",
        "total_layers": 0,
        "overall_signal": "NEUTRAL",
        "strength": 0.0,
        "reason": "🧠 Layers DISABLED — pass-through",
    }
