"""
🧠 AI Calibrator — يعاير ثقة الـ AI مقابل النتائج الفعلية

يتتبع: هل لما AI يقول 70% ثقة فعلاً 70% من الصفقات تنجح؟
إذا لا — يضبط معامل التصحيح تلقائياً.

Calibration buckets:
  0-20%, 21-40%, 41-60%, 61-80%, 81-100%

لكل دلو: عدد الصفقات، عدد الناجحة، نسبة النجاح الفعلية
إذا الفعلي أقل من المتوقع → تقليل الثقة
إذا الفعلي أعلى من المتوقع → زيادة الثقة
"""
import json
import time
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("crypto-signal-calibrator")

CALIB_DIR = Path("/root/.crypto-signal-bot/calibration")
CALIB_DIR.mkdir(parents=True, exist_ok=True)
CALIB_FILE = CALIB_DIR / "ai_calibration.json"

# Confidence buckets: (min, max, label)
BUCKETS = [
    (0, 20, "منخفضة جداً"),
    (21, 40, "منخفضة"),
    (41, 60, "متوسطة"),
    (61, 80, "عالية"),
    (81, 100, "عالية جداً"),
]


def _load() -> dict:
    """Load calibration data"""
    try:
        if CALIB_FILE.exists():
            return json.loads(CALIB_FILE.read_text())
    except Exception as e:
        logger.debug(f"Calibration file init failed: {e}")
        return CALIB_FILE
    return {"buckets": {}, "total_trades": 0, "total_wins": 0, "last_updated": 0}


def _save(data: dict):
    """Save calibration data"""
    try:
        data["last_updated"] = time.time()
        CALIB_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Failed to save calibration: {e}")


def record_outcome(ai_confidence: float, was_win: bool, symbol: str = ""):
    """
    سجل نتيجة صفقة: هل نجحت ولا لا + كم كانت ثقة AI.
    تُستدعى بعد إغلاق أي صفقة.
    """
    data = _load()
    data["total_trades"] = data.get("total_trades", 0) + 1
    if was_win:
        data["total_wins"] = data.get("total_wins", 0) + 1

    # Find bucket
    bucket_key = None
    for lo, hi, label in BUCKETS:
        if lo <= ai_confidence <= hi:
            bucket_key = f"{lo}-{hi}"
            break

    if not bucket_key:
        bucket_key = "41-60"  # fallback

    if bucket_key not in data["buckets"]:
        data["buckets"][bucket_key] = {
            "min": int(bucket_key.split("-")[0]),
            "max": int(bucket_key.split("-")[1]),
            "total": 0,
            "wins": 0,
            "win_rate": 0.0,
            "last_trade": "",
        }

    b = data["buckets"][bucket_key]
    b["total"] += 1
    if was_win:
        b["wins"] += 1
    b["win_rate"] = round(b["wins"] / b["total"] * 100, 1) if b["total"] > 0 else 0
    b["last_trade"] = f"{symbol} {'✅' if was_win else '❌'}"

    _save(data)
    logger.info(f"📊 Calibration: AI conf={ai_confidence:.0f}% → bucket {bucket_key} | "
                f"Win {'✅' if was_win else '❌'} | Bucket WR={b['win_rate']:.1f}%")


def get_calibrated_confidence(raw_confidence: float) -> tuple:
    """
    يرجع (ثقة مصححة, معامل التصحيح, شرح)

    إذا الدلو عنده 20 صفقة أو أكثر → نصحح
    إذا أقل → نرجع الثقة الأصلية بدون تغيير
    """
    data = _load()
    buckets = data.get("buckets", {})

    if not buckets or data.get("total_trades", 0) < 10:
        return raw_confidence, 1.0, ""

    # Find which bucket this confidence falls into
    expected_mid = raw_confidence
    for lo, hi, label in BUCKETS:
        if lo <= raw_confidence <= hi:
            expected_mid = (lo + hi) / 2
            break

    # Find actual win rate for this bucket
    bucket_key = None
    for lo, hi, label in BUCKETS:
        if lo <= raw_confidence <= hi:
            bucket_key = f"{lo}-{hi}"
            break

    if not bucket_key or bucket_key not in buckets:
        return raw_confidence, 1.0, ""

    b = buckets[bucket_key]
    if b["total"] < 5:  # تحتاج 5 صفقات على الأقل للتصحيح
        return raw_confidence, 1.0, ""

    actual_wr = b["win_rate"]

    # Calculate correction
    if expected_mid > 0:
        ratio = actual_wr / expected_mid
    else:
        ratio = 1.0

    # Safe bounds: لا نصحح أكثر من 30% في أي اتجاه
    ratio = max(0.70, min(1.30, ratio))

    calibrated = raw_confidence * ratio
    calibrated = max(5, min(95, calibrated))  # clamp

    note = f"AI قال {raw_confidence:.0f}% → الفعلي {actual_wr:.1f}% → معامل {ratio:.2f} → مصحح {calibrated:.0f}%"

    return round(calibrated, 1), round(ratio, 3), note


def get_calibration_summary() -> str:
    """ملخص المعايرة للتقارير"""
    data = _load()
    buckets = data.get("buckets", {})
    total = data.get("total_trades", 0)
    total_wins = data.get("total_wins", 0)
    overall_wr = round(total_wins / total * 100, 1) if total > 0 else 0

    if total < 5:
        return ""

    lines = [
        f"🧠 معايرة AI: {total} صفقة | نسبة نجاح {overall_wr:.0f}%",
    ]
    for key in sorted(buckets.keys()):
        b = buckets[key]
        if b["total"] >= 3:
            lines.append(f"  ثقة {b['min']}-{b['max']}%: {b['wins']}/{b['total']} نجاح ({b['win_rate']:.0f}%)")

    return "\n".join(lines)
