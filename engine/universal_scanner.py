"""
🦅🌍 UNIVERSAL AI SCANNER — v3 ASATIR (أسطوري)
مسح كل عملات كل المنصات الخمس بدون استثناء
صفر تدخل ميكانيكي — AI عميق يقرر بتأني
كل عملة 10 ثواني — 24/7 بلا توقف — أسطوري
"""
import time
import json
import os
import logging
import time
import types
from pathlib import Path
logger = logging.getLogger("universal-scanner")

PROGRESS_FILE = Path("/root/.crypto-signal-bot/universal_progress.json")
BROADCAST_CACHE_FILE = Path("/root/.crypto-signal-bot/universal_broadcast_cache.json")
SIGNAL_MSGS_FILE = Path("/root/.crypto-signal-bot/signal_messages.json")
TRADES_FILE = Path("/root/.crypto-signal-bot/trades.json")
TRADES_HISTORY_FILE = Path("/root/.crypto-signal-bot/trades_history.json")
COOLDOWN_ACTIVE_SEC = 3600   # 1h — لا إشارة لنفس العملة وهي نشطة
COOLDOWN_CLOSED_SEC = 1800   # 30m — كول داون بعد إغلاق الصفقة
OWNER_ID = 528864559
MAX_ACTIVE_TRADES = 10  # حد أقصى 10 صفقات نشطة — للحفاظ على AI credits

# ─── Stablecoins comprehensive ───
STABLECOINS = {
   "USDC","BUSD","DAI","TUSD","USDG","FDUSD","EURS","EURC","USTC",
   "XAUT","PAXG","USDP","GUSD","HUSD","SUSD","LUSD","FRAX","USX",
   "UST","USDK","USDN","USDD","USDM","USDJ","USDO",
   "USD1","USD2","USD3","USD4","USD5","USD6","USD7","USD8","USD9",
   "USDE","USDF","USDH","USDI","USDL","USDM","USDQ","USDR",
   "USDT0","USDT1","USDT2","USDT3","USDT4","USDT5","USDT6",
   "CUSD","CEUR","EURL","EUROC","EUTB","ALUSD","MIM","FEI",
   "FRAX","LQDX","BAC","MAI",
   "RLUSD",  # Ripple USD
}

def _is_stablecoin(symbol: str) -> bool:
   sym = symbol.upper().replace("USDT", "")
   if sym in STABLECOINS:
       return True
   if sym.startswith("USD") and len(sym) > 3:
       return True
   if sym in ("3USD","4USD","CNYT","XCHF","XBASE"):
       return True
   if any(x in sym for x in ["3L","3S","5L","5S","BULL","BEAR","DOWN","UP","HEDGE"]):
       return True
   return False


STOCK_TOKEN_PREFIXES = ('R', 'Z')  # Known stock token prefixes

def _is_stock_token(symbol: str) -> bool:
   """Check if symbol is a stock token (e.g. RNVDAUSDT, RDELLUSDT)"""
   base = symbol.replace('USDT', '')
   if len(base) >= 2 and base[0] in STOCK_TOKEN_PREFIXES and base[1].isupper():
       # Check if after removing prefix, it looks like a stock (no numbers at start)
       stripped = base[1:]
       if stripped and stripped[0].isalpha():
           return True
   return False


# ═══════════════════════════════════════
# 🔒 DUPLICATION PREVENTION — 3 Layers
# ═══════════════════════════════════════

def _can_broadcast(symbol: str, broadcast_cache: dict) -> tuple:
   """
   3-layer duplication prevention.
   Returns (can_broadcast: bool, reason: str)
   Layer 1: broadcast_cache (1h cooldown)
   Layer 2: active/pending trades check
   Layer 3: recently closed trades (30min cooldown)
   """
   now = time.time()

   # Layer 1: Broadcast cache (1h)
   last_broadcast = broadcast_cache.get(symbol, 0)
   # Check file for thread-safety
   try:
       file_cache = _load_json(BROADCAST_CACHE_FILE)
       file_last = file_cache.get(symbol, 0)
       if file_last > last_broadcast:
           last_broadcast = file_last
           broadcast_cache[symbol] = file_last
   except Exception:
       logger.debug("Failed to load broadcast cache for %s", symbol)
   
   if now - last_broadcast < COOLDOWN_ACTIVE_SEC:
       remaining = int(COOLDOWN_ACTIVE_SEC - (now - last_broadcast))
       return False, f"مبثوثة منذ {remaining//60} دقيقة"

   # Layer 2: Active or pending trade in trades.json
   try:
       if TRADES_FILE.exists():
           trades = json.loads(TRADES_FILE.read_text())
           for t in trades:
               if t.get("symbol") == symbol and t.get("status") in ("active", "pending"):
                   return False, f"صفقة نشطة/معلقة"
   except Exception as e:
       logger.debug(f"  ⚠️ trades.json check failed: {e}")

   # Layer 3: Recently closed trade (30min cooldown)
   try:
       if TRADES_HISTORY_FILE.exists():
           history = json.loads(TRADES_HISTORY_FILE.read_text())
           for h in reversed(history):
               if h.get("symbol") == symbol:
                   closed_at = h.get("closed_at", 0)
                   if now - closed_at < COOLDOWN_CLOSED_SEC:
                       remaining = int(COOLDOWN_CLOSED_SEC - (now - closed_at))
                       return False, f"أغلقت منذ {remaining//60} دقيقة"
                   break
   except Exception as e:
       logger.debug(f"  ⚠️ history check failed: {e}")

   return True, ""


def _track_signal_messages(symbol: str, msg_ids: dict):
   """Save message_ids per symbol for reply-based updates"""
   try:
       data = _load_json(SIGNAL_MSGS_FILE)
       data[symbol] = msg_ids
       _save_json(SIGNAL_MSGS_FILE, data)
       logger.info(f"  📝 Tracked {len(msg_ids)} message IDs for {symbol}")
   except Exception as e:
       logger.debug(f"  ⚠️ Signal message tracking failed: {e}")


def _broadcast_update(symbol: str, update_text: str):
   """Send update as reply to original signal message"""
   try:
       data = _load_json(SIGNAL_MSGS_FILE)
       msg_ids = data.get(symbol, {})
       if not msg_ids:
           logger.info(f"  ⏭️ No tracked messages for {symbol} — can't send update as reply")
           return

       from bot.handlers import send_msg, load_subscribers
       sent = 0
       for chat_id_str, reply_to in msg_ids.items():
           try:
               chat_id = int(chat_id_str)
               mid = send_msg(chat_id, update_text, reply_to_msg_id=reply_to)
               if mid:
                   sent += 1
               time.sleep(0.1)
           except Exception as e:
               logger.debug(f"  ⚠️ Update reply failed for {chat_id_str}: {e}")
       logger.info(f"  📨 Update for {symbol}: {sent} replies sent")
   except Exception as e:
       logger.warning(f"  ⚠️ Update broadcast failed: {e}")


def _load_json(path):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        logger.debug(f"Failed to load {path}（returning empty）")
    return {}


def _save_json(path, data):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    except Exception:
        logger.error(f"Failed to save {path}")

def _count_active_trades() -> int:
   """Count active trades from TRADES_FILE. Returns 0 on failure."""
   try:
       if TRADES_FILE.exists():
           raw = json.loads(TRADES_FILE.read_text())
           if isinstance(raw, dict):
               return len(raw)
           elif isinstance(raw, list):
               return len([t for t in raw if t.get('status') in ('active', 'pending')])
   except Exception:
       logger.debug("Failed to count active trades（returning 0）")
   return 0


def _gather_all_exchange_coins(fetcher, min_volume: float = 500000):
   """
   🎯 Gather ALL coins from ALL exchanges, filter by volume.
   """
   from data.fetcher import EXCLUDED_SYMBOLS

   raw_pool = []
   stats = {}

   for provider in fetcher.providers:
       if not provider.healthy:
           stats[provider.name] = {"status": "unhealthy", "coins": 0}
           continue
       try:
           tickers = provider.fetch_tickers_24hr()
           count_before_filter = 0
           for t in tickers:
               sym = t["symbol"]
               if not sym.endswith("USDT"):
                   continue
               if _is_stablecoin(sym) or sym in EXCLUDED_SYMBOLS:
                   continue
               t["exchange"] = provider.name
               raw_pool.append(t)
               count_before_filter += 1
           stats[provider.name] = {"status": "healthy", "raw": count_before_filter}
           logger.info(f"  ✅ {provider.name}: {count_before_filter} raw USDT pairs")
       except Exception as e:
           stats[provider.name] = {"status": f"error: {str(e)[:50]}", "coins": 0}
           logger.warning(f"  ⚠️ {provider.name}: {e}")

   volume_sums = {}
   exchange_data = {}
   for t in raw_pool:
       sym = t["symbol"]
       vol = float(t.get("quote_volume", 0) or 0)
       volume_sums[sym] = volume_sums.get(sym, 0) + vol
       if sym not in exchange_data:
           exchange_data[sym] = {}
       exchange_data[sym][t["exchange"]] = t

   best = {}
   for sym, total_vol in volume_sums.items():
       if total_vol < min_volume:
           continue
       best_ticker = max(exchange_data[sym].values(), key=lambda t: float(t.get("quote_volume", 0) or 0))
       best_ticker["total_volume"] = round(total_vol, 2)
       best[sym] = best_ticker

   all_tickers = sorted(best.values(), key=lambda t: float(t.get("total_volume", 0) or 0), reverse=True)

   exchange_counts = {}
   for t in all_tickers:
       ex = t["exchange"]
       exchange_counts[ex] = exchange_counts.get(ex, 0) + 1
   for name in stats:
       if stats[name]["status"] == "healthy":
           stats[name]["coins"] = exchange_counts.get(name, 0)

   vol_brackets = {"≥$5M": 0, "$1M-5M": 0, "$500K-1M": 0}
   for t in all_tickers:
       tv = float(t.get("total_volume", 0))
       if tv >= 5_000_000:
           vol_brackets["≥$5M"] += 1
       elif tv >= 1_000_000:
           vol_brackets["$1M-5M"] += 1
       else:
           vol_brackets["$500K-1M"] += 1

   logger.info(f"  🎯 Dynamic filter: {len(raw_pool)} raw → {len(volume_sums)} unique → {len(best)} coins ≥ ${min_volume/1000:.0f}K → {len(all_tickers)} after dedup")
   logger.info(f"  📊 Volume brackets: {json.dumps(vol_brackets)}")
   return all_tickers, stats, volume_sums


def _wait_remaining(start_time):
   """Wait remaining time from start to maintain ~4s per coin"""
   elapsed = time.time() - start_time
   if elapsed < 3:
       time.sleep(3 - elapsed)


def _broadcast_signal(result, ai_result, symbol):
   try:
       agg = result.aggregated
       entry = agg.get("entry", 0)
       targets = agg.get("targets", [])
       sl = agg.get("stop_loss", 0)

       # Targets/SL already validated in scan loop — no auto-generation here

       from report.telegram import format_signal_report_arabic_simple
       from bot.handlers import broadcast
       try:
           from engine.regime import get_cached_regime
           regime_data = get_cached_regime() or {}
       except Exception:
           regime_data = {}

       report = format_signal_report_arabic_simple(
           result, is_signal=True,
           regime_str=regime_data.get("regime", ""),
           ai_result=ai_result,
       )
       keyboard = {
           "inline_keyboard": [[
               {"text": "➕ أضف إلى قائمتي", "callback_data": f"add_{symbol}"}
           ]]
       }
       msg_ids = broadcast(report, reply_markup=keyboard, return_msg_ids=True)
       if not msg_ids:
           logger.warning(f"  ⚠️ {symbol}: فشل الإرسال — لا يوجد مشتركين أو التوكن غير صالح")
           logger.warning(f"  ⚠️ {symbol}: لم يتم حفظ الصفقة لأنها لم ترسل فعلياً")
           return

       if msg_ids:
           _track_signal_messages(symbol, msg_ids)

       # 📝 Save signal to active trades tracker
       try:
           from bot.tracker import add_trade
           st = ai_result.get("strength", 0)
           conf = ai_result.get("confidence", 0)
           success, msg = add_trade(
               symbol=symbol,
               entry=entry,
               targets=targets,
               stop_loss=sl,
               confidence=conf,
               strength=st,
               timeframe="4h",
               entry_type="now",
               quality_score=conf,
               strategy_signals=["AI Strategy"],
           )
           if success:
               logger.info(f"  📋 Trade saved: {symbol}")
               try:
                   from bot.user_lists import subscribe_to_trade
                   subscribe_to_trade(symbol, OWNER_ID)
               except Exception as e:
                   logger.debug(f"  ⚠️ Owner subscribe failed: {e}")
           else:
               logger.warning(f"  ⚠️ {symbol}: add_trade failed: {msg}")
       except Exception as e:
           logger.warning(f"  ⚠️ Trade save error: {e}")

       logger.info(f"  📨 Broadcast: {symbol}")
   except Exception as e:
       logger.warning(f"  ⚠️ Broadcast error for {symbol}: {e}", exc_info=True)


# ═══════════════════════════════════════
# 🚀 MAIN SCANNER LOOP
# ═══════════════════════════════════════

def universal_scan_loop():
   """
   🚀 v3 ASATIR — Scan ALL coins from ALL exchanges, deep AI, 24/7
   """
   SCANNER_LOCK = "/tmp/cryptosignal-scanner.lock"
   old_pid = None
   if os.path.exists(SCANNER_LOCK):
      try:
         old_pid = int(open(SCANNER_LOCK).read().strip())
         os.kill(old_pid, 0)
         logger.warning(f"🔒 Scanner lock found (PID {old_pid}) — another scanner is running, exiting")
         return
      except (ValueError, ProcessLookupError):
         logger.info(f"🧹 Scanner lock stale (PID {old_pid}) — removing")
         try:
            os.unlink(SCANNER_LOCK)
         except Exception:
            logger.warning(f"Failed to remove stale lock {SCANNER_LOCK}")
      except Exception:
         logger.warning(f"Unexpected error reading scanner lock: {e}")

   try:
      with open(SCANNER_LOCK, "w") as f:
         f.write(str(os.getpid()))
      logger.info(f"🔒 Scanner lock acquired (PID {os.getpid()})")
   except Exception:
      logger.warning(f"Failed to acquire scanner lock {SCANNER_LOCK}")

   from data.fetcher import get_fetcher
   from engine.ai_analyst import analyze_coin_pure

   fetcher = get_fetcher()
   progress = _load_json(PROGRESS_FILE)
   broadcast_cache = _load_json(BROADCAST_CACHE_FILE)
   cycle = progress.get("cycle", 0)

   while True:
       cycle += 1

       # 🛑 قبل أي شيء — نتحقق من المساحة المتاحة عشان نوفر AI credits و API calls
       active_now = _count_active_trades()
       if active_now >= MAX_ACTIVE_TRADES:
           logger.info(f"🛑 CYCLE #{cycle}: مكتمل ({active_now}/{MAX_ACTIVE_TRADES}) — انتظار 5 دقائق بدون تحليل...")
           time.sleep(300)
           continue

       logger.info(f"🦅🌍 ===== UNIVERSAL CYCLE #{cycle} — ALL 5 EXCHANGES =====\n")

       tickers, exchange_stats, volume_sums = _gather_all_exchange_coins(fetcher)

       total = len(tickers)
       logger.info(f"📊 Exchange summary: {json.dumps(exchange_stats, indent=2)}")
       logger.info(f"📡 TOTAL: {total} unique moving coins across all exchanges")

       coin_list = [(t["symbol"], t.get("exchange", "")) for t in tickers]

       start_idx = progress.get("index", 0) if progress.get("cycle") == cycle else 0
       if start_idx >= total or start_idx < 0:
           start_idx = 0

       coins_analyzed = 0
       signals_found = 0
       cycle_start = time.time()

       for i in range(start_idx, total):
           symbol, source_exchange = coin_list[i]

           # ⏭️ Stock token filter — R/Z prefix tokens (e.g. RNVDAUSDT, RDELLUSDT)
           if _is_stock_token(symbol):
               logger.info(f"  ⏭️ {symbol}: stock token (ممنوع)")
               continue

           coin_start = time.time()

           try:
               can_bd, reason = _can_broadcast(symbol, broadcast_cache)
               if not can_bd:
                   coins_analyzed += 1
                   logger.info(f"  ⏭️ {symbol}: مكرر ({reason})")
                   _wait_remaining(coin_start)
                   continue

               # 🛑 حد أقصى — إيقاف الدورة فوراً للحفاظ على AI credits
               if _count_active_trades() >= MAX_ACTIVE_TRADES:
                   logger.info(f"  🛑 بلغ الحد الأقصى ({_count_active_trades()}/{MAX_ACTIVE_TRADES}) — إيقاف الدورة")
                   # إعادة الدورة للصفر عشان الجاية تبدأ من أول (الأسعار تغيرت)
                   progress = {"cycle": cycle, "index": 0, "total_coins": total}
                   _save_json(PROGRESS_FILE, progress)
                   break

               df = fetcher.fetch_klines_from(symbol, "4h", 200, preferred=source_exchange)
               if df is None or len(df) < 50:
                   coins_analyzed += 1
                   logger.info(f"  ⏭️ {symbol}: بيانات غير كافية (klines={len(df) if df is not None else None})")
                   _wait_remaining(coin_start)
                   continue

               try:
                   from engine.regime import get_cached_regime
                   regime_data = get_cached_regime() or {}
               except Exception:
                   regime_data = {}

               try:
                   last_close = df["close"].iloc[-1]
                   price_str = str(last_close).rstrip('.')
                   if not price_str or price_str == '.':
                       raise ValueError
                   price = float(price_str)
               except (ValueError, TypeError):
                   logger.info(f"  ⏭️ {symbol}: سعر غير صالح ({df['close'].iloc[-1]})")
                   coins_analyzed += 1
                   _wait_remaining(coin_start)
                   continue

               ai_result = analyze_coin_pure(symbol, price, df, regime_data)

               if ai_result is None:
                   coins_analyzed += 1
                   logger.info(f"  ⏭️ {symbol}: AI فشل (None)")
                   _wait_remaining(coin_start)
                   continue

               ai_decision = ai_result.get("decision", "SKIP").upper()
               ai_direction = ai_result.get("direction", "").upper()
               ai_conf = ai_result.get("confidence", 0)
               ai_strength = ai_result.get("strength", 0)

               # Adaptive thresholds
               try:
                   from engine.self_learning_v2 import get_adaptive_thresholds
                   adj_strength, adj_conf = get_adaptive_thresholds(25, 40)
                   if ai_conf < adj_conf:
                       logger.debug(f"  ⏭️ {symbol}: confidence {ai_conf}% < adaptive {adj_conf}% — skipped")
                       coins_analyzed += 1
                       _wait_remaining(coin_start)
                       continue
               except Exception as e:
                   logger.debug(f"Adaptive thresholds unavailable: {e}")

               if ai_decision == "ENTER" and ai_direction != "SELL":
                   # Validate entry/targets/SL
                   ai_entry = ai_result.get("entry", 0)
                   targets = ai_result.get("targets", [])
                   ai_sl = ai_result.get("stop_loss", 0)
                   
                   if ai_entry <= 0 or ai_entry > price * 1.2:
                       logger.info(f"  🔧 {symbol}: AI entry ${ai_entry:.6f} too high, using current ${price:.6f}")
                       ai_entry = price
                       ai_result["entry"] = price
                   if ai_entry < price * 0.5:
                       logger.info(f"  🔧 {symbol}: AI entry ${ai_entry:.6f} too low, using current ${price:.6f}")
                       ai_entry = price
                       ai_result["entry"] = price
                   
                   # 🛡️ Validate SL & targets from AI analysis — ممنوع التوليد التلقائي
                   if not ai_sl or not targets or len(targets) == 0:
                       logger.info(f"  ⏭️ {symbol}: AI لم يعطِ أهدافاً أو ستوب لوز — رفض")
                       coins_analyzed += 1
                       _wait_remaining(coin_start)
                       continue

                   # SL must be below entry for BUY
                   if ai_sl >= ai_entry:
                       logger.info(f"  ⏭️ {symbol}: SL ({ai_sl:.6f}) ≥ entry ({ai_entry:.6f}) — ستوب فوق السعر, رفض")
                       coins_analyzed += 1
                       _wait_remaining(coin_start)
                       continue

                   # All targets must be above entry
                   targets = [t for t in targets if t > ai_entry]
                   if not targets:
                       logger.info(f"  ⏭️ {symbol}: جميع الأهداف تحت سعر الدخول — رفض")
                       coins_analyzed += 1
                       _wait_remaining(coin_start)
                       continue

                   sl_dist = abs(ai_entry - ai_sl) / ai_entry * 100
                   tp1_dist = abs(targets[0] - ai_entry) / ai_entry * 100

                   # 🚫 SL ≥ 3% — رفض
                   if sl_dist >= 3.0:
                       logger.info(f"  ⏭️ {symbol}: SL {sl_dist:.2f}% ≥ 3% — مخاطرة عالية, رفض")
                       coins_analyzed += 1
                       _wait_remaining(coin_start)
                       continue

                   # 🚫 SL ≥ TP1 (R:R < 1:1) — رفض
                   if tp1_dist > 0 and sl_dist >= tp1_dist:
                       logger.info(f"  ⏭️ {symbol}: SL {sl_dist:.2f}% ≥ TP1 {tp1_dist:.2f}% — خسارة أكبر من الربح, رفض")
                       coins_analyzed += 1
                       _wait_remaining(coin_start)
                       continue

                   ai_result["targets"] = targets

                   
                   # Fetch live price
                   try:
                       prices = fetcher.fetch_all_prices()
                       live_price = prices.get(symbol)
                       if live_price and live_price > 0 and live_price != price:
                           change_pct = abs(live_price - price) / price * 100
                           if change_pct > 0.1:
                               logger.info(f"  🔄 {symbol}: kline close ${price:.{6 if price < 1 else 4}f} → real-time ${live_price:.{6 if live_price < 1 else 4}f} ({change_pct:.2f}%)")
                               if price > 0 and ai_result.get("entry"):
                                   old_entry = ai_result["entry"]
                                   if ai_result.get("stop_loss"):
                                       sl_pct = (old_entry - ai_result["stop_loss"]) / old_entry
                                       new_sl = round(live_price * (1 - sl_pct), 8)
                                       ai_result["stop_loss"] = new_sl
                                   if ai_result.get("targets"):
                                       new_targets = []
                                       for t in ai_result["targets"]:
                                           tp_pct = (t - old_entry) / old_entry
                                           new_tp = round(live_price * (1 + tp_pct), 8)
                                           new_targets.append(new_tp)
                                       ai_result["targets"] = new_targets
                                       targets = new_targets
                                   ai_result["entry"] = live_price
                                   price = live_price
                                   ai_entry = live_price
                   except Exception as e:
                       logger.debug(f"  ⚠️ {symbol}: Live price unavailable: {e}")
                   
                   # Create fake AnalysisResult for broadcast
                   fake_result = types.SimpleNamespace(
                       symbol=symbol,
                       price=price,
                       timeframe="4h",
                       signals=[],
                       sr={},
                       aggregated={
                           "direction": "BUY",
                           "entry": ai_result.get("entry", price),
                           "targets": ai_result.get("targets", []),
                           "stop_loss": ai_result.get("stop_loss", 0),
                           "confidence": ai_conf,
                           "strength": ai_strength,
                           "buy_count": 1,
                           "sell_count": 0,
                       },
                   )
                   signals_found += 1
                   _broadcast_signal(fake_result, ai_result, symbol)
                   logger.info(f"  ✅🚀 SIGNAL #{signals_found}: {symbol} ({ai_conf}%)")
                   broadcast_cache[symbol] = time.time()
               else:
                   if ai_direction == "SELL":
                       logger.info(f"  ⏭️ {symbol}: SELL ({ai_conf}%)")
                   else:
                       logger.info(f"  ⏭️ {symbol}: SKIP ({ai_conf}%)")
               
               coins_analyzed += 1
               _wait_remaining(coin_start)
               
               # Save progress
               progress = {"cycle": cycle, "index": i + 1, "total_coins": total}
               _save_json(PROGRESS_FILE, progress)
           
           except Exception as e:
               logger.warning(f"  ⚠️ Error scanning {symbol}: {e}")
               continue
       
       # Cycle complete
       elapsed = time.time() - cycle_start
       logger.info(f"\U0001f98e\U0001f30d CYCLE #{cycle} COMPLETE: {coins_analyzed} coins, {signals_found} signals in {elapsed:.0f}s")
       
       # Reset progress for next cycle
       progress = {"cycle": cycle, "index": 0, "total_coins": total}
       _save_json(PROGRESS_FILE, progress)
       
       # Wait between cycles
       active_now = _count_active_trades()
       if active_now >= MAX_ACTIVE_TRADES:
           # 🛑 مكتمل — بدلاً من التعليق للأبد، ننتظر بذكاء مع logs وننتقل للدورة التالية
           logger.info(f"🛑 CYCLE #{cycle} بلغ الحد الأقصى ({active_now}/{MAX_ACTIVE_TRADES}) — انتظار ذكي للمساحة...")
           wait_cycles = 0
           while _count_active_trades() >= MAX_ACTIVE_TRADES:
               wait_cycles += 1
               if wait_cycles == 1:
                   wait_time = 300  # أول مرة: 5 دقائق
               elif wait_cycles == 2:
                   wait_time = 600  # ثاني مرة: 10 دقائق
               else:
                   wait_time = 600  # باقي المرات: 10 دقائق (بدون زيادة لا نهائية)
               current_active = _count_active_trades()
               logger.info(f"⏳ Scanner waiting: {current_active}/{MAX_ACTIVE_TRADES} active trades — check again in {wait_time//60}min (wait attempt #{wait_cycles})")
               time.sleep(wait_time)
               if _count_active_trades() < MAX_ACTIVE_TRADES:
                   logger.info(f"✅ مساحة متاحة! ({_count_active_trades()}/{MAX_ACTIVE_TRADES}) — بدء الدورة الجديدة")
                   break
               # بعد 3 محاولات، ننتقل للدورة التالية على أي حال
               if wait_cycles >= 3:
                   logger.info(f"🔄 Still full at {_count_active_trades()}/{MAX_ACTIVE_TRADES} — proceeding with next cycle anyway")
                   break
       else:
           # عادي — انتظر المدة المتبقية قبل الدورة الجديدة
           if elapsed < 3600:
               wait = 3600 - elapsed
               logger.info(f"⏳ انتظار {wait:.0f}s قبل الدورة التالية...")
               time.sleep(wait)
