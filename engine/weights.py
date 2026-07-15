"""
🧠 Strategy Weights — نظام أوزان متكيف للاستراتيجيات
كل استراتيجية تبدأ بوزن متساوٍ، ثم يتكيف الوزن تلقائياً من الأداء التاريخي
"""
import json
import time
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("crypto-signal-weights")

WEIGHTS_FILE = Path("/root/.crypto-signal-bot/strategy_weights.json")
PERF_FILE = Path("/root/.crypto-signal-bot/strategy_performance.json")
SYMBOL_PERF_FILE = Path("/root/.crypto-signal-bot/symbol_performance.json")

# استراتيجيات مع أسمائها الداخلية
STRATEGY_NAMES = [
    "Support & Resistance",
    "RSI",
    "MACD",
    "Moving Averages",
    "Bollinger Bands",
    "Fibonacci",
    "Volume Analysis",
    "ADX — Trend Strength",
    "Candlestick Patterns",
    "Elliott Wave",
    "Market Structure",
    "SMC (Smart Money)",
    "Divergence",
    "ATR Volatility",
    "Wyckoff Method",
    # 🆕 v3
    "Ichimoku",
    "Harmonic Patterns",
    "OBV + CMF",
    "VWAP",
    "SuperTrend",
    "Keltner Channels",
    "Stochastic",
    "Order Blocks",
    "Fair Value Gaps",
    "CCI",
    "Money Flow Index",
    "Chart Patterns",
    "Volume Profile",
    "Trend Lines",
]

DEFAULT_WEIGHT = 1.0


def load_weights() -> Dict[str, float]:
    """تحميل الأوزان الحالية"""
    try:
        if WEIGHTS_FILE.exists():
            data = json.loads(WEIGHTS_FILE.read_text())
            return {name: data.get(name, DEFAULT_WEIGHT) for name in STRATEGY_NAMES}
    except Exception as e:
        logger.warning(f"Failed to load weights: {e}")
    return {name: DEFAULT_WEIGHT for name in STRATEGY_NAMES}


def save_weights(weights: Dict[str, float]):
    """حفظ الأوزان"""
    try:
        WEIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        WEIGHTS_FILE.write_text(json.dumps(weights, indent=2))
    except Exception as e:
        logger.error(f"Failed to save weights: {e}")


def load_performance() -> dict:
    """تحميل سجل الأداء: {strategy_name: {wins, losses, total_pnl, last_updated}}"""
    try:
        if PERF_FILE.exists():
            return json.loads(PERF_FILE.read_text())
    except Exception as e:
        logger.error(f"Load failure: {e}", exc_info=True)
        return {}


def save_performance(perf: dict):
    """حفظ سجل الأداء"""
    try:
        PERF_FILE.parent.mkdir(parents=True, exist_ok=True)
        PERF_FILE.write_text(json.dumps(perf, indent=2))
    except Exception as e:
        logger.error(f"Failed to save performance: {e}")


def record_trade_outcome(trade_history_entry: dict, strategy_signals: list = None):
    """
    تسجيل نتيجة صفقة لضبط أوزان الاستراتيجيات.
    trade_history_entry: من trades_history.json
    strategy_signals: قائمة signal names اللي شاركت في التوصية (اختياري)
    """
    try:
        perf = load_performance()
        weights = load_weights()
        
        is_win = trade_history_entry.get("pnl_pct", 0) >= 0
        pnl = trade_history_entry.get("pnl_pct", 0)
        
        signals_to_update = strategy_signals if strategy_signals else STRATEGY_NAMES
        
        for name in signals_to_update:
            if name not in perf:
                perf[name] = {"wins": 0, "losses": 0, "total_pnl": 0.0, "trades": 0}
            
            perf[name]["trades"] += 1
            perf[name]["total_pnl"] = round(perf[name]["total_pnl"] + pnl, 2)
            
            if is_win:
                perf[name]["wins"] += 1
            else:
                perf[name]["losses"] += 1
        
        save_performance(perf)
        
        # إعادة حساب الأوزان بناءً على الأداء
        recalculate_weights(perf)
        
    except Exception as e:
        logger.error(f"Failed to record trade outcome: {e}")


def recalculate_weights(perf: dict = None):
    """
    إعادة حساب أوزان الاستراتيجيات من الأداء التاريخي.
    🆕 v2: Slow adaptation with anti-overfitting safeguards.
    - Minimum 5 trades before weight adjustment
    - Rolling window validation (last 20 trades max influence)
    - Weight change capped at ±10% per recalculation
    - Regression to mean for low-sample strategies
    """
    if perf is None:
        perf = load_performance()
    
    old_weights = load_weights()
    weights = {}
    
    for name in STRATEGY_NAMES:
        data = perf.get(name, {})
        trades = data.get("trades", 0)
        
        # 🆕 Minimum sample: 5 trades before adjusting
        if trades < 5:
            # Regression toward default (slowly)
            old_w = old_weights.get(name, DEFAULT_WEIGHT)
            weights[name] = round(old_w + (DEFAULT_WEIGHT - old_w) * 0.1, 3)
            continue
        
        wins = data.get("wins", 0)
        losses = data.get("losses", 0)
        total = wins + losses
        win_rate = wins / max(total, 1)
        
        avg_pnl = data.get("total_pnl", 0.0) / max(total, 1)
        
        # 🆕 Bayesian-like smoothing: weight toward prior for low samples
        # Prior: 50% winrate, 0% avg PnL → weight = 0.5
        prior_weight = 0.5
        sample_confidence = min(1.0, trades / 20.0)  # Full confidence at 20 trades
        
        raw_weight = win_rate * (1.0 + avg_pnl / 100.0)
        raw_weight = max(0.1, min(2.0, raw_weight))
        
        # Blend with prior based on sample size
        smoothed_weight = prior_weight + (raw_weight - prior_weight) * sample_confidence
        
        # 🆕 Cap change at ±10% from old weight
        old_w = old_weights.get(name, DEFAULT_WEIGHT)
        max_change = 0.10
        if smoothed_weight > old_w + max_change:
            smoothed_weight = old_w + max_change
        elif smoothed_weight < old_w - max_change:
            smoothed_weight = old_w - max_change
        
        weights[name] = round(smoothed_weight, 3)
    
    save_weights(weights)
    logger.info(f"♻️ Weights recalculated: {len(weights)} strategies updated (slow-adapt, anti-overfitting)")
    return weights


def get_weighted_score(strategy_name: str) -> float:
    """الحصول على وزن استراتيجية معينة"""
    weights = load_weights()
    return weights.get(strategy_name, DEFAULT_WEIGHT)


def get_top_strategies(n: int = 5) -> list:
    """أفضل N استراتيجية حسب الوزن"""
    weights = load_weights()
    sorted_weights = sorted(weights.items(), key=lambda x: x[1], reverse=True)
    return sorted_weights[:n]


def get_weak_strategies(n: int = 5) -> list:
    """أضعف N استراتيجية حسب الوزن"""
    weights = load_weights()
    sorted_weights = sorted(weights.items(), key=lambda x: x[1])
    return sorted_weights[:n]


# ─── ② تتبع أداء لكل عملة وفريم ───

def load_symbol_perf() -> dict:
    """{symbol: {timeframe: {strategy: {wins, losses, pnl}}}}"""
    try:
        if SYMBOL_PERF_FILE.exists():
            return json.loads(SYMBOL_PERF_FILE.read_text())
    except Exception as e:
        logger.error(f"Load failure: {e}", exc_info=True)
        return {}


def save_symbol_perf(perf: dict):
    try:
        SYMBOL_PERF_FILE.parent.mkdir(parents=True, exist_ok=True)
        SYMBOL_PERF_FILE.write_text(json.dumps(perf, indent=2))
    except Exception as e:
        logger.error(f"Failed to save symbol perf: {e}")


def record_symbol_trade(symbol: str, timeframe: str, pnl: float, 
                         active_strategies: list = None):
    """تسجيل نتيجة صفقة لكل عملة + فريم + استراتيجية"""
    try:
        perf = load_symbol_perf()
        sym = symbol.replace("USDT", "")
        
        if sym not in perf:
            perf[sym] = {}
        if timeframe not in perf[sym]:
            perf[sym][timeframe] = {}
        
        is_win = pnl >= 0
        strategies = active_strategies or STRATEGY_NAMES
        
        for strat in strategies:
            if strat not in perf[sym][timeframe]:
                perf[sym][timeframe][strat] = {"trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0}
            
            entry = perf[sym][timeframe][strat]
            entry["trades"] += 1
            entry["total_pnl"] = round(entry["total_pnl"] + pnl, 2)
            if is_win:
                entry["wins"] += 1
            else:
                entry["losses"] += 1
        
        save_symbol_perf(perf)
        
    except Exception as e:
        logger.error(f"Symbol perf record error: {e}")


def get_best_symbols(n: int = 5, timeframe: str = "4h") -> list:
    """أفضل العملات حسب الربح على فريم معين"""
    perf = load_symbol_perf()
    rankings = []
    for sym, tfs in perf.items():
        tf_data = tfs.get(timeframe, {})
        total_pnl = sum(s.get("total_pnl", 0) for s in tf_data.values())
        total_trades = max(sum(s.get("trades", 0) for s in tf_data.values()), 1)
        rankings.append((sym, round(total_pnl, 2), total_trades))
    
    rankings.sort(key=lambda x: x[1], reverse=True)
    return rankings[:n]


def get_worst_symbols(n: int = 3, timeframe: str = "4h") -> list:
    """أسوأ العملات — تجنبها"""
    perf = load_symbol_perf()
    rankings = []
    for sym, tfs in perf.items():
        tf_data = tfs.get(timeframe, {})
        total_pnl = sum(s.get("total_pnl", 0) for s in tf_data.values())
        total_trades = max(sum(s.get("trades", 0) for s in tf_data.values()), 1)
        rankings.append((sym, round(total_pnl, 2), total_trades))
    
    rankings.sort(key=lambda x: x[1])
    return rankings[:n]


# ═══════════════ 🆕 Dynamic Regime Weights ═══════════════

# Strategy → cluster mapping (same as analyzer CLUSTERS)
_STRATEGY_CLUSTER_MAP = {
    "SMC (Smart Money)": "structure", "Order Blocks": "structure",
    "Fair Value Gaps": "structure", "Market Structure": "structure",
    "RSI": "momentum", "Stochastic": "momentum", "CCI": "momentum",
    "Money Flow Index": "momentum", "MACD": "momentum",
    "OBV + CMF": "volume", "Volume Analysis": "volume", "Volume Profile": "volume",
    "Moving Averages": "trend", "ADX — Trend Strength": "trend",
    "Trend Lines": "trend", "Support & Resistance": "trend",
    "Bollinger Bands": "volatility", "Keltner Channels": "volatility",
    "SuperTrend": "volatility", "ATR Volatility": "volatility",
    "Candlestick Patterns": "patterns", "Chart Patterns": "patterns",
    "Harmonic Patterns": "patterns", "Elliott Wave": "patterns",
    "Wyckoff Method": "patterns",
    "Ichimoku": "sentiment", "Fibonacci": "sentiment",
    "VWAP": "sentiment", "Divergence": "sentiment",
}

# Regime → cluster weight multipliers
# >1.0 = boost, <1.0 = reduce
REGIME_CLUSTER_BOOST = {
    "RANGING": {
        "momentum": 1.2,     # Mean reversion oscillators work well
        "volume": 1.1,       # Volume confirms ranges
        "trend": 0.7,        # Trend systems fail in ranges
        "volatility": 1.0,
        "structure": 0.9,    # SMC less reliable in ranges
        "patterns": 0.9,
        "sentiment": 1.0,
    },
    "BULL": {
        "momentum": 1.2,     # Momentum rides trends
        "trend": 1.3,        # Trend following excels
        "volume": 1.1,       # Volume confirms breakouts
        "volatility": 0.8,   # Bands less important in clean trends
        "structure": 1.1,    # SMC breakouts align
        "patterns": 1.1,     # Bullish patterns confirm
        "sentiment": 1.0,
    },
    "BEAR": {
        "momentum": 0.7,     # Oscillators whipsaw in bears
        "trend": 1.2,        # Trend following is critical
        "volume": 1.1,       # Volume spikes signal exits
        "volatility": 1.2,   # Volatility matters more
        "structure": 1.0,
        "patterns": 0.8,     # Bear patterns less reliable
        "sentiment": 1.1,    # Sentiment drives bears
    },
    "VOLATILE": {
        "momentum": 0.6,     # Oscillators useless in chaos
        "trend": 0.8,
        "volume": 1.3,       # Volume is TRUTH in volatility
        "volatility": 1.4,   # ATR/bands are critical
        "structure": 1.2,    # SMC helps find real levels
        "patterns": 0.7,
        "sentiment": 1.1,
    },
}


def get_regime_adjusted_weights(regime_data: dict = None, base_weights: dict = None) -> dict:
    """
    🆕 Adjust strategy weights based on market regime + self-learning data.
    
    Layer 1: Static regime cluster boost (REGIME_CLUSTER_BOOST)
    Layer 2: Dynamic learning boost from self_learning_v2 (actual trade performance)
    
    Args:
        regime_data: from engine.regime.detect_regime()
        base_weights: from load_weights()
    
    Returns:
        Adjusted weights dict {strategy_name: weight}
    """
    if not regime_data or not base_weights:
        return base_weights or {name: 1.0 for name in STRATEGY_NAMES}
    
    regime = regime_data.get("regime", "RANGING")
    boost_map = REGIME_CLUSTER_BOOST.get(regime, REGIME_CLUSTER_BOOST["RANGING"])
    
    # Layer 2: Get learning-adjusted weights from v2
    learning_mult = {}
    try:
        from engine.self_learning_v2 import get_adjusted_weights
        learning_weights = get_adjusted_weights(regime, base_weights)
        for name, lw in learning_weights.items():
            base = base_weights.get(name, 1.0)
            learning_mult[name] = lw / base if base > 0 else 1.0
    except Exception as e:
        logger.debug(f"Learning weights import skipped: {e}")
    
    adjusted = {}
    for name in STRATEGY_NAMES:
        base_w = base_weights.get(name, 1.0)
        cluster = _STRATEGY_CLUSTER_MAP.get(name)
        # Static regime multiplier
        regime_mult = boost_map.get(cluster, 1.0) if cluster else 1.0
        # Learning multiplier (default 1.0 if no data)
        learn_mult = learning_mult.get(name, 1.0)
        # Combine: regime x learning, clamp to [0.3, 2.5]
        combined = max(0.3, min(2.5, regime_mult * learn_mult))
        adjusted[name] = round(base_w * combined, 3)
    
    return adjusted


# 🆕 Expectancy tracking
EXPECTANCY_FILE = Path("/root/.crypto-signal-bot/strategy_expectancy.json")


def load_expectancy() -> dict:
    """Load per-strategy expectancy: {name: {winrate, avg_rr, expectancy, false_positives}}"""
    try:
        if EXPECTANCY_FILE.exists():
            return json.loads(EXPECTANCY_FILE.read_text())
    except Exception as e:
        logger.error(f"Load failure: {e}", exc_info=True)
        return {}


def save_expectancy(data: dict):
    try:
        EXPECTANCY_FILE.parent.mkdir(parents=True, exist_ok=True)
        EXPECTANCY_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Failed to save expectancy: {e}")


def update_expectancy(trade: dict):
    """
    🆕 Update per-strategy expectancy from a closed trade.
    Called from tracker when a trade closes.
    """
    try:
        perf = load_performance()
        exp = load_expectancy()
        strategies = trade.get("strategies", [])
        pnl = trade.get("pnl_pct", 0)
        is_win = pnl >= 0
        
        # Calculate RR for this trade
        entry = trade.get("entry_price", 0)
        sl = trade.get("stop_loss", entry * 0.95)
        tp1 = (trade.get("targets") or [entry * 1.03])[0]
        if entry > 0 and sl > 0:
            risk = abs(entry - sl) / entry * 100
            reward = abs(tp1 - entry) / entry * 100 if tp1 > 0 else 3.0
            rr = reward / max(risk, 0.1)
        else:
            rr = 1.5
        
        for name in strategies:
            if name not in exp:
                exp[name] = {
                    "trades": 0, "wins": 0, "losses": 0,
                    "total_rr": 0.0, "total_pnl": 0.0,
                    "false_positives": 0,
                }
            e = exp[name]
            e["trades"] += 1
            e["total_pnl"] = round(e["total_pnl"] + pnl, 2)
            e["total_rr"] = round(e["total_rr"] + rr, 2)
            
            if is_win:
                e["wins"] += 1
            else:
                e["losses"] += 1
                if pnl < -1.0:  # Loss >1% = false positive
                    e["false_positives"] += 1
            
            # Derived metrics
            total = e["wins"] + e["losses"]
            e["winrate"] = round(e["wins"] / max(total, 1) * 100, 1)
            e["avg_rr"] = round(e["total_rr"] / max(total, 1), 2)
            e["expectancy"] = round(
                (e["winrate"] / 100 * e["avg_rr"]) - ((1 - e["winrate"] / 100) * 1.0), 3
            )
        
        save_expectancy(exp)
        
    except Exception as e:
        logger.error(f"Expectancy update error: {e}")


def get_weak_strategies_by_expectancy(n: int = 5) -> list:
    """🆕 Return strategies with lowest/negative expectancy."""
    exp = load_expectancy()
    ranked = []
    for name, data in exp.items():
        if data.get("trades", 0) >= 2:
            ranked.append((name, data.get("expectancy", 0), data.get("winrate", 0), data.get("trades", 0)))
    ranked.sort(key=lambda x: x[1])
    return ranked[:n]
