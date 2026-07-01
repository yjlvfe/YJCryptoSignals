"""
📡 CryptoSignal — Multi-Exchange Data Fetcher
5 منصات مع fallback تلقائي: MEXC → OKX → Gate.io → KuCoin → Bitget
أي منصة تفشل — ينتقل للثانية فوراً. إعادة محاولة كل 5 دقائق.
"""
import time
import threading
import logging
import requests
import pandas as pd
import numpy as np

logger = logging.getLogger("crypto-signal-fetcher")

# ═══════════════════════════════════════
# 🚫 EXCLUDED SYMBOLS — known invalid pairs that cause 400 errors
# ═══════════════════════════════════════
EXCLUDED_SYMBOLS = {
    "USDGUSDT",  # stablecoin pair, not available on MEXC klines
    "XAUTUSDT",  # gold-backed token, not available on MEXC klines
    "USDCUSDT", "USDTUSDT", "DAIUSDT", "BUSDUSDT", "TUSDUSDT",  # stablecoins
    "USTCUSDT", "EURSUSDT", "EURCUSDT",  # fiat-pegged
}

# ═══════════════════════════════════════
# 🏷️ TOP SYMBOLS
# ═══════════════════════════════════════
TOP_SYMBOLS = [
    # ─── Top 50 by market cap ───
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "DOTUSDT", "LINKUSDT",
    "POLUSDT",  # MATIC→POL
    "SHIBUSDT", "TRXUSDT", "ATOMUSDT", "ETCUSDT",
    "XLMUSDT", "BCHUSDT", "ALGOUSDT", "VETUSDT", "FILUSDT",
    "ICPUSDT", "SANDUSDT", "MANAUSDT", "AXSUSDT", "APEUSDT",
    "NEARUSDT", "OPUSDT", "ARBUSDT", "INJUSDT", "TIAUSDT",
    "PEPEUSDT", "FLOKIUSDT", "SUIUSDT", "SEIUSDT", "APTUSDT",
    # ─── Mid-cap momentum ───
    "WIFUSDT", "ONDOUSDT", "JUPUSDT", "TNSRUSDT", "PYTHUSDT",
    "STRKUSDT", "ZROUSDT", "NOTUSDT", "DOGSUSDT", "HMSTRUSDT",
    "IOUSDT", "TAOUSDT", "FETUSDT", "AGIXUSDT", "OCEANUSDT",
    "RNDRUSDT", "AKTUSDT", "LDOUSDT", "RPLUSDT", "SSVUSDT",
    "ENAUSDT", "ETHFIUSDT", "REZUSDT", "ALTUSDT", "PORTALUSDT",
    "PIXELUSDT", "OMNIUSDT", "SAGAUSDT", "AEVOUSDT", "DYMUSDT",
    # ─── High-volume altcoins ───
    "WUSDT", "PENDLEUSDT", "PRIMEUSDT", "BEAMUSDT", "ATHUSDT",
    "OMUSDT", "DOGUSDT", "MOGUSDT", "POPCATUSDT", "MEWUSDT",
    "BONKUSDT", "MYROUSDT", "WENUSDT", "SILLYUSDT", "SAMOUSDT",
    # ─── Layer 1 / Infra ───
    "TONUSDT", "FTMUSDT", "SUSDT",  # Sonic (prev FTM)
    "KAIAUSDT", "MINAUSDT", "ZENUSDT", "XMRUSDT",
    "DASHUSDT", "ZECUSDT", "KASUSDT", "RUNEUSDT", "THORUSDT",
]

# ═══════════════════════════════════════
# 🕐 TIMEFRAME MAPPING (per exchange)
# ═══════════════════════════════════════
TIMEFRAME_MAP = {
    "15m":  {"mexc": "15m", "okx": "15m", "gate": "15m", "kucoin": "15min", "bitget": "15min"},
    "1h":   {"mexc": "60m", "okx": "1H",  "gate": "1h",  "kucoin": "1hour",  "bitget": "1h"},
    "4h":   {"mexc": "4h",  "okx": "4H",  "gate": "4h",  "kucoin": "4hour",  "bitget": "4h"},
    "1d":   {"mexc": "1d",  "okx": "1D",  "gate": "1d",  "kucoin": "1day",   "bitget": "1day"},
    "1w":   {"mexc": "1w",  "okx": "1W",  "gate": "7d",  "kucoin": "1week",  "bitget": "1week"},
}

# ═══════════════════════════════════════
# 🏦 Base Exchange Provider
# ═══════════════════════════════════════
class ExchangeProvider:
    """Base class for exchange data providers"""
    name: str = "base"
    healthy: bool = True
    last_error: str = ""
    error_count: int = 0
    _lock: threading.Lock = threading.Lock()
    
    def _mark_fail(self, err: str):
        with self._lock:
            self.error_count += 1
            self.last_error = err
            if self.error_count >= 3:
                self.healthy = False
                logger.warning(f"🔴 {self.name}: marked UNHEALTHY after {self.error_count} errors: {err[:80]}")
    
    def _mark_success(self):
        with self._lock:
            was_unhealthy = not self.healthy
            self.error_count = 0
            self.last_error = ""
            self.healthy = True
            if was_unhealthy:
                logger.info(f"🟢 {self.name}: recovered!")
    
    def symbol_to_exchange(self, symbol: str) -> str:
        """Convert USDT symbol to exchange format. Override per exchange."""
        return symbol
    
    def fetch_klines(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        raise NotImplementedError
    
    def fetch_tickers_24hr(self) -> list:
        raise NotImplementedError
    
    def fetch_all_prices(self) -> dict:
        """Returns {SYMBOL: price} dict"""
        raise NotImplementedError

# ═══════════════════════════════════════
# 🔵 MEXC Provider
# ═══════════════════════════════════════
class MEXCProvider(ExchangeProvider):
    name = "MEXC"
    
    def fetch_klines(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        # 🚫 Skip excluded symbols to avoid 400 errors
        if symbol.upper() in EXCLUDED_SYMBOLS:
            raise ValueError(f"Symbol {symbol} is excluded (stablecoin/fiat-pegged)")
        tf = TIMEFRAME_MAP.get(interval, {}).get("mexc", interval)
        url = "https://api.mexc.com/api/v3/klines"
        params = {"symbol": symbol.upper(), "interval": tf, "limit": limit}
        
        for attempt in range(3):
            try:
                resp = requests.get(url, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                if not data or not isinstance(data, list):
                    raise ValueError(f"Empty response for {symbol}")
                
                rows = [{
                    "date": pd.to_datetime(int(k[0]), unit="ms"),
                    "open": float(k[1]), "high": float(k[2]),
                    "low": float(k[3]), "close": float(k[4]),
                    "volume": float(k[5]),
                } for k in data]
                self._mark_success()
                return pd.DataFrame(rows)
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                self._mark_fail(str(e))
                raise
    
    def fetch_tickers_24hr(self) -> list:
        url = "https://api.mexc.com/api/v3/ticker/24hr"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        self._mark_success()
        return [{
            "symbol": p["symbol"], "last": float(p["lastPrice"]),
            "high": float(p["highPrice"]), "low": float(p["lowPrice"]),
            "volume": float(p.get("volume", 0)),
            "quote_volume": float(p.get("quoteVolume", 0)),
            "change_pct": float(p.get("priceChangePercent", 0)),
        } for p in data if p["symbol"].endswith("USDT")]
    
    def fetch_all_prices(self) -> dict:
        url = "https://api.mexc.com/api/v3/ticker/price"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        self._mark_success()
        return {p["symbol"]: float(p["price"]) for p in data}

# ═══════════════════════════════════════
# 🟠 OKX Provider
# ═══════════════════════════════════════
class OKXProvider(ExchangeProvider):
    name = "OKX"
    
    def symbol_to_exchange(self, symbol: str) -> str:
        return symbol.replace("USDT", "-USDT")
    
    def fetch_klines(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        tf = TIMEFRAME_MAP.get(interval, {}).get("okx", interval)
        inst_id = self.symbol_to_exchange(symbol)
        url = "https://www.okx.com/api/v5/market/candles"
        params = {"instId": inst_id, "bar": tf, "limit": str(limit)}
        
        for attempt in range(3):
            try:
                resp = requests.get(url, params=params, timeout=15)
                resp.raise_for_status()
                j = resp.json()
                if j.get("code") != "0" or not j.get("data"):
                    raise ValueError(f"OKX error: {j.get('msg', 'no data')}")
                
                rows = [{
                    "date": pd.to_datetime(int(k[0]), unit="ms"),
                    "open": float(k[1]), "high": float(k[2]),
                    "low": float(k[3]), "close": float(k[4]),
                    "volume": float(k[5]),
                } for k in j["data"]]
                self._mark_success()
                return pd.DataFrame(rows)
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                self._mark_fail(str(e))
                raise
    
    def fetch_tickers_24hr(self) -> list:
        url = "https://www.okx.com/api/v5/market/tickers?instType=SPOT"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        j = resp.json()
        self._mark_success()
        return [{
            "symbol": p["instId"].replace("-", ""),
            "last": float(p["last"]),
            "high": float(p["high24h"]), "low": float(p["low24h"]),
            "volume": float(p.get("vol24h", 0)),
            "quote_volume": float(p.get("volCcy24h", 0)),
            "change_pct": 0,  # OKX doesn't provide direct pct
        } for p in j.get("data", []) if p["instId"].endswith("-USDT")]
    
    def fetch_all_prices(self) -> dict:
        url = "https://www.okx.com/api/v5/market/tickers?instType=SPOT"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        j = resp.json()
        self._mark_success()
        return {p["instId"].replace("-", ""): float(p["last"]) 
                for p in j.get("data", []) if p["instId"].endswith("-USDT")}

# ═══════════════════════════════════════
# 🟢 Gate.io Provider
# ═══════════════════════════════════════
class GateProvider(ExchangeProvider):
    name = "Gate.io"
    
    def symbol_to_exchange(self, symbol: str) -> str:
        return symbol.replace("USDT", "_USDT")
    
    def fetch_klines(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        tf = TIMEFRAME_MAP.get(interval, {}).get("gate", interval)
        pair = self.symbol_to_exchange(symbol)
        url = "https://api.gateio.ws/api/v4/spot/candlesticks"
        params = {"currency_pair": pair, "interval": tf, "limit": limit}
        
        for attempt in range(3):
            try:
                resp = requests.get(url, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                if not data or not isinstance(data, list):
                    raise ValueError(f"Gate empty data for {symbol}")
                
                # Gate format: [ts_sec, volume_quote, close, high, low, open, amount]
                rows = [{
                    "date": pd.to_datetime(int(k[0]), unit="s"),
                    "open": float(k[5]), "high": float(k[3]),
                    "low": float(k[4]), "close": float(k[2]),
                    "volume": float(k[6]),  # base volume
                } for k in data]
                self._mark_success()
                return pd.DataFrame(rows)
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                self._mark_fail(str(e))
                raise
    
    def fetch_tickers_24hr(self) -> list:
        url = "https://api.gateio.ws/api/v4/spot/tickers"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        self._mark_success()
        return [{
            "symbol": p["currency_pair"].replace("_", ""),
            "last": float(p["last"]),
            "high": float(p["high_24h"]), "low": float(p["low_24h"]),
            "volume": float(p.get("base_volume", 0)),
            "quote_volume": float(p.get("quote_volume", 0)),
            "change_pct": float(p.get("change_percentage", 0)),
        } for p in data if p["currency_pair"].endswith("_USDT")]
    
    def fetch_all_prices(self) -> dict:
        url = "https://api.gateio.ws/api/v4/spot/tickers"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        self._mark_success()
        return {p["currency_pair"].replace("_", ""): float(p["last"])
                for p in data if p["currency_pair"].endswith("_USDT")}

# ═══════════════════════════════════════
# 🟣 KuCoin Provider
# ═══════════════════════════════════════
class KuCoinProvider(ExchangeProvider):
    name = "KuCoin"
    
    def symbol_to_exchange(self, symbol: str) -> str:
        return symbol.replace("USDT", "-USDT")
    
    def fetch_klines(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        tf = TIMEFRAME_MAP.get(interval, {}).get("kucoin", interval)
        ksym = self.symbol_to_exchange(symbol)
        url = "https://api.kucoin.com/api/v1/market/candles"
        params = {"type": tf, "symbol": ksym}
        
        for attempt in range(3):
            try:
                resp = requests.get(url, params=params, timeout=15)
                resp.raise_for_status()
                j = resp.json()
                if j.get("code") != "200000" or not j.get("data"):
                    raise ValueError(f"KuCoin error: {j.get('msg', 'no data')}")
                
                # KuCoin format: [ts_sec, open, close, high, low, volume, turnover]
                rows = [{
                    "date": pd.to_datetime(int(k[0]), unit="s"),
                    "open": float(k[1]), "high": float(k[3]),
                    "low": float(k[4]), "close": float(k[2]),
                    "volume": float(k[5]),
                } for k in j["data"]]
                self._mark_success()
                return pd.DataFrame(rows)
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                self._mark_fail(str(e))
                raise
    
    def fetch_tickers_24hr(self) -> list:
        url = "https://api.kucoin.com/api/v1/market/allTickers"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        j = resp.json()
        self._mark_success()
        tickers = j.get("data", {}).get("ticker", [])
        return [{
            "symbol": p["symbol"].replace("-", ""),
            "last": float(p.get("last") or p.get("buy") or 0),
            "high": float(p.get("high") or 0),
            "low": float(p.get("low") or 0),
            "volume": float(p.get("vol") or 0),
            "quote_volume": float(p.get("volValue") or 0),
            "change_pct": float(p.get("changeRate") or 0) * 100,
        } for p in tickers if p.get("symbol", "").endswith("-USDT")]
    
    def fetch_all_prices(self) -> dict:
        url = "https://api.kucoin.com/api/v1/market/allTickers"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        j = resp.json()
        self._mark_success()
        tickers = j.get("data", {}).get("ticker", [])
        return {p["symbol"].replace("-", ""): float(p.get("last", p.get("buy", 0)))
                for p in tickers if p.get("symbol", "").endswith("-USDT")}

# ═══════════════════════════════════════
# 🔴 Bitget Provider
# ═══════════════════════════════════════
class BitgetProvider(ExchangeProvider):
    name = "Bitget"
    
    def fetch_klines(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        tf = TIMEFRAME_MAP.get(interval, {}).get("bitget", interval)
        url = "https://api.bitget.com/api/v2/spot/market/candles"
        params = {"symbol": symbol.upper(), "granularity": tf, "limit": str(limit)}
        
        for attempt in range(3):
            try:
                resp = requests.get(url, params=params, timeout=15)
                resp.raise_for_status()
                j = resp.json()
                if j.get("code") != "00000" or not j.get("data"):
                    raise ValueError(f"Bitget error: {j.get('msg', 'no data')}")
                
                # Bitget format: [ts_ms, open, high, low, close, vol_base, vol_quote, vol_usdt]
                rows = [{
                    "date": pd.to_datetime(int(k[0]), unit="ms"),
                    "open": float(k[1]), "high": float(k[2]),
                    "low": float(k[3]), "close": float(k[4]),
                    "volume": float(k[5]),
                } for k in j["data"]]
                self._mark_success()
                return pd.DataFrame(rows)
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                self._mark_fail(str(e))
                raise
    
    def fetch_tickers_24hr(self) -> list:
        url = "https://api.bitget.com/api/v2/spot/market/tickers"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        j = resp.json()
        self._mark_success()
        return [{
            "symbol": p["symbol"],
            "last": float(p["lastPr"]),
            "high": float(p["high24h"]), "low": float(p["low24h"]),
            "volume": float(p.get("baseVolume", 0)),
            "quote_volume": float(p.get("quoteVolume", 0)),
            "change_pct": 0,
        } for p in j.get("data", []) if p["symbol"].endswith("USDT")]
    
    def fetch_all_prices(self) -> dict:
        url = "https://api.bitget.com/api/v2/spot/market/tickers"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        j = resp.json()
        self._mark_success()
        return {p["symbol"]: float(p["lastPr"])
                for p in j.get("data", []) if p["symbol"].endswith("USDT")}

# ═══════════════════════════════════════
# 🚀 Multi-Exchange Fetcher
# ═══════════════════════════════════════
class MultiExchangeFetcher:
    """
    يدير 5 منصات مع fallback تلقائي.
    MEXC → OKX → Gate.io → KuCoin → Bitget
    أي منصة تفشل 3 مرات تتعطل مؤقتاً وتتم إعادة محاولتها كل 5 دقائق.
    """
    def __init__(self):
        self.providers = [
            MEXCProvider(),
            OKXProvider(),
            GateProvider(),
            KuCoinProvider(),
            BitgetProvider(),
        ]
        self._recovery_interval = 300  # 5 min
        self._last_recovery_check = 0
        logger.info(f"🌐 MultiExchangeFetcher ready: {[p.name for p in self.providers]}")
    
    def _check_recovery(self):
        """كل 5 دقائق، جرب تشغيل المنصات المتعطلة"""
        now = time.time()
        if now - self._last_recovery_check < self._recovery_interval:
            return
        self._last_recovery_check = now
        
        for p in self.providers:
            if not p.healthy:
                try:
                    # Quick health check
                    p.fetch_all_prices()
                except Exception as e:
                    logger.debug(f"Provider {p.name} still unhealthy: {e}")  # Still down, keep marked unhealthy
    
    def _try_all(self, method: str, *args, **kwargs) -> tuple:
        """
        Try a method across all healthy providers with fallback.
        Returns (result, provider_name) or raises RuntimeError if all fail.
        """
        self._check_recovery()
        errors = []
        unhealthy = [p.name for p in self.providers if not p.healthy]
        if unhealthy:
            logger.debug(f"⚠️ Unhealthy providers: {unhealthy}")
        
        for p in self.providers:
            if not p.healthy:
                continue
            try:
                fn = getattr(p, method)
                result = fn(*args, **kwargs)
                return result, p.name
            except Exception as e:
                err_msg = f"{p.name}: {str(e)[:100]}"
                errors.append(err_msg)
                logger.warning(f"  ⚠️ {err_msg}")
                continue
        
        # All failed — one more attempt across ALL providers (force retry)
        logger.error(f"❌ All healthy providers failed! Forcing retry on all...")
        for p in self.providers:
            try:
                p.healthy = True  # Force
                p.error_count = 0
                fn = getattr(p, method)
                result = fn(*args, **kwargs)
                logger.info(f"🔄 Forced recovery via {p.name}")
                # Success — re-enable all providers
                for pp in self.providers:
                    pp.healthy = True
                    pp.error_count = 0
                return result, p.name
            except Exception as e:
                errors.append(f"{p.name}(forced): {str(e)[:100]}")
                continue
        raise RuntimeError(f"❌ All 5 exchanges failed for {method}:\n" + "\n".join(errors))
    
    def fetch_klines(self, symbol: str, interval: str = "1d", limit: int = 200) -> pd.DataFrame:
        result, provider = self._try_all("fetch_klines", symbol, interval, limit)
        return result
    
    def fetch_klines_from(self, symbol: str, interval: str, limit: int, preferred: str = None) -> pd.DataFrame:
        """جلب klines مع محاولة منصة محددة أولاً"""
        if preferred:
            for p in self.providers:
                if p.name.upper() == preferred.upper() and p.healthy:
                    try:
                        result = p.fetch_klines(symbol, interval, limit)
                        return result
                    except Exception as e:
                        logger.debug(f"  ⚠️ {p.name}: klines failed for {symbol}, fallback...")
                        break  # fallback to _try_all
        return self.fetch_klines(symbol, interval, limit)
    
    def fetch_tickers_24hr(self) -> list:
        result, provider = self._try_all("fetch_tickers_24hr")
        return result
    
    def fetch_all_prices(self) -> dict:
        result, provider = self._try_all("fetch_all_prices")
        return result
    
    def status(self) -> str:
        lines = ["🌐 **Multi-Exchange Status**", ""]
        for p in self.providers:
            icon = "🟢" if p.healthy else "🔴"
            lines.append(f"{icon} **{p.name}**: {'OK' if p.healthy else p.last_error[:50]}")
        return "\n".join(lines)

# ═══════════════════════════════════════
# 🌍 Global Fetcher Instance
# ═══════════════════════════════════════
_fetcher = None
_fetcher_lock = threading.Lock()

def get_fetcher() -> MultiExchangeFetcher:
    global _fetcher
    if _fetcher is None:
        with _fetcher_lock:
            if _fetcher is None:
                _fetcher = MultiExchangeFetcher()
    return _fetcher

# ═══════════════════════════════════════
# 🔌 Public API (backward compatible)
# ═══════════════════════════════════════
def fetch_klines(symbol: str, interval: str = "1d", limit: int = 200) -> pd.DataFrame:
    """جلب OHLCV من أول منصة متاحة"""
    return get_fetcher().fetch_klines(symbol, interval, limit)

def fetch_multi_timeframe(symbol: str, timeframes: list = None) -> dict:
    """جلب بيانات لعدة فريمات"""
    if timeframes is None:
        timeframes = ["15m", "1h", "4h", "1d"]
    result = {}
    for tf in timeframes:
        limit = 500 if tf in ["15m", "1h"] else 200
        result[tf] = fetch_klines(symbol, tf, limit)
        time.sleep(0.3)
    return result

def search_symbols(query: str) -> list:
    """البحث عن أزواج USDT تطابق الاستعلام"""
    try:
        prices = get_fetcher().fetch_all_prices()
        matches = [s for s in prices if query.upper() in s and s.endswith("USDT")]
        return sorted(matches)[:20]
    except Exception as e:
        logger.warning(f"Symbol search failed for '{query}': {e}")
        return []

def get_top_volume_pairs(limit: int = 50) -> list:
    """أعلى العملات من حيث حجم التداول"""
    try:
        tickers = get_fetcher().fetch_tickers_24hr()
        usdt_pairs = [t for t in tickers if t["symbol"].endswith("USDT")]
        usdt_pairs.sort(key=lambda t: t.get("quote_volume", 0), reverse=True)
        return [t["symbol"] for t in usdt_pairs[:limit]]
    except Exception as e:
        logger.warning(f"Failed to fetch top volume pairs: {e}")
        return TOP_SYMBOLS

def get_fetcher_status() -> str:
    return get_fetcher().status()

if __name__ == "__main__":
    print("🧪 Testing Multi-Exchange Fetcher...")
    f = get_fetcher()
    
    print("\n📊 Status:")
    print(f.status())
    
    print("\n🔍 Fetching BTC klines...")
    df = fetch_klines("BTCUSDT", "4h", 3)
    print(df[["date", "open", "high", "low", "close"]].to_string())
    
    print("\n💵 Fetching all prices (sample)...")
    prices = f.fetch_all_prices()
    sample = list(prices.items())[:5]
    for s, p in sample:
        print(f"  {s}: ${p}")
    
    print("\n📈 Fetching top volume...")
    top = get_top_volume_pairs(5)
    print(f"  Top 5: {top}")
    
    print("\n✅ Done!")
