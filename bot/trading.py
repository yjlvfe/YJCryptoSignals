"""CryptoSignal Bot — Trading Loop + Signal Processing"""
import sys, os, json, time, threading, subprocess, logging, random
from pathlib import Path
from bot.config import *
from bot.handlers import *
from bot.tracker import add_trade, check_trades, get_active_trades, format_trades_list, update_current_prices, load_trades, save_trades, generate_daily_report, cleanup_trades, MAX_TRADES, _calc_pnl
from sectors.categories import analyze_sectors, find_rotation_opportunity
from engine.analyzer import Analyzer
from engine.scanner import CryptoScanner
from data.fetcher import fetch_klines
from data.exchanges import check_availability
from report.sectors import format_sector_report
from report.telegram import format_signal_report, format_signal_report_arabic_simple, format_scan_summary
from bot.keyboard import build_list_keyboard, build_detail_keyboard, build_back_keyboard, format_trade_detail_text, analyze_support_levels
from bot.user_lists import (
    get_user_list, add_to_user_list, remove_from_user_list, is_in_user_list,
    subscribe_to_trade, unsubscribe_from_trade, get_trade_subscribers,
    remove_trade_subscribers, cleanup_closed_trade, get_users_with_symbol
)
from engine.multi_analyzer import analyze_mtf, scan_strength_matrix, format_strength_matrix

logger = logging.getLogger("crypto-signal-bot")

def run_scan(chat_id: int):
    """تشغيل scan في thread منفصل"""
    try:
        logger.info(f"Running scan for {chat_id}")
        scanner = CryptoScanner()
        candidates = scanner.scan_market(max_coins=5, timeframes=["4h"])
        report = format_scan_summary(candidates)
        safe_send(chat_id, report)
        # سبوت فقط — نرسل تفاصيل فرص الشراء
        buy_candidates = [c for c in candidates if c.aggregated["direction"] == "BUY"]
        for c in buy_candidates[:2]:
            try:
                r = format_signal_report(c)
                safe_send(chat_id, r)
                time.sleep(1)
            except Exception as e:
                logger.error(f"Error in scan detail for {c.symbol}: {e}")
                continue
        logger.info(f"Scan completed for {chat_id}")
    except Exception as e:
        logger.error(f"Scan error: {e}")
        safe_send(chat_id, f"❌ Scan error: {str(e)[:100]}")

    """Run sectors in separate thread"""
    try:
        logger.info(f"Running sectors for {chat_id}")
        data = analyze_sectors()
        if not data:
            safe_send(chat_id, "⚠️ Insufficient sector data right now.")
            return
        
        opps = find_rotation_opportunity(data)
        
        # Analyze coins from most active sectors
        coin_results = {}  # symbol -> AnalysisResult
        for opp in opps[:3]:
            for c in opp.get("top_gainers", [])[:2]:
                sym = c["symbol"]
                try:
                    ana = Analyzer()
                    df_dict = {"4h": fetch_klines(sym, "4h", 200)}
                    time.sleep(0.3)
                    result = ana.analyze(sym, df_dict, "4h")
                    coin_results[sym] = result
                    logger.info(f"  Analyzed {sym}: {result.aggregated['direction']}")
                except Exception as e:
                    logger.error(f"  Error analyzing {sym}: {e}")
                    continue
        
        # Build coin_analysis from results (for sector report)
        coin_analysis = {}
        for sym, result in coin_results.items():
            a = result.aggregated
            coin_analysis[sym] = {
                "direction": a["direction"],
                "confidence": a["confidence"],
                "strength": a["strength"],
                "entry": a["entry"],
                "dec": 8 if result.price < 1 else 6 if result.price < 100 else 4 if result.price < 1000 else 2,
            }
        
        logger.info(f"Analyzed {len(coin_results)} coins for sector report")
        
        # ─── 1. General sector report ───
        report = format_sector_report(data, opps, coin_analysis)
        safe_send(chat_id, report)
        time.sleep(1)
        
        # ─── 2. Each BUY coin as separate message ───
        buy_sent = 0
        for sym, result in coin_results.items():
            if result.aggregated["direction"] == "BUY":
                report = format_signal_report(result)
                safe_send(chat_id, report)
                buy_sent += 1
                time.sleep(1)
        
        if buy_sent == 0:
            safe_send(chat_id, "⚪ No strong buy opportunities right now.\nMarket is quiet, wait for liquidity.")
        
        logger.info(f"Sectors completed: {buy_sent} buy signals sent")
    except Exception as e:
        logger.error(f"Sectors error: {e}")
        safe_send(chat_id, f"❌ Sector analysis error: {str(e)[:100]}")

    """Run analysis — full English, simple Arabic, or full max — now with AI"""
    try:
        logger.info(f"Running multi-TF analysis for {symbol}")
        if not symbol.endswith("USDT"):
            symbol = symbol.upper() + "USDT"
        
        # Multi-TF analysis behind the scenes
        from engine.multi_analyzer import analyze_mtf
        mtf_result = analyze_mtf(symbol)
        
        # Use primary timeframe (4h) for recommendation
        primary = mtf_result.get("timeframes", {}).get("4h", {})
        if primary.get("error"):
            msg = f"⚠️ Error analyzing {symbol.replace('USDT','')}: {primary['error']}"
            safe_send(chat_id, msg)
            return
        
        # Build AnalysisResult from primary TF
        from engine.analyzer import Analyzer
        from data.fetcher import fetch_klines
        df = fetch_klines(symbol, "4h", 200)
        if df is None or len(df) < 50:
            msg = f"⚠️ Insufficient data for {symbol}"
            safe_send(chat_id, msg)
            return
        
        analyzer = Analyzer()
        result = analyzer.analyze(symbol, {"4h": df}, "4h")
        
        # 🧠 AI Deep Analysis — always on for both /analysis and /max
        ai_result = None
        try:
            from engine.ai_analyst import analyze_coin, enrich_with_modules
            signals = getattr(result, 'signals', [])
            regime_data = {}
            try:
                from engine.regime import get_cached_regime
                regime_data = get_cached_regime() or {}
            except Exception as e:
                logger.debug(f"Regime cache skipped: {e}")
            enriched = enrich_with_modules(symbol, df)
            ai_result = analyze_coin(
                symbol, result.price, signals, regime_data,
                liquidity_intel=enriched.get("liquidity_intel"),
                breakout_data=enriched.get("breakout_data"),
            )
            logger.info(f"🧠 AI: {symbol} → {ai_result.get('decision','?')} ({ai_result.get('confidence',0)}%)")
        except Exception as e:
            logger.warning(f"AI analysis failed for {symbol}: {e}")
            ai_result = None
        
        if arabic:
            # تقرير عربي بسيط + AI
            report = format_signal_report_arabic_simple(result, mtf_result, ai_result=ai_result)
        else:
            # Full English report + AI
            report = format_signal_report(result, mtf_result, ai_result=ai_result)
        
        safe_send(chat_id, report)
        logger.info(f"Multi-TF + AI analyze completed for {symbol}: {mtf_result['alignment']}/{mtf_result['total']}")
    except Exception as e:
        logger.error(f"Analyze error for {symbol}: {e}")
        safe_send(chat_id, f"❌ Error analyzing {symbol}: {str(e)[:100]}")


    """Scan strength matrix across all timeframes"""
    try:
        logger.info(f"Running strength matrix for {chat_id}")
        from data.fetcher import TOP_SYMBOLS
        from sectors.categories import get_all_sector_coins
        
        # Collect coins: main list + sector coins
        all_symbols = list(dict.fromkeys(TOP_SYMBOLS + get_all_sector_coins()))
        
        results = scan_strength_matrix(all_symbols, max_coins=30)
        if not results:
            safe_send(chat_id, "⚠️ No results available.")
            return
        
        report = format_strength_matrix(results)
        safe_send(chat_id, report)
        
        # Send top 3 BUY opportunities individually
        tier1 = [r for r in results if r["alignment"] == 3 and r["overall"] == "BUY"]
        if tier1:
            safe_send(chat_id, "━━━ 🔥 **Top Picks — Full Analysis** ━━━")
            for r in tier1[:3]:
                try:
                    from engine.analyzer import Analyzer
                    from data.fetcher import fetch_klines
                    df = fetch_klines(r["symbol"], "4h", 200)
                    if df is not None and len(df) >= 50:
                        result = Analyzer().analyze(r["symbol"], {"4h": df}, "4h")
                        report = format_signal_report(result, r)
                        safe_send(chat_id, report)
                        time.sleep(1)
                except Exception as e:
                    logger.error(f"Matrix detail error for {r['symbol']}: {e}")
                    continue
        
        logger.info(f"Strength matrix completed for {chat_id}")
    except Exception as e:
        logger.error(f"Matrix error: {e}")
        safe_send(chat_id, f"❌ Matrix error: {str(e)[:100]}")


# ─── Files for persistent state (survive restarts) ───

def run_sectors(chat_id: int):
    """Run sectors in separate thread"""
    try:
        logger.info(f"Running sectors for {chat_id}")
        data = analyze_sectors()
        if not data:
            safe_send(chat_id, "⚠️ Insufficient sector data right now.")
            return
        
        opps = find_rotation_opportunity(data)
        
        # Analyze coins from most active sectors
        coin_results = {}  # symbol -> AnalysisResult
        for opp in opps[:3]:
            for c in opp.get("top_gainers", [])[:2]:
                sym = c["symbol"]
                try:
                    ana = Analyzer()
                    df_dict = {"4h": fetch_klines(sym, "4h", 200)}
                    time.sleep(0.3)
                    result = ana.analyze(sym, df_dict, "4h")
                    coin_results[sym] = result
                    logger.info(f"  Analyzed {sym}: {result.aggregated['direction']}")
                except Exception as e:
                    logger.error(f"  Error analyzing {sym}: {e}")
                    continue
        
        # Build coin_analysis from results (for sector report)
        coin_analysis = {}
        for sym, result in coin_results.items():
            a = result.aggregated
            coin_analysis[sym] = {
                "direction": a["direction"],
                "confidence": a["confidence"],
                "strength": a["strength"],
                "entry": a["entry"],
                "dec": 8 if result.price < 1 else 6 if result.price < 100 else 4 if result.price < 1000 else 2,
            }
        
        logger.info(f"Analyzed {len(coin_results)} coins for sector report")
        
        # ─── 1. General sector report ───
        report = format_sector_report(data, opps, coin_analysis)
        safe_send(chat_id, report)
        time.sleep(1)
        
        # ─── 2. Each BUY coin as separate message ───
        buy_sent = 0
        for sym, result in coin_results.items():
            if result.aggregated["direction"] == "BUY":
                report = format_signal_report(result)
                safe_send(chat_id, report)
                buy_sent += 1
                time.sleep(1)
        
        if buy_sent == 0:
            safe_send(chat_id, "⚪ No strong buy opportunities right now.\nMarket is quiet, wait for liquidity.")
        
        logger.info(f"Sectors completed: {buy_sent} buy signals sent")
    except Exception as e:
        logger.error(f"Sectors error: {e}")
        safe_send(chat_id, f"❌ Sector analysis error: {str(e)[:100]}")

    """Run analysis — full English, simple Arabic, or full max — now with AI"""
    try:
        logger.info(f"Running multi-TF analysis for {symbol}")
        if not symbol.endswith("USDT"):
            symbol = symbol.upper() + "USDT"
        
        # Multi-TF analysis behind the scenes
        from engine.multi_analyzer import analyze_mtf
        mtf_result = analyze_mtf(symbol)
        
        # Use primary timeframe (4h) for recommendation
        primary = mtf_result.get("timeframes", {}).get("4h", {})
        if primary.get("error"):
            msg = f"⚠️ Error analyzing {symbol.replace('USDT','')}: {primary['error']}"
            safe_send(chat_id, msg)
            return
        
        # Build AnalysisResult from primary TF
        from engine.analyzer import Analyzer
        from data.fetcher import fetch_klines
        df = fetch_klines(symbol, "4h", 200)
        if df is None or len(df) < 50:
            msg = f"⚠️ Insufficient data for {symbol}"
            safe_send(chat_id, msg)
            return
        
        analyzer = Analyzer()
        result = analyzer.analyze(symbol, {"4h": df}, "4h")
        
        # 🧠 AI Deep Analysis — always on for both /analysis and /max
        ai_result = None
        try:
            from engine.ai_analyst import analyze_coin, enrich_with_modules
            signals = getattr(result, 'signals', [])
            regime_data = {}
            try:
                from engine.regime import get_cached_regime
                regime_data = get_cached_regime() or {}
            except Exception as e:
                logger.debug(f"Regime cache skipped: {e}")
            enriched = enrich_with_modules(symbol, df)
            ai_result = analyze_coin(
                symbol, result.price, signals, regime_data,
                liquidity_intel=enriched.get("liquidity_intel"),
                breakout_data=enriched.get("breakout_data"),
            )
            logger.info(f"🧠 AI: {symbol} → {ai_result.get('decision','?')} ({ai_result.get('confidence',0)}%)")
        except Exception as e:
            logger.warning(f"AI analysis failed for {symbol}: {e}")
            ai_result = None
        
        if arabic:
            # تقرير عربي بسيط + AI
            report = format_signal_report_arabic_simple(result, mtf_result, ai_result=ai_result)
        else:
            # Full English report + AI
            report = format_signal_report(result, mtf_result, ai_result=ai_result)
        
        safe_send(chat_id, report)
        logger.info(f"Multi-TF + AI analyze completed for {symbol}: {mtf_result['alignment']}/{mtf_result['total']}")
    except Exception as e:
        logger.error(f"Analyze error for {symbol}: {e}")
        safe_send(chat_id, f"❌ Error analyzing {symbol}: {str(e)[:100]}")



def run_analyze(chat_id: int, symbol: str, full: bool = True, arabic: bool = False):
    """Run analysis — full English, simple Arabic, or full max — now with AI"""
    try:
        logger.info(f"Running multi-TF analysis for {symbol}")
        if not symbol.endswith("USDT"):
            symbol = symbol.upper() + "USDT"
        
        # Multi-TF analysis behind the scenes
        from engine.multi_analyzer import analyze_mtf
        mtf_result = analyze_mtf(symbol)
        
        # Use primary timeframe (4h) for recommendation
        primary = mtf_result.get("timeframes", {}).get("4h", {})
        if primary.get("error"):
            msg = f"⚠️ Error analyzing {symbol.replace('USDT','')}: {primary['error']}"
            safe_send(chat_id, msg)
            return
        
        # Build AnalysisResult from primary TF
        from engine.analyzer import Analyzer
        from data.fetcher import fetch_klines
        df = fetch_klines(symbol, "4h", 200)
        if df is None or len(df) < 50:
            msg = f"⚠️ Insufficient data for {symbol}"
            safe_send(chat_id, msg)
            return
        
        analyzer = Analyzer()
        result = analyzer.analyze(symbol, {"4h": df}, "4h")
        
        # 🧠 AI Deep Analysis — always on for both /analysis and /max
        ai_result = None
        try:
            from engine.ai_analyst import analyze_coin, enrich_with_modules
            signals = getattr(result, 'signals', [])
            regime_data = {}
            try:
                from engine.regime import get_cached_regime
                regime_data = get_cached_regime() or {}
            except Exception as e:
                logger.debug(f"Regime cache skipped: {e}")
            enriched = enrich_with_modules(symbol, df)
            ai_result = analyze_coin(
                symbol, result.price, signals, regime_data,
                liquidity_intel=enriched.get("liquidity_intel"),
                breakout_data=enriched.get("breakout_data"),
            )
            logger.info(f"🧠 AI: {symbol} → {ai_result.get('decision','?')} ({ai_result.get('confidence',0)}%)")
        except Exception as e:
            logger.warning(f"AI analysis failed for {symbol}: {e}")
            ai_result = None
        
        if arabic:
            # ─── قالب التحليل (نفس قالب التوصيات مع استبدال "توصية" بـ "تحليل") ───
            ctx_regime = regime_data.get("regime", "") if regime_data else ""
            
            # 🎯 استخراج الاستراتيجيات + ATR (مطابق لمسار التوصيات)
            atr_val = None
            buy_strategies = []
            for sig in getattr(result, "signals", []):
                if hasattr(sig, 'name'):
                    if 'ATR' in sig.name:
                        import re
                        m = re.search(r'ATR=([\d.]+)%', sig.reason or '')
                        if m:
                            atr_pct = float(m.group(1))
                            atr_val = (atr_pct / 100) * (result.aggregated.get("entry", result.price))
                    if sig.signal == "BUY":
                        buy_strategies.append(sig.name)
            
            # 🎯 Smart Targets — تحسين الأهداف حسب ATR والتقلب
            a = result.aggregated
            try:
                from engine.smart_targets import enhance_signal_targets
                # Ensure a has the needed fields for enhance_signal_targets
                signal_dict = {
                    "entry": a.get("entry", result.price),
                    "targets": a.get("targets", []),
                    "stop_loss": a.get("stop_loss"),
                    "confidence": a.get("confidence", 50),
                    "direction": a.get("direction", "BUY"),
                }
                # Merge AI targets if available
                if ai_result and ai_result.get("targets"):
                    signal_dict["targets"] = ai_result["targets"]
                    signal_dict["entry"] = ai_result.get("entry", signal_dict["entry"])
                    signal_dict["stop_loss"] = ai_result.get("stop_loss", signal_dict["stop_loss"])
                    signal_dict["confidence"] = ai_result.get("confidence", signal_dict["confidence"])
                
                signal_dict = enhance_signal_targets(signal_dict, df, ctx_regime)
                result.aggregated["targets"] = signal_dict.get("targets", a.get("targets", []))
                result.aggregated["stop_loss"] = signal_dict.get("stop_loss", a.get("stop_loss"))
                if signal_dict.get("_target_source"):
                    logger.info(f"  🎯 {symbol}: Targets optimized ({signal_dict.get('_target_source')})")
            except Exception as e:
                logger.debug(f"  Smart targets skipped for analysis: {e}")
            
            # Kronos score (disabled — always returns 50)
            kronos_score = 0
            try:
                from engine.kronos import compute_kronos
                kronos_result = compute_kronos(
                    ta_signal=result.aggregated.get("direction", "NEUTRAL"),
                    ta_strength=result.aggregated.get("strength", 0),
                    regime_data=regime_data,
                )
                kronos_score = kronos_result.get("score", 0) if kronos_result else 0
            except Exception as e:
                logger.debug(f"Kronos skipped: {e}")
            
            # Layer agreement
            layer_agreement = ""
            try:
                from engine.layers import analyze_all_layers
                la = analyze_all_layers(symbol, df)
                layer_agreement = la.get("agreement", "")
            except Exception as e:
                logger.debug(f"Layer agreement skipped: {e}")
            
            report = format_signal_report_arabic_simple(
                result, mtf_result, is_signal=False,
                regime_str=ctx_regime,
                kronos_score=kronos_score,
                layer_agreement=layer_agreement,
                buy_strategies=buy_strategies,
                ai_result=ai_result,
                label="تحليل"
            )
        else:
            # Full English report + AI
            report = format_signal_report(result, mtf_result, ai_result=ai_result)
        
        safe_send(chat_id, report)
        logger.info(f"Multi-TF + AI analyze completed for {symbol}: {mtf_result['alignment']}/{mtf_result['total']}")
    except Exception as e:
        logger.error(f"Analyze error for {symbol}: {e}")
        safe_send(chat_id, f"❌ Error analyzing {symbol}: {str(e)[:100]}")


def run_matrix(chat_id: int):
    """Scan strength matrix across all timeframes"""
    try:
        logger.info(f"Running strength matrix for {chat_id}")
        from data.fetcher import TOP_SYMBOLS
        from sectors.categories import get_all_sector_coins
        
        # Collect coins: main list + sector coins
        all_symbols = list(dict.fromkeys(TOP_SYMBOLS + get_all_sector_coins()))
        
        results = scan_strength_matrix(all_symbols, max_coins=30)
        if not results:
            safe_send(chat_id, "⚠️ No results available.")
            return
        
        report = format_strength_matrix(results)
        safe_send(chat_id, report)
        
        # Send top 3 BUY opportunities individually
        tier1 = [r for r in results if r["alignment"] == 3 and r["overall"] == "BUY"]
        if tier1:
            safe_send(chat_id, "━━━ 🔥 **Top Picks — Full Analysis** ━━━")
            for r in tier1[:3]:
                try:
                    from engine.analyzer import Analyzer
                    from data.fetcher import fetch_klines
                    df = fetch_klines(r["symbol"], "4h", 200)
                    if df is not None and len(df) >= 50:
                        result = Analyzer().analyze(r["symbol"], {"4h": df}, "4h")
                        report = format_signal_report(result, r)
                        safe_send(chat_id, report)
                        time.sleep(1)
                except Exception as e:
                    logger.error(f"Matrix detail error for {r['symbol']}: {e}")
                    continue
        
        logger.info(f"Strength matrix completed for {chat_id}")
    except Exception as e:
        logger.error(f"Matrix error: {e}")
        safe_send(chat_id, f"❌ Matrix error: {str(e)[:100]}")


# ─── Global cycle tracking ───
_cycle_broadcast = set()  # symbols already broadcast this cycle

# ─── مراقبة أهداف المستخدمين بعد إغلاق الصفقة العالمية ───
def check_user_tracking_targets():
    """فحص أهداف T2/T3 للمستخدمين اللي عندهم تتبع نشط بعد إغلاق الصفقة العالمية"""
    try:
        from bot.user_lists import TRACKING_FILE
        if not TRACKING_FILE.exists():
            return
        
        import json
        tracking = json.loads(TRACKING_FILE.read_text())
        if not tracking:
            return
        
        # جمع كل الرموز اللي المستخدمين يتتبعونها
        tracked_symbols = set()
        user_map = {}  # {symbol: [(user_id, tracking_data)]}
        for uid, syms in tracking.items():
            for sym, info in syms.items():
                if info.get("tracking_status") == "active":
                    tracked_symbols.add(sym)
                    if sym not in user_map:
                        user_map[sym] = []
                    user_map[sym].append((int(uid), info))
        
        if not tracked_symbols:
            return
        
        # جلب الأسعار الحالية
        from data.fetcher import get_fetcher
        prices = get_fetcher().fetch_all_prices()
        
        for symbol, users in user_map.items():
            cp = prices.get(symbol)
            if not cp:
                continue
            
            for uid, info in users:
                targets = info.get("targets", [])
                targets_hit = info.get("targets_hit", [])
                target_count = info.get("target_count", 1)
                
                if len(targets_hit) >= target_count:
                    continue  # المستخدم خلص أهدافه
                
                # فحص الأهداف من T2 فصاعداً (T1 أغلقت عالمياً)
                for i in range(1, len(targets)):
                    if i not in targets_hit and i < len(targets) and cp >= targets[i]:
                        # 🎯 هدف جديد تحقق للمستخدم
                        from bot.user_lists import mark_user_target_hit, get_user_target_count, mark_user_tracking_complete, remove_from_user_list, unsubscribe_from_trade, get_user_entry_price, record_sale
                        mark_user_target_hit(uid, symbol, i)
                        
                        sym_clean = symbol.replace("USDT", "")
                        target_names = {1: "هدف T2", 2: "هدف T3"}
                        target_name = target_names.get(i, f"هدف T{i+1}")
                        
                        entry_price = info.get("entry_price", 0)
                        gain_pct = 0
                        if entry_price > 0:
                            gain_pct = _calc_pnl(entry_price, cp)
                        
                        # تحقق: هل هذا آخر هدف للمستخدم؟
                        current_hits = len(info.get("targets_hit", [])) + (1 if i not in info.get("targets_hit", []) else 0)
                        is_last = (current_hits >= target_count)
                        
                        if is_last:
                            # آخر هدف → تسجيل تلقائي
                            if entry_price > 0:
                                record_sale(uid, symbol, entry_price, cp, i)
                            mark_user_tracking_complete(uid, symbol)
                            remove_from_user_list(uid, symbol)
                            unsubscribe_from_trade(symbol, uid)
                            from bot.handlers import safe_send
                            safe_send(uid, (
                                f"📈 **{sym_clean}** » {target_name} ✅\n"
                                f"الربح » +{gain_pct:.2f}%\n"
                                f"⚠️ متابعه العمله منتهيه لتحقيقها {target_name}\n\n"
                                f"📊 /portfolio"
                            ))
                            logger.info(f"  🎯 User-tracked {sym_clean}: T{i+1} last target for {uid}")
                        else:
                            # هدف وسيط → زر تم البيع
                            from bot.handlers import send_msg_premium
                            reply_markup = {
                                "inline_keyboard": [
                                    [{"text": "💰 تم البيع", "callback_data": f"sold_{i}_{symbol}"}]
                                ]
                            }
                            send_msg_premium(uid, (
                                f"📈 **{sym_clean}** » {target_name} ✅\\n"
                                f"الربح » +{gain_pct:.2f}%\\n"
                                f"السعر » `${cp:.{dec}f}`"
                            ), reply_markup=reply_markup)
                            logger.info(f"  🎯 User-tracked {sym_clean}: T{i+1} hit for {uid}")
                        break  # هدف واحد فقط كل دورة
    except Exception as e:
        logger.debug(f"User tracking check failed: {e}")

# ─── Files for persistent state (survive restarts) ───
LAST_REPORT_FILE = DATA_DIR / "last_report.json"
BROADCAST_CACHE_FILE = DATA_DIR / "broadcast_cache.json"

def load_last_report_date() -> str:
    """تحميل تاريخ آخر تقرير من الملف"""
    try:
        if LAST_REPORT_FILE.exists():
            data = json.loads(LAST_REPORT_FILE.read_text())
            return data.get("last_report_date", "")
    except Exception as e:
        logger.debug(f"Report format failed: {e}")
        return ""
    return ""

def save_last_report_date(date_str: str):
    """حفظ تاريخ آخر تقرير"""
    try:
        LAST_REPORT_FILE.write_text(json.dumps({"last_report_date": date_str}))
    except Exception as e:
        logger.error(f"Failed to save last report date: {e}")

def load_broadcast_cache() -> dict:
    """تحميل سجل التوصيات السابق (نجاة من إعادة التشغيل)"""
    try:
        if BROADCAST_CACHE_FILE.exists():
            data = json.loads(BROADCAST_CACHE_FILE.read_text())
            cutoff = time.time() - 3600
            return {k: v for k, v in data.items() if v > cutoff}
    except Exception as e:
        logger.debug(f"Sector analysis failed: {e}")
        return {}
    return {}

def save_broadcast_cache():
    """حفظ سجل التوصيات"""
    global recently_broadcast
    try:
        BROADCAST_CACHE_FILE.write_text(json.dumps(recently_broadcast))
    except Exception as e:
        logger.error(f"Failed to save broadcast cache: {e}")

def scheduler_loop():
    """
    🚀 v2 REVOLUTION — Universal AI Scanner
    No mechanical filters. Pure AI. Every coin, every exchange, 10s per coin.
    Active trade monitoring in a background thread.
    """
    global recently_broadcast
    logger.info("🚀 v2 Universal Scheduler starting!")
    
    # 🗄️ Load persistent state
    last_report_date = load_last_report_date()
    recently_broadcast = load_broadcast_cache()
    if recently_broadcast:
        logger.info(f"📡 Loaded {len(recently_broadcast)} broadcast records from cache")
    if last_report_date:
        logger.info(f"📅 Last report date: {last_report_date}")
    
    REPORT_HOUR = 0  # منتصف الليل
    
    # ⏱️ Jitter: random delay to stagger scanner cycles vs V2
    jitter = random.uniform(30, 90)
    logger.info(f"⏱️ Initial jitter: {jitter:.0f}s (to prevent scanner collision with V2)")
    time.sleep(jitter)
    
    # ─── Main monitoring loop (every 5s — فحص سريع للأهداف والوقف) ───
    monitor_cycle = 0
    while True:
        try:
            monitor_cycle += 1
            time.sleep(5)
            
            # 🛡️ Self-defense: detect duplicate bot instances (warn only, systemd manages lifecycle)
            # Note: V2 scanner runs as separate systemd service now, no killing needed
            if monitor_cycle == 1:  # first cycle only
                import subprocess
                my_pid = os.getpid()
                my_cwd = os.path.realpath(os.getcwd())
                result = subprocess.run(
                    ["ps", "-eo", "pid,cwd,args"], capture_output=True, text=True, timeout=5
                )
                others = []
                for line in result.stdout.split('\n'):
                    if 'bot/main.py' not in line:
                        continue
                    parts = line.split(None, 2)
                    if len(parts) < 3:
                        continue
                    try:
                        pid = int(parts[0])
                        proc_cwd = parts[1]
                        cmd = parts[2]
                    except (ValueError, IndexError):
                        continue
                    if not cmd.startswith('python'):
                        continue
                    if pid == my_pid:
                        continue
                    try:
                        real_cwd = os.path.realpath(proc_cwd)
                        if real_cwd == my_cwd:
                            others.append(pid)
                    except Exception:
                        logger.debug("CWD comparison failed for PID（non-critical）")
                if len(others) > 1:
                    logger.warning(f"⚠️ {len(others)} duplicate V1 instances running (PIDs: {others}) — may cause Telegram 409 conflicts")
                elif others:
                    logger.info(f"📋 Found {len(others)} other V1 instance(s) (PIDs: {others}) — systemd should manage lifecycle")
            
            # 📅 Daily report at midnight
            now = time.time()
            tm = time.localtime(now)
            today = time.strftime("%Y-%m-%d", tm)
            current_hour = tm.tm_hour
            
            if current_hour == REPORT_HOUR and today != last_report_date:
                last_report_date = today
                save_last_report_date(today)
                report = generate_daily_report()
                if report:
                    broadcast(report)
                    logger.info(f"📅 Daily report broadcast for {today}")
                else:
                    logger.info(f"📅 No closed trades yesterday — skipping daily report")
            
            # 👁️ Monitor active trades (every 60s)
            try:
                trades = load_trades()
                active_trades = [t for t in trades if t.get("status") == "active"]
                if active_trades:
                    # Log monitoring every 30 cycles (~2.5 min at 5s/cycle) to reduce log spam
                    if monitor_cycle % 30 == 0:
                        logger.info(f"📊 Monitoring {len(active_trades)} active trades...")
                    else:
                        logger.debug(f"📊 Monitoring {len(active_trades)} active trades...")
                    trades = update_current_prices(trades)
                    active_symbols_before = {t["symbol"] for t in trades if t.get("status") == "active"}
                    trades, trade_alerts = check_trades(trades)
                    active_symbols_after = {t["symbol"] for t in trades if t.get("status") == "active"}
                    closed_symbols = active_symbols_before - active_symbols_after
                    if closed_symbols:
                        try:
                            hist_file = DATA_DIR / "trades_history.json"
                            history = json.loads(hist_file.read_text()) if hist_file.exists() else []
                        except Exception:
                            history = []
                        for sym in closed_symbols:
                            recent = [h for h in history if h.get("symbol") == sym]
                            if recent:
                                latest = max(recent, key=lambda h: h.get("closed_at", 0))
                                if latest.get("status") == "sl_hit":
                                    symbol_cooldown[sym] = time.time()
                                    logger.info(f"  ⏱️ {sym}: SL cooldown active")
                    save_trades(trades)
                    
                    try:
                        from engine.portfolio_heat import track_trade_lifecycle
                        for t in active_trades:
                            track_trade_lifecycle(t, is_closed=False)
                    except Exception:
                        logger.debug("Portfolio heat tracking failed（non-critical）")
                    
                    if trade_alerts:
                        for alert in trade_alerts:
                            send_trade_alert_to_subscribers(alert)
                            logger.info(f"  📊 Trade alert sent: {alert[:80]}")
                    
                    # 👁️ مراقبة أهداف المستخدمين (T2/T3) بعد إغلاق الصفقة العالمية
                    check_user_tracking_targets()
                    logger.debug("  👁️ User tracking targets checked")
            except Exception as e:
                logger.warning(f"⚠️ Trade monitoring error: {e}")
        
        except Exception as e:
            logger.error(f"Monitor error: {e}", exc_info=True)
            time.sleep(120)

# ─── Main ───
