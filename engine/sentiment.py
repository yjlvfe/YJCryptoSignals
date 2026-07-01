"""
🔮 Sentiment Layer — Fear & Greed Index + Long/Short Ratio
يوفر طبقة معنويات السوق لأخذها في الاعتبار عند التحليل
"""
import time
import json
import logging
import requests
from pathlib import Path

logger = logging.getLogger("crypto-signal-sentiment")

SENTIMENT_CACHE = Path("/root/.crypto-signal-bot/sentiment_cache.json")
CACHE_TTL = 3600  # ساعة واحدة


def _load_cache() -> dict:
    try:
        if SENTIMENT_CACHE.exists():
            return json.loads(SENTIMENT_CACHE.read_text())
    except Exception as e:
        logger.debug(f"Sentiment cache load failed: {e}")
    return {}


def _save_cache(data: dict):
    try:
        SENTIMENT_CACHE.parent.mkdir(parents=True, exist_ok=True)
        SENTIMENT_CACHE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.debug(f"Cache save failure: {e}")
        pass  # cache save failure non-fatal


def fetch_fear_greed() -> dict:
    """
    جلب Fear & Greed Index من Alternative.me API.
    Returns: {value: 0-100, classification: str, signal: BULLISH/BEARISH/NEUTRAL}
    """
    try:
        cache = _load_cache()
        now = time.time()
        if "fear_greed" in cache and (now - cache["fear_greed"].get("ts", 0)) < CACHE_TTL:
            return cache["fear_greed"]

        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                value = int(data[0].get("value", 50))
                classification = data[0].get("value_classification", "Neutral")

                # Signal mapping
                if value <= 25:  # Extreme Fear → contrarian BUY
                    signal = "BULLISH"
                    strength = min(1.0, (25 - value) / 25)
                elif value >= 75:  # Extreme Greed → contrarian SELL
                    signal = "BEARISH"
                    strength = min(1.0, (value - 75) / 25)
                elif value <= 40:
                    signal = "BULLISH"
                    strength = 0.4
                elif value >= 60:
                    signal = "BEARISH"
                    strength = 0.4
                else:
                    signal = "NEUTRAL"
                    strength = 0.2

                result = {
                    "value": value,
                    "classification": classification,
                    "signal": signal,
                    "strength": round(strength, 2),
                    "ts": time.time(),
                }
                cache["fear_greed"] = result
                _save_cache(cache)
                return result
    except Exception as e:
        logger.warning(f"Fear & Greed fetch failed: {e}")

    return {"value": 50, "classification": "Neutral", "signal": "NEUTRAL", "strength": 0, "ts": time.time()}


def fetch_long_short_ratio(symbol: str = "BTCUSDT") -> dict:
    """
    جلب Long/Short Ratio من MEXC futures API.
    Returns: {long_pct, short_pct, ratio, signal}
    """
    try:
        cache = _load_cache()
        cache_key = f"ls_{symbol}"
        now = time.time()
        if cache_key in cache and (now - cache[cache_key].get("ts", 0)) < CACHE_TTL:
            return cache[cache_key]

        sym = symbol.replace("USDT", "_USDT")
        r = requests.get(
            f"https://contract.mexc.com/api/v1/contract/long_short_ratio/{sym}"
            "?interval=1h&limit=1", timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("success"):
                items = data.get("data", {}).get("list", [])
                if items:
                    long_pct = float(items[0].get("longAccount", 50))
                    short_pct = float(items[0].get("shortAccount", 50))
                else:
                    long_pct = short_pct = 50

                # Signal: if longs dominate → caution (crowded trade)
                if long_pct > 65:
                    signal = "BEARISH"
                    strength = min(1.0, (long_pct - 50) / 50)
                elif long_pct < 35:
                    signal = "BULLISH"
                    strength = min(1.0, (50 - long_pct) / 50)
                else:
                    signal = "NEUTRAL"
                    strength = 0.2

                result = {
                    "long_pct": round(long_pct, 1),
                    "short_pct": round(short_pct, 1),
                    "ratio": round(long_pct / max(short_pct, 1), 2),
                    "signal": signal,
                    "strength": round(strength, 2),
                    "ts": time.time(),
                }
                cache[cache_key] = result
                _save_cache(cache)
                return result
    except Exception as e:
        logger.warning(f"Long/Short ratio fetch failed: {e}")

    return {"long_pct": 50, "short_pct": 50, "ratio": 1.0, "signal": "NEUTRAL", "strength": 0, "ts": time.time()}


def analyze_sentiment() -> dict:
    """
    تحليل معنويات السوق — يجمع Fear & Greed + Long/Short Ratio.
    Returns: {overall_signal, strength, confidence_boost, reason}
    """
    fg = fetch_fear_greed()
    ls = fetch_long_short_ratio()

    buy_votes = 0
    sell_votes = 0
    total_strength = 0

    if fg["signal"] == "BULLISH":
        buy_votes += 1
        total_strength += fg["strength"]
    elif fg["signal"] == "BEARISH":
        sell_votes += 1
        total_strength += fg["strength"]

    if ls["signal"] == "BULLISH":
        buy_votes += 1
        total_strength += ls["strength"]
    elif ls["signal"] == "BEARISH":
        sell_votes += 1
        total_strength += ls["strength"]

    if buy_votes > sell_votes:
        overall = "BULLISH"
    elif sell_votes > buy_votes:
        overall = "BEARISH"
    else:
        overall = "NEUTRAL"

    agreement = max(buy_votes, sell_votes)
    boost = agreement * 8  # 8% لكل إشارة متفقة (أقوى من طبقات السوق)

    reason_parts = []
    if fg["signal"] != "NEUTRAL":
        reason_parts.append(f"F&G={fg['value']}({fg['classification']})")
    if ls["signal"] != "NEUTRAL":
        reason_parts.append(f"L/S={ls['long_pct']:.0f}/{ls['short_pct']:.0f}")
    reason = " | ".join(reason_parts) if reason_parts else "Sentiment neutral"

    return {
        "overall_signal": overall,
        "strength": round(total_strength / max(agreement, 1), 2),
        "agreement": f"{agreement}/2",
        "confidence_boost": boost,
        "fear_greed": fg,
        "long_short": ls,
        "reason": f"🧿 {agreement}/2 sentiment agree → {overall}: {reason}",
    }
