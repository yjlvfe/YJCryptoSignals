"""
🌐 مدقق توفر العملات في المنصات — Exchange Availability Checker
"""
import time
import logging
import requests

logger = logging.getLogger(__name__)


EXCHANGES = {
    "Binance": "https://api.binance.com/api/v3/ticker/price?symbol={symbol}",
    "MEXC": "https://api.mexc.com/api/v3/ticker/price?symbol={symbol}",
    "Bybit": "https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}",
    "KuCoin": "https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={symbol}",
    "OKX": "https://www.okx.com/api/v5/market/ticker?instId={symbol}",
    "Gate.io": "https://api.gateio.ws/api/v4/spot/tickers?currency_pair={symbol}",
}


def check_availability(symbol: str) -> dict:
    """
    تفحص وجود العملة في كل منصة وترجع السعر إن وجد.
    symbol: مثل "BTCUSDT"
    """
    base = symbol.replace("USDT", "")
    results = {}

    for exchange, url_template in EXCHANGES.items():
        try:
            if exchange == "Binance":
                url = url_template.format(symbol=symbol)
                resp = requests.get(url, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    results[exchange] = {"available": True, "price": float(data.get("price", 0))}

            elif exchange == "MEXC":
                url = url_template.format(symbol=symbol)
                resp = requests.get(url, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    price = data.get("price", "0")
                    results[exchange] = {"available": True, "price": float(price)} if price != "0" else {"available": False}

            elif exchange == "Bybit":
                url = url_template.format(symbol=symbol)
                resp = requests.get(url, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("retCode") == 0:
                        price = data["result"]["list"][0].get("lastPrice", "0")
                        results[exchange] = {"available": True, "price": float(price)}
                    else:
                        results[exchange] = {"available": False}

            elif exchange == "KuCoin":
                url = url_template.format(symbol=symbol)
                resp = requests.get(url, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == "200000":
                        results[exchange] = {"available": True, "price": float(data["data"].get("price", 0))}
                    else:
                        results[exchange] = {"available": False}

            elif exchange == "OKX":
                # OKX uses "-" separator
                okx_symbol = symbol.replace("USDT", "-USDT")
                url = url_template.format(symbol=okx_symbol)
                resp = requests.get(url, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == "0" and data.get("data"):
                        results[exchange] = {"available": True, "price": float(data["data"][0].get("last", 0))}
                    else:
                        results[exchange] = {"available": False}

            elif exchange == "Gate.io":
                gate_symbol = symbol.lower().replace("usdt", "_usdt")
                url = url_template.format(symbol=gate_symbol)
                resp = requests.get(url, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list) and len(data) > 0:
                        results[exchange] = {"available": True, "price": float(data[0].get("last", 0))}
                    elif isinstance(data, dict) and "last" in data:
                        results[exchange] = {"available": True, "price": float(data["last"])}
                    else:
                        results[exchange] = {"available": False}

            time.sleep(0.1)

        except Exception as e:
            logger.warning(f"Exchange {exchange} check failed: {e}")
            results[exchange] = {"available": False}

    return results


def format_availability(avail: dict, symbol_price: float) -> str:
    """تنسيق جدول توفر المنصات"""
    lines = ["📌 **التوفر في المنصات:**"]
    has_price_diff = False
    prices = []

    for exchange, info in avail.items():
        if info["available"]:
            p = info.get("price", 0)
            prices.append(p)
            diff = (p - symbol_price) / symbol_price * 100 if symbol_price > 0 else 0
            emoji = "✅"
            if abs(diff) > 0.5:
                has_price_diff = True
                emoji = "💸" if diff > 0 else "💎"
            lines.append(f"  {emoji} **{exchange}**: `${p:.4f}` ({diff:+.2f}%)")
        else:
            lines.append(f"  ❌ **{exchange}**: غير متاح")

    if has_price_diff and prices:
        cheapest = min(prices)
        most_expensive = max(prices)
        lines.append(f"\n💡 أرجع: **${cheapest:.4f}** | أغلى: **${most_expensive:.4f}**")
        lines.append(f"📊 فارق: **{(most_expensive-cheapest)/cheapest*100:.2f}%**")

    return "\n".join(lines)
