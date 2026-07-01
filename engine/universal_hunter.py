"""
🦅 Universal Coin Hunter — Multi-Exchange Pre-Pump Scanner
Phase 9.0 — Scans ALL coins across ALL exchanges, detects pre-pump conditions

Architecture:
  1. Fetch all USDT pairs from MEXC + OKX + KuCoin + Gate + Bitget
  2. Deduplicate (same base coin → pick highest-volume exchange)
  3. Multi-stage mechanical filtering (fast, no AI)
  4. Score & rank candidates (Kronos-style multi-factor scoring)
  5. Return top candidates for AI analysis

Stages:
  Stage 0: Fetch & dedup (2,000-8,000 pairs → ~2,500 unique)
  Stage 1: Basic filters (price > $0, 24h vol > $50K) → ~800-1,200
  Stage 2: Pre-pump detection (ATR contraction, BB squeeze, CVD, volume dry-up) → ~100-200
  Stage 3: Technical scan (trend, S/R proximity, MA alignment) → ~30-50
  Stage 4: Multi-factor scoring & ranking → top 20
"""
import json
import logging
import time
import requests
from typing import Optional
from pathlib import Path

from data.fetcher import EXCLUDED_SYMBOLS

logger = logging.getLogger("crypto-signal-hunter")

# ═══════════════ Exchange Config ═══════════════
EXCHANGES = {
    "mexc": {
        "ticker_url": "https://api.mexc.com/api/v3/ticker/24hr",
        "klines_url": "https://api.mexc.com/api/v3/klines",
        "timeout": 15,
    },
    "okx": {
        "ticker_url": "https://www.okx.com/api/v5/market/tickers?instType=SPOT",
        "klines_url": "https://www.okx.com/api/v5/market/candles",
        "timeout": 15,
        "wrapper": "okx",  # Different response format
    },
    "kucoin": {
        "ticker_url": "https://api.kucoin.com/api/v1/market/allTickers",
        "klines_url": "https://api.kucoin.com/api/v1/market/candles",
        "timeout": 15,
        "wrapper": "kucoin",
    },
    "gate": {
        "ticker_url": "https://api.gateio.ws/api/v4/spot/tickers",
        "klines_url": "https://api.gateio.ws/api/v4/spot/candlesticks",
        "timeout": 15,
        "wrapper": "gate",
    },
    "bitget": {
        "ticker_url": "https://api.bitget.com/api/v2/spot/market/tickers",
        "klines_url": "https://api.bitget.com/api/v2/spot/market/candles",
        "timeout": 15,
        "wrapper": "bitget",
    },
}

# ═══════════════ Filter Constants ═══════════════
MIN_24H_VOL_USD = 50000      # Minimum 24h volume
MIN_PRICE = 0.0001            # Exclude dust
MAX_PRICE = 50000             # Exclude ultra-expensive (BTC already covered)
MAX_SPREAD_PCT = 5.0          # Max bid/ask spread
MIN_CVD_DAYS = 3              # CVD must be positive over this many days

# ═══════════════ Pre-Pump Detection ═══════════════
BB_SQUEEZE_THRESHOLD = 0.15   # BB width < 15% of price → squeeze
ATR_CONTRACTION_PCT = 0.02    # ATR < 2% of price → coiled spring
VOLUME_DRYUP_RATIO = 0.6      # Current vol < 60% of 20-period avg → drying up
CVD_POSITIVE_DAYS = 2         # CVD positive for last N days
OBV_DIVERGENCE_LOOKBACK = 14  # Lookback for OBV divergence


class UniversalHunter:
    """
    Multi-exchange coin hunter with pre-pump detection.
    
    Usage:
        hunter = UniversalHunter()
        candidates = hunter.hunt(max_candidates=30)
        # candidates is list of dicts with symbol, price, score, signals, etc.
    """
    
    def __init__(self):
        self.all_coins = {}     # {base_symbol: {exchange, symbol, price, volume, ...}}
        self.candidates = []
        self.stats = {
            "stage0_fetched": 0,
            "stage0_deduped": 0,
            "stage1_passed": 0,
            "stage2_passed": 0,
            "stage3_passed": 0,
            "stage4_final": 0,
        }
    
    # ═══════════════════════════════════════════
    # STAGE 0: Fetch & Dedup
    # ═══════════════════════════════════════════
    
    def _fetch_mexc_tickers(self) -> list:
        """Fetch all USDT tickers from MEXC"""
        try:
            resp = requests.get(EXCHANGES["mexc"]["ticker_url"], timeout=15)
            data = resp.json()
            pairs = []
            for item in data:
                symbol = item.get("symbol", "")
                if not symbol.endswith("USDT"):
                    continue
                # 🚫 Skip excluded symbols (stablecoins, gold-pegged, etc.)
                if symbol in EXCLUDED_SYMBOLS:
                    continue
                try:
                    vol = float(item.get("quoteVolume", 0) or 0)
                    price = float(item.get("lastPrice", 0) or 0)
                    change = float(item.get("priceChangePercent", 0) or 0)
                    high = float(item.get("highPrice", 0) or 0)
                    low = float(item.get("lowPrice", 0) or 0)
                    base = symbol.replace("USDT", "")
                    pairs.append({
                        "symbol": symbol,
                        "exchange": "mexc",
                        "base": base,
                        "price": price,
                        "volume_24h": vol,
                        "change_24h": change,
                        "high_24h": high,
                        "low_24h": low,
                    })
                except (ValueError, TypeError):
                    continue
            logger.info(f"MEXC: {len(pairs)} USDT pairs fetched")
            return pairs
        except Exception as e:
            logger.warning(f"MEXC ticker fetch failed: {e}")
            return []
    
    def _fetch_okx_tickers(self) -> list:
        """Fetch all USDT spot tickers from OKX"""
        try:
            resp = requests.get(EXCHANGES["okx"]["ticker_url"], timeout=15)
            data = resp.json()
            if data.get("code") != "0":
                return []
            pairs = []
            for item in data.get("data", []):
                inst_id = item.get("instId", "")
                if not inst_id.endswith("-USDT"):
                    continue
                symbol = inst_id.replace("-", "")
                base = inst_id.replace("-USDT", "")
                try:
                    vol = float(item.get("vol24h", 0) or 0)
                    price = float(item.get("last", 0) or 0)
                    change_pct = (float(item.get("last", 0) or 0) / float(item.get("open24h", 1) or 1) - 1) * 100 if float(item.get("open24h", 0) or 0) > 0 else 0
                    high = float(item.get("high24h", 0) or 0)
                    low = float(item.get("low24h", 0) or 0)
                    pairs.append({
                        "symbol": symbol,
                        "exchange": "okx",
                        "base": base,
                        "price": price,
                        "volume_24h": vol * price,  # OKX returns base vol, convert to USD
                        "change_24h": change_pct,
                        "high_24h": high,
                        "low_24h": low,
                    })
                except (ValueError, TypeError):
                    continue
            logger.info(f"OKX: {len(pairs)} USDT pairs fetched")
            return pairs
        except Exception as e:
            logger.warning(f"OKX ticker fetch failed: {e}")
            return []
    
    def _fetch_kucoin_tickers(self) -> list:
        """Fetch all USDT tickers from KuCoin"""
        try:
            resp = requests.get(EXCHANGES["kucoin"]["ticker_url"], timeout=15)
            data = resp.json()
            if data.get("code") != "200000":
                return []
            pairs = []
            tickers = data.get("data", {}).get("ticker", [])
            for item in tickers:
                symbol = item.get("symbol", "")
                if not symbol.endswith("-USDT"):
                    continue
                clean_symbol = symbol.replace("-", "")
                base = symbol.replace("-USDT", "")
                try:
                    vol = float(item.get("volValue", 0) or 0)  # KuCoin gives USD volume
                    price = float(item.get("last", 0) or 0)
                    change = float(item.get("changeRate", 0) or 0) * 100
                    high = float(item.get("high", 0) or 0)
                    low = float(item.get("low", 0) or 0)
                    pairs.append({
                        "symbol": clean_symbol,
                        "exchange": "kucoin",
                        "base": base,
                        "price": price,
                        "volume_24h": vol,
                        "change_24h": change,
                        "high_24h": high,
                        "low_24h": low,
                    })
                except (ValueError, TypeError):
                    continue
            logger.info(f"KuCoin: {len(pairs)} USDT pairs fetched")
            return pairs
        except Exception as e:
            logger.warning(f"KuCoin ticker fetch failed: {e}")
            return []
    
    def _fetch_gate_tickers(self) -> list:
        """Fetch all USDT tickers from Gate.io"""
        try:
            resp = requests.get(EXCHANGES["gate"]["ticker_url"], timeout=15)
            data = resp.json()
            pairs = []
            for item in data:
                pair = item.get("currency_pair", "")
                if not pair.endswith("_USDT"):
                    continue
                symbol = pair.replace("_", "")
                base = pair.replace("_USDT", "")
                try:
                    vol = float(item.get("quote_volume", 0) or 0)
                    price = float(item.get("last", 0) or 0)
                    change = float(item.get("change_percentage", 0) or 0)
                    high = float(item.get("high_24h", 0) or 0)
                    low = float(item.get("low_24h", 0) or 0)
                    pairs.append({
                        "symbol": symbol,
                        "exchange": "gate",
                        "base": base,
                        "price": price,
                        "volume_24h": vol,
                        "change_24h": change,
                        "high_24h": high,
                        "low_24h": low,
                    })
                except (ValueError, TypeError):
                    continue
            logger.info(f"Gate.io: {len(pairs)} USDT pairs fetched")
            return pairs
        except Exception as e:
            logger.warning(f"Gate.io ticker fetch failed: {e}")
            return []
    
    def _fetch_bitget_tickers(self) -> list:
        """Fetch all USDT tickers from Bitget"""
        try:
            resp = requests.get(EXCHANGES["bitget"]["ticker_url"], timeout=15)
            data = resp.json()
            if data.get("code") != "00000":
                return []
            pairs = []
            for item in data.get("data", []):
                symbol = item.get("symbol", "")
                if not symbol.endswith("USDT"):
                    continue
                base = symbol.replace("USDT", "")
                try:
                    vol = float(item.get("usdtVolume", 0) or 0)
                    price = float(item.get("lastPr", 0) or 0)
                    change = float(item.get("changePercent", 0) or 0)
                    high = float(item.get("high24h", 0) or 0)
                    low = float(item.get("low24h", 0) or 0)
                    pairs.append({
                        "symbol": symbol,
                        "exchange": "bitget",
                        "base": base,
                        "price": price,
                        "volume_24h": vol,
                        "change_24h": change,
                        "high_24h": high,
                        "low_24h": low,
                    })
                except (ValueError, TypeError):
                    continue
            logger.info(f"Bitget: {len(pairs)} USDT pairs fetched")
            return pairs
        except Exception as e:
            logger.warning(f"Bitget ticker fetch failed: {e}")
            return []
    
    def _fetch_all_tickers(self) -> list:
        """Fetch tickers from all exchanges in parallel (sequentially for safety)"""
        all_pairs = []
        
        fetchers = [
            ("MEXC", self._fetch_mexc_tickers),
            ("OKX", self._fetch_okx_tickers),
            ("KuCoin", self._fetch_kucoin_tickers),
            ("Gate.io", self._fetch_gate_tickers),
            ("Bitget", self._fetch_bitget_tickers),
        ]
        
        for name, fetcher in fetchers:
            try:
                pairs = fetcher()
                all_pairs.extend(pairs)
                logger.info(f"  {name}: {len(pairs)} pairs")
            except Exception as e:
                logger.warning(f"  {name}: FAILED — {e}")
        
        self.stats["stage0_fetched"] = len(all_pairs)
        logger.info(f"Stage 0: {len(all_pairs)} total pairs fetched from all exchanges")
        return all_pairs
    
    def _deduplicate(self, all_pairs: list) -> dict:
        """
        Deduplicate: same base coin on multiple exchanges → pick highest 24h volume.
        Returns: {base_symbol: best_pair_dict}
        """
        deduped = {}
        for pair in all_pairs:
            base = pair["base"]
            if base not in deduped or pair["volume_24h"] > deduped[base]["volume_24h"]:
                deduped[base] = pair
        
        self.stats["stage0_deduped"] = len(deduped)
        logger.info(f"Stage 0 dedup: {len(all_pairs)} → {len(deduped)} unique coins")
        return deduped
    
    # ═══════════════════════════════════════════
    # STAGE 1: Basic Filters
    # ═══════════════════════════════════════════
    
    def _stage1_filter(self, coins: dict) -> dict:
        """
        Filter out:
        - Ultra-low volume (< $50K/24h)
        - Dust prices (< $0.0001)
        - Ultra-expensive (> $50K, BTC already covered)
        - Stablecoins (USDC, DAI, BUSD, etc.)
        """
        stablecoins = {"USDC", "DAI", "BUSD", "TUSD", "USDP", "USDD", "FDUSD", "USDE", "USDX"}
        passed = {}
        
        for base, coin in coins.items():
            if base in stablecoins:
                continue
            if coin["volume_24h"] < MIN_24H_VOL_USD:
                continue
            if coin["price"] < MIN_PRICE:
                continue
            if coin["price"] > MAX_PRICE:
                continue
            # Exclude leveraged tokens
            if "UPUSDT" in coin["symbol"] or "DOWNUSDT" in coin["symbol"]:
                continue
            if "BEAR" in coin["symbol"] or "BULL" in coin["symbol"]:
                continue
            
            passed[base] = coin
        
        self.stats["stage1_passed"] = len(passed)
        logger.info(f"Stage 1 filter: {len(coins)} → {len(passed)} (vol>{MIN_24H_VOL_USD}, price>{MIN_PRICE})")
        return passed
    
    # ═══════════════════════════════════════════
    # STAGE 2: Pre-Pump Detection (Mechanical)
    # ═══════════════════════════════════════════
    
    def _detect_pre_pump(self, symbol: str, exchange: str) -> dict:
        """
        Run pre-pump detection signals on a single coin.
        Uses DIRECT MEXC API (fast, single-exchange) instead of multi-exchange fetcher.
        Returns dict with signals and scores, or None if data unavailable.
        """
        try:
            import numpy as np
            
            # 🔧 Direct MEXC klines — MUCH faster than multi-exchange fetch_klines
            kline_url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=4h&limit=100"
            resp = requests.get(kline_url, timeout=8)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if not data or len(data) < 50:
                return None
            
            # Parse kline data [open_time, open, high, low, close, volume, ...]
            closes = np.array([float(c[4]) for c in data])
            highs = np.array([float(c[2]) for c in data])
            lows = np.array([float(c[3]) for c in data])
            volumes = np.array([float(c[5]) for c in data])
            
            price = closes[-1]
            if price <= 0:
                return None
            
            signals = {}
            scores = {}
            
            # ─── 1. ATR Contraction (coiled spring) ───
            atr = self._calc_atr(highs, lows, closes, 14)
            atr_pct = atr / price if price > 0 else 999
            signals["atr_pct"] = round(atr_pct * 100, 2)
            if atr_pct < ATR_CONTRACTION_PCT:
                scores["atr_squeeze"] = 25  # Strong signal
            elif atr_pct < ATR_CONTRACTION_PCT * 1.5:
                scores["atr_squeeze"] = 15
            else:
                scores["atr_squeeze"] = 0
            
            # ─── 2. BB Squeeze (Bollinger Band width) ───
            bb_width = self._calc_bb_width(closes, 20, 2)
            signals["bb_width_pct"] = round(bb_width * 100, 2)
            if bb_width < BB_SQUEEZE_THRESHOLD:
                scores["bb_squeeze"] = 25
            elif bb_width < BB_SQUEEZE_THRESHOLD * 1.5:
                scores["bb_squeeze"] = 15
            else:
                scores["bb_squeeze"] = 0
            
            # ─── 3. Volume Dry-Up (quiet before storm) ───
            vol_ma20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else volumes[-1]
            vol_current = volumes[-1] if len(volumes) > 0 else 0
            vol_ratio = vol_current / vol_ma20 if vol_ma20 > 0 else 1
            signals["vol_ratio"] = round(vol_ratio, 2)
            if vol_ratio < VOLUME_DRYUP_RATIO:
                scores["vol_dryup"] = 20
            elif vol_ratio < VOLUME_DRYUP_RATIO * 1.2:
                scores["vol_dryup"] = 10
            else:
                scores["vol_dryup"] = 0
            
            # ─── 4. CVD Direction (accumulation) ───
            try:
                from engine.cvd_strategy import compute_cvd
                cvd = compute_cvd(df)
                if cvd is not None and hasattr(cvd, 'values'):
                    cvd_vals = cvd.values if hasattr(cvd, 'values') else cvd
                    if len(cvd_vals) >= CVD_POSITIVE_DAYS + 1:
                        cvd_slope = (cvd_vals[-1] - cvd_vals[-CVD_POSITIVE_DAYS-1]) / (price * CVD_POSITIVE_DAYS)
                        signals["cvd_slope"] = round(cvd_slope, 6)
                        if cvd_slope > 0.0005:
                            scores["cvd_positive"] = 15
                        elif cvd_slope > 0:
                            scores["cvd_positive"] = 8
                        else:
                            scores["cvd_positive"] = 0
                    else:
                        scores["cvd_positive"] = 0
                else:
                    scores["cvd_positive"] = 0
            except Exception as e:
                logger.debug(f"CVD compute failure: {e}")
                scores["cvd_positive"] = 0  # CVD compute failure non-fatal
            
            # ─── 5. Price Position (near support = higher bounce potential) ───
            recent_low = np.min(lows[-20:])
            recent_high = np.max(highs[-20:])
            price_range = recent_high - recent_low
            if price_range > 0:
                price_position = (price - recent_low) / price_range
                signals["price_position"] = round(price_position, 2)
                if price_position < 0.3:  # Near bottom of range
                    scores["near_support"] = 20
                elif price_position < 0.5:
                    scores["near_support"] = 10
                else:
                    scores["near_support"] = 0
            else:
                scores["near_support"] = 0
            
            # ─── 6. MA Compression (multiple MAs converging) ───
            ma10 = np.mean(closes[-10:]) if len(closes) >= 10 else price
            ma20 = np.mean(closes[-20:]) if len(closes) >= 20 else price
            ma50 = np.mean(closes[-50:]) if len(closes) >= 50 else price
            ma_spread = (max(ma10, ma20, ma50) - min(ma10, ma20, ma50)) / price
            signals["ma_spread_pct"] = round(ma_spread * 100, 2)
            if ma_spread < 0.03:
                scores["ma_compression"] = 15
            elif ma_spread < 0.05:
                scores["ma_compression"] = 8
            else:
                scores["ma_compression"] = 0
            
            # ─── 7. Higher Low formation (bullish structure) ───
            hl_signal = self._detect_higher_lows(lows, 14)
            signals["higher_lows"] = hl_signal
            if hl_signal:
                scores["higher_lows"] = 10
            else:
                scores["higher_lows"] = 0
            
            # ─── Total pre-pump score ───
            total_score = sum(scores.values())
            
            return {
                "price": price,
                "signals": signals,
                "scores": scores,
                "total_score": total_score,
                "max_score": 130,  # Max possible score
            }
            
        except Exception as e:
            logger.debug(f"Pre-pump detection failed for {symbol}: {e}")
            return None
    
    def _calc_atr(self, highs, lows, closes, period=14):
        """Calculate ATR"""
        import numpy as np
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                abs(highs[1:] - closes[:-1]),
                abs(lows[1:] - closes[:-1])
            )
        )
        return np.mean(tr[-period:]) if len(tr) >= period else tr[-1] if len(tr) > 0 else 0
    
    def _calc_bb_width(self, closes, period=20, std=2):
        """Calculate Bollinger Band width as percentage of price"""
        import numpy as np
        if len(closes) < period:
            return 1.0
        ma = np.mean(closes[-period:])
        std_val = np.std(closes[-period:])
        upper = ma + std * std_val
        lower = ma - std * std_val
        if ma > 0:
            return (upper - lower) / ma
        return 1.0
    
    def _detect_higher_lows(self, lows, lookback=14):
        """Detect if recent lows are trending higher"""
        import numpy as np
        if len(lows) < lookback * 2:
            return False
        first_half_low = np.min(lows[-lookback*2:-lookback])
        second_half_low = np.min(lows[-lookback:])
        return second_half_low > first_half_low
    
    def _stage2_prepump_scan(self, coins: dict) -> list:
        """
        Run pre-pump detection on all coins that passed Stage 1.
        Returns list of candidates with scores.
        """
        candidates = []
        total = len(coins)
        
        for i, (base, coin) in enumerate(coins.items()):
            if i % 200 == 0:
                logger.info(f"  Pre-pump scan: {i}/{total}...")
            
            result = self._detect_pre_pump(coin["symbol"], coin["exchange"])
            if result is None:
                continue
            
            # Stage 2 threshold: need at least 30/130 pre-pump score
            if result["total_score"] < 30:
                continue
            
            candidate = {
                **coin,
                "price": result["price"],
                "pre_pump_signals": result["signals"],
                "pre_pump_scores": result["scores"],
                "pre_pump_total": result["total_score"],
            }
            candidates.append(candidate)
            
            # Small delay to avoid rate limiting
            if i % 10 == 0:
                time.sleep(0.05)
        
        # Sort by pre-pump score
        candidates.sort(key=lambda c: c["pre_pump_total"], reverse=True)
        
        self.stats["stage2_passed"] = len(candidates)
        logger.info(f"Stage 2 pre-pump: {total} → {len(candidates)} candidates (score >= 30)")
        return candidates
    
    # ═══════════════════════════════════════════
    # STAGE 3: Technical Analysis Scan
    # ═══════════════════════════════════════════
    
    def _stage3_technical_scan(self, candidates: list) -> list:
        """
        Run full technical analysis on candidates.
        Uses DIRECT MEXC API for speed (avoids multi-exchange overhead).
        Filters to top candidates with confirmed technical signals.
        """
        from engine.analyzer import Analyzer
        import pandas as pd
        
        analyzer = Analyzer()
        passed = []
        total = min(len(candidates), 50)  # Cap at 50 for performance
        
        for i, c in enumerate(candidates[:total]):
            try:
                # 🔧 Direct MEXC klines — avoids multi-exchange fetcher overhead
                kline_url = f"https://api.mexc.com/api/v3/klines?symbol={c['symbol']}&interval=4h&limit=100"
                resp = requests.get(kline_url, timeout=10)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if not data or len(data) < 50:
                    continue
                
                # Parse to DataFrame for Analyzer
                df = pd.DataFrame(data, columns=[
                    "open_time", "open", "high", "low", "close", "volume",
                    "close_time", "quote_vol"
                ])
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = df[col].astype(float)
                
                result = analyzer.analyze(c["symbol"], {"4h": df}, "4h")
                a = result.aggregated
                
                # Must be BUY
                if a["direction"] != "BUY":
                    continue
                
                # Enhance candidate with technical data
                c["ta_direction"] = a["direction"]
                c["ta_confidence"] = a["confidence"]
                c["ta_strength"] = a["strength"]
                c["ta_entry"] = a["entry"]
                c["ta_targets"] = a["targets"]
                c["ta_stop_loss"] = a["stop_loss"]
                c["ta_signals"] = [s.name for s in getattr(result, "signals", []) if s.signal == "BUY"]
                
                # Combined score: pre-pump (40%) + technical (60%)
                ta_score_normalized = min(a["strength"] / 100, 1.0) * 100
                combined_score = c["pre_pump_total"] * 0.4 + ta_score_normalized * 0.6
                c["combined_score"] = round(combined_score, 1)
                
                # Risk-adjusted score: penalize if confidence < strength
                confidence_gap = max(0, a["strength"] - a["confidence"])
                c["risk_adj_score"] = round(combined_score - confidence_gap * 0.3, 1)
                
                passed.append(c)
                
                if i % 10 == 0:
                    time.sleep(0.05)
                    
            except Exception as e:
                logger.debug(f"Technical scan failed for {c['symbol']}: {e}")
                continue
        
        # Sort by risk-adjusted score
        passed.sort(key=lambda c: c.get("risk_adj_score", 0), reverse=True)
        
        self.stats["stage3_passed"] = len(passed)
        logger.info(f"Stage 3 technical: {len(candidates)} → {len(passed)} BUY candidates")
        return passed
    
    # ═══════════════════════════════════════════
    # STAGE 4: Final Ranking
    # ═══════════════════════════════════════════
    
    def _stage4_final_ranking(self, candidates: list, max_final: int = 30) -> list:
        """
        Final ranking with adaptive quality filters based on market regime.
        In BEAR: lower thresholds (opportunities are rarer, any BUY signal is notable)
        In BULL: higher thresholds (many signals, need to filter noise)
        """
        # Get market regime for adaptive thresholds
        regime = "RANGING"
        try:
            from engine.regime import get_cached_regime
            reg = get_cached_regime()
            regime = (reg or {}).get("regime", "RANGING")
        except Exception as e:
            logger.debug(f"Regime cache unavailable: {e}")
            pass  # regime cache unavailable — use default RANGING
        
        # ─── Master YJ Adaptive thresholds (via regime.py + self-learning) ───
        from engine.regime import get_min_strength_for_regime
        regime_data = {"regime": regime}
        min_strength, min_confidence = get_min_strength_for_regime(regime_data)
        # Combined score = average of strength and confidence
        min_combined = int((min_strength + min_confidence) * 0.6)
        
        logger.info(f"  Regime: {regime} — thresholds: str>={min_strength}, conf>={min_confidence}, comb>={min_combined}")
        
        # Filter minimum quality
        quality_filtered = [
            c for c in candidates
            if c.get("ta_strength", 0) >= min_strength
            and c.get("ta_confidence", 0) >= min_confidence
            and c.get("combined_score", 0) >= min_combined
        ]
        
        # Take top N
        final = quality_filtered[:max_final]
        
        self.stats["stage4_final"] = len(final)
        logger.info(f"Stage 4 ranking: {len(candidates)} → {len(final)} final candidates")
        return final
    
    # ═══════════════════════════════════════════
    # MAIN HUNT METHOD
    # ═══════════════════════════════════════════
    
    def hunt(self, max_candidates: int = 30, skip_prepump: bool = False) -> dict:
        """
        Main hunt method. Runs all stages and returns final candidates.
        
        Args:
            max_candidates: Max number of final candidates to return
            skip_prepump: If True, skip Stage 2 pre-pump scan (faster but less selective)
        
        Returns:
            dict with:
                - candidates: list of candidate dicts
                - stats: hunting statistics
                - elapsed: total time in seconds
        """
        start_time = time.time()
        logger.info("🦅 Universal Hunter — Starting hunt...")
        
        # Stage 0: Fetch & Dedup
        logger.info("━ Stage 0: Fetching all tickers...")
        all_pairs = self._fetch_all_tickers()
        coins = self._deduplicate(all_pairs)
        
        # Stage 1: Basic filters
        logger.info("━ Stage 1: Basic filtering...")
        coins = self._stage1_filter(coins)
        
        # Stage 2: Pre-pump detection
        if not skip_prepump:
            logger.info("━ Stage 2: Pre-pump detection (mechanical)...")
            candidates = self._stage2_prepump_scan(coins)
        else:
            # Without pre-pump, just convert coins to candidate format
            candidates = [{**coin, "pre_pump_total": 0, "pre_pump_signals": {}, "pre_pump_scores": {}} 
                         for coin in list(coins.values())[:200]]
            self.stats["stage2_passed"] = len(candidates)
            logger.info(f"Stage 2 skipped — {len(candidates)} candidates (top 200 by volume)")
        
        # Stage 3: Technical analysis
        logger.info("━ Stage 3: Technical analysis...")
        candidates = self._stage3_technical_scan(candidates)
        
        # Stage 4: Final ranking
        logger.info("━ Stage 4: Final ranking...")
        final = self._stage4_final_ranking(candidates, max_candidates)
        
        elapsed = time.time() - start_time
        logger.info(f"🦅 Hunt complete in {elapsed:.1f}s — {len(final)} candidates found")
        
        return {
            "candidates": final,
            "stats": self.stats,
            "elapsed": round(elapsed, 1),
        }


# ═══════════════════════════════════════════
# Convenience Functions
# ═══════════════════════════════════════════

def hunt_all(max_candidates: int = 30) -> dict:
    """Convenience: run full hunt and return results"""
    hunter = UniversalHunter()
    return hunter.hunt(max_candidates=max_candidates)


def hunt_quick(top_n: int = 100) -> dict:
    """Quick hunt: skip pre-pump, just scan top volume coins"""
    hunter = UniversalHunter()
    return hunter.hunt(max_candidates=min(top_n, 30), skip_prepump=True)


# ═══════════════════════════════════════════
# Test
# ═══════════════════════════════════════════
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    result = hunt_all(max_candidates=20)
    print(f"\n📊 Stats: {json.dumps(result['stats'], indent=2)}")
    print(f"⏱ Elapsed: {result['elapsed']}s")
    print(f"\n🏆 Top candidates:")
    for i, c in enumerate(result["candidates"][:10]):
        print(f"  {i+1}. {c['base']:8s} | Price: ${c['price']:.6f} | Pre-pump: {c['pre_pump_total']}/130 | "
              f"TA: {c.get('ta_strength',0):.0f}% | Combined: {c.get('combined_score',0):.0f} | "
              f"Exch: {c['exchange']}")
