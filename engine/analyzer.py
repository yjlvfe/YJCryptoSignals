"""
🧠 المحلل الأساسي — يشغل 11 استراتيجية منتقاة ويجمع النتائج
🆕 v5: Phase 2 purge — 29→11 strategies, simplified clusters
"""
import numpy as np
import pandas as pd
from strategies.base import Signal

# ═══ 11 Core Strategies (Phase 2 — quality over quantity) ═══
from strategies.smc import SMCStrategy
from strategies.market_structure import MarketStructureStrategy
from strategies.macd_strategy import MACDStrategy
from strategies.rsi_strategy import RSIStrategy
from strategies.atr_analyzer import ATRStrategy
from strategies.moving_average import MAStrategy
from strategies.cvd_strategy import CVDStrategy
from strategies.obv_cmf import OBVCMFStrategy
from strategies.vwap import VWAPStrategy
from strategies.support_resistance import SupportResistanceStrategy
from strategies.divergence import DivergenceStrategy

# نظام الأوزان
try:
    from engine.weights import load_weights, STRATEGY_NAMES, get_regime_adjusted_weights
except ImportError:
    load_weights = lambda: {}
    STRATEGY_NAMES = []
    get_regime_adjusted_weights = lambda regime_data, base_weights: base_weights


ALL_STRATEGIES = [
    # ─── Structure (2) ───
    SMCStrategy(),
    MarketStructureStrategy(),
    # ─── Momentum (2) ───
    MACDStrategy(),
    RSIStrategy(),
    # ─── Flow & Volume (3) ───
    CVDStrategy(),
    OBVCMFStrategy(),
    VWAPStrategy(),
    # ─── Trend & Levels (2) ───
    MAStrategy(),
    SupportResistanceStrategy(),
    # ─── Volatility (1) ───
    ATRStrategy(),
    # ─── Reversal (1) ───
    DivergenceStrategy(),
]

# Simplified clusters (6 groups, 11 strategies)
CLUSTERS = {
    "structure": {
        "members": ["SMC (Smart Money)", "Market Structure"],
        "quality_weight": 0.90,
    },
    "momentum": {
        "members": ["MACD", "RSI"],
        "quality_weight": 0.65,
    },
    "flow": {
        "members": ["Volume Analysis", "OBV + CMF", "VWAP"],
        "quality_weight": 0.75,
    },
    "trend": {
        "members": ["Moving Averages", "Support & Resistance"],
        "quality_weight": 0.65,
    },
    "volatility": {
        "members": ["ATR Volatility"],
        "quality_weight": 0.60,
    },
    "reversal": {
        "members": ["Divergence"],
        "quality_weight": 0.70,
    },
}

# Max weight per cluster (prevents triple-counting)
MAX_INTRA_CLUSTER_WEIGHT = 1.5

# Inter-cluster agreement bonus per additional cluster
INTER_CLUSTER_BONUS = 0.12  # +12% quality per additional agreeing cluster


class AnalysisResult:
    """النتيجة النهائية لتحليل عملة واحدة"""
    def __init__(self, symbol: str, price: float, signals: list, timeframe: str,
                 sr_data: dict = None, regime_data: dict = None):
        self.symbol = symbol
        self.price = price
        self.signals = signals
        self.timeframe = timeframe
        self.regime_data = regime_data
        self.aggregated = self._aggregate()
        self.sr = sr_data or {"supports": [], "resistances": [], "ma20": price, "ma50": price, "ma200": price}

    def _aggregate(self) -> dict:
        """دمج نتائج جميع الاستراتيجيات — 🆕 v4: meta-confluence + quality + neutral fix"""
        entries = []
        stops = []
        targets_list = []
        buy_signals = []
        sell_signals = []
        total_confidence = 0.0
        active_signal_count = 0  # 🆕 Only BUY/SELL count (not NEUTRAL)

        # تحميل الأوزان الحالية (🆕 regime-adjusted)
        base_weights = load_weights()
        weights = get_regime_adjusted_weights(self.regime_data, base_weights) if self.regime_data else base_weights

        # Track cluster contributions for de-dup + meta-confluence
        cluster_buy_weights = {c: 0.0 for c in CLUSTERS}
        cluster_sell_weights = {c: 0.0 for c in CLUSTERS}
        cluster_buy_present = set()
        cluster_sell_present = set()

        for s in self.signals:
            # 🆕 NEUTRAL fix: contributes ZERO to confidence
            # Previously: neutral added 0.3 * confidence to total AND counted in signal_count
            # Now: neutral is tracked separately, does NOT dilute active signals
            if s.signal == "NEUTRAL":
                continue

            # وزن الاستراتيجية (base weight from performance)
            w = weights.get(s.name, 1.0)

            # 🆕 Find which cluster this strategy belongs to
            strategy_cluster = None
            cluster_quality = 1.0
            for cluster_name, cluster_info in CLUSTERS.items():
                if s.name in cluster_info["members"]:
                    strategy_cluster = cluster_name
                    cluster_quality = cluster_info["quality_weight"]
                    break

            # 🆕 Intra-cluster cap: prevent triple-counting same cluster
            if strategy_cluster:
                if s.signal == "BUY":
                    current_w = cluster_buy_weights[strategy_cluster]
                    if current_w + w > MAX_INTRA_CLUSTER_WEIGHT:
                        w = max(0.1, MAX_INTRA_CLUSTER_WEIGHT - current_w)
                    cluster_buy_weights[strategy_cluster] += w
                    cluster_buy_present.add(strategy_cluster)
                else:  # SELL
                    current_w = cluster_sell_weights[strategy_cluster]
                    if current_w + w > MAX_INTRA_CLUSTER_WEIGHT:
                        w = max(0.1, MAX_INTRA_CLUSTER_WEIGHT - current_w)
                    cluster_sell_weights[strategy_cluster] += w
                    cluster_sell_present.add(strategy_cluster)

            # 🆕 Quality-weighted confidence contribution
            quality_adjusted_conf = s.confidence * w * cluster_quality
            total_confidence += quality_adjusted_conf
            active_signal_count += 1

            if s.signal == "BUY":
                buy_signals.append((s, w))
            elif s.signal == "SELL":
                sell_signals.append((s, w))

        # 🆕 Weighted votes (intra-cluster-capped weights)
        weighted_buy = sum(w for _, w in buy_signals)
        weighted_sell = sum(w for _, w in sell_signals)

        if weighted_buy > weighted_sell:
            direction = "BUY"
            primary = [s for s, _ in buy_signals]
            agreeing_clusters = cluster_buy_present
            total_cluster_weight = sum(
                min(cluster_buy_weights[c], MAX_INTRA_CLUSTER_WEIGHT)
                for c in cluster_buy_present
            )
        elif weighted_sell > weighted_buy:
            direction = "SELL"
            primary = [s for s, _ in sell_signals]
            agreeing_clusters = cluster_sell_present
            total_cluster_weight = sum(
                min(cluster_sell_weights[c], MAX_INTRA_CLUSTER_WEIGHT)
                for c in cluster_sell_present
            )
        else:
            direction = "NEUTRAL"
            primary = [s for s, _ in buy_signals + sell_signals]
            agreeing_clusters = set()
            total_cluster_weight = 0

        # نجيب الإدخال والإيقاف والأهداف فقط من الإشارات المتفقة مع الاتجاه
        for s in primary:
            if s.signal != direction and direction != "NEUTRAL":
                continue
            if s.entry: entries.append(s.entry)
            if s.stop_loss: stops.append(s.stop_loss)
            if s.targets: targets_list.append(s.targets)

        # متوسط الدخول
        avg_entry = float(np.mean(entries)) if entries else self.price
        avg_stop = float(np.mean(stops)) if stops else None

        # كاب لوقف الخسارة — ما يزيد عن 20٪ من سعر الدخول
        if avg_stop and avg_entry > 0:
            if direction == "BUY":
                max_stop = avg_entry * 0.80
                if avg_stop < max_stop:
                    avg_stop = max_stop
            elif direction == "SELL":
                max_stop = avg_entry * 1.20
                if avg_stop > max_stop:
                    avg_stop = max_stop
            else:
                min_stop = avg_entry * 0.80
                max_stop = avg_entry * 1.20
                if avg_stop < min_stop:
                    avg_stop = min_stop
                elif avg_stop > max_stop:
                    avg_stop = max_stop

        # متوسط الأهداف
        avg_targets = []
        if targets_list:
            for level in range(3):
                level_targets = [float(t[level]) for t in targets_list if len(t) > level]
                if level_targets:
                    avg_targets.append(round(float(np.mean(level_targets)), 8))

        if not avg_targets and avg_entry and avg_entry > 0:
            if direction == "BUY":
                avg_targets = [round(avg_entry * 1.03, 8), round(avg_entry * 1.06, 8), round(avg_entry * 1.10, 8)]
            elif direction == "SELL":
                avg_targets = [round(avg_entry * 0.97, 8), round(avg_entry * 0.94, 8), round(avg_entry * 0.90, 8)]
            else:
                avg_targets = [round(avg_entry * 1.03, 8), round(avg_entry * 1.05, 8), round(avg_entry * 1.08, 8)]

        if not avg_stop:
            avg_stop = avg_entry * 0.95 if direction == "BUY" else avg_entry * 1.05 if direction == "SELL" else avg_entry * 0.97

        # 🆕 CONFIDENCE: average of active (BUY/SELL) quality-adjusted confidences ONLY
        avg_confidence = total_confidence / max(active_signal_count, 1)

        # 🆕 STRENGTH: agreement ratio × confidence
        total_weight = weighted_buy + weighted_sell
        if total_weight > 0:
            agreement = max(weighted_buy, weighted_sell) / total_weight
        else:
            agreement = 0.5
        final_strength = agreement * (avg_confidence / 100) * 100

        # 🆕 QUALITY SCORE: independent of confidence
        # Based on: cluster count, cluster quality weights, agreement ratio
        num_agreeing_clusters = len(agreeing_clusters)
        if num_agreeing_clusters > 0:
            avg_cluster_quality = sum(
                CLUSTERS[c]["quality_weight"] for c in agreeing_clusters
            ) / num_agreeing_clusters
        else:
            avg_cluster_quality = 0.5

        # Inter-cluster bonus: more clusters agreeing = higher quality
        inter_cluster_bonus = (num_agreeing_clusters - 1) * INTER_CLUSTER_BONUS if num_agreeing_clusters > 1 else 0

        # Quality score: combines cluster diversity + agreement strength + cluster quality
        quality_score = min(95, round((
            avg_cluster_quality * 40 +           # Base: how good are the agreeing clusters
            inter_cluster_bonus * 30 +           # Bonus: cross-cluster agreement
            agreement * 30                        # Agreement ratio contribution
        ), 1))

        # 🆕 Quality-adjusted strength for final output
        quality_adjusted_strength = round(final_strength * (0.6 + 0.4 * (quality_score / 100)), 1)

        return {
            "direction": direction,
            "entry": round(avg_entry, 8),
            "stop_loss": round(avg_stop, 8) if avg_stop else None,
            "targets": avg_targets,
            "confidence": round(avg_confidence, 1),
            "buy_count": len(buy_signals),
            "sell_count": len(sell_signals),
            "neutral_count": len([s for s in self.signals if s.signal == "NEUTRAL"]),
            "active_count": active_signal_count,
            "weighted_buy": round(weighted_buy, 2),
            "weighted_sell": round(weighted_sell, 2),
            "strength": round(final_strength, 1),
            "quality_score": quality_score,
            "quality_str": round(quality_adjusted_strength, 1),
            "agreeing_clusters": list(agreeing_clusters),
            "num_clusters": num_agreeing_clusters,
            "reasons": [s.reason for s, _ in buy_signals + sell_signals if s.reason],
            "buy_reasons": [s.reason for s, _ in buy_signals if s.reason],
            "sell_reasons": [s.reason for s, _ in sell_signals if s.reason],
        }

    def summary(self) -> str:
        a = self.aggregated
        lines = [
            f"━━━ {self.symbol} ━━━",
            f"📊 السعر الحالي: ${self.price:.4f}",
            f"🎯 الاتجاه: {'شراء 🟢' if a['direction']=='BUY' else 'بيع 🔴' if a['direction']=='SELL' else 'محايد ⚪'}",
            f"📥 الدخول: ${a['entry']:.4f}",
        ]
        if a['stop_loss']:
            loss_pct = (a['stop_loss'] - a['entry']) / a['entry'] * 100 if a['direction'] == 'BUY' else (a['entry'] - a['stop_loss']) / a['entry'] * 100
            lines.append(f"🛑 وقف الخسارة: ${a['stop_loss']:.4f} ({abs(loss_pct):.1f}%)")
        if a['targets']:
            lines.append(f"🎯 الأهداف:")
            for i, t in enumerate(a['targets']):
                gain_pct = (t - a['entry']) / a['entry'] * 100 if a['direction'] == 'BUY' else (a['entry'] - t) / a['entry'] * 100
                lines.append(f"   T{i+1}: ${t:.4f} (ربح {abs(gain_pct):.1f}%)")
        lines.append(f"📊 الثقة: {a['confidence']:.0f}% | الجودة: {a['quality_score']:.0f}%")
        lines.append(f"💪 القوة: {a['strength']:.0f}% | 🏛️ تجمعات: {a['num_clusters']}")
        if a['reasons']:
            lines.append(f"📋 أهم الأسباب:")
            for r in a['reasons'][:5]:
                lines.append(f"   • {r}")
        return "\n".join(lines)


class Analyzer:
    """يحلل عملة بكل الاستراتيجيات"""

    def __init__(self, strategies: list = None, regime_data: dict = None):
        self.strategies = strategies or ALL_STRATEGIES
        self.regime_data = regime_data

    def analyze(self, symbol: str, df_dict: dict, timeframe: str = "4h") -> AnalysisResult:
        """تحليل عملة بكل المدارس"""
        df = df_dict.get(timeframe)
        if df is None or len(df) < 50:
            raise ValueError(f"بيانات غير كافية لـ {symbol} على {timeframe}")

        price = df["close"].iloc[-1]
        signals = []

        for strategy in self.strategies:
            try:
                signal = strategy.analyze(df)
                signals.append(signal)
            except Exception as e:
                signals.append(Signal(
                    name=strategy.name, signal="NEUTRAL", strength=0,
                    entry=price, confidence=0,
                    reason=f"⚠️ خطأ: {str(e)[:50]}"
                ))

        sr_data = self._compute_sr(df, price)

        return AnalysisResult(symbol, price, signals, timeframe, sr_data, self.regime_data)

    def _compute_sr(self, df: pd.DataFrame, price: float) -> dict:
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values

        supports = []
        window = 8
        for i in range(window, len(lows) - window):
            if all(lows[i] <= lows[i - j] and lows[i] <= lows[i + j] for j in range(1, window + 1)):
                supports.append(lows[i])

        resistances = []
        for i in range(window, len(highs) - window):
            if all(highs[i] >= highs[i - j] and highs[i] >= highs[i + j] for j in range(1, window + 1)):
                resistances.append(highs[i])

        supports_below = sorted([s for s in supports if s < price], reverse=True)[:3]
        resistances_above = sorted([r for r in resistances if r > price])[:3]

        ma20 = float(np.mean(closes[-20:])) if len(closes) >= 20 else price
        ma50 = float(np.mean(closes[-50:])) if len(closes) >= 50 else price
        ma200 = float(np.mean(closes[-200:])) if len(closes) >= 200 else price

        return {
            "supports": supports_below,
            "resistances": resistances_above,
            "ma20": round(ma20, 8),
            "ma50": round(ma50, 8),
            "ma200": round(ma200, 8),
        }
