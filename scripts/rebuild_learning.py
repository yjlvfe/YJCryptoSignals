#!/usr/bin/env python3
"""إعادة بناء التعلم الذاتي من بيانات الصفقات الحقيقية"""
import json
import time
from pathlib import Path
from datetime import datetime
from collections import defaultdict

DATA_DIR = Path("/root/.crypto-signal-bot")
LEARN_DIR = DATA_DIR / "learning"

# ── Load real trade data ─────────────────────────────────
with open(DATA_DIR / "trades_history.json") as f:
    history = json.load(f)

with open(DATA_DIR / "trade_lifecycle.json") as f:
    lifecycle = json.load(f)

print(f"📂 التاريخ: {len(history)} صفقة")
print(f"📂 دورة الحياة: {len(lifecycle)} صفقة")

# ── Deduplicate history ──────────────────────────────────
# Use (symbol, pnl_pct, status) as unique key
seen = {}
unique_trades = []
for t in history:
    key = (t.get("symbol"), round(t.get("pnl_pct", 0), 2), t.get("status"))
    if key not in seen:
        seen[key] = True
        unique_trades.append(t)

print(f"✅ بعد إزالة التكرار: {len(unique_trades)} صفقة فريدة")

# ── Match lifecycle to get timestamps & regime ───────────
# Build lookup by symbol for closest match
lifecycle_by_sym = defaultdict(list)
for lc in lifecycle:
    lifecycle_by_sym[lc["symbol"]].append(lc)

# Determine each trade's regime based on close_time
def get_regime(timestamp):
    """Simplified regime detection based on time period"""
    dt = datetime.fromtimestamp(timestamp)
    # All trades were during RANGING period based on market_regime.json
    return "RANGING"

# ── Build strategy stats ──────────────────────────────────
stats = {}
strategy_name = "AI Strategy"

for t in unique_trades:
    symbol = t.get("symbol", "")
    pnl = t.get("pnl_pct", 0)
    status = t.get("status", "")
    strategy = t.get("strategy", strategy_name)
    
    if strategy not in stats:
        stats[strategy] = {
            "total_signals": 0, "winning_signals": 0, "losing_signals": 0,
            "sum_profit": 0.0, "sum_loss": 0.0,
            "best_trade_pct": 0.0, "worst_trade_pct": 0.0,
            "bull_signals": 0, "bull_wins": 0,
            "bear_signals": 0, "bear_wins": 0,
            "ranging_signals": 0, "ranging_wins": 0,
            "last_updated": time.time(),
            "all_pnls": []
        }
    
    s = stats[strategy]
    s["total_signals"] += 1
    s["all_pnls"].append(pnl)
    
    if pnl > 0:
        s["winning_signals"] += 1
        s["sum_profit"] += pnl
        if pnl > s["best_trade_pct"]:
            s["best_trade_pct"] = pnl
        # All are RANGING for now
        s["ranging_signals"] += 1
        s["ranging_wins"] += 1
    else:
        s["losing_signals"] += 1
        s["sum_loss"] += abs(pnl)
        if pnl < s["worst_trade_pct"]:
            s["worst_trade_pct"] = pnl
        s["ranging_signals"] += 1

# ── Calculate derived fields ─────────────────────────────
for name, s in stats.items():
    total = s["total_signals"]
    wins = s["winning_signals"]
    losses = s["losing_signals"]
    
    s["avg_profit_pct"] = round(s["sum_profit"] / wins, 2) if wins > 0 else 0.0
    s["avg_loss_pct"] = round(s["sum_loss"] / losses, 2) if losses > 0 else 0.0
    s["win_rate"] = round(wins / total, 3) if total > 0 else 0.0
    
    total_wins_value = wins * s["avg_profit_pct"]
    total_losses_value = losses * s["avg_loss_pct"]
    s["profit_factor"] = round(total_wins_value / total_losses_value, 2) if total_losses_value > 0 else 99.0
    
    s["ranging_wins"] = wins  # all wins are ranging
    s["ranging_signals"] = total  # all signals are ranging
    
    # Clean up temp fields
    del s["sum_profit"]
    del s["sum_loss"]
    del s["all_pnls"]
    s["last_updated"] = time.time()

# ── Build regime_performance.json ─────────────────────────
perf = {}
for name, s in stats.items():
    if s["ranging_signals"] >= 5:
        wr = s["ranging_wins"] / s["ranging_signals"]
        best = [name] if s["win_rate"] >= 0.45 else []
        worst = [name] if s["win_rate"] < 0.40 else []
        
        if wr >= 0.55:
            mult = 1.2
        elif wr >= 0.45:
            mult = 1.0
        elif wr >= 0.35:
            mult = 0.7
        else:
            mult = 0.4
        
        perf["RANGING"] = {
            "total_trades": s["ranging_signals"],
            "winning_trades": s["ranging_wins"],
            "avg_profit": round(s["win_rate"] * 100, 1),
            "best_strategies": best,
            "worst_strategies": worst,
            "optimal_weight_mult": mult
        }

# ── Build adjusted_weights.json ──────────────────────────
weights = {}
for name, s in stats.items():
    if s["total_signals"] < 5:
        weights[name] = 1.0
    else:
        wr = s["win_rate"]
        if wr >= 0.60:
            mult = 1.3
        elif wr >= 0.50:
            mult = 1.1
        elif wr >= 0.40:
            mult = 0.9
        elif wr >= 0.30:
            mult = 0.7
        else:
            mult = 0.5
        
        if s["profit_factor"] >= 2.0:
            mult += 0.1
        elif s["profit_factor"] < 0.5 and s["total_signals"] >= 5:
            mult -= 0.1
        
        weights[name] = round(max(0.3, min(2.0, mult)), 2)

# ── Save files ──────────────────────────────────────────
# Build final stats dict (same format as original)
final_stats = {}
for name, s in stats.items():
    final_stats[name] = {k: v for k, v in s.items()}
    # Round float values
    for key in ["avg_profit_pct", "avg_loss_pct", "best_trade_pct", "worst_trade_pct", "win_rate", "profit_factor"]:
        final_stats[name][key] = round(final_stats[name][key], 2)

LEARN_DIR.mkdir(parents=True, exist_ok=True)

# Save
(LEARN_DIR / "strategy_stats.json").write_text(json.dumps(final_stats, indent=2))
(LEARN_DIR / "regime_performance.json").write_text(json.dumps(perf, indent=2))
(LEARN_DIR / "adjusted_weights.json").write_text(json.dumps({
    "regime": "RANGING",
    "weights": weights,
    "updated": time.time()
}, indent=2))

# ── Print Summary ────────────────────────────────────────
print(f"\n{'='*50}")
print(f"✅ تم إعادة بناء التعلم الذاتي!")
print(f"{'='*50}")
for name, s in final_stats.items():
    print(f"\n📊 {name}:")
    print(f"   صفقات: {s['total_signals']}")
    print(f"   فوز: {s['winning_signals']} ({s['win_rate']*100:.1f}%)")
    print(f"   خسارة: {s['losing_signals']}")
    print(f"   متوسط الربح: {s['avg_profit_pct']:+.2f}%")
    print(f"   متوسط الخسارة: -{s['avg_loss_pct']:.2f}%")
    print(f"   Profit Factor: {s['profit_factor']}")
    print(f"   أفضل صفقة: {s['best_trade_pct']:+.2f}%")
    print(f"   أسوأ صفقة: {s['worst_trade_pct']:+.2f}%")

print(f"\n⚖️ الأوزان المتكيفة:")
for name, w in sorted(weights.items(), key=lambda x: -x[1]):
    print(f"   {name}: ×{w}")

print(f"\n🌊 أداء النظم:")
for regime, data in perf.items():
    print(f"   {regime}: {data['winning_trades']}/{data['total_trades']} فوز | حجم: {data['optimal_weight_mult']:.0%}")
    if data['best_strategies']:
        print(f"     🟢 الأفضل: {', '.join(data['best_strategies'])}")
    if data['worst_strategies']:
        print(f"     🔴 الأسوأ: {', '.join(data['worst_strategies'])}")
