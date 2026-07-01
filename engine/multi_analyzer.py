"""
🧠 CryptoSignal Multi-Timeframe Analyzer — تحليل متعدد الفريمات
يشغل تحليل ثقيل خلف الكواليس ويعطي نتيجة مبسطة
"""
import time
import logging

logger = logging.getLogger("crypto-signal-mtf")

# Primary timeframes for multi-analysis
TIMEFRAMES = ["1h", "4h", "1d"]
TF_LABELS = {"1h": "1h", "4h": "4h", "1d": "1d"}
TF_LIMITS = {"1h": 200, "4h": 200, "1d": 150}


def analyze_mtf(symbol: str, analyzer=None) -> dict:
    """
    تحليل عملة على كل الفريمات.
    returns: {
        "symbol": str,
        "timeframes": {"1h": {...}, "4h": {...}, "1d": {...}},
        "alignment": int,  # كم فريم متوافق مع BUY
        "total": 3,
        "primary_tf": "4h",  # الفريم الأساسي
    }
    """
    from engine.analyzer import Analyzer
    from data.fetcher import fetch_klines

    if analyzer is None:
        analyzer = Analyzer()

    results = {}
    buy_count = 0
    sell_count = 0
    neutral_count = 0

    for tf in TIMEFRAMES:
        try:
            limit = TF_LIMITS.get(tf, 200)
            df = fetch_klines(symbol, tf, limit)
            if df is None or len(df) < 50:
                logger.warning(f"Insufficient data for {symbol} on {tf}")
                results[tf] = {"direction": "NEUTRAL", "confidence": 0, "strength": 0, "price": 0, "error": "no data"}
                neutral_count += 1
                continue

            result = analyzer.analyze(symbol, {tf: df}, tf)
            a = result.aggregated
            sr = getattr(result, "sr", {})
            results[tf] = {
                "direction": a["direction"],
                "confidence": a["confidence"],
                "strength": a["strength"],
                "price": result.price,
                "entry": a["entry"],
                "targets": a["targets"],
                "stop_loss": a["stop_loss"],
                "buy_count": a["buy_count"],
                "sell_count": a["sell_count"],
                "supports": sr.get("supports", []),
                "resistances": sr.get("resistances", []),
            }

            if a["direction"] == "BUY":
                buy_count += 1
            elif a["direction"] == "SELL":
                sell_count += 1
            else:
                neutral_count += 1

            time.sleep(0.3)  # تجنب rate limit

        except Exception as e:
            logger.warning(f"[SKIP] MTF for {symbol} on {tf}: {str(e)[:80]}")
            results[tf] = {"direction": "NEUTRAL", "confidence": 0, "strength": 0, "price": 0, "error": str(e)[:50]}
            neutral_count += 1

    # التوافق: الفريمات الي تقول BUY
    alignment = buy_count
    total = len(TIMEFRAMES)

    # الاتجاه العام حسب القوة
    if buy_count >= 2:
        overall = "BUY"
    elif sell_count >= 2:
        overall = "SELL"
    else:
        overall = "NEUTRAL"

    return {
        "symbol": symbol,
        "timeframes": results,
        "alignment": alignment,
        "total": total,
        "overall": overall,
        "primary_tf": "4h",
    }


def build_mtf_alignment_line(mtf_data: dict) -> str:
    """Build multi-timeframe alignment line in English"""
    if not mtf_data:
        return ""

    alignment = mtf_data.get("alignment", 0)
    total = mtf_data.get("total", 3)
    tfs = mtf_data.get("timeframes", {})

    # Icon based on alignment
    if alignment == total:
        icon = "🔥🔥🔥"
        status = f"Full — {alignment}/{total} TF"
    elif alignment >= 2:
        icon = "🔥"
        status = f"Strong — {alignment}/{total} TF"
    elif alignment >= 1:
        icon = "⚡"
        status = f"Weak — {alignment}/{total} TF"
    else:
        icon = "⚠️"
        status = f"None — {alignment}/{total} TF"

    # TF details
    tf_details = []
    for tf in TIMEFRAMES:
        data = tfs.get(tf, {})
        direction = data.get("direction", "NEUTRAL")
        conf = data.get("confidence", 0)
        if direction == "BUY":
            emoji = "🟢"
        elif direction == "SELL":
            emoji = "🔴"
        else:
            emoji = "⚪"
        tf_details.append(f"{tf}: {emoji} {direction} ({conf:.0f}%)")

    lines = [f"{icon} {status}"]
    lines.append(" | ".join(tf_details))
    return "\n".join(lines)


def scan_strength_matrix(symbols: list, max_coins: int = 30) -> list:
    """
    مسح شامل متعدد الفريمات لقائمة عملات.
    returns: [
        {"symbol": ..., "alignment": 3, "overall": "BUY", "avg_strength": ..., "timeframes": {...}},
        ...
    ]
    مرتبة حسب الأقوى.
    """
    from engine.analyzer import Analyzer
    analyzer = Analyzer()
    results = []

    logger.info(f"🔬 Scanning strength matrix for {min(max_coins, len(symbols))} coins...")

    for i, symbol in enumerate(symbols[:max_coins]):
        try:
            mtf = analyze_mtf(symbol, analyzer)

            # متوسط القوة عبر الفريمات
            strengths = [tf.get("strength", 0) for tf in mtf["timeframes"].values()]
            avg_strength = sum(strengths) / max(len(strengths), 1)

            results.append({
                "symbol": symbol,
                "alignment": mtf["alignment"],
                "total": mtf["total"],
                "overall": mtf["overall"],
                "avg_strength": round(avg_strength, 1),
                "timeframes": mtf["timeframes"],
            })

            logger.info(f"  [{i+1}/{min(max_coins, len(symbols))}] {symbol}: {mtf['alignment']}/{mtf['total']} → {mtf['overall']}")

        except Exception as e:
            logger.warning(f"[SKIP] Matrix scan for {symbol}: {str(e)[:80]}")
            continue

    # ترتيب: الأكثر توافقاً × القوة
    results.sort(key=lambda r: (r["alignment"], r["avg_strength"]), reverse=True)
    return results


def format_strength_matrix(matrix_results: list) -> str:
    """Format strength matrix — English, clean for Telegram"""
    if not matrix_results:
        return "⚠️ No results available."

    msg = ["━━━ 📊 **STRENGTH MATRIX** ━━━", ""]

    # Tier 1: Full alignment (3/3)
    tier1 = [r for r in matrix_results if r["alignment"] == 3 and r["overall"] == "BUY"]
    if tier1:
        msg.append("🔥 **Tier 1 — Full (3/3):**")
        for i, r in enumerate(tier1[:5]):
            sym = r["symbol"].replace("USDT", "")
            tf_detail = " | ".join([
                f"{tf}: {'🟢' if d.get('direction')=='BUY' else '🔴' if d.get('direction')=='SELL' else '⚪'}"
                for tf, d in r["timeframes"].items()
            ])
            msg.append(f"  {i+1}. **{sym}** — {r['avg_strength']:.0f}%")
            msg.append(f"     {tf_detail}")
        msg.append("")

    # Tier 2: Good alignment (2/3)
    tier2 = [r for r in matrix_results if r["alignment"] == 2 and r["overall"] == "BUY"]
    if tier2:
        msg.append("⚡ **Tier 2 — Good (2/3):**")
        for i, r in enumerate(tier2[:5]):
            sym = r["symbol"].replace("USDT", "")
            tf_detail = " | ".join([
                f"{tf}: {'🟢' if d.get('direction')=='BUY' else '🔴' if d.get('direction')=='SELL' else '⚪'}"
                for tf, d in r["timeframes"].items()
            ])
            msg.append(f"  {i+1}. **{sym}** — {r['avg_strength']:.0f}%")
            msg.append(f"     {tf_detail}")
        msg.append("")

    # Tier 3: Rest
    tier3 = [r for r in matrix_results if r not in tier1 and r not in tier2]
    if tier3:
        msg.append("💤 **Tier 3 — Weak/Bearish:**")
        for i, r in enumerate(tier3[:5]):
            sym = r["symbol"].replace("USDT", "")
            direction_emoji = "🔴" if r["overall"] == "SELL" else "⚪"
            msg.append(f"  {i+1}. {direction_emoji} **{sym}** — {r['alignment']}/{r['total']} TF | {r['avg_strength']:.0f}%")
        msg.append("")

    # Summary
    msg.append(f"📊 Scanned **{len(matrix_results)}** coins on **3 TFs** ({len(tier1)} strong)")
    msg.append("💡 `/analyze COIN` for full breakdown")
    msg.append(f"⏱️ 1h / 4h / 1d | 🤖 CryptoSignal Bot")

    return "\n".join(msg)
