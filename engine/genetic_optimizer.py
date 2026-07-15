"""
🧬 Genetic Optimizer — التطور الاصطناعي لاستراتيجيات التداول
═════════════════════════════════════════════════════════════
Phase 5 Sprint 1 — يستخدم Backtesting Engine كـ fitness function
يجد أفضل باراميترات لكل استراتيجية عبر 15 جيل من التطور

تم البناء حسب PHASE5_ARCHITECTURAL_VISION.md Section 3
"""
import json
import os
import time
import random
import logging
import numpy as np
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Callable
from copy import deepcopy

logger = logging.getLogger("crypto-signal-genetic")

# ═══════════════════════════════════════════════════════════
# 🧬 CONFIG
# ═══════════════════════════════════════════════════════════

DATA_DIR = Path(os.getenv("DATA_DIR", "/root/.crypto-signal-bot"))

# ═══════════════════════════════════════════════════════════
# 🧬 GENE DEFINITIONS — الجينات لكل استراتيجية
# ═══════════════════════════════════════════════════════════

GENE_DEFINITIONS = {
    "RSI": {
        "rsi_period":      {"min": 7,  "max": 21, "int": True,  "default": 14},
        "rsi_oversold":    {"min": 20, "max": 35, "int": True,  "default": 30},
        "rsi_overbought":  {"min": 65, "max": 80, "int": True,  "default": 70},
    },
    "MACD": {
        "macd_fast":            {"min": 5,  "max": 20, "int": True,  "default": 12},
        "macd_slow":            {"min": 15, "max": 40, "int": True,  "default": 26},
        "macd_signal_period":   {"min": 5,  "max": 15, "int": True,  "default": 9},
    },
    "Moving Averages": {
        "fast_period":  {"min": 10, "max": 30, "int": True,  "default": 20},
        "slow_period":  {"min": 30, "max": 100,"int": True,  "default": 50},
    },
    "ATR Volatility": {
        "atr_period":       {"min": 7,  "max": 21, "int": True,  "default": 14},
        "atr_multiplier":   {"min": 1.0,"max": 3.0,"int": False, "default": 2.0},
    },
    "Divergence": {
        "div_lookback":     {"min": 14, "max": 30, "int": True,  "default": 20},
        "div_rsi_period":   {"min": 7,  "max": 21, "int": True,  "default": 14},
    },
    "SMC (Smart Money)": {
        "smc_lookback":     {"min": 10, "max": 30, "int": True,  "default": 20},
        "smc_min_swing_pct":{"min": 0.5,"max": 2.0,"int": False, "default": 1.0},
    },
    "Market Structure": {
        "ms_lookback":     {"min": 10, "max": 30, "int": True,  "default": 20},
    },
    "CVD Strategy": {
        "cvd_lookback":    {"min": 10, "max": 30, "int": True,  "default": 20},
    },
    "OBV + CMF": {
        "cmf_period":      {"min": 14, "max": 30, "int": True,  "default": 20},
    },
    "VWAP": {
        "vwap_period":     {"min": 14, "max": 30, "int": True,  "default": 20},
    },
    "Support & Resistance": {
        "sr_window":       {"min": 5,  "max": 20, "int": True,  "default": 10},
    },
}

# خوارزمية جينية — باراميترات ثابتة
POPULATION_SIZE = 50
SELECTION_TOP = 0.30
MUTATION_RATE = 0.15
MUTATION_AMOUNT = 0.10
CROSSOVER_RATE = 0.70
NUM_GENERATIONS = 15
TOURNAMENT_SIZE = 5


# ═══════════════════════════════════════════════════════════
# 🧬 DATA STRUCTURES
# ═══════════════════════════════════════════════════════════

@dataclass
class Chromosome:
    """
    كروموسوم واحد — يمثل مجموعة باراميترات لكل الاستراتيجيات.
    
    Example:
      {"RSI": {"period": 14, "oversold": 30, "overbought": 70}, ...}
    """
    genes: Dict[str, Dict[str, float]] = field(default_factory=dict)
    fitness: float = 0.0
    fitness_details: dict = field(default_factory=dict)


@dataclass
class GenerationLog:
    """سجل جيل واحد للتحليل اللاحق."""
    generation: int = 0
    best_fitness: float = 0.0
    avg_fitness: float = 0.0
    median_fitness: float = 0.0
    best_chromosome: Optional[Chromosome] = None
    elapsed_seconds: float = 0.0


# ═══════════════════════════════════════════════════════════
# 🧬 PARAMETRIZED STRATEGY WRAPPER
# ═══════════════════════════════════════════════════════════

class ParametrizedStrategy:
    """
    غلاف لاستراتيجية موجودة — يضخ باراميترات مخصصة.

    بما أن الاستراتيجيات الحالية تستخدم local variables داخل analyze()
    بدلاً من instance attributes، هذا الغلاف:
    1. ينسخ الاستراتيجية الأصلية
    2. ينشئ دالة analyze() جديدة تحقن الباراميترات
    3. يستدعي الـ analyze الأصلي

    عند إعادة هيكلة الاستراتيجيات لدعم instance attributes،
    هذا الغلاف سيظل متوافقاً.
    """

    def __init__(self, base_strategy, name: str, params: dict):
        self.name = name
        self._base = base_strategy
        self._params = params
        self._original_analyze = base_strategy.analyze

    def analyze(self, df) -> Any:
        """
        تحليل مع باراميترات مخصصة.
        
        يحاول تعيين الباراميترات كـ instance attributes
        قبل استدعاء الـ analyze الأصلي.
        """
        # Inject params as instance attributes on the base strategy
        for key, value in self._params.items():
            setattr(self._base, key, value)
        # Call original analyze
        result = self._original_analyze(df)
        return result


# ═══════════════════════════════════════════════════════════
# 🧬 GENETIC OPTIMIZER
# ═══════════════════════════════════════════════════════════

class GeneticOptimizer:
    """
    محرك التحسين الجيني للاستراتيجيات.

    Usage:
        optimizer = GeneticOptimizer()
        best = optimizer.run("BTCUSDT", "4h")
        optimizer.deploy(best)  # تحديث الاستراتيجيات الحية
    """

    def __init__(self, population_size: int = POPULATION_SIZE):
        self.population_size = population_size
        self.rng = random.Random(42)
        self.best_ever: Optional[Chromosome] = None
        self.generation_logs: List[GenerationLog] = []

    # ─── توليد الكروموسومات ───

    def create_random_chromosome(self) -> Chromosome:
        """توليد كروموسوم عشوائي."""
        genes = {}
        for strategy_name, gene_defs in GENE_DEFINITIONS.items():
            strategy_genes = {}
            for param_name, param_def in gene_defs.items():
                if param_def["int"]:
                    value = self.rng.randint(param_def["min"], param_def["max"])
                else:
                    value = round(
                        self.rng.uniform(param_def["min"], param_def["max"]),
                        1,
                    )
                strategy_genes[param_name] = value
            genes[strategy_name] = strategy_genes
        return Chromosome(genes=genes)

    def create_default_chromosome(self) -> Chromosome:
        """توليد كروموسوم بالقيم الافتراضية (baseline للمقارنة)."""
        genes = {}
        for strategy_name, gene_defs in GENE_DEFINITIONS.items():
            strategy_genes = {}
            for param_name, param_def in gene_defs.items():
                strategy_genes[param_name] = param_def["default"]
            genes[strategy_name] = strategy_genes
        return Chromosome(genes=genes)

    # ─── تقييم اللياقة ───

    def _create_parametrized_strategies(self, chromosome: Chromosome) -> list:
        """
        إنشاء استراتيجيات م parametrized من الكروموسوم.

        يطابق أسماء الاستراتيجيات في GENE_DEFINITIONS مع
        الاستراتيجيات الفعلية في ALL_STRATEGIES عبر الخاصية name.
        """
        from engine.analyzer import ALL_STRATEGIES

        parametrized = []
        for strat in ALL_STRATEGIES:
            params = chromosome.genes.get(strat.name, {})
            if params:
                parametrized.append(ParametrizedStrategy(strat, strat.name, params))
            else:
                parametrized.append(strat)
        return parametrized

    def evaluate_fitness(
        self,
        chromosome: Chromosome,
        symbol: str = "BTCUSDT",
        timeframe: str = "4h",
        from_date: str = "2025-11-01",
        to_date: str = "2026-05-19",
    ) -> float:
        """
        تقييم كروموسوم = تشغيل Backtest + حساب متوسط Sharpe.

        Args:
            chromosome: الكروموسوم المراد تقييمه
            symbol, timeframe, from_date, to_date: نطاق الاختبار

        Returns:
            fitness (Sharpe) — مقيّد بين -10 و +10
        """
        from engine.backtesting import (
            DataFeeder, StrategyRunner, backtest_strategy,
        )

        try:
            # 1. جلب البيانات
            feeder = DataFeeder()
            df = feeder.fetch_historical(symbol, timeframe, from_date, to_date)
            if df is None or len(df) < 50:
                return -5.0

            # 2. إنشاء الاستراتيجيات الم parametrized
            parametrized_strategies = self._create_parametrized_strategies(chromosome)

            # 3. تشغيل الاستراتيجيات على البيانات
            runner = StrategyRunner(strategies=parametrized_strategies)
            all_signals = runner.run_all_strategies(df)

            if not all_signals:
                return -3.0

            # 4. Backtest لكل استراتيجية
            sharpes = []
            win_rates = []
            profit_factors = []

            for strategy_name, signals in all_signals.items():
                result = backtest_strategy(
                    df=df,
                    signals=signals,
                    symbol=symbol,
                    timeframe=timeframe,
                )
                result.strategy_name = strategy_name

                if result.total_trades >= 5:
                    if result.sharpe_ratio != 0:
                        sharpes.append(result.sharpe_ratio)
                    win_rates.append(result.win_rate)
                    if result.profit_factor > 0 and result.profit_factor < 9998:
                        profit_factors.append(result.profit_factor)

            # 5. حساب fitness
            fitness = float(np.mean(sharpes)) if sharpes else 0.0

            # Bonus: win rate > 50%
            avg_win_rate = float(np.mean(win_rates)) if win_rates else 0.0
            if avg_win_rate > 50:
                fitness *= 1.1

            # Bonus: profit factor > 1.5
            avg_pf = float(np.mean(profit_factors)) if profit_factors else 0.0
            if avg_pf > 1.5:
                fitness *= 1.05

            # تسجيل التفاصيل
            chromosome.fitness_details = {
                "avg_sharpe": round(fitness / (1.1 if avg_win_rate > 50 else 1.0), 4) if fitness else 0,
                "avg_win_rate": round(avg_win_rate, 2),
                "avg_profit_factor": round(avg_pf, 2),
                "strategies_with_trades": len(sharpes),
                "total_trades_all": sum(len(backtest_strategy(df, all_signals[s], symbol=symbol).trade_log) for s in all_signals),
            }

            return max(-10.0, min(10.0, fitness))  # Clamp

        except Exception as e:
            logger.warning(f"  ⚠️ Fitness eval failed: {e}")
            return -5.0

    # ─── الاختيار ───

    def select_parents(self, population: List[Chromosome]) -> Chromosome:
        """اختيار كروموسوم واحد باستخدام tournament selection."""
        tournament = self.rng.sample(
            population, min(TOURNAMENT_SIZE, len(population))
        )
        return max(tournament, key=lambda c: c.fitness)

    # ─── التزاوج ───

    def crossover(
        self,
        parent1: Chromosome,
        parent2: Chromosome,
    ) -> Tuple[Chromosome, Chromosome]:
        """
        تزاوج كروموسومين — blend/uniform crossover.

        لكل جين: 50% من الأب الأول, 50% من الأب الثاني.
        """
        if self.rng.random() > CROSSOVER_RATE:
            return deepcopy(parent1), deepcopy(parent2)

        child1_genes: Dict[str, Dict[str, float]] = {}
        child2_genes: Dict[str, Dict[str, float]] = {}

        all_strategies = set(parent1.genes.keys()) | set(parent2.genes.keys())

        for strategy in all_strategies:
            g1 = parent1.genes.get(strategy, {})
            g2 = parent2.genes.get(strategy, {})

            child1: Dict[str, float] = {}
            child2: Dict[str, float] = {}
            all_params = set(g1.keys()) | set(g2.keys())

            for param in all_params:
                v1 = g1.get(param, 0)
                v2 = g2.get(param, 0)

                if self.rng.random() < 0.5:
                    child1[param] = v1
                    child2[param] = v2
                else:
                    child1[param] = v2
                    child2[param] = v1

            child1_genes[strategy] = child1
            child2_genes[strategy] = child2

        return (
            Chromosome(genes=child1_genes),
            Chromosome(genes=child2_genes),
        )

    # ─── الطفرة ───

    def mutate(self, chromosome: Chromosome) -> Chromosome:
        """طفرة عشوائية — تغيير كل جين باحتمال MUTATION_RATE."""
        result = deepcopy(chromosome)

        for strategy_name, gene_defs in GENE_DEFINITIONS.items():
            if strategy_name not in result.genes:
                continue
            for param_name, param_def in gene_defs.items():
                if param_name not in result.genes[strategy_name]:
                    continue
                if self.rng.random() < MUTATION_RATE:
                    current = result.genes[strategy_name][param_name]
                    delta = current * MUTATION_AMOUNT
                    if param_def["int"]:
                        delta = int(max(1, round(delta)))
                        new_val = current + self.rng.choice([-delta, delta])
                    else:
                        new_val = current + self.rng.uniform(-delta, delta)
                    # Clamp
                    new_val = max(param_def["min"], min(param_def["max"], new_val))
                    if param_def["int"]:
                        new_val = int(round(new_val))
                    result.genes[strategy_name][param_name] = new_val

        return result

    # ─── تشغيل التطور ───

    def run(
        self,
        symbol: str = "BTCUSDT",
        timeframe: str = "4h",
        from_date: str = "2025-11-01",
        to_date: str = "2026-05-19",
        generations: int = NUM_GENERATIONS,
        callback: Optional[Callable] = None,
    ) -> Chromosome:
        """
        تشغيل الخوارزمية الجينية.

        Args:
            symbol: رمز العملة
            timeframe: الفترة
            from/to: نطاق التدريب
            generations: عدد الأجيال
            callback: fn(gen, best_fitness, avg_fitness) لكل جيل

        Returns:
            أفضل كروموسوم
        """
        logger.info(
            f"🧬 Starting Genetic Optimization: {symbol} {timeframe}\n"
            f"   Population: {self.population_size}, Generations: {generations}"
        )

        self.generation_logs = []

        # Generation 0: population عشوائي
        population = [
            self.create_random_chromosome()
            for _ in range(self.population_size)
        ]

        for generation in range(generations):
            gen_start = time.time()

            # Evaluate fitness
            for chromo in population:
                if chromo.fitness == 0.0:
                    chromo.fitness = self.evaluate_fitness(
                        chromo, symbol, timeframe, from_date, to_date
                    )

            # Sort by fitness (descending)
            population.sort(key=lambda c: c.fitness, reverse=True)

            best = population[0]
            all_fitness = [c.fitness for c in population]
            avg_fitness = float(np.mean(all_fitness))
            median_fitness = float(np.median(all_fitness))

            # Track best ever
            if self.best_ever is None or best.fitness > self.best_ever.fitness:
                self.best_ever = deepcopy(best)

            elapsed = time.time() - gen_start

            logger.info(
                f"   Gen {generation+1}/{generations}: "
                f"best={best.fitness:.4f}, avg={avg_fitness:.4f}, "
                f"time={elapsed:.1f}s"
            )

            # Log
            self.generation_logs.append(GenerationLog(
                generation=generation + 1,
                best_fitness=best.fitness,
                avg_fitness=avg_fitness,
                median_fitness=median_fitness,
                best_chromosome=deepcopy(best),
                elapsed_seconds=round(elapsed, 1),
            ))

            if callback:
                callback(generation, best.fitness, avg_fitness)

            # Selection: keep top 30%
            top_count = max(2, int(self.population_size * SELECTION_TOP))
            parents = population[:top_count]

            # Create next generation
            next_population: List[Chromosome] = []

            # Elitism: keep top 2
            next_population.extend(deepcopy(p) for p in parents[:2])

            # Fill rest with crossover + mutation
            while len(next_population) < self.population_size:
                p1 = self.select_parents(parents)
                p2 = self.select_parents(parents)
                c1, c2 = self.crossover(p1, p2)
                c1 = self.mutate(c1)
                c2 = self.mutate(c2)
                c1.fitness = 0.0  # Reset — needs re-evaluation
                c2.fitness = 0.0
                next_population.extend([c1, c2])

            population = next_population[:self.population_size]

        logger.info(
            f"🧬 Done! Best fitness: {self.best_ever.fitness:.4f}"
        )
        return self.best_ever

    # ─── النشر ───

    def deploy(self, chromosome: Chromosome):
        """
        نشر أفضل كروموسوم — حفظ الباراميترات المحسّنة إلى ملف JSON.

        يكتب إلى optimized_params.json في DATA_DIR.
        """
        params_file = DATA_DIR / "optimized_params.json"
        params_file.write_text(json.dumps({
            "timestamp": time.time(),
            "fitness": chromosome.fitness,
            "params": chromosome.genes,
        }, indent=2))

        logger.info(
            f"🧬 Deployed optimized params (fitness={chromosome.fitness:.4f})\n"
            f"   → {params_file}"
        )

    # ─── تقرير ───

    def generate_report(self) -> dict:
        """توليد تقرير كامل عن آخر تشغيل."""
        return {
            "best_fitness": self.best_ever.fitness if self.best_ever else 0.0,
            "population_size": self.population_size,
            "generations_run": len(self.generation_logs),
            "generation_logs": [
                {
                    "gen": g.generation,
                    "best": round(g.best_fitness, 4),
                    "avg": round(g.avg_fitness, 4),
                    "time": g.elapsed_seconds,
                }
                for g in self.generation_logs
            ],
            "total_elapsed": round(
                sum(g.elapsed_seconds for g in self.generation_logs), 1
            ),
        }

    def get_params_summary(self, chromosome: Chromosome) -> str:
        """تنسيق ملخص الباراميترات كنص."""
        lines = ["🧬 **Optimized Parameters**", ""]
        for strategy_name, params in chromosome.genes.items():
            if not params:
                continue
            param_str = " | ".join(
                f"{k}={v}" for k, v in params.items()
            )
            lines.append(f"• **{strategy_name}**: {param_str}")

        lines.append(f"\n🏆 Fitness: {chromosome.fitness:.4f}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 🌐 SEED FROM OPTIMIZER — تغذية Self-Learning بالباراميترات
# ═══════════════════════════════════════════════════════════

def seed_optimized_params_to_weights(chromosome: Chromosome):
    """
    تحويل الباراميترات المحسّنة إلى أوزان أولية لـ Self-Learning.

    الاستراتيجيات ذات أداء جيد تحصل weight أعلى.
    """
    try:
        from engine.weights import save_weights
    except ImportError:
        logger.warning("  ⚠️ engine.weights not available — skipping")
        return

    weights = {}
    for strategy_name, params in chromosome.genes.items():
        if not params:
            continue
        # كلما كانت الباراميترات مختلفة عن الافتراضي → weight أعلى
        default_strat = GENE_DEFINITIONS.get(strategy_name, {})
        deviation = 0.0
        count = 0
        for param_name, value in params.items():
            param_def = default_strat.get(param_name)
            if param_def:
                default_val = param_def["default"]
                range_size = param_def["max"] - param_def["min"]
                if range_size > 0:
                    deviation += abs(value - default_val) / range_size
                    count += 1

        if count > 0:
            avg_deviation = deviation / count
            # 0.8 (قريب من الافتراضي) → 1.5 (مختلف جداً)
            weight = round(0.8 + avg_deviation * 0.7, 2)
            weights[strategy_name] = max(0.3, min(2.0, weight))

    if weights:
        save_weights(weights)
        logger.info(
            f"🧬 Optimizer fed {len(weights)} strategy weights to Self-Learning"
        )
