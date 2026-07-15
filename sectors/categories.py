"""
🗂️ قطاعات السوق — Sector Classification Map
تصنيف العملات حسب القطاع الاقتصادي
"""
import time
import requests
import numpy as np
from data.fetcher import fetch_klines

# ════════════════════════════════════════════
# خريطة القطاعات — يدوية + محدثة
# ════════════════════════════════════════════

SECTORS = {
    "AI 🧠": {
        "name": "الذكاء الاصطناعي",
        "description": "مشاريع الذكاء الاصطناعي وتعلم الآلة",
        "coins": [
            "FETUSDT", "AGIXUSDT", "OCEANUSDT", "RNDRUSDT", "TAOUSDT",
            "NFPUSDT", "CTXCUSDT", "ALIUSDT", "MDTUSDT", "PONDUSDT",
            "PHBUSDT", "VRAUSDT", "DLTUSDT", "SNETUSDT",
        ]
    },
    "RWA 🏛️": {
        "name": "الأصول العقارية والمالية",
        "description": "Real World Assets — الأصول الحقيقية المرمزة",
        "coins": [
            "ONDOUSDT", "MKRUSDT", "POLYXUSDT", "CFGUSDT",
            "MPLUSDT", "IXSUSDT", "PROUSDT", "RWAUSDT",
            "LTOUSDT", "TRACUSDT", "DUSKUSDT", "LCXUSDT",
        ]
    },
    "DeFi 🏦": {
        "name": "التمويل اللامركزي",
        "description": "Decentralized Finance — الإقراض والتبادل اللامركزي",
        "coins": [
            "UNIUSDT", "AAVEUSDT", "CRVUSDT", "CAKEUSDT", "SUSHIUSDT",
            "COMPUSDT", "MKRUSDT", "LDOUSDT", "FXSUSDT", "BALUSDT",
            "DYDXUSDT", "PERPUSDT", "GMXUSDT", "RDNTUSDT", "PENDLEUSDT",
            "INJUSDT", "SNXUSDT", "UMAUSDT", "YFIUSDT", "ALPACAUSDT",
        ]
    },
    "GameFi 🎮": {
        "name": "الألعاب والعوالم الافتراضية",
        "description": "Gaming و Metaverse — ألعاب البلوكشين",
        "coins": [
            "GALAUSDT", "SANDUSDT", "MANAUSDT", "AXSUSDT", "ENJUSDT",
            "IMXUSDT", "MAGICUSDT", "ALICEUSDT", "TLMUSDT", "CHRUSDT",
            "WAXPUSDT", "C98USDT", "YGGUSDT", "PRIMEUSDT", "PIXELUSDT",
        ]
    },
    "Meme 🐸": {
        "name": "الرموز الميمية",
        "description": "Meme Coins — عملات المجتمع والميم",
        "coins": [
            "DOGEUSDT", "SHIBUSDT", "PEPEUSDT", "FLOKIUSDT", "BONKUSDT",
            "WIFUSDT", "MEMEUSDT", "BABYDOGEUSDT", "SAMOUSDT", "ELONUSDT",
        ]
    },
    "L1 🔗": {
        "name": "الطبقة الأولى",
        "description": "Layer 1 — سلاسل الكتل الأساسية",
        "coins": [
            "SOLUSDT", "AVAXUSDT", "NEARUSDT", "APTUSDT", "SUIUSDT",
            "TIAUSDT", "SEIUSDT", "INJUSDT", "FTMUSDT", "EGLDUSDT",
            "ALGOUSDT", "KASUSDT", "TONUSDT", "RUNBUSDT", "VETUSDT",
        ]
    },
    "L2 ⚡": {
        "name": "الطبقة الثانية",
        "description": "Layer 2 — حلول التوسع",
        "coins": [
            "OPUSDT", "ARBUSDT", "MATICUSDT", "METISUSDT",
            "SKLUSDT", "BOBAUSDT", "CTSIUSDT", "IMXUSDT",
        ]
    },
    "DePIN 📡": {
        "name": "الشبكات اللامركزية",
        "description": "DePIN — البنية التحتية المادية اللامركزية",
        "coins": [
            "HNTUSDT", "FILUSDT", "ARUSDT", "THETAUSDT",
            "IOTXUSDT", "DIONEUSDT", "AKTUSDT", "LPTUSDT",
            "RNDRUSDT", "LMWRUSDT",
        ]
    },
    "CeFi 🏛️": {
        "name": "التمويل المركزي",
        "description": "Centralized Finance — المنصات المركزية",
        "coins": [
            "BNBUSDT", "CROUSDT", "LEOUSDT", "OKBUSDT",
            "GTUSDT", "KCSUSDT", "BGBUSDT", "MXUSDT",
        ]
    },
    "Infra 🏗️": {
        "name": "البنية التحتية",
        "description": "Infrastructure — البنية التحتية للبلوكشين",
        "coins": [
            "LINKUSDT", "GRTUSDT", "ARBUSDT", "DOTUSDT",
            "ATOMUSDT", "ICPUSDT", "FETUSDT", "BANDUSDT",
        ]
    },
}


def get_all_sector_coins() -> list:
    """إرجاع قائمة بكل العملات في كل القطاعات (مع منع التكرار)"""
    seen = set()
    coins = []
    for sector, info in SECTORS.items():
        for c in info["coins"]:
            if c not in seen:
                seen.add(c)
                coins.append(c)
    return coins


def get_sector_for_coin(symbol: str) -> str:
    """إرجاع اسم القطاع لعملة معينة"""
    for sector, info in SECTORS.items():
        if symbol in info["coins"]:
            return sector
    return "Other ❓"


def analyze_sectors(mexc_only: bool = True) -> dict:
    """
    تحليل أداء كل قطاع — سوبر سريع (1-2 ثانية)
    يستخدم MultiExchangeFetcher مع fallback تلقائي
    """
    from data.fetcher import get_fetcher
    
    # نجيب كل التيكرات مره وحده من أول منصة متاحة
    try:
        f = get_fetcher()
        tickers = f.fetch_tickers_24hr()
    except Exception as e:
        logger.error(f"Failed to fetch tickers: {e}", exc_info=True)
        return {}
    
    # نحول لقاموس للوصول السريع
    ticker_map = {}
    for t in tickers:
        ticker_map[t["symbol"]] = {
            "price": t["last"],
            "change": t.get("change_pct", 0),
            "volume": t.get("quote_volume", 0),
        }

    results = {}

    for sector, info in SECTORS.items():
        coins = info["coins"]
        changes = []
        volumes = []
        active_coins = []

        for symbol in coins:
            t = ticker_map.get(symbol)
            if t is None:
                continue

            active_coins.append({
                "symbol": symbol,
                "price": t["price"],
                "change_24h": round(t["change"], 2),
                "volume": t["volume"],
            })
            changes.append(t["change"])
            volumes.append(t["volume"])

        if active_coins:
            avg_change = np.mean(changes)
            total_volume = sum(volumes)
            up_count = sum(1 for c in changes if c > 0)
            down_count = sum(1 for c in changes if c < 0)

            sorted_coins = sorted(active_coins, key=lambda x: abs(x["change_24h"]), reverse=True)
            momentum = "🟢" if avg_change > 0 else "🔴"

            results[sector] = {
                "name": info["name"],
                "description": info["description"],
                "avg_change_24h": round(avg_change, 2),
                "total_volume": total_volume,
                "active_coins": len(active_coins),
                "up_count": up_count,
                "down_count": down_count,
                "momentum": momentum,
                "top_gainers": sorted_coins[:5],
                "coin_count": len(coins),
            }

    return results


def find_rotation_opportunity(sector_data: dict) -> list:
    """
    إيجاد فرص تناوب السيولة بين القطاعات.
    """
    # تحسين حساب النشاط: نعطي وزناً للحجم حتى لو التغير قليل
    ranked = []
    for sector, data in sector_data.items():
        if data["active_coins"] < 3:
            continue
        # النشاط = |تغير| × (حجم/١مليون) + (عدد العملات النشطة / عدد العملات الكلي) × 10
        change_weight = max(0.1, abs(data["avg_change_24h"]))
        volume_score = data["total_volume"] / 1e6
        coverage = data["active_coins"] / max(data["coin_count"], 1) * 10
        activity_score = change_weight * volume_score + coverage
        ranked.append({
            "sector": sector,
            "data": data,
            "score": round(activity_score, 1),
        })

    ranked.sort(key=lambda x: x["score"], reverse=True)

    # تحديد القطاعات النشطة
    opportunities = []
    for r in ranked[:5]:
        direction = "ارتفاع" if r["data"]["avg_change_24h"] > 0 else "انخفاض"
        opp = {
            "sector": r["sector"],
            "direction": direction,
            "avg_change": r["data"]["avg_change_24h"],
            "volume": r["data"]["total_volume"],
            "top_gainers": r["data"]["top_gainers"][:3],
            "score": r["score"],
            "momentum": r["data"]["momentum"],
        }
        # Define opportunity type based on change and volume
        if r["data"]["avg_change_24h"] > 3 and r["data"]["up_count"] > r["data"]["down_count"] * 1.5:
            opp["type"] = "🔥 Liquidity entering — Buy!"
        elif r["data"]["avg_change_24h"] > 0:
            opp["type"] = "📈 Positive momentum"
        elif r["data"]["avg_change_24h"] < -3:
            opp["type"] = "⚠️ Correction — possible bounce"
        else:
            opp["type"] = "➡️ Quiet"

        opportunities.append(opp)

    return opportunities
