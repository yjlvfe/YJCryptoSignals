"""
📊 CryptoSignal Trade Tracker — Active trade monitoring
"""
import json
import time
import logging
import threading
import os
import fcntl
import concurrent.futures
from pathlib import Path
from datetime import datetime, timezone, timedelta

from bot.config import POSITION_SIZE_PCT

logger = logging.getLogger("crypto-signal-tracker")

DATA_DIR = Path("/root/.crypto-signal-bot")
TRADES_FILE = DATA_DIR / "trades.json"
HISTORY_FILE = DATA_DIR / "trades_history.json"
MAX_TRADES = 10  # حد أقصى 10 صفقات نشطة

# 🔒 Thread-safe file access lock for trades.json
_trades_lock = threading.Lock()

# 🔒 Cross-process file lock for trades.json
_TRADES_FILE_LOCK = DATA_DIR / "trades.lock"


def _acquire_file_lock(lock_file, blocking=True):
    """Acquire fcntl lock on a lock file"""
    fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR, 0o644)
    flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
    try:
        fcntl.flock(fd, flags)
        return fd
    except (IOError, OSError):
        os.close(fd)
        return None


def _release_file_lock(fd):
    """Release fcntl lock"""
    if fd is not None:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _calc_pnl(entry: float, close: float, direction: str = "BUY") -> float:
    """Calculate PnL percentage for a trade"""
    if direction == "SELL":
        return (entry - close) / entry * 100
    return (close - entry) / entry * 100


def load_trades() -> list:
    """Load all trades from JSON file (thread-safe + cross-process safe)"""
    with _trades_lock:  # internal thread lock
        fd = _acquire_file_lock(_TRADES_FILE_LOCK)
        try:
            if TRADES_FILE.exists():
                return json.loads(TRADES_FILE.read_text())
        except Exception as e:
            logger.error(f"Failed to load trades: {e}")
            return []
        finally:
            _release_file_lock(fd)
        return []


def save_trades(trades: list):
    """Save trades to file with backup protection (thread-safe + cross-process safe)"""
    with _trades_lock:  # internal thread lock
        fd = _acquire_file_lock(_TRADES_FILE_LOCK)
        try:
            # 🛡️ Never save empty list if trades existed before (protect against data loss)
            if len(trades) == 0 and TRADES_FILE.exists():
                try:
                    old = json.loads(TRADES_FILE.read_text())
                    if len(old) > 0:
                        logger.error(f"⛔ REFUSED to overwrite {len(old)} active trades with empty list!")
                        # Keep backup
                        backup = TRADES_FILE.with_suffix(".json.bak")
                        TRADES_FILE.rename(backup)
                        logger.warning(f"📦 Backup saved to {backup}")
                        return
                except Exception:
                    logger.debug("Backup rename failed（non-fatal）")
            
            # 📦 Keep backup of previous state
            if TRADES_FILE.exists():
                try:
                    backup = TRADES_FILE.with_suffix(".json.bak")
                    TRADES_FILE.rename(backup)
                except Exception:
                    logger.debug("Trades backup rename failed（non-fatal）")
            
            TRADES_FILE.write_text(json.dumps(trades, indent=2))
        except Exception as e:
            logger.error(f"Failed to save trades: {e}")
        finally:
            _release_file_lock(fd)


def add_trade(symbol: str, entry: float, targets: list, stop_loss: float,
              confidence: float = 0, strength: float = 0, timeframe: str = "4h",
              atr_val: float = None, strategy_signals: list = None,
              entry_type: str = "now", cancel_level: float = None,
              cancel_source: str = None, quality_score: float = 50,
              position_size: dict = None) -> tuple:
    """
    Add a new trade to the tracker.
    Uses ATR-based stop loss if atr_val is provided (stop = entry - 2×ATR).
    strategy_signals: list of strategy names that voted BUY (for independent PnL tracking).
    entry_type: "now" or "limit"
    cancel_level: resistance above entry for limit order cancellation
    Returns (success, message).
    """
    trades = load_trades()

    # ممنوع التكرار — أي صفقة مو "closed" تعتبر نشطة
    for t in trades:
        if t["symbol"] == symbol and t.get("status") not in ("closed",):
            return False, f"⚠️ {symbol.replace('USDT','')} متابعة بالفعل"

    # الحد الأقصى — نحسب بس الصفقات النشطة فعلاً
    active = [t for t in trades if t.get("status") == "active"]
    if len(active) >= MAX_TRADES:
        return False, f"⚠️ Max trades reached ({MAX_TRADES}). Close some trades first."

    # Determine initial status
    if entry_type == "limit":
        initial_status = "pending"
        limit_price = entry
    else:
        initial_status = "active"
        limit_price = None

    trade = {
        "symbol": symbol,
        "entry_price": entry,
        "targets": targets,
        "stop_loss": stop_loss,
        "timeframe": timeframe,
        "confidence": confidence,
        "strength": strength,
        "added_at": time.time(),
        "added_date": time.strftime("%Y-%m-%d %H:%M"),
        "status": initial_status,
        "tp_hit": [],
        "highest_price": entry,   # تتبع أعلى سعر — لاكتشاف TP قبل SL
        "lowest_price": entry,    # تتبع أدنى سعر — للصفقات القصيرة مستقبلاً
        "strategies": strategy_signals or [],  # Strategies participating
        "alert_state": None,
        "quality_score": quality_score if quality_score else 50,  # Signal quality
        "position_size": position_size or {},  # Position sizing details
        "entry_type": entry_type,
    }

    # 📍 Limit order fields
    if entry_type == "limit":
        trade["entry_type"] = "limit"
        trade["limit_price"] = limit_price
        trade["cancel_level"] = cancel_level
        trade["cancel_source"] = cancel_source or "tp1"
        trade["limit_status"] = "pending"
    else:
        trade["entry_type"] = "now"

    trades.append(trade)
    save_trades(trades)
    status_label = "معلق ⏳" if entry_type == "limit" else "نشط"
    logger.info(f"📊 Trade added: {symbol} @ {entry} [{status_label}]")
    return True, f"✅ {symbol.replace('USDT','')} added to tracker [{status_label}]"


def update_current_prices(trades: list) -> list:
    """تحديث الأسعار الحالية من Multi-Exchange Fetcher مع timeout"""
    if not trades:
        return trades

    try:
        from data.fetcher import get_fetcher
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(get_fetcher().fetch_all_prices)
            try:
                prices = future.result(timeout=30)
            except concurrent.futures.TimeoutError:
                logger.warning("⏱️ fetch_all_prices timed out after 30s — skipping price update")
                return trades
        for t in trades:
            sym = t["symbol"]
            price = None
            if sym in prices:
                price = prices[sym]
            else:
                # Try removing single-letter prefix (R, Z, etc.)
                if len(sym) > 5 and sym[0] in 'RZ':
                    alt_sym = sym[1:]
                    if alt_sym in prices:
                        price = prices[alt_sym]
                        logger.debug(f"  🔄 {sym} → {alt_sym}: price found via stripped prefix")
            if price is not None:
                if t.get("status") == "active":
                    t["current_price"] = price
                # تتبع أعلى/أدنى سعر — لكل الصفقات (حتى المغلقة للتاريخ)
                if price > t.get("highest_price", t["entry_price"]):
                    t["highest_price"] = price
                if price < t.get("lowest_price", t["entry_price"]):
                    t["lowest_price"] = price
    except Exception as e:
        logger.warning(f"Failed to update prices: {e}")
    return trades


def _format_duration(added_at: float) -> str:
    """Format trade duration in Arabic"""
    seconds = time.time() - added_at
    if seconds < 3600:
        mins = int(seconds / 60)
        return f"{mins} دقيقة" if mins > 0 else "أقل من دقيقة"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        mins = int((seconds % 3600) / 60)
        if mins > 0:
            return f"{hours} ساعة و {mins} دقيقة"
        return f"{hours} ساعة"
    else:
        days = int(seconds / 86400)
        hours = int((seconds % 86400) / 3600)
        if hours > 0:
            return f"{days} يوم و {hours} ساعة"
        return f"{days} يوم"

def check_trades(trades: list) -> tuple:
    """
    Check trades: hit target or stop loss.
    Completed trades (TP/SL hit) are removed immediately.
    Uses highest_price to detect TP-hit-before-SL scenario.
    Returns (updated_trades, [alert_texts]).
    """
    alerts = []
    to_remove = []

    # ⏰ Auto-close stale trades (older than 7 days)
    now = time.time()
    stale_timeout = 7 * 86400  # 7 days
    for t in trades[:]:  # iterate copy
        if t.get("status") == "active" and (now - t.get("added_at", 0)) > stale_timeout:
            sym = t["symbol"].replace("USDT", "")
            logger.info(f"⏰ Auto-closing stale trade: {sym} (age: {(now - t.get('added_at', 0))/86400:.1f} days)")
            t["status"] = "closed"
            t["close_reason"] = "timeout"
            t["current_price"] = t["entry_price"]  # neutral PnL at 0%
            to_remove.append(t)

    # ⏰ Auto-close zombie trades (older than 24h with NO current_price)
    stale_no_price_timeout = 24 * 3600  # 24 hours
    for t in trades[:]:  # iterate copy
        if t.get("status") == "active" and t.get("current_price") is None:
            age = now - t.get("added_at", 0)
            if age > stale_no_price_timeout:
                sym = t["symbol"].replace("USDT", "")
                logger.warning(f"⏰ Auto-closing zombie trade (no price): {sym} (age: {age/3600:.1f}h)")
                t["status"] = "closed"
                t["close_reason"] = "timeout_no_price"
                t["current_price"] = t["entry_price"]  # neutral PnL at 0%
                to_remove.append(t)

    for t in trades:
        # 📍 [NEW] Limit Order Handling — check pending orders first
        if t.get("status") == "pending" and t.get("entry_type") == "limit":
            cp = t.get("current_price")
            if cp is None:
                continue

            sym = t["symbol"].replace("USDT", "")
            limit_price = t.get("limit_price", t["entry_price"])
            cancel_level = t.get("cancel_level")
            cancel_source = t.get("cancel_source", "tp1")
            dec = 8 if limit_price < 1 else 6 if limit_price < 100 else 4

            # حالة ① — تم التنفيذ: price dropped to or below limit
            if cp <= limit_price * 1.003:
                t["status"] = "active"
                t["limit_status"] = "filled"
                t["entry_price"] = cp  # actual fill price
                alerts.append(
                    f"✅ **تم تنفيذ الأوردر**\n\n"
                    f"🟢 **{sym}** » شراء @ ${cp:.{dec}f}\n"
                    f"🎯 الأهداف: " + " | ".join(f"${tgt:.{dec}f}" for tgt in t.get("targets", [])[:2]) + "\n"
                    f"🛑 الوقف: ${t['stop_loss']:.{dec}f}\n"
                    f"💡 بدء المتابعة الآن"
                )
                logger.info(f"  ✅ {sym}: Limit order FILLED @ {cp}")
                save_trades(trades)
                continue  # skip TP/SL check this cycle — will check next cycle

            # حالة ② — كسر مستوى الإلغاء: price went ABOVE cancel level
            if cancel_level and cp > cancel_level:
                cancel_src_label = {
                    "resistance": "المقاومة", "ob": "Order Block",
                    "fvg": "FVG", "fib61.8": "Fib 61.8%", "tp1": "TP1"
                }.get(cancel_source, cancel_source)
                alerts.append(
                    f"❌ **إلغاء تلقائي**\n\n"
                    f"🔴 **{sym}** » الأوردر لم ينفذ\n"
                    f"📈 السعر تجاوز {cancel_src_label}: ${cancel_level:.{dec}f}\n"
                    f"💡 الارتداد المتوقع انتهى — الأوردر لم يعد منطقياً\n"
                    f"⏳ كان معلقاً عند: ${limit_price:.{dec}f}"
                )
                t["status"] = "cancelled"
                to_remove.append(t)
                logger.info(f"  ❌ {sym}: Limit order CANCELLED — price {cp} > cancel {cancel_level} ({cancel_source})")
                continue

            # حالة ③ — ينتظر: still pending, do nothing
            continue

        if t.get("status") != "active":
            continue
        cp = t.get("current_price")
        if cp is None:
            continue

        entry = t["entry_price"]
        sym = t["symbol"].replace("USDT", "")
        dec = 8 if entry < 1 else 6 if entry < 100 else 4 if entry < 1000 else 2
        duration = _format_duration(t.get("added_at", time.time()))
        highest = t.get("highest_price", entry)

        # ─── ① Check targets FIRST (current price) ───
        tp_hit = t.get("tp_hit", [])
        for i, target in enumerate(t["targets"]):
            if i not in tp_hit and cp >= target:
                tp_hit.append(i)
                t["tp_hit"] = tp_hit
                gain_pct = _calc_pnl(entry, cp)

                if i == 0:  # T1 → trade complete, remove
                    target_gain = _calc_pnl(entry, target)
                    ai_conf = t.get("ai_confidence", 0)
                    entry_type = t.get("entry_type", "now")
                    entry_label = "🎯 فوري" if entry_type == "now" else "📉 معلق"
                    alert = (
                        f"📊 **اشعار توصيه**\n\n"
                        f"🟢 **{sym}** » اول هدف ✅\n"
                        f"الربح » {target_gain:+.2f}%\n"
                        f"سعر الهدف » `${target:.{dec}f}`\n"
                        f"السعر الحالي » `${cp:.{dec}f}`\n"
                        f"مده التوصيه » {duration}\n"
                    )
                    if ai_conf > 0:
                        alert += f"🧠 ثقة AI » {ai_conf:.0f}% | {entry_label}\n"
                    alert += f"⚠️ متابعه العمله منتهيه لتحقيقها اول هدف"
                    alerts.append(alert)
                    to_remove.append(t)
                    break
                else:
                    alerts.append(
                        f"📈 **{sym}** » هدف T{i+1} ✅\n"
                        f"الربح » {gain_pct:+.2f}%\n"
                        f"السعر » `${cp:.{dec}f}`"
                    )

        # ─── ② If T1 already hit (from break above), skip SL check ───
        if t in to_remove:
            continue

        # ─── ③ Check stop loss ───
        if cp <= t["stop_loss"]:
            loss_pct = _calc_pnl(entry, t["stop_loss"])  # Use SL price, not current_price (slippage-proof)

            # 🔍 هل وصل السعر لأي هدف قبل ما يضرب الوقف؟
            tp_hit_before_sl = []
            for i, target in enumerate(t["targets"]):
                if highest >= target:
                    tp_hit_before_sl.append(i)

            if tp_hit_before_sl:
                # ⚡ السعر وصل للهدف أول بعدين نزل للوقف — نحسبه ربح
                tp_hit = t.get("tp_hit", [])
                for i in tp_hit_before_sl:
                    if i not in tp_hit:
                        tp_hit.append(i)
                t["tp_hit"] = tp_hit
                # نحسب الربح من أول هدف تحقق
                first_tp = t["targets"][tp_hit_before_sl[0]]
                gain_pct = _calc_pnl(entry, first_tp)
                ai_conf = t.get("ai_confidence", 0)
                entry_type = t.get("entry_type", "now")
                entry_label = "🎯 فوري" if entry_type == "now" else "📉 معلق"
                alert = (
                    f"📊 **اشعار توصيه**\n\n"
                    f"🟢 **{sym}** » اول هدف ✅ (وصل {first_tp:.{dec}f} ثم تراجع)\n"
                    f"الربح » {gain_pct:+.2f}%\n"
                    f"اعلى سعر » `${highest:.{dec}f}`\n"
                    f"مده التوصيه » {duration}\n"
                )
                if ai_conf > 0:
                    alert += f"🧠 ثقة AI » {ai_conf:.0f}% | {entry_label}\n"
                alert += f"⚠️ متابعه العمله منتهيه لتحقيقها اول هدف"
                alerts.append(alert)
                to_remove.append(t)
                continue

            # ❌ ما وصل لأي هدف — خساره حقيقية
            ai_conf = t.get("ai_confidence", 0)
            entry_type = t.get("entry_type", "now")
            entry_label = "🎯 فوري" if entry_type == "now" else "📉 معلق"
            alert = (
                f"📊 **اشعار توصيه**\n\n"
                f"🔴 **{sym}** » وقف خساره ❌\n"
                f"الخساره » {loss_pct:.2f}%\n"
                f"اغلقت بسعر » `${cp:.{dec}f}`\n"
                f"مده التوصيه » {duration}\n"
            )
            if ai_conf > 0:
                alert += f"🧠 ثقة AI » {ai_conf:.0f}% | {entry_label}\n"
            alert += f"⚠️ متابعه العمله منتهيه لضرب وقف الخساره"
            alerts.append(alert)
            to_remove.append(t)

    # Remove completed trades immediately & save to history
    if to_remove:
        _save_to_history(to_remove)
        for t in to_remove:
            trades.remove(t)
        save_trades(trades)
    
    return trades, alerts


def _save_to_history(closed_trades: list):
    """Save completed trades to history file for daily reports"""
    try:
        history = []
        if HISTORY_FILE.exists():
            history = json.loads(HISTORY_FILE.read_text())
        for t in closed_trades:
            entry = t["entry_price"]
            highest = t.get("highest_price", entry)
            tp_hit_list = t.get("tp_hit", [])

            # تحديد حالة الصفقة
            if t.get("status") == "cancelled" or t.get("limit_status") == "cancelled":
                status = "cancelled"
                close_price = t.get("cancel_level", entry)
                pnl = 0  # لا ربح ولا خسارة
            elif tp_hit_list:
                status = "tp_hit"
                # استخدم أول هدف تحقق لحساب الربح
                first_tp_idx = min(tp_hit_list)
                close_price = t["targets"][first_tp_idx] if t.get("targets") else highest
                pnl = _calc_pnl(entry, close_price)
            else:
                status = "sl_hit"
                close_price = t.get("current_price", entry)
                pnl = _calc_pnl(entry, close_price)

            history.append({
                "symbol": t["symbol"],
                "entry_price": entry,
                "close_price": close_price,
                "pnl_pct": round(pnl, 2),
                "position_size_pct": POSITION_SIZE_PCT,
                "status": status,
                "timeframe": t.get("timeframe", "4h"),
                "strategies": t.get("strategies", []),  # ⭐ للتعلم الذاتي
                "confidence": t.get("confidence", 0),    # ⭐ لمعايرة AI
                "closed_at": time.time(),
                "closed_date": time.strftime("%Y-%m-%d %H:%M"),
                "added_date": t.get("added_date", ""),
                "duration_min": int((time.time() - t.get("added_at", time.time())) / 60),
            })
        HISTORY_FILE.write_text(json.dumps(history, indent=2))
        
        # 🤖 تسجيل النتيجة في نظام التعلم الذاتي v2
        try:
            from engine.self_learning_v2 import evaluate_closed_trade
            for entry in history[-len(closed_trades):] if closed_trades else []:
                evaluate_closed_trade(entry)
        except Exception as e:
            logger.warning(f"Self-learning v2 skipped: {e}")
        
        # 🛡️ تسجيل نتيجة الصفقة في Safety Walls (Phase 5.8)
        try:
            from engine.safety_walls import record_trade_result
            for entry in history[-len(closed_trades):] if closed_trades else []:
                pnl = entry.get("pnl_pct", 0)
                record_trade_result(pnl)
        except Exception as e:
            logger.debug(f"Safety record skipped: {e}")
        
        # 🆕 Track trade lifecycle (MFE/MAE close)
        try:
            from engine.portfolio_heat import track_trade_lifecycle
            for t in closed_trades:
                track_trade_lifecycle(t, is_closed=True)
        except Exception as e:
            logger.debug(f"Lifecycle tracking skipped: {e}")
        
        # 🧠 AI Calibration — سجل نتيجة الصفقة لمعايرة ثقة AI
        try:
            from engine.ai_calibrator import record_outcome
            for t in closed_trades:
                ai_conf = t.get("ai_confidence", 0)
                # Determine if win (TP hit or highest > entry)
                tp_hit = t.get("tp_hit", [])
                highest = t.get("highest_price", t.get("entry_price", 0))
                entry = t.get("entry_price", 0)
                was_win = bool(tp_hit) or (highest > entry * 1.005)  # 0.5% threshold
                if ai_conf > 0:
                    record_outcome(ai_conf, was_win, t.get("symbol", ""))
        except Exception as e:
            logger.debug(f"AI calibration skipped: {e}")
    except Exception as e:
        logger.error(f"Failed to save history: {e}")


def generate_daily_report() -> str:
    """
    تقرير يومي لكل المشتركين — قالب جديد: أفضل 5 + أسوأ 5 + ملخص العملات المتكررة
    """
    try:
        if not HISTORY_FILE.exists():
            return None
        
        history = json.loads(HISTORY_FILE.read_text())
        if not history:
            return None
        
        tz_utc3 = timezone(timedelta(hours=3))
        now_utc3 = datetime.now(tz_utc3)
        midnight_utc3 = now_utc3.replace(hour=0, minute=0, second=0, microsecond=0)
        
        day_start = midnight_utc3.timestamp()
        today_trades = [h for h in history if h.get("closed_at", 0) >= day_start]
        
        if today_trades:
            # فيه صفقات اليوم — اعرضها
            recent = today_trades
            report_date_str = now_utc3.strftime("%Y-%m-%d")
        elif now_utc3.hour < 6:
            # لسى ما في صفقات اليوم ولسى بدري — اعرض الأمس
            yesterday = midnight_utc3 - timedelta(days=1)
            day_start = yesterday.timestamp()
            day_end = midnight_utc3.timestamp()
            recent = [h for h in history if day_start <= h.get("closed_at", 0) < day_end]
            report_date_str = yesterday.strftime("%Y-%m-%d")
        else:
            recent = []
            report_date_str = now_utc3.strftime("%Y-%m-%d")
        
        if not recent:
            return None
        
        recent.sort(key=lambda h: h.get("closed_at", 0))
        
        wins = [h for h in recent if h["pnl_pct"] >= 0 and h.get("status") != "cancelled"]
        losses = [h for h in recent if h["pnl_pct"] < 0 and h.get("status") != "cancelled"]
        all_trades = [h for h in recent if h.get("status") != "cancelled"]
        # صافي = مجموع كل النسب (الناجحة - السالبة)
        n = len(all_trades)
        if n > 0:
            total_pnl_raw = sum(h["pnl_pct"] for h in all_trades)
            total_pnl = round(max(total_pnl_raw, -99.99), 2)
            sum_wins = sum(h["pnl_pct"] for h in all_trades if h["pnl_pct"] >= 0)
            sum_losses = sum(h["pnl_pct"] for h in all_trades if h["pnl_pct"] < 0)
        else:
            total_pnl = 0.0
            sum_wins = 0.0
            sum_losses = 0.0
        win_rate = round(len(wins) / max(len(wins) + len(losses), 1) * 100)
        
        lines = [
            "📊 **التقرير اليومي**",
            f"📅 {report_date_str} (UTC+3)",
            "",
        ]
        
        try:
            from engine.regime import get_cached_regime
            regime_data = get_cached_regime()
            if regime_data:
                regime = regime_data.get("regime", "?")
                regime_emoji = {"BULL": "🟢", "BEAR": "🔴", "RANGING": "🟡", "VOLATILE": "🟠"}.get(regime, "⚪")
                lines.append(f"🌊 السوق: {regime_emoji} {regime}")
                entry_filter = regime_data.get("entry_filter", "")
                if entry_filter:
                    lines.append(f"   فلتر: {entry_filter}")
        except Exception:
            logger.debug("Regime data unavailable for report")
        
        lines.append("")
        lines.append(f"✅ ناجحة: {len(wins)} | ❌ خاسرة: {len(losses)}")
        lines.append(f"📋 إجمالي: {len(recent)} | 🎯 نسبة النجاح: {win_rate}%")
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━")
        lines.append("")
        
        total_trades = len(recent)
        if total_trades > 30:
            lines.append(f"⚠ عدد الصفقات كبير ({total_trades}), عرض ملخص:")
            lines.append("")
        
        # Top 5 winners
        sorted_wins = sorted(wins, key=lambda h: h["pnl_pct"], reverse=True)
        lines.append("🏆 **أفضل 5 أرباح:**")
        top_n = min(5, len(sorted_wins))
        if top_n == 0:
            lines.append("  — لا يوجد")
        else:
            for h in sorted_wins[:top_n]:
                sym = h["symbol"].replace("USDT", "")
                lines.append(f"  🟢 {sym} » {h['pnl_pct']:+.2f}%")
        
        lines.append("")
        
        # Worst 5 losers
        sorted_losses = sorted(losses, key=lambda h: h["pnl_pct"])
        lines.append("💔 **أسوأ 5 خسائر:**")
        bottom_n = min(5, len(sorted_losses))
        if bottom_n == 0:
            lines.append("  — لا يوجد")
        else:
            for h in sorted_losses[:bottom_n]:
                sym = h["symbol"].replace("USDT", "")
                lines.append(f"  🔴 {sym} » {h['pnl_pct']:+.2f}%")
        
        lines.append("")
        
        # Per-coin summary (coins with 2+ trades)
        from collections import defaultdict
        sym_trades = defaultdict(list)
        for h in all_trades:
            sym = h["symbol"].replace("USDT", "")
            sym_trades[sym].append(h["pnl_pct"])
        
        multi_syms = [(s, pnls) for s, pnls in sym_trades.items() if len(pnls) >= 2]
        multi_syms.sort(key=lambda x: -len(x[1]) * 100 + sum(x[1]) / max(len(x[1]), 1))
        
        if multi_syms:
            lines.append("📊 **ملخص العملات:**")
            for sym, pnls in multi_syms[:15]:
                cnt = len(pnls)
                w = sum(1 for p in pnls if p >= 0)
                l = cnt - w
                total = sum(pnls)
                lines.append(f"  {sym}: {cnt} صفقة | {w}✔ {l}❌ | {total:+.2f}%")
            
            remaining_coins = len(sym_trades) - len(multi_syms)
            if remaining_coins > 0:
                lines.append(f"  ... و {remaining_coins} عملة أخرى")
        
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━")
        lines.append("")
        
        if n > 0:
            pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
            lines.append(f"{pnl_emoji} **صافي » {total_pnl:+.2f}%**")
        
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Failed to generate daily report: {e}")
        return None
def cleanup_trades():
    """إزالة الصفقات zombie (بحالة غير status="active") ومنع تراكمها"""
    try:
        trades = load_trades()
        cleaned = [t for t in trades if t.get("status") in ("active", "pending")]
        zombie_count = len(trades) - len(cleaned)
        if zombie_count > 0:
            save_trades(cleaned)
            logger.info(f"🧹 Cleaned {zombie_count} zombie trades from trades.json")
        return cleaned
    except Exception as e:
        logger.error(f"Failed to cleanup trades: {e}")
        return load_trades()


def get_active_trades() -> list:
    """Return active AND pending trades (without fetching live prices)"""
    trades = load_trades()
    trades = [t for t in trades if t.get("status") in ("active", "pending")]
    return trades


def format_trades_list(trades: list) -> str:
    """Format trade list for /list — includes pending"""
    trades = get_active_trades()

    if not trades:
        return (
            "📋 **التوصيات**\n\n"
            "لا توجد توصيات حالياً."
        )

    total_pnl = 0
    active_count = len([t for t in trades if t.get("status") == "active"])
    pending_count = len([t for t in trades if t.get("status") == "pending"])
    header = f"📋 **التوصيات — {len(trades)}/{MAX_TRADES}**"
    if pending_count > 0:
        header += f" ({pending_count} معلقة)"
    msg = [header]
    msg.append("")

    for i, t in enumerate(trades):
        sym = t["symbol"].replace("USDT", "")
        entry = t["entry_price"]
        cp = t.get("current_price", entry)
        status = t.get("status", "active")

        if status == "pending":
            # صفقة معلقة — لا ربح ولا خسارة
            msg.append(f"{i+1}. ⏳ **{sym}** [معلقة]")
            msg.append(f"   📥 أمر معلق @ ${entry:.8f}")
            msg.append(f"   📊 السعر الحالي: ${cp:.8f} (ينتظر التنفيذ)")
            sl = t["stop_loss"]
            sl_pct = (entry - sl) / entry * 100
            msg.append(f"   🛑 الوقف: ${sl:.8f} ({sl_pct:.2f}%)")
            msg.append(f"   🚫 يلغى إذا تجاوز: ${t.get('cancel_level', 0):.8f}" if t.get("cancel_level") else "")
            msg.append(f"   ⏱️ {t.get('added_date', '')}")
        else:
            # صفقة نشطة
            pnl_pct = _calc_pnl(entry, cp)
            total_pnl += pnl_pct
            pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"

            dec = 8 if entry < 1 else 6 if entry < 100 else 4 if entry < 1000 else 2

            msg.append(f"{i+1}. {pnl_emoji} **{sym}**")
            msg.append(f"   📥 Entry: `${entry:.{dec}f}`")
            msg.append(f"   📊 Current: `${cp:.{dec}f}` ({pnl_pct:+.2f}%)")

            if t.get("targets"):
                t1 = t["targets"][0]
                t1_pct = _calc_pnl(entry, t1)
                t1_status = "✅" if 0 in t.get("tp_hit", []) else "🎯"
                msg.append(f"   {t1_status} T1: `${t1:.{dec}f}` ({t1_pct:+.2f}%)")

            sl = t["stop_loss"]
            sl_pct = _calc_pnl(entry, sl)
            msg.append(f"   🛑 Stop: `${sl:.{dec}f}` ({sl_pct:.2f}%)")
            msg.append(f"   ⏱️ {t.get('added_date', '')} | Conf {t.get('confidence', 0):.0f}% | Str {t.get('strength', 0):.0f}%")

        msg.append("")

    # Total P&L (active trades only)
    if active_count > 0:
        avg_pnl = total_pnl / max(active_count, 1)
        total_emoji = "🟢" if avg_pnl > 0 else "🔴"
        msg.append(f"**{total_emoji} متوسط P&L:** {avg_pnl:+.2f}% (للصفقات النشطة)")

    return "\n".join(msg)
