"""
👑 Kronos Confluence Score — DISABLED (Phase 5.x purge)
Always returns score=50, verdict=WATCH, boost=0.
Never blocks or boosts any signal. Neutral pass-through.
"""
import logging

logger = logging.getLogger("crypto-signal-kronos")


def compute_kronos(
    ta_signal: str = "NEUTRAL",
    ta_strength: float = 0,
    layers_data: dict = None,
    sentiment_data: dict = None,
    regime_data: dict = None,
) -> dict:
    """Disabled — always returns neutral WATCH verdict."""
    return {
        "score": 50.0,
        "direction": "NEUTRAL",
        "verdict": "WATCH",
        "confidence_boost": 0,
        "breakdown": {},
        "reason": "👑 Kronos DISABLED — pass-through",
        "thresholds": {"gate": 0, "strong": 999, "rationale": "disabled"},
    }


def get_kronos_verdict(kronos_result: dict) -> str:
    """Disabled — always MODERATE."""
    return "👑 Kronos DISABLED — MODERATE confluence (pass-through)"
