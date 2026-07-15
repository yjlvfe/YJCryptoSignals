"""
🔍 Scanner — يمسح السوق ويلتقط الفرص
v2: مع regime filter + multi-timeframe conflict detection
"""
import time
import logging
from data.fetcher import fetch_klines, TOP_SYMBOLS
from engine.analyzer import Analyzer

logger = logging.getLogger("crypto-signal-scanner")


class CryptoScanner:
    """يمسح العملات ويلتقط الأنسب للدخول"""

    def __init__(self):
        self.analyzer = Analyzer()

    def scan_market(self, max_coins: int = 30, timeframes: list = None) -> list:
        """
        مسح السوق كله وإرجاع قائمة بالفرص مرتبة حسب القوة.
        """
        if timeframes is None:
            timeframes = ["4h"]

        # تحميل regime مرة واحدة للمسح كله
        regime_data = None
        min_str, min_conf = 40, 45
        try:
            from engine.regime import get_cached_regime, get_min_strength_for_regime
            regime_data = get_cached_regime()
            min_str, min_conf = get_min_strength_for_regime(regime_data)
        except Exception as e:
            logger.warning(f"Single coin scan failure: {e}")
            pass  # single coin scan failure non-fatal

        candidates = []

        print(f"🔍 بدء مسح {max_coins} عملة...")
        if regime_data:
            print(f"🌊 Market: {regime_data.get('regime','?')} | Filter: {regime_data.get('entry_filter','?')} | Min str: {min_str}% conf: {min_conf}%")
        symbols = TOP_SYMBOLS[:max_coins]

        for i, symbol in enumerate(symbols):
            try:
                print(f"  [{i+1}/{len(symbols)}] {symbol}...", end=" ")

                # جلب البيانات
                df_dict = {}
                for tf in timeframes:
                    limit = 200 if tf in ["4h", "1d"] else 500
                    df = fetch_klines(symbol, tf, limit)
                    df_dict[tf] = df
                    time.sleep(0.25)

                # تحليل على الفريم الأساسي
                result = self.analyzer.analyze(symbol, df_dict, timeframes[0])
                agg = result.aggregated

                # ─── BTC Correlation Filter — 🗑️ REMOVED
                # Each coin is analyzed independently. No BTC penalties.

                # ─── Multi-TF Conflict Detection ───
                # 🗑️ MTF conflict check REMOVED — AI handles multi-timeframe
                # Let all signals through

                # فلترة: الفرص حسب الاتجاه فقط، بدون عتبات عالية
                if agg["direction"] in ("BUY", "SELL") and agg["strength"] >= 10:
                    candidates.append(result)
                    print(f"✅ إشارة {agg['direction']} بقوة {agg['strength']:.0f}% ثقة {agg['confidence']:.0f}%")
                else:
                    print(f"⏭️ {agg['direction']} قوة {agg.get('strength',0):.0f}%")

            except Exception as e:
                print(f"❌ {str(e)[:60]}")

        # ترتيب حسب القوة
        candidates.sort(key=lambda r: r.aggregated["strength"], reverse=True)

        print(f"\n✅ تم العثور على {len(candidates)} فرصة من {max_coins} عملة")
        return candidates

    def analyze_single(self, symbol: str, timeframes: list = None) -> object:
        """تحليل عملة محددة بكل المدارس"""
        if timeframes is None:
            timeframes = ["15m", "1h", "4h"]

        df_dict = {}
        for tf in timeframes:
            limit = 500 if tf in ["15m", "1h"] else 200
            df = fetch_klines(symbol, tf, limit)
            df_dict[tf] = df
            time.sleep(0.25)

        # تحليل على كل فريم
        results = {}
        for tf in timeframes:
            try:
                result = self.analyzer.analyze(symbol, df_dict, tf)
                results[tf] = result
            except Exception as e:
                print(f"⚠️ خطأ في تحليل {symbol} على {tf}: {e}")

        return results
