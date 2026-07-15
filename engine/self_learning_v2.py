"""
🧠 Self-Learning Engine v2 — Learns from closed trades
محور ١٤: تعلم ذاتي — يعرف أي استراتيجية تربح في أي سوق

Tracks per-strategy performance across market regimes:
  - Which strategies win most in BEAR markets?
  - Which patterns are most reliable in BULL markets?
  - Adjusts strategy weights dynamically based on win rate.

All data persisted to JSON for survival across restarts.
"""
import json
import time
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import math

logger = logging.getLogger("crypto-signal-selflearn")

# ═══════════════════════════════════════
# Config
# ═══════════════════════════════════════
LEARN_DIR = Path("/root/.crypto-signal-bot/learning")
LEARN_DIR.mkdir(parents=True, exist_ok=True)
LEARN_FILE = LEARN_DIR / "strategy_stats.json"
WEIGHTS_FILE = LEARN_DIR / "adjusted_weights.json"
PERF_FILE = LEARN_DIR / "regime_performance.json"

# ═══════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════

@dataclass
class StrategyStats:
    """Per-strategy performance tracking."""
    name: str
    total_signals: int = 0
    winning_signals: int = 0
    losing_signals: int = 0
    avg_profit_pct: float = 0.0
    avg_loss_pct: float = 0.0
    best_trade_pct: float = 0.0
    worst_trade_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    last_updated: float = 0.0
    
    # Per-regime breakdown
    bull_signals: int = 0
    bull_wins: int = 0
    bear_signals: int = 0
    bear_wins: int = 0
    ranging_signals: int = 0
    ranging_wins: int = 0


@dataclass
class RegimePerformance:
    """Market regime performance analysis."""
    regime: str                     # "BULL" / "BEAR" / "RANGING" / "VOLATILE"
    total_trades: int = 0
    winning_trades: int = 0
    avg_profit: float = 0.0
    best_strategies: List[str] = field(default_factory=list)  # top 3
    worst_strategies: List[str] = field(default_factory=list)  # bottom 3
    optimal_weight_mult: float = 1.0  # position size multiplier for this regime


@dataclass
class TradeRecord:
    """Record of a closed trade for learning."""
    symbol: str
    direction: str           # BUY / SELL
    entry: float
    exit: float
    profit_pct: float
    strategies_used: List[str]
    market_regime: str       # BULL / BEAR / RANGING / VOLATILE
    btc_trend: str           # UP / DOWN / SIDEWAYS
    duration_hours: float
    closed_at: float         # timestamp


# ═══════════════════════════════════════
# Persistence
# ═══════════════════════════════════════

def _load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception as e:
        logger.debug(f"JSON load failed for {path.name}: {e}")
    return {}


def _save_json(path: Path, data: dict):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, default=str))
    except Exception as e:
        logger.error(f"Failed to save {path.name}: {e}")


# ═══════════════════════════════════════
# Strategy Performance Tracking
# ═══════════════════════════════════════

# In-memory stats (persisted to disk)
_strategy_stats: Dict[str, StrategyStats] = {}
_stats_lock = threading.Lock()


def _get_or_create_stats(name: str) -> StrategyStats:
    """Get or create strategy stats."""
    if name not in _strategy_stats:
        _strategy_stats[name] = StrategyStats(name=name)
    return _strategy_stats[name]


def record_trade_outcome(trade_record: TradeRecord):
    """
    Record a closed trade outcome for learning.
    
    Called when a trade closes (TP, SL, or manual).
    Updates strategy stats and regime performance.
    """
    with _stats_lock:
        regime = trade_record.market_regime
        
        for strategy in trade_record.strategies_used:
            stats = _get_or_create_stats(strategy)
            stats.total_signals += 1
            stats.last_updated = time.time()
            
            # Win/loss tracking
            if trade_record.profit_pct > 0:
                stats.winning_signals += 1
                stats.avg_profit_pct = (
                    (stats.avg_profit_pct * (stats.winning_signals - 1) + trade_record.profit_pct)
                    / stats.winning_signals
                )
                stats.best_trade_pct = max(stats.best_trade_pct, trade_record.profit_pct)
            else:
                stats.losing_signals += 1
                stats.avg_loss_pct = (
                    (stats.avg_loss_pct * (stats.losing_signals - 1) + abs(trade_record.profit_pct))
                    / stats.losing_signals
                )
                stats.worst_trade_pct = min(stats.worst_trade_pct, trade_record.profit_pct)
            
            # Win rate
            if stats.total_signals > 0:
                stats.win_rate = stats.winning_signals / stats.total_signals
            
            # Profit factor
            total_wins = stats.winning_signals * stats.avg_profit_pct
            total_losses = stats.losing_signals * stats.avg_loss_pct
            stats.profit_factor = total_wins / total_losses if total_losses > 0 else 99.0
            
            # Per-regime tracking
            if regime == "BULL":
                stats.bull_signals += 1
                if trade_record.profit_pct > 0:
                    stats.bull_wins += 1
            elif regime == "BEAR":
                stats.bear_signals += 1
                if trade_record.profit_pct > 0:
                    stats.bear_wins += 1
            elif regime == "RANGING":
                stats.ranging_signals += 1
                if trade_record.profit_pct > 0:
                    stats.ranging_wins += 1
        
        # Save to disk
        _persist_stats()
        _update_regime_performance()


def _persist_stats():
    """Save stats to JSON."""
    data = {}
    for name, stats in _strategy_stats.items():
        data[name] = {
            "total_signals": stats.total_signals,
            "winning_signals": stats.winning_signals,
            "losing_signals": stats.losing_signals,
            "avg_profit_pct": round(stats.avg_profit_pct, 2),
            "avg_loss_pct": round(stats.avg_loss_pct, 2),
            "best_trade_pct": round(stats.best_trade_pct, 2),
            "worst_trade_pct": round(stats.worst_trade_pct, 2),
            "win_rate": round(stats.win_rate, 3),
            "profit_factor": round(stats.profit_factor, 2),
            "bull_signals": stats.bull_signals,
            "bull_wins": stats.bull_wins,
            "bear_signals": stats.bear_signals,
            "bear_wins": stats.bear_wins,
            "ranging_signals": stats.ranging_signals,
            "ranging_wins": stats.ranging_wins,
            "last_updated": stats.last_updated,
        }
    _save_json(LEARN_FILE, data)


def load_stats():
    """Load stats from disk on startup."""
    global _strategy_stats
    data = _load_json(LEARN_FILE)
    with _stats_lock:
        for name, d in data.items():
            stats = StrategyStats(name=name)
            stats.total_signals = d.get("total_signals", 0)
            stats.winning_signals = d.get("winning_signals", 0)
            stats.losing_signals = d.get("losing_signals", 0)
            stats.avg_profit_pct = d.get("avg_profit_pct", 0)
            stats.avg_loss_pct = d.get("avg_loss_pct", 0)
            stats.best_trade_pct = d.get("best_trade_pct", 0)
            stats.worst_trade_pct = d.get("worst_trade_pct", 0)
            stats.win_rate = d.get("win_rate", 0)
            stats.profit_factor = d.get("profit_factor", 0)
            stats.bull_signals = d.get("bull_signals", 0)
            stats.bull_wins = d.get("bull_wins", 0)
            stats.bear_signals = d.get("bear_signals", 0)
            stats.bear_wins = d.get("bear_wins", 0)
            stats.ranging_signals = d.get("ranging_signals", 0)
            stats.ranging_wins = d.get("ranging_wins", 0)
            stats.last_updated = d.get("last_updated", 0)
            _strategy_stats[name] = stats

def get_all_stats() -> dict:
    """Return all strategy stats — used by adaptive thresholds"""
    return dict(_strategy_stats)


def _wilson_lower_bound(wins: int, total: int, z: float = 1.96) -> float:
    """Wilson score lower bound — conservative win rate estimate at 95% CI.
    
    Guards against over-trusting strategies with few trades that got lucky.
    Returns 0 if total is 0, otherwise the lower bound of the confidence interval.
    """
    if total <= 0:
        return 0.0
    p = wins / total
    if total < 30:
        # Not enough data — use a stronger penalty: reduce z for fewer trades
        z = 1.44  # 85% CI for small samples
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    ci = z * math.sqrt((p * (1 - p) / total + z * z / (4 * total * total))) / denom
    return max(0.0, center - ci)


def get_adjusted_weights(current_regime: str = "BEAR",
                         base_weights: Dict[str, float] = None) -> Dict[str, float]:
    """
    Compute dynamically adjusted strategy weights based on historical performance.
    
    Strategies with higher win rate in the current regime get boosted.
    Strategies with poor performance get reduced.
    
    Args:
        current_regime: BULL / BEAR / RANGING / VOLATILE
        base_weights: default weights (if None, all strategies start at 1.0)
        
    Returns:
        dict of {strategy_name: weight_multiplier}
    """
    if base_weights is None:
        base_weights = {}
    
    adjusted = {}
    kill_switched = []
    
    with _stats_lock:
        for name, stats in _strategy_stats.items():
            base = base_weights.get(name, 1.0)
            
            # ─── Get regime-specific data ───
            if current_regime == "BULL":
                regime_signals = stats.bull_signals
                regime_wins = stats.bull_wins
            elif current_regime == "BEAR":
                regime_signals = stats.bear_signals
                regime_wins = stats.bear_wins
            elif current_regime == "RANGING":
                regime_signals = stats.ranging_signals
                regime_wins = stats.ranging_wins
            else:
                regime_signals = 0
                regime_wins = 0
            
            # ─── 🔴 KILL SWITCH (Fix 1) ───
            # If a strategy has catastrophic performance after enough trades → ZERO
            enough_data = stats.total_signals >= 10
            if enough_data:
                wr_catastrophic = stats.win_rate <= 0.10
                pf_catastrophic = stats.profit_factor <= 0.10
                if wr_catastrophic or pf_catastrophic:
                    adjusted[name] = 0.0
                    kill_switched.append(name)
                    logger.warning(
                        f"🔴 KILL SWITCH: {name} disabled "
                        f"(WR={stats.win_rate:.1%}, PF={stats.profit_factor:.2f}, "
                        f"trades={stats.total_signals})"
                    )
                    continue
            
            # ─── 🟠 Minimum 30 trades for regime-specific adjustment (Fix 5) ───
            if regime_signals >= 30:
                # Confident adjustment with Wilson CI lower bound
                regime_win_rate = _wilson_lower_bound(regime_wins, regime_signals)
                use_overall = False
            elif stats.total_signals >= 30:
                # Fall back to overall win rate if regime data insufficient
                regime_win_rate = _wilson_lower_bound(stats.winning_signals, stats.total_signals)
                use_overall = True
            else:
                # Not enough data — keep base weight, don't adjust yet
                adjusted[name] = base
                continue
            
            # ─── Determine multiplier from win rate ───
            # More granular and aggressive on the downside
            if regime_win_rate >= 0.65:
                multiplier = 1.5
            elif regime_win_rate >= 0.55:
                multiplier = 1.25
            elif regime_win_rate >= 0.50:
                multiplier = 1.1
            elif regime_win_rate >= 0.45:
                multiplier = 0.9
            elif regime_win_rate >= 0.35:
                multiplier = 0.6
            elif regime_win_rate >= 0.25:
                multiplier = 0.4
            else:
                multiplier = 0.2  # Very poor but not kill-switch territory
            
            # ─── 🟠 Loss-Aware Weighting (Fix 6) ───
            # Penalize strategies with severe losses, reward tight SL discipline
            if stats.total_signals >= 5 and stats.avg_loss_pct > 0:
                # Baseline: 5% avg loss is normal
                loss_severity = stats.avg_loss_pct / 5.0
                if loss_severity > 1.5:
                    # Losses 50%+ worse than baseline → heavy penalty
                    multiplier *= max(0.3, 1.0 - (loss_severity - 1.5) * 0.4)
                    logger.debug(
                        f"📉 Loss penalty: {name} avg_loss={stats.avg_loss_pct:.1f}% "
                        f"(severity={loss_severity:.1f}x) → mult={multiplier:.2f}"
                    )
                elif loss_severity < 0.7:
                    # Tight stops → small bonus
                    multiplier *= min(1.15, 1.0 + (0.7 - loss_severity) * 0.3)
            
            # Profit factor bonus (but not as aggressive)
            if stats.profit_factor >= 3.0 and stats.total_signals >= 10:
                multiplier += 0.1
            elif stats.profit_factor < 0.3 and stats.total_signals >= 10:
                multiplier -= 0.15
            
            # Clamp: 0.0 to 2.5 (note: 0.0 is possible via kill switch only)
            adjusted[name] = round(base * max(0.05, min(2.5, multiplier)), 2)
    
    # Save adjusted weights
    _save_json(WEIGHTS_FILE, {
        "regime": current_regime,
        "weights": adjusted,
        "kill_switched": kill_switched,
        "updated": time.time(),
    })
    
    if kill_switched:
        logger.warning(f"🔴 KILL SWITCH activated for {len(kill_switched)} strategy(ies): {kill_switched}")
    
    return adjusted


# ═══════════════════════════════════════
# Regime Performance Analysis
# ═══════════════════════════════════════

def _update_regime_performance():
    """Update regime-level performance stats."""
    regimes = defaultdict(lambda: {"total": 0, "wins": 0, "strategies": defaultdict(lambda: [0, 0])})
    
    for name, stats in _strategy_stats.items():
        if stats.bull_signals >= 3:
            r = regimes["BULL"]
            r["total"] += stats.bull_signals
            r["wins"] += stats.bull_wins
            r["strategies"][name] = [stats.bull_wins, stats.bull_signals]
        
        if stats.bear_signals >= 3:
            r = regimes["BEAR"]
            r["total"] += stats.bear_signals
            r["wins"] += stats.bear_wins
            r["strategies"][name] = [stats.bear_wins, stats.bear_signals]
        
        if stats.ranging_signals >= 3:
            r = regimes["RANGING"]
            r["total"] += stats.ranging_signals
            r["wins"] += stats.ranging_wins
            r["strategies"][name] = [stats.ranging_wins, stats.ranging_signals]
    
    perf_data = {}
    for regime, r in regimes.items():
        if r["total"] < 5:
            continue
        
        # Find best/worst strategies with win rate thresholds
        strat_rates = []
        for sname, (wins, total) in r["strategies"].items():
            if total >= 3:
                strat_rates.append((sname, wins / total, wins, total))
        
        strat_rates.sort(key=lambda x: x[1], reverse=True)
        
        # Best: win rate >= 50%
        best = [s for s, rate, _, _ in strat_rates if rate >= 0.50][:3]
        # Worst: win rate < 40% and NOT already in best
        worst = [s for s, rate, _, _ in strat_rates if rate < 0.40 and s not in best][-3:]
        
        # Position size recommendation
        win_rate = r["wins"] / r["total"] if r["total"] > 0 else 0.5
        if win_rate >= 0.55:
            mult = 1.2
        elif win_rate >= 0.45:
            mult = 1.0
        elif win_rate >= 0.35:
            mult = 0.7
        else:
            mult = 0.4
        
        perf_data[regime] = {
            "total_trades": r["total"],
            "winning_trades": r["wins"],
            "avg_profit": round(win_rate * 100, 1),
            "best_strategies": best,
            "worst_strategies": worst,
            "optimal_weight_mult": mult,
        }
    
    _save_json(PERF_FILE, perf_data)


# ═══════════════════════════════════════
# Learning Report
# ═══════════════════════════════════════

def generate_learning_report(current_regime: str = "BEAR") -> str:
    """
    Generate a comprehensive learning report in Arabic.
    
    Shows:
      - Top strategies for current regime
      - Strategies to AVOID in current regime  
      - Recommended position sizing
      - Overall win rate in this regime
    """
    perf = _load_json(PERF_FILE)
    regime_data = perf.get(current_regime, {})
    
    if not regime_data:
        return "📚 **التعلم الذاتي**: لا توجد بيانات كافية بعد — يحتاج ٥ صفقات على الأقل لكل نظام سوق."
    
    lines = [
        f"📚 **تقرير التعلم — {current_regime}**",
        "",
        f"📊 **إحصائيات {current_regime}:**",
        f"   صفقات: {regime_data.get('total_trades', 0)}",
        f"   فوز: {regime_data.get('winning_trades', 0)} ({regime_data.get('avg_profit', 0):.0f}%)",
        "",
    ]
    
    best = regime_data.get("best_strategies", [])
    if best:
        lines.append("🟢 **أفضل الاستراتيجيات:**")
        for s in best:
            lines.append(f"   ✅ {s}")
    
    worst = regime_data.get("worst_strategies", [])
    if worst:
        lines.append("")
        lines.append("🔴 **أسوأ الاستراتيجيات (تجنب):**")
        for s in worst:
            lines.append(f"   ❌ {s}")
    
    mult = regime_data.get("optimal_weight_mult", 1.0)
    lines.append("")
    lines.append(f"⚖️ **حجم المركز الموصى:** {mult:.0%} من الحجم الأساسي")
    
    return "\n".join(lines)


# ═══════════════════════════════════════
# Integration Helper
# ═══════════════════════════════════════

def evaluate_closed_trade(trade: dict):
    """
    Bridge function — called when a trade closes in main.py.
    
    Converts the trade dict to TradeRecord and feeds into learning.
    
    Args:
        trade: dict from tracker.py with keys:
            symbol, entry_price, exit_price, profit_pct, strategies, regime, etc.
    """
    try:
        from engine.regime import get_cached_regime
        regime_data = get_cached_regime()
        regime = regime_data.get("regime", "RANGING")
        btc_trend = regime_data.get("btc_trend", "SIDEWAYS")
    except Exception as e:
        logger.debug(f"Learning save skipped: {e}")
        btc_trend = "SIDEWAYS"
    
    record = TradeRecord(
        symbol=trade.get("symbol", ""),
        direction=trade.get("direction", "BUY"),
        entry=trade.get("entry_price", 0),
        exit=trade.get("close_price", trade.get("current_price", 0)),
        profit_pct=trade.get("pnl_pct", 0),  # ✅ تصحيح: pnl_pct ← كان profit_pct
        strategies_used=trade.get("strategies", []),
        market_regime=regime,
        btc_trend=btc_trend,
        duration_hours=trade.get("duration_min", 0) / 60,  # ✅ تصحيح: تحويل دقائق لساعات
        closed_at=time.time(),
    )
    
    record_trade_outcome(record)
    logger.info(f"📚 Learning: recorded {record.symbol} {record.profit_pct:+.2f}% — {len(record.strategies_used)} strategies")


# ═══════════════════════════════════════
# 🎯 Adaptive Entry Thresholds — Self-Learning
# ═══════════════════════════════════════

def get_adaptive_thresholds(base_strength: int, base_confidence: int) -> tuple:
    """
    Adjust entry thresholds based on recent win/loss performance.
    
    Logic:
    - Win rate ≥ 65% → slightly relax (-5 each) to capture more opportunities
    - Win rate 50-65% → keep base thresholds (balanced)
    - Win rate 35-50% → tighten (+5 each) to be more selective
    - Win rate < 35% → heavily tighten (+10 each) — something is wrong
    
    Only uses last 50 trades to stay responsive to changing markets.
    Returns (adjusted_strength, adjusted_confidence)
    """
    stats = get_all_stats()
    if not stats:
        return (base_strength, base_confidence)
    
    # Calculate overall recent win rate
    total = sum(s.total_signals for s in stats.values())
    wins = sum(s.winning_signals for s in stats.values())
    
    if total < 10:
        # Not enough data — use base thresholds
        logger.debug(f"📚 Adaptive thresholds: only {total} trades — using base ({base_strength}, {base_confidence})")
        return (base_strength, base_confidence)
    
    win_rate = wins / total if total > 0 else 0.5
    
    if win_rate >= 0.65:
        adj_str = max(15, base_strength - 5)
        adj_conf = max(20, base_confidence - 5)
        action = "relaxed"
    elif win_rate >= 0.50:
        adj_str = base_strength
        adj_conf = base_confidence
        action = "kept"
    elif win_rate >= 0.35:
        adj_str = min(60, base_strength + 5)
        adj_conf = min(70, base_confidence + 5)
        action = "tightened"
    else:
        adj_str = min(60, base_strength + 10)
        adj_conf = min(70, base_confidence + 10)
        action = "heavily_tightened"
    
    logger.info(
        f"📚 Adaptive thresholds: win_rate={win_rate:.1%} ({wins}/{total}) → "
        f"{action}: ({base_strength},{base_confidence}) → ({adj_str},{adj_conf})"
    )
    return (adj_str, adj_conf)


# Load existing stats on import
load_stats()


def get_all_stats() -> dict:
    """Return all strategy stats — used by adaptive thresholds"""
    return dict(_strategy_stats)
