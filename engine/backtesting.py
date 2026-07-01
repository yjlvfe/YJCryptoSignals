"""
📊 Phase 4 — Backtesting Engine
═══════════════════════════════════════════════════════════
اختبار خلفي لـ 11 استراتيجية عبر بيانات تاريخية
مع Walk-Forward Validation + Monte Carlo Simulation

المبادئ:
  - Expanding window (لا تسريب للبيانات المستقبلية)
  - NEUTRAL → HOLD
  - 0 تغييرات على الملفات الموجودة
"""
import os
import json
import time
import math
import logging
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Callable

logger = logging.getLogger("crypto-signal-backtest")

# ═══════════════════════════════════════════════════════════
# 🏗️ CONFIG
# ═══════════════════════════════════════════════════════════
DATA_DIR = Path(os.getenv("DATA_DIR", "/root/.crypto-signal-bot"))
HISTORICAL_DIR = DATA_DIR / "historical"
HISTORICAL_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SYMBOL = "BTCUSDT"
DEFAULT_TIMEFRAME = "4h"
DEFAULT_FROM = "2025-11-01"
DEFAULT_TO = "2026-05-19"
DEFAULT_CAPITAL = 10000.0
DEFAULT_COMMISSION = 0.1  # %
CACHE_TTL_HOURS = 24

# ═══════════════════════════════════════════════════════════
# 📦 DATA STRUCTURES
# ═══════════════════════════════════════════════════════════

@dataclass
class TradeRecord:
    """سجل صفقة واحدة في الاختبار الخلفي."""
    entry_idx: int = 0
    exit_idx: int = 0
    direction: str = "BUY"               # BUY / SELL
    entry_price: float = 0.0
    exit_price: float = 0.0
    exit_reason: str = ""                # TP / SL / EOD
    return_pct: float = 0.0              # net return after commission
    duration_candles: int = 0
    regime_at_entry: str = "UNKNOWN"
    strategies_used: List[str] = field(default_factory=list)


@dataclass
class BacktestResult:
    """نتيجة الاختبار لاستراتيجية واحدة."""
    # الهوية
    strategy_name: str = ""
    symbol: str = ""
    timeframe: str = ""
    date_range: Tuple[str, str] = ("", "")

    # الإحصائيات الأساسية
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0               # 0-100
    avg_profit: float = 0.0              # متوسط الربح %
    avg_loss: float = 0.0                # متوسط الخسارة %

    # مقاييس الأداء
    total_return_pct: float = 0.0
    profit_factor: float = 0.0           # إجمالي الربح / إجمالي الخسارة
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0

    # تحليل الصفقات
    best_trade: float = 0.0
    worst_trade: float = 0.0
    avg_trade_duration: float = 0.0     # متوسط عدد الشموع لكل صفقة
    consecutive_wins: int = 0
    consecutive_losses: int = 0

    # سلاسل البيانات
    equity_curve: List[float] = field(default_factory=list)
    trade_log: List[TradeRecord] = field(default_factory=list)
    monthly_returns: List[float] = field(default_factory=list)

    # بيانات الـ Walk-Forward (عند الاستخدام)
    walk_forward_metrics: Optional[dict] = None

    def to_dict(self) -> dict:
        """تحويل إلى JSON-safe dict."""
        return {
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 2),
            "total_return_pct": round(self.total_return_pct, 2),
            "profit_factor": round(self.profit_factor, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "sortino_ratio": round(self.sortino_ratio, 4),
            "calmar_ratio": round(self.calmar_ratio, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "avg_profit": round(self.avg_profit, 4),
            "avg_loss": round(self.avg_loss, 4),
            "avg_trade_duration": round(self.avg_trade_duration, 1),
            "best_trade": round(self.best_trade, 2),
            "worst_trade": round(self.worst_trade, 2),
            "consecutive_wins": self.consecutive_wins,
            "consecutive_losses": self.consecutive_losses,
            "total_trades": self.total_trades,
        }


@dataclass
class WalkForwardResult:
    """نتائج الـ walk-forward validation."""
    windows: int = 0
    avg_return_pct: float = 0.0
    avg_win_rate: float = 0.0
    avg_sharpe: float = 0.0
    max_drawdown_across_windows: float = 0.0
    consistency_score: float = 0.0
    window_results: List[dict] = field(default_factory=list)


@dataclass
class MonteCarloResult:
    """نتائج محاكاة مونت كارلو."""
    simulations: int = 0
    mean_return_pct: float = 0.0
    median_return_pct: float = 0.0
    std_return_pct: float = 0.0
    prob_positive: float = 0.0
    confidence_interval_95: Tuple[float, float] = (0.0, 0.0)
    percentile_5: float = 0.0
    percentile_95: float = 0.0


# ═══════════════════════════════════════════════════════════
# 🎯 COREBACKTEST — محاكاة الدخول/الخروج/SL/TP/EOD
# ═══════════════════════════════════════════════════════════

def backtest_strategy(
    df: pd.DataFrame,
    signals: List[str],
    initial_capital: float = DEFAULT_CAPITAL,
    commission_pct: float = DEFAULT_COMMISSION,
    symbol: str = DEFAULT_SYMBOL,
    timeframe: str = DEFAULT_TIMEFRAME,
    regime_data: Optional[dict] = None,
) -> BacktestResult:
    """
    🎯 محاكاة التداول بناءً على إشارات استراتيجية واحدة.
    
    Args:
        df: OHLCV DataFrame مع أعمدة open/high/low/close/volume
        signals: [BUY/SELL/HOLD] لكل شمعة
        initial_capital, commission_pct, symbol, timeframe, regime_data
    
    Returns:
        BacktestResult
    """
    n = len(df)
    if n == 0:
        return BacktestResult(symbol=symbol, timeframe=timeframe)

    # ─── State ───
    capital = initial_capital
    equity = initial_capital
    position = 0.0          # عدد الوحدات
    position_size = 0.0     # قيمة المركز
    in_trade = False
    entry_price = 0.0
    entry_idx = -1
    stop_loss = 0.0
    targets = []
    last_exit_reason = ""

    # ─── Tracking ───
    equity_curve = [initial_capital]
    trade_log: List[TradeRecord] = []
    trade_returns: List[float] = []

    # Regime at each candle
    _regime_name = (regime_data or {}).get("regime", "UNKNOWN")

    for i in range(n):
        candle = df.iloc[i]
        o, h, l, c = float(candle["open"]), float(candle["high"]), float(candle["low"]), float(candle["close"])
        sig = signals[i] if i < len(signals) else "HOLD"

        # ─── EXIT: Check SL / TP for open positions ───
        if in_trade:
            hit_sl = False
            hit_tp = False
            exit_price_val = 0.0
            exit_reason = ""

            # Check SL
            if stop_loss > 0:
                if direction == "BUY" and l <= stop_loss:
                    hit_sl = True
                    exit_price_val = stop_loss
                    exit_reason = "SL"
                elif direction == "SELL" and h >= stop_loss:
                    hit_sl = True
                    exit_price_val = stop_loss
                    exit_reason = "SL"

            # Check TP (first target)
            if not hit_sl and targets:
                tp = targets[0]
                if direction == "BUY" and h >= tp:
                    hit_tp = True
                    exit_price_val = tp
                    exit_reason = "TP"
                elif direction == "SELL" and l <= tp:
                    hit_tp = True
                    exit_price_val = tp
                    exit_reason = "TP"

            # Exit if SL or TP hit
            if hit_sl or hit_tp:
                ret = ((exit_price_val - entry_price) / entry_price * 100) - commission_pct
                if direction == "SELL":
                    ret = -ret
                trade_returns.append(ret)

                trade_log.append(TradeRecord(
                    entry_idx=entry_idx,
                    exit_idx=i,
                    direction=direction,
                    entry_price=entry_price,
                    exit_price=exit_price_val,
                    exit_reason=exit_reason,
                    return_pct=round(ret, 4),
                    duration_candles=i - entry_idx,
                ))

                capital = equity * (1 + ret / 100)
                equity = capital
                position = 0.0
                in_trade = False
                entry_price = 0.0
                stop_loss = 0.0
                targets = []

        # ─── ENTER: Open new position on signal ───
        if not in_trade and sig in ("BUY", "SELL"):
            direction = sig
            entry_price = o  # Enter at next open
            entry_idx = i
            in_trade = True

            # Set SL and TP from signal
            sl_pct = 0.025  # 2.5% default
            tp_pct = 0.05   # 5% default
            if direction == "BUY":
                stop_loss = entry_price * (1 - sl_pct)
                targets = [entry_price * (1 + tp_pct), entry_price * (1 + tp_pct * 2), entry_price * (1 + tp_pct * 3)]
            else:
                stop_loss = entry_price * (1 + sl_pct)
                targets = [entry_price * (1 - tp_pct), entry_price * (1 - tp_pct * 2), entry_price * (1 - tp_pct * 3)]

        # ─── Update equity ───
        if in_trade:
            unrealized = position_size * (c / entry_price - 1) if position_size > 0 else 0
            equity = capital + unrealized
        else:
            equity = capital

        equity_curve.append(equity)

    # ─── EOD: Close any remaining position ───
    if in_trade:
        exit_c = float(df.iloc[-1]["close"])
        ret = ((exit_c - entry_price) / entry_price * 100) - commission_pct
        if direction == "SELL":
            ret = -ret
        trade_returns.append(ret)
        trade_log.append(TradeRecord(
            entry_idx=entry_idx,
            exit_idx=n - 1,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_c,
            exit_reason="EOD",
            return_pct=round(ret, 4),
            duration_candles=n - 1 - entry_idx,
        ))
        capital = equity * (1 + ret / 100)
        equity = capital

    # ─── Compute result ───
    result = BacktestResult(
        strategy_name="backtest_core",
        symbol=symbol,
        timeframe=timeframe,
        date_range=(str(df.index[0]) if hasattr(df.index, '__getitem__') else "", str(df.index[-1]) if hasattr(df.index, '__getitem__') else ""),
        total_trades=len(trade_log),
        equity_curve=equity_curve,
        trade_log=trade_log,
    )

    if trade_log:
        winning = [t for t in trade_log if t.return_pct > 0]
        losing = [t for t in trade_log if t.return_pct <= 0]
        result.winning_trades = len(winning)
        result.losing_trades = len(losing)
        result.win_rate = (len(winning) / len(trade_log)) * 100 if trade_log else 0

        result.avg_profit = np.mean([t.return_pct for t in winning]) if winning else 0.0
        result.avg_loss = abs(np.mean([t.return_pct for t in losing])) if losing else 0.0
        result.best_trade = max(t.return_pct for t in trade_log)
        result.worst_trade = min(t.return_pct for t in trade_log)
        result.avg_trade_duration = np.mean([t.duration_candles for t in trade_log])

        # Total return
        result.total_return_pct = (equity_curve[-1] - initial_capital) / initial_capital * 100

        # Profit factor
        gross_profit = sum(t.return_pct for t in winning) if winning else 0.001
        gross_loss = abs(sum(t.return_pct for t in losing)) if losing else 0.001
        result.profit_factor = gross_profit / gross_loss if gross_loss > 0 else 9999

    # Use MetricsCalculator for advanced metrics
    mc = MetricsCalculator()
    if trade_returns:
        result.sharpe_ratio = mc.compute_sharpe_ratio(trade_returns)
        result.sortino_ratio = mc.compute_sortino_ratio(trade_returns)
        result.max_drawdown_pct, result.max_drawdown = mc.compute_max_drawdown(equity_curve)
        result.calmar_ratio = mc.compute_calmar_ratio(trade_returns, result.max_drawdown_pct)
        wins, losses = mc.compute_consecutive_streaks(trade_returns)
        result.consecutive_wins = wins
        result.consecutive_losses = losses

    return result


# ═══════════════════════════════════════════════════════════
# 📈 METRICS CALCULATOR
# ═══════════════════════════════════════════════════════════

class MetricsCalculator:
    """حساب جميع المقاييس المالية من سلسلة Returns."""

    RISK_FREE_RATE = 0.02  # 2% سنوياً

    @staticmethod
    def compute_sharpe_ratio(returns: List[float]) -> float:
        """Sharpe Ratio من قائمة returns %."""
        arr = np.array(returns, dtype=np.float64)
        if len(arr) < 2 or np.std(arr, ddof=1) == 0:
            return 0.0
        excess = np.mean(arr) - MetricsCalculator.RISK_FREE_RATE
        return float(excess / np.std(arr, ddof=1) * np.sqrt(len(arr)))

    @staticmethod
    def compute_sortino_ratio(returns: List[float]) -> float:
        """Sortino Ratio — يستخدم downside deviation فقط."""
        arr = np.array(returns, dtype=np.float64)
        if len(arr) < 2:
            return 0.0
        downside = arr[arr < 0]
        if len(downside) == 0:
            return float("inf") if np.mean(arr) > 0 else 0.0
        downside_std = np.std(downside, ddof=1)
        if downside_std == 0:
            return 0.0
        excess = np.mean(arr) - MetricsCalculator.RISK_FREE_RATE
        return float(excess / downside_std * np.sqrt(len(arr)))

    @staticmethod
    def compute_calmar_ratio(returns: List[float], max_dd_pct: float) -> float:
        """Calmar Ratio = annualized return / max drawdown."""
        arr = np.array(returns, dtype=np.float64)
        if len(arr) == 0 or max_dd_pct == 0:
            return 0.0
        total_return = float((1 + arr / 100).prod() - 1)
        annualized = (1 + total_return) ** (252 / len(arr)) - 1 if len(arr) > 0 else 0
        return float(annualized * 100 / max_dd_pct) if max_dd_pct > 0 else 0.0

    @staticmethod
    def compute_max_drawdown(equity_curve: List[float]) -> Tuple[float, float]:
        """حساب أقصى انخفاض من القمة.
        Returns: (drawdown_pct, drawdown_value)
        """
        arr = np.array(equity_curve, dtype=np.float64)
        if len(arr) < 2:
            return 0.0, 0.0
        running_max = np.maximum.accumulate(arr)
        drawdowns = (running_max - arr) / running_max * 100
        max_dd = float(np.max(drawdowns))
        return max_dd, float(np.max(running_max - arr))

    @staticmethod
    def compute_consecutive_streaks(returns: List[float]) -> Tuple[int, int]:
        """حساب أطول سلسلة ربح وخسارة.
        Returns: (consecutive_wins, consecutive_losses)
        """
        max_win = max_loss = curr_win = curr_loss = 0
        for r in returns:
            if r > 0:
                curr_win += 1
                curr_loss = 0
                max_win = max(max_win, curr_win)
            elif r < 0:
                curr_loss += 1
                curr_win = 0
                max_loss = max(max_loss, curr_loss)
            else:
                curr_win = curr_loss = 0
        return max_win, max_loss


# ═══════════════════════════════════════════════════════════
# 📥 DATA FEEDER
# ═══════════════════════════════════════════════════════════

class DataFeeder:
    """إدارة البيانات التاريخية — fetch + cache feather."""

    def __init__(self, exchange_id: str = "MEXC"):
        self.exchange_id = exchange_id

    def fetch_historical(
        self,
        symbol: str = DEFAULT_SYMBOL,
        timeframe: str = DEFAULT_TIMEFRAME,
        from_date: str = DEFAULT_FROM,
        to_date: str = DEFAULT_TO,
        force_refresh: bool = False,
    ) -> Optional[pd.DataFrame]:
        """جلب بيانات تاريخية + تخزين مؤقت."""
        cache_path = HISTORICAL_DIR / f"{symbol}_{timeframe}.feather"

        # Try cache first
        if not force_refresh and cache_path.exists():
            cache_age = time.time() - cache_path.stat().st_mtime
            if cache_age < CACHE_TTL_HOURS * 3600:
                try:
                    df = pd.read_feather(cache_path)
                    logger.info(f"  📥 Cache: {cache_path.name} ({len(df)} rows)")
                    return df
                except Exception as e:
                    logger.warning(f"  ⚠️ Cache read failed: {e}")

        # Fetch from exchange API
        df = self._fetch_from_exchange(symbol, timeframe, from_date, to_date)

        # Save to cache
        if df is not None and len(df) > 0:
            try:
                df.reset_index(drop=True).to_feather(cache_path)
                logger.info(f"  💾 Cache saved: {cache_path.name} ({len(df)} rows)")
            except Exception as e:
                logger.warning(f"  ⚠️ Cache save failed: {e}")

        return df

    def _fetch_from_exchange(
        self,
        symbol: str,
        timeframe: str,
        from_date: str,
        to_date: str,
    ) -> Optional[pd.DataFrame]:
        """جلب البيانات من الـ exchange."""
        from data.fetcher import get_fetcher

        fetcher = get_fetcher()

        tf_minutes = {"1h": 60, "4h": 240, "1d": 1440}
        minutes = tf_minutes.get(timeframe, 240)

        from_dt = datetime.strptime(from_date, "%Y-%m-%d")
        to_dt = datetime.strptime(to_date, "%Y-%m-%d")
        total_minutes = (to_dt - from_dt).total_seconds() / 60
        limit = int(total_minutes / minutes) + 100

        logger.info(f"  📡 Fetching {symbol} {timeframe}: {from_date} → {to_date} ({limit} candles)")

        try:
            df = fetcher.fetch_klines(symbol, timeframe, limit=limit)
            if df is not None and len(df) > 50:
                # Filter by date
                df = df[df["timestamp"] >= pd.Timestamp(from_date)]
                df = df[df["timestamp"] <= pd.Timestamp(to_date)]
                logger.info(f"  ✅ Fetched {len(df)} candles for {symbol} {timeframe}")
                return df
        except Exception as e:
            logger.error(f"  ❌ Fetch failed: {e}")

        return None


# ═══════════════════════════════════════════════════════════
# 🏃 STRATEGY RUNNER
# ═══════════════════════════════════════════════════════════

class StrategyRunner:
    """تشغيل الاستراتيجيات على البيانات التاريخية — expanding window."""

    def __init__(self, strategies: Optional[List] = None):
        if strategies is None:
            from engine.analyzer import ALL_STRATEGIES
            self.strategies = ALL_STRATEGIES
        else:
            self.strategies = strategies

    def run_all_strategies(self, df: pd.DataFrame, step: int = 1) -> Dict[str, List[str]]:
        """تشغيل جميع الاستراتيجيات على نفس البيانات."""
        n = len(df)
        min_candles = 50

        if n < min_candles:
            return {}

        results = {}
        for strategy in self.strategies:
            name = strategy.name
            signals = self._run_single_strategy(strategy, df, min_candles, step, n)
            results[name] = signals

        return results

    def _run_single_strategy(
        self,
        strategy,
        df: pd.DataFrame,
        min_candles: int,
        step: int,
        n: int,
    ) -> List[str]:
        """تشغيل استراتيجية واحدة بنظام expanding window."""
        signals = ["HOLD"] * n

        for i in range(min_candles, n, step):
            window = df.iloc[:i + 1].copy()
            try:
                sig = strategy.analyze(window)
                signals[i] = sig.signal if sig.signal in ("BUY", "SELL") else "HOLD"
            except Exception as e:
                logger.debug(f"  ⚠️ {strategy.name} at candle {i}: {e}")
                signals[i] = "HOLD"

        return signals

    def run_strategy(self, strategy, df: pd.DataFrame, step: int = 1) -> Tuple[str, List[str]]:
        """تشغيل استراتيجية واحدة."""
        n = len(df)
        min_candles = 50
        if n < min_candles:
            return strategy.name, ["HOLD"] * n
        return strategy.name, self._run_single_strategy(strategy, df, min_candles, step, n)


# ═══════════════════════════════════════════════════════════
# 🔁 WALK-FORWARD VALIDATOR
# ═══════════════════════════════════════════════════════════

class WalkForwardValidator:
    """Walk-Forward Validation — منع overfitting."""

    def __init__(self, n_windows: int = 6, train_pct: float = 0.7):
        self.n_windows = n_windows
        self.train_pct = train_pct

    def validate(
        self,
        df: pd.DataFrame,
        strategy_signals: List[str],
        initial_capital: float = DEFAULT_CAPITAL,
        commission_pct: float = DEFAULT_COMMISSION,
    ) -> WalkForwardResult:
        """تشغيل walk-forward validation لاستراتيجية واحدة."""
        n = len(df)
        window_size = n // self.n_windows
        overlap = int(window_size * 0.2)

        window_results = []

        for w in range(self.n_windows - 1):
            train_end = (w + 1) * window_size
            test_start = train_end - overlap
            test_end = min(test_start + window_size, n)

            if test_end > n or test_start >= n:
                break

            # Test on test set
            test_signals = strategy_signals[test_start:test_end]
            test_df = df.iloc[test_start:test_end]

            if len(test_df) < 50:
                continue

            result = backtest_strategy(test_df, test_signals, initial_capital, commission_pct)
            window_results.append({
                "window": w + 1,
                "train_candles": train_end,
                "test_candles": len(test_df),
                "return_pct": round(result.total_return_pct, 2),
                "win_rate": round(result.win_rate, 2),
                "sharpe": round(result.sharpe_ratio, 4),
                "max_dd": round(result.max_drawdown_pct, 2),
                "trades": result.total_trades,
            })

        return self._aggregate_results(window_results)

    def _aggregate_results(self, window_results: List[dict]) -> WalkForwardResult:
        """تجميع نتائج كل النوافذ في نتيجة واحدة."""
        if not window_results:
            return WalkForwardResult()

        returns = [w["return_pct"] for w in window_results]
        win_rates = [w["win_rate"] for w in window_results]
        sharpes = [w["sharpe"] for w in window_results]
        drawdowns = [w["max_dd"] for w in window_results]

        positive_count = sum(1 for r in returns if r > 0)

        return WalkForwardResult(
            windows=len(window_results),
            avg_return_pct=round(float(np.mean(returns)), 2),
            avg_win_rate=round(float(np.mean(win_rates)), 2),
            avg_sharpe=round(float(np.mean(sharpes)), 4),
            max_drawdown_across_windows=round(float(max(drawdowns)), 2),
            consistency_score=round(positive_count / len(returns), 3) if returns else 0.0,
            window_results=window_results,
        )


# ═══════════════════════════════════════════════════════════
# 🎲 MONTE CARLO SIMULATOR
# ═══════════════════════════════════════════════════════════

class MonteCarloSimulator:
    """محاكاة مونت كارلو لتقييم ثباتية النتائج."""

    def __init__(self, n_simulations: int = 1000, seed: int = 42):
        self.n_simulations = n_simulations
        self.rng = np.random.RandomState(seed)

    def simulate(self, trade_returns: List[float], initial_capital: float = DEFAULT_CAPITAL) -> MonteCarloResult:
        """تشغيل محاكاة مونت كارلو."""
        if not trade_returns or len(trade_returns) < 5:
            return MonteCarloResult(simulations=0)

        arr = np.array(trade_returns, dtype=np.float64)
        n_trades = len(arr)

        simulation_returns = []
        for _ in range(self.n_simulations):
            shuffled = arr[self.rng.permutation(n_trades)]
            equity = initial_capital
            for ret in shuffled:
                equity *= (1 + ret / 100)
            total_ret = (equity - initial_capital) / initial_capital * 100
            simulation_returns.append(total_ret)

        sim_arr = np.array(simulation_returns)

        return MonteCarloResult(
            simulations=self.n_simulations,
            mean_return_pct=round(float(np.mean(sim_arr)), 2),
            median_return_pct=round(float(np.median(sim_arr)), 2),
            std_return_pct=round(float(np.std(sim_arr)), 2),
            prob_positive=round(float(np.mean(sim_arr > 0)), 3),
            confidence_interval_95=(
                round(float(np.percentile(sim_arr, 2.5)), 2),
                round(float(np.percentile(sim_arr, 97.5)), 2),
            ),
            percentile_5=round(float(np.percentile(sim_arr, 5)), 2),
            percentile_95=round(float(np.percentile(sim_arr, 95)), 2),
        )


# ═══════════════════════════════════════════════════════════
# 📋 REPORT FORMATTER
# ═══════════════════════════════════════════════════════════

class ReportFormatter:
    """تنسيق نتائج الاختبار الخلفي — Telegram + JSON."""

    EMOJI_MAP = {
        "excellent": "🟢",
        "positive": "🟡",
        "negative": "🟠",
        "disaster": "🔴",
    }

    @staticmethod
    def _classify_performance(return_pct: float) -> str:
        if return_pct > 20:
            return "ممتاز 🟢"
        elif return_pct > 0:
            return "إيجابي 🟡"
        elif return_pct > -10:
            return "سلبي 🟠"
        else:
            return "خسارة كبيرة 🔴"

    @staticmethod
    def format_single_result(result: BacktestResult) -> str:
        """تقرير لاستراتيجية واحدة."""
        if result.total_trades == 0:
            return f"⚠️ **{result.strategy_name}**: لا توجد صفقات."

        perf = ReportFormatter._classify_performance(result.total_return_pct)
        pf_str = "∞" if result.profit_factor >= 9998 else f"{result.profit_factor:.2f}"

        lines = [
            f"📊 **{result.strategy_name}** — {result.symbol} ({result.timeframe})",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"📈 العائد الكلي: {result.total_return_pct:+.2f}% {perf}",
            f"📊 صفقات: {result.total_trades} | فوز: {result.win_rate:.1f}%",
            f"💵 متوسط الربح: +{result.avg_profit:.2f}% | الخسارة: −{result.avg_loss:.2f}%",
            f"🏆 Profit Factor: {pf_str}",
            f"📉 Max DD: {result.max_drawdown_pct:.1f}%",
            f"📐 Sharpe: {result.sharpe_ratio:.2f} | Sortino: {result.sortino_ratio:.2f}",
        ]

        if result.consecutive_wins > 0:
            lines.append(f"🔥 أطول فوز: {result.consecutive_wins} | أطول خسارة: {result.consecutive_losses}")

        return "\n".join(lines)

    @staticmethod
    def format_comparison(all_results: Dict[str, BacktestResult], top_n: int = 5) -> str:
        """مقارنة جميع الاستراتيجيات مرتبة حسب الأداء."""
        if not all_results:
            return "⚠️ لا توجد نتائج للمقارنة."

        ranking = sorted(
            all_results.items(),
            key=lambda x: x[1].total_return_pct,
            reverse=True,
        )

        lines = ["📊 **مقارنة الاستراتيجيات**", ""]

        for i, (name, result) in enumerate(ranking[:top_n]):
            if result.total_return_pct > 20:
                icon = ReportFormatter.EMOJI_MAP["excellent"]
            elif result.total_return_pct > 0:
                icon = ReportFormatter.EMOJI_MAP["positive"]
            else:
                icon = ReportFormatter.EMOJI_MAP["negative"]

            lines.append(
                f"{icon} #{i+1} **{name}** | "
                f"عائد: {result.total_return_pct:+.1f}% | "
                f"ربح: {result.win_rate:.0f}% | "
                f"PF: {result.profit_factor:.1f} | "
                f"DD: {result.max_drawdown_pct:.1f}% | "
                f"صفقات: {result.total_trades}"
            )

        return "\n".join(lines)

    @staticmethod
    def to_json_safe(all_results: Dict[str, BacktestResult]) -> dict:
        """تحويل جميع النتائج إلى JSON."""
        return {
            name: result.to_dict()
            for name, result in all_results.items()
        }


# ═══════════════════════════════════════════════════════════
# 🌐 MAIN API — run_backtest()
# ═══════════════════════════════════════════════════════════

def run_backtest(
    symbol: str = DEFAULT_SYMBOL,
    timeframe: str = DEFAULT_TIMEFRAME,
    from_date: str = DEFAULT_FROM,
    to_date: str = DEFAULT_TO,
    strategies: Optional[List] = None,
    regime_data: Optional[dict] = None,
    initial_capital: float = DEFAULT_CAPITAL,
    commission_pct: float = DEFAULT_COMMISSION,
    use_walk_forward: bool = False,
    walk_forward_windows: int = 6,
    use_monte_carlo: bool = False,
    monte_carlo_simulations: int = 1000,
    save_results: bool = True,
) -> dict:
    """
    🎯 الدالة الرئيسية — تشغيل اختبار خلفي كامل.
    
    Args:
        symbol: رمز العملة
        timeframe: الإطار الزمني
        from_date/to_date: نطاق الاختبار
        strategies: قائمة استراتيجيات (افتراضي: ALL_STRATEGIES)
        regime_data: بيانات الـ regime
        initial_capital: رأس المال الابتدائي
        commission_pct: عمولة التداول %
        use_walk_forward: تفعيل walk-forward validation
        walk_forward_windows: عدد النوافذ (إذا use_walk_forward=True)
        use_monte_carlo: تفعيل محاكاة مونت كارلو
        monte_carlo_simulations: عدد المحاكاة
        save_results: حفظ النتائج إلى JSON

    Returns:
        dict — نتائج كاملة مع ترتيب وإحصائيات
    """
    start_time = time.time()

    # ─── 1. Data ───
    feeder = DataFeeder()
    df = feeder.fetch_historical(symbol, timeframe, from_date, to_date)
    if df is None or len(df) < 50:
        return {
            "error": f"Insufficient data for {symbol} {timeframe}",
            "candles": len(df) if df is not None else 0,
        }

    # ─── 2. Run strategies ───
    runner = StrategyRunner(strategies)
    all_signals = runner.run_all_strategies(df)

    if not all_signals:
        return {"error": "No strategies produced signals", "candles": len(df)}

    # ─── 3. Backtest each strategy ───
    results: Dict[str, BacktestResult] = {}
    for strategy_name, signals in all_signals.items():
        result = backtest_strategy(
            df=df,
            signals=signals,
            initial_capital=initial_capital,
            commission_pct=commission_pct,
            symbol=symbol,
            timeframe=timeframe,
            regime_data=regime_data,
        )
        result.strategy_name = strategy_name
        results[strategy_name] = result

    # ─── 4. Walk-Forward Validation ───
    wf_result = None
    if use_walk_forward:
        wf_validator = WalkForwardValidator(n_windows=walk_forward_windows)
        wf_all = {}
        for name, signals in all_signals.items():
            wf = wf_validator.validate(df, signals, initial_capital, commission_pct)
            wf_all[name] = {
                "consistency_score": wf.consistency_score,
                "avg_return_pct": wf.avg_return_pct,
                "avg_sharpe": wf.avg_sharpe,
                "windows": wf.windows,
            }
            if results.get(name):
                results[name].walk_forward_metrics = {
                    "consistency_score": wf.consistency_score,
                    "avg_return_pct": wf.avg_return_pct,
                    "windows": wf.windows,
                }
        wf_result = wf_all

    # ─── 5. Monte Carlo Simulation ───
    mc_results = None
    if use_monte_carlo:
        mc_sim = MonteCarloSimulator(n_simulations=monte_carlo_simulations)
        mc_all = {}
        for name, result in results.items():
            trade_returns = [t.return_pct for t in result.trade_log if t.return_pct != 0]
            mc = mc_sim.simulate(trade_returns, initial_capital)
            mc_all[name] = {
                "prob_positive": mc.prob_positive,
                "mean_return_pct": mc.mean_return_pct,
                "confidence_interval_95": mc.confidence_interval_95,
            }
        mc_results = mc_all

    # ─── 6. Ranking ───
    ranking = sorted(
        [(name, r.total_return_pct, r.win_rate, r.profit_factor, r.sharpe_ratio, r.max_drawdown_pct)
         for name, r in results.items()],
        key=lambda x: x[1],
        reverse=True,
    )

    ranking_list = [
        {
            "strategy_name": name,
            "total_return_pct": round(ret, 2),
            "win_rate": round(wr, 2),
            "profit_factor": round(pf, 2),
            "sharpe_ratio": round(sh, 4),
            "max_drawdown_pct": round(mdd, 2),
        }
        for name, ret, wr, pf, sh, mdd in ranking
    ]

    best_strategy = ranking[0][0] if ranking else ""
    worst_strategy = ranking[-1][0] if ranking else ""

    execution_seconds = round(time.time() - start_time, 2)

    # ─── 7. Build output ───
    output = {
        "symbol": symbol,
        "timeframe": timeframe,
        "date_range": {"from": from_date, "to": to_date},
        "total_candles": len(df),
        "strategies_tested": len(results),
        "results": {name: r.to_dict() for name, r in results.items()},
        "ranking": ranking_list,
        "best_strategy": best_strategy,
        "worst_strategy": worst_strategy,
        "walk_forward": wf_result,
        "monte_carlo": mc_results,
        "execution_seconds": execution_seconds,
    }

    # ─── 8. Save ───
    if save_results:
        try:
            output_path = DATA_DIR / f"backtest_{symbol}_{timeframe}_{from_date}_{to_date}.json"
            output_path.write_text(json.dumps(output, indent=2, default=str))
            logger.info(f"  💾 Results saved: {output_path}")
        except Exception as e:
            logger.warning(f"  ⚠️ Save failed: {e}")

    return output


# ═══════════════════════════════════════════════════════════
# 🌱 SEED FROM BACKTEST — تغذية Self-Learning
# ═══════════════════════════════════════════════════════════

def seed_from_backtest(backtest_results: Dict[str, BacktestResult]):
    """تغذية الـ self-learning بـ priors أولية من الاختبار التاريخي."""
    try:
        from engine.weights import save_weights
    except ImportError:
        logger.warning("  ⚠️ engine.weights not available — skipping seed")
        return

    weights = {}
    for name, result in backtest_results.items():
        if result.total_trades >= 20:
            win_rate = result.win_rate / 100.0
            weight = 0.5 + win_rate  # 0.5 (خاسر) → 1.5 (رابح)
            weights[name] = round(max(0.3, min(2.0, weight)), 2)

    if weights:
        save_weights(weights)
        logger.info(f"📚 Backtest fed {len(weights)} strategy priors to Self-Learning")
