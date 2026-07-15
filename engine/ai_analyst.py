"""
🧠 AI Trading Analyst — Multi-Provider AI
Phase 4: Full AI-powered market analysis replacing mechanical aggregation.

The AI receives ALL strategy outputs + market data and makes
the final trading decision — not just validating, but ANALYZING.
"""
import json
import logging
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry as UrllibRetry
from typing import Optional

logger = logging.getLogger("crypto-signal-ai-analyst")

# ═══════════════ Config ═══════════════
# 🔥 Multi-Provider AI Router — 15+ providers with auto-failover
# If a provider runs out of credits / rate-limited / fails,
# the system automatically falls back to the next provider in priority order.
# NEVER STOP — أسطوري
import os
import threading

AI_MAX_TOKENS = int(os.getenv("CRYPTOSIGNAL_AI_MAX_TOKENS", "900"))
AI_TIMEOUT = int(os.getenv("CRYPTOSIGNAL_AI_TIMEOUT", "45"))
# ⚡ 10 retries (configurable) on transient errors with exponential backoff
AI_MAX_RETRIES = int(os.getenv("CRYPTOSIGNAL_AI_MAX_RETRIES", "10"))
AI_RETRY_BASE_DELAY = float(os.getenv("CRYPTOSIGNAL_AI_RETRY_BASE_DELAY", "0.5"))  # 0.5s, 1s, 2s, 4s, 8s, 16s, 32s...

# ─── HTTP Session with connection pooling (speed ⚡) ───
# Reuses TCP connections — 3-5x faster for sequential calls
_http_session = None
_http_session_lock = threading.Lock()

def _get_session() -> requests.Session:
    """Get or create a thread-safe HTTP session with connection pooling."""
    global _http_session
    with _http_session_lock:
        if _http_session is None:
            session = requests.Session()
            # Connection pooling — reuse TCP connections across calls
            adapter = HTTPAdapter(
                pool_connections=20,    # Max connections to keep open per host
                pool_maxsize=50,        # Max connections in pool
                max_retries=0,          # We do our own retry (more flexible)
            )
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            _http_session = session
        return _http_session


# ─── Retry helper with exponential backoff ───
def _request_with_retry(url: str, headers: dict, json_payload: dict, timeout: int,
                        max_retries: int = AI_MAX_RETRIES, provider_name: str = "?") -> Optional[requests.Response]:
    """
    ⚡ HTTP POST with up to 10 retries on transient errors.

    Retries on:
      - Connection errors (network blip, DNS, etc.)
      - Timeouts (server slow)
      - 5xx server errors (provider overload)
      - 429 rate limit (with longer backoff)
      - 408 request timeout

    Does NOT retry on:
      - 401 unauthorized (bad key — fail fast)
      - 402 payment required (no credits — fail fast)
      - 403 forbidden (fail fast)
      - 404 not found (bad model — fail fast)
      - 400 bad request (malformed — fail fast)

    Exponential backoff: 0.5s, 1s, 2s, 4s, 8s, 16s, 32s, 32s, 32s (capped)
    Total max wait: ~125s across 10 attempts
    """
    session = _get_session()
    last_err = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = session.post(
                url,
                headers=headers,
                json=json_payload,
                timeout=timeout,
            )

            # Success
            if resp.status_code == 200:
                if attempt > 1:
                    logger.info(f"🔁 {provider_name}: succeeded on attempt {attempt}/{max_retries}")
                return resp

            # Permanent client errors — don't retry, fail fast
            if resp.status_code in (400, 401, 402, 403, 404):
                return resp  # Caller decides what to do

            # Transient errors — retry
            if resp.status_code in (408, 429, 500, 502, 503, 504) or resp.status_code >= 500:
                # 429 rate limit: only retry 3 times (won't clear by hammering)
                rate_limit_retries = min(3, max_retries)
                if resp.status_code == 429 and attempt >= rate_limit_retries:
                    logger.warning(f"🔁 {provider_name}: gave up after {rate_limit_retries} attempts (rate limited)")
                    return resp

                last_err = f"HTTP {resp.status_code}"
                if attempt >= max_retries:
                    logger.warning(f"🔁 {provider_name}: gave up after {max_retries} attempts ({last_err})")
                    return resp

                # 429 gets longer backoff (rate limit)
                if resp.status_code == 429:
                    delay = min(30, AI_RETRY_BASE_DELAY * (2 ** (attempt - 1)))
                else:
                    delay = min(16, AI_RETRY_BASE_DELAY * (2 ** (attempt - 1)))

                logger.debug(f"🔁 {provider_name}: {last_err} (attempt {attempt}/{max_retries}), retry in {delay:.1f}s")
                time.sleep(delay)
                continue

            # Unknown status code — treat as transient
            last_err = f"HTTP {resp.status_code}"
            if attempt >= max_retries:
                return resp
            delay = min(8, AI_RETRY_BASE_DELAY * (2 ** (attempt - 1)))
            time.sleep(delay)

        except requests.exceptions.Timeout as e:
            last_err = "timeout"
            if attempt >= max_retries:
                logger.warning(f"🔁 {provider_name}: gave up after {max_retries} attempts (timeout)")
                raise  # Let outer handler catch it
            delay = min(8, AI_RETRY_BASE_DELAY * (2 ** (attempt - 1)))
            logger.debug(f"🔁 {provider_name}: timeout (attempt {attempt}/{max_retries}), retry in {delay:.1f}s")
            time.sleep(delay)

        except requests.exceptions.ConnectionError as e:
            last_err = f"connection: {str(e)[:50]}"
            if attempt >= max_retries:
                logger.warning(f"🔁 {provider_name}: gave up after {max_retries} attempts (connection)")
                raise
            delay = min(8, AI_RETRY_BASE_DELAY * (2 ** (attempt - 1)))
            logger.debug(f"🔁 {provider_name}: {last_err} (attempt {attempt}/{max_retries}), retry in {delay:.1f}s")
            time.sleep(delay)

        except Exception as e:
            # Unknown error — fail fast (could be bug)
            logger.error(f"❌ {provider_name}: unexpected error: {e}")
            raise

    return None  # Should never reach here

# ─── Provider configs (ordered by priority) ───
# Each provider: {name, base_url, models[], api_keys[], max_rpm, max_rpd, priority}
# Lower priority number = tried first (best quality/speed for trading analysis)
# Rate limits are approximate — the system adapts automatically.
#
# ✅ UPDATED 2026-06-18 — 5 verified working providers
# ❌ Removed (dead): SambaNova (always 429 rate locked),
#    Groq(bad key), DeepSeek(402), DeepInfra(402),
#    Hyperbolic(402), Together(402), Venice(402), Fireworks(401),
#    Cerebras(404), Replicate(404), Zhipu(400), AI21(422),
#    GitHub Models(401), KiloCode(404), HuggingFace(bad key), OpenRouter(banned)
PROVIDERS = [
    # ═══════════════════════════════════════════════════════════════
    #  🔥 TIER 1: ⚡ Fastest verified working — sub-1s latency
    # ═══════════════════════════════════════════════════════════════

    # 1. Mistral — mistral-small-latest (389ms, multilingual ممتاز)
    {"name":"Mistral","base_url":"https://api.mistral.ai/v1",
     "models":["mistral-small-latest"],
     "api_keys":["REPLACE_WITH_YOUR_API_KEY"],
     "max_rpm":30,"max_rpd":5000,"priority":1},

    # 2. NVIDIA NIM — llama-3.1-8b (360ms, reliable)
    {"name":"NVIDIA","base_url":"https://integrate.api.nvidia.com/v1",
     "models":["meta/llama-3.1-8b-instruct","meta/llama-3.3-70b-instruct"],
     "api_keys":["REPLACE_WITH_YOUR_API_KEY"],
     "max_rpm":30,"max_rpd":5000,"priority":2},

    # 3. Novita AI — llama-3.1-8b (سريع)
    {"name":"Novita","base_url":"https://api.novita.ai/v3/openai",
     "models":["meta-llama/llama-3.1-8b-instruct"],
     "api_keys":["REPLACE_WITH_YOUR_API_KEY"],
     "max_rpm":30,"max_rpd":5000,"priority":3},

    # 4. LLM7 — gpt-4o-mini (backup)
    {"name":"LLM7","base_url":"https://api.llm7.io/v1",
     "models":["gpt-4o-mini"],
     "api_keys":["REPLACE_WITH_YOUR_API_KEY"],
     "max_rpm":30,"max_rpd":5000,"priority":4},

    # ═══════════════════════════════════════════════════════════════
    #  🥈 TIER 2: Cloudflare — custom API (model in URL, not body)
    # ═══════════════════════════════════════════════════════════════

    # 5. Cloudflare — 70B (uses non-standard endpoint, model in URL)
    {"name":"Cloudflare_Backup","base_url":"https://REPLACE_WITH_YOUR_CLOUDFLARE_ACCOUNT/ai/run/@cf/meta/llama-3.3-70b-instruct-fp8-fast",
     "models":[],  # Model is embedded in URL
     "api_keys":["REPLACE_WITH_YOUR_API_KEY"],
     "max_rpm":50,"max_rpd":10000,"priority":5},
]
# Re-sort by priority just in case
PROVIDERS.sort(key=lambda p: p["priority"])

# ─── Provider runtime state ───
_p_lock = threading.Lock()
_p_key_idx = {p["name"]: 0 for p in PROVIDERS}
_p_rpm_calls = {p["name"]: [] for p in PROVIDERS}   # timestamps, last 60s
_p_rpd_calls = {p["name"]: 0 for p in PROVIDERS}
_p_rpd_reset = {p["name"]: time.time() for p in PROVIDERS}
_p_fails = {p["name"]: 0 for p in PROVIDERS}        # consecutive failures
_p_last_fail = {p["name"]: 0.0 for p in PROVIDERS} # timestamp of last fail
_p_healthy = {p["name"]: True for p in PROVIDERS}
_last_call_time = 0.0

# ═══════════════ PURE AI SYSTEM — Natural language analysis ═══════════════
AI_ANALYST_PURE_SYSTEM = """أنت محلل عملات رقمي خبير.

⚠️ اتبع هذا التنسيق بالضبط — كل عنصر في سطر منفصل:

القرار: ENTER أو SKIP
الاتجاه: BUY أو SELL
الثقة: رقم من 0-100 (حسب قوة الإشارة)
وقف الخسارة: سعر محدد بالدولار (رقم فقط، أقل من سعر الدخول للـ BUY)
الأهداف: سعر1, سعر2, سعر3 (3 أرقام محددة بالدولار، كلها أعلى من سعر الدخول)
المدة: رقم فقط (عدد الساعات المتوقعة لتحقيق أول هدف، مثلاً 4 أو 8 أو 12 أو 24)
السبب: 15-20 كلمة تحليل فني عربي (مباشر، لا وصف للمهمة)

🚨 ممنوع:
- لا تكتب "ساعة" بعد المدة (رقم فقط)
- لا تكتب "%" بعد وقف الخسارة
- لا تترك أي حقل فارغ
- لا تصف المهمة (لا "سأحلل" أو "بناءً على البيانات")

ثم اكتب تحليلك بالمدارس الستة في أسطر منفصلة بعد التنسيق أعلاه."""

AI_ANALYST_SYSTEM = """أنت محلل عملات رقمية. مهمتك: إخراج JSON فقط فيه تحليلك.

🚨 القاعدة الذهبية: reason = تحليلك أنت، وليس وصف للمهمة.
- ✅ صح: "توافق SMC مع RSI إيجابي + كسر مقاومة 1.23"
- ❌ غلط: "نحن بحاجة لتحليل" ← هذا ممنوع
- ❌ غلط: "بناءً على البيانات المعطاة" ← هذا ممنوع
- ❌ غلط: أي جملة تبدأ بـ "تحليل" أو "نحن" أو "سأقوم" ← ممنوع

🎯 المدارس الستة:
1. هيكل السعر (SMC + Market Structure)
2. الزخم (RSI + MACD)
3. التدفق (CVD + OBV/CMF + VWAP)
4. الاتجاه (MA + Support/Resistance)
5. التقلب (ATR)
6. الانعكاس (Divergence)

📋 القواعد:
- 3+ مدارس متوافقة = إشارة قوية
- كلها محايدة = لا تدخل (SKIP)
- قوة < 25% = تجاهل

📤 أخرج JSON فقط — reason يحلل فني بحت بالعربي (15-25 كلمة):
{"decision":"ENTER أو SKIP","direction":"BUY أو SELL","confidence":0-100,"entry":السعر,"stop_loss":سعر,"targets":[هدف1,هدف2,هدف3],"risk_level":"LOW أو MEDIUM أو HIGH","reason":"تحليلك الفني المباشر","schools_agreeing":عدد,"key_signal":"الإشارة الأقوى"}"""


def call_ai(system: str, user: str, max_tokens: int = AI_MAX_TOKENS) -> Optional[str]:
    """Call AI with multi-provider failover.
    Tries 15+ providers in priority order. Each has its own keys + rate limits.
    Never stops — if DeepSeek runs out, falls to Groq → Cerebras → OpenRouter → ...
    
    Public API — safe to use from external modules (keyboard.py, etc.)"""
    return _call_ai(system, user, max_tokens)


def _call_ai(system: str, user: str, max_tokens: int = AI_MAX_TOKENS) -> Optional[str]:
    """🔥 Multi-Provider AI Router — auto-failover across 13+ providers.
    
    Strategy:
    1. Try each provider in priority order
    2. Within each provider, rotate through its API keys (round-robin)
    3. Respect RPM/RPD limits per provider
    4. Mark unhealthy after 3 consecutive failures (5-min recovery)
    5. If all providers fail, return None (bot uses fallback logic)
    """
    global _last_call_time
    
    # ─── Global rate gate: minimum 0.3s between ANY provider call ───
    now = time.time()
    elapsed = now - _last_call_time
    if elapsed < 0.3:
        time.sleep(0.3 - elapsed)
    _last_call_time = time.time()
    
    now = time.time()
    
    # Reset stale daily counters
    _reset_stale_counts(now)
    
    errors = []
    
    # Try providers in priority order
    for prov in PROVIDERS:
        name = prov["name"]
        
        # ═══ State checks (under lock) ═══
        with _p_lock:
            # Skip unhealthy (5-min cooldown for recovery)
            if not _p_healthy[name]:
                since_fail = now - _p_last_fail[name]
                if since_fail < 300:  # 5 min cooldown before retry
                    continue
                # Recovery attempt
                _p_healthy[name] = True
                _p_fails[name] = 0
                logger.info(f"🔄 Recovery attempt: {name}")
            
            # RPM check: count calls in last 60s
            cutoff = now - 60
            recent = _p_rpm_calls[name]
            _p_rpm_calls[name] = [t for t in recent if t > cutoff]
            if len(_p_rpm_calls[name]) >= prov.get("max_rpm", 30):
                errors.append(f"{name} ⏳ RPM limit")
                continue
            
            # RPD check
            if _p_rpd_calls[name] >= prov.get("max_rpd", 50000):
                errors.append(f"{name} 📆 daily limit")
                continue
            
            # Round-robin key selection
            keys = prov["api_keys"]
            if not keys:
                errors.append(f"{name} 🔑 no keys")
                continue
            ki = _p_key_idx[name]
            _p_key_idx[name] = (ki + 1) % len(keys)
            key = keys[ki]
            
            # Reserve this call
            _p_rpm_calls[name].append(now)
            _p_rpd_calls[name] += 1
        
        # ═══ Try the request (outside lock) with 10 retries ⚡ ═══
        models_list = prov.get("models", [])
        if models_list:
            model = models_list[0]
            url = f"{prov['base_url'].rstrip('/')}/chat/completions"
        else:
            # Model path embedded in base_url (e.g. Cloudflare Workers AI)
            model = None
            url = prov['base_url']

        try:
            # ⚡ Use retry-aware request (up to AI_MAX_RETRIES=10 attempts)
            # Build payload — standard OpenAI-compatible or bare messages (Cloudflare)
            if model:
                json_payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user}
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.2,
                }
            else:
                # Cloudflare Workers AI: model in URL, no "model" field in body
                json_payload = {
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user}
                    ],
                    "max_tokens": max_tokens,
                }
            resp = _request_with_retry(
                url=url,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}"
                },
                json_payload=json_payload,
                timeout=AI_TIMEOUT,
                max_retries=AI_MAX_RETRIES,
                provider_name=name,
            )
            if resp is None:
                errors.append(f"{name} ❌ no response")
                with _p_lock:
                    _p_fails[name] += 1
                    _p_last_fail[name] = now
                continue
            
            if resp.status_code == 200:
                data = resp.json()
                if model:
                    # Standard OpenAI-compatible format
                    msg = data["choices"][0].get("message", {})
                    content = msg.get("content") or msg.get("reasoning_content") or msg.get("reasoning") or ""
                else:
                    # Cloudflare Workers AI: {result: {response: "..."}}
                    content = (data.get("result", {}) or {}).get("response", "") or ""
                if content.strip():
                    with _p_lock:
                        _p_fails[name] = 0
                        _p_healthy[name] = True
                    logger.info(f"✅ AI: {name}/{model or 'workers-ai'}")
                    return content.strip()
            
            # HTTP errors
            if resp.status_code == 429:
                errors.append(f"{name} ⏳ 429")
            elif resp.status_code == 402:
                errors.append(f"{name} 💸 402 credits")
            elif resp.status_code == 401:
                errors.append(f"{name} 🔑 401 bad key")
            else:
                err_body = resp.text[:80] if resp.text else "no body"
                errors.append(f"{name} HTTP {resp.status_code}")
                logger.debug(f"  {name} {resp.status_code}: {err_body}")
            
            with _p_lock:
                _p_fails[name] += 1
                _p_last_fail[name] = now
                if _p_fails[name] >= 3:
                    _p_healthy[name] = False
                    logger.warning(f"🔴 {name}: marked UNHEALTHY (3 fails)")
        
        except requests.exceptions.Timeout:
            errors.append(f"{name} ⏱️ timeout")
            with _p_lock:
                _p_fails[name] += 1
                _p_last_fail[name] = now
        except requests.exceptions.ConnectionError as e:
            errors.append(f"{name} 🔌 connection")
            logger.debug(f"  {name} connection: {e}")
            with _p_lock:
                _p_fails[name] += 1
                _p_last_fail[name] = now
        except Exception as e:
            errors.append(f"{name} ❌ {str(e)[:80]}")
            with _p_lock:
                _p_fails[name] += 1
                _p_last_fail[name] = now
        
        # Try next provider
        continue
    
    logger.warning(f"⚠️ AI: all providers failed — {'; '.join(errors)}")
    return None


def _reset_stale_counts(now: float):
    """Reset daily counters for providers with stale timestamps (>24h)"""
    for p in PROVIDERS:
        name = p["name"]
        if now - _p_rpd_reset.get(name, 0) > 86400:
            with _p_lock:
                _p_rpd_calls[name] = 0
                _p_rpd_reset[name] = now


def analyze_coin(
    symbol: str,
    price: float,
    signals: list,           # List of Signal objects
    regime_data: dict,       # Market regime
    df_recent: dict = None,  # Recent OHLCV for context
    sector_data: dict = None, # Sector info
    liquidity_intel: dict = None,   # 🆕 from liquidity_intel.py
    breakout_data: dict = None,     # 🆕 from breakout_hunter.py
    btc_correlation: dict = None,   # 🆕 from correlation.py
) -> dict:
    """
    AI performs comprehensive multi-school analysis and returns trading decision.

    Args:
        symbol: e.g., 'BTCUSDT'
        price: current price
        signals: list of strategy Signal objects with .name, .signal, .confidence, .reason
        regime_data: market regime dict from regime.py
        df_recent: recent price action
        sector_data: sector rotation context

    Returns:
        dict with decision, direction, confidence, entry, stop_loss, targets, reason
    """
    # ─── Build strategy summary ───
    buy_signals = []
    sell_signals = []
    neutral_signals = []

    for s in signals:
        entry = f"{s.name}: {s.signal}"
        if s.reason:
            entry += f" ({s.reason[:60]})"
        if s.signal == "BUY":
            buy_signals.append(entry)
        elif s.signal == "SELL":
            sell_signals.append(entry)
        else:
            neutral_signals.append(entry)

    # ─── Build regime summary ───
    regime = regime_data.get("regime", "?")
    entry_filter = regime_data.get("entry_filter", "?")
    
    # REMOVED: btc_trend, btc_strength, btc_vol — each coin analyzed independently

    # ─── Build recent price action ───
    price_context = ""
    if df_recent and len(df_recent) >= 20:
        closes = list(df_recent["close"].values)
        highs = list(df_recent["high"].values)
        lows = list(df_recent["low"].values)
        chg_24h = ((closes[-1] - closes[0]) / closes[0] * 100) if closes[0] > 0 else 0
        hi_24h = max(highs)
        lo_24h = min(lows)
        price_context = f"24h: ${lo_24h:.2f} → ${hi_24h:.2f} | تغير: {chg_24h:+.1f}%"

    # ─── Build sector context ───
    sector_context = ""
    if sector_data:
        sector_context = f"القطاع: {sector_data.get('sector','?')} | التدفق: {sector_data.get('flow','?')}"

    # 🆕 ─── Build liquidity intelligence context ───
    liq_context = ""
    if liquidity_intel and liquidity_intel.get("status") != "insufficient_data":
        liq_score = liquidity_intel.get("liquidity_score", 50)
        liq_bias = liquidity_intel.get("bias", "NEUTRAL")
        liq_alerts = liquidity_intel.get("alerts", [])
        liq_context = f"💧 السيولة: {liq_score}/100 ({liq_bias})"
        if liq_alerts:
            liq_context += f" | تنبيهات: {'; '.join(liq_alerts[:3])}"

    # 🆕 ─── Build breakout context ───
    brk_context = ""
    if breakout_data and breakout_data.get("status") != "insufficient_data":
        brk_score = breakout_data.get("breakout_score", 30)
        brk_alerts = breakout_data.get("alerts", [])
        brk_context = f"🎯 الاختراق: {brk_score}/100"
        if brk_alerts:
            brk_context += f" | {'; '.join(brk_alerts[:2])}"

    # 🆕 ─── Build BTC correlation context ───
    corr_context = ""
    if btc_correlation:
        corr_val = btc_correlation.get("correlation_30d", 0)
        corr_cls = btc_correlation.get("classification", "?")
        corr_context = f"🔗 ارتباط BTC: {corr_val:.0%} ({corr_cls})"

    # ─── Compose user prompt ───
    user_prompt = f"""تحليل {symbol} @ ${price:.2f}

📊 **إشارات الاستراتيجيات (11 مدرسة):**
✅ شراء ({len(buy_signals)}): {'; '.join(buy_signals) if buy_signals else 'لا يوجد'}
❌ بيع ({len(sell_signals)}): {'; '.join(sell_signals) if sell_signals else 'لا يوجد'}
⚪ محايد ({len(neutral_signals)}): {len(neutral_signals)} استراتيجية

🌊 **حالة السوق:**
النظام: {regime} | فلتر الدخول: {entry_filter}

📈 **السعر:** {price_context}
🏛️ {sector_context}
{liq_context}
{brk_context}
{corr_context}

حلل عبر المدارس الستة. القرار؟""" if price_context else f"""تحليل {symbol} @ ${price:.2f}

📊 **إشارات الاستراتيجيات:**
✅ شراء ({len(buy_signals)}): {'; '.join(buy_signals) if buy_signals else 'لا يوجد'}
❌ بيع ({len(sell_signals)}): {'; '.join(sell_signals) if sell_signals else 'لا يوجد'}
⚪ محايد: {len(neutral_signals)} استراتيجية

🌊 **السوق:** {regime}
{liq_context}
{brk_context}
{corr_context}

حلل عبر المدارس الستة وأعطي القرار."""

    response = _call_ai(AI_ANALYST_SYSTEM, user_prompt, max_tokens=AI_MAX_TOKENS)

    if not response:
        return _fallback_analysis(symbol, price, signals, regime_data)

    # Parse JSON response
    return _parse_ai_response(response, symbol, price, signals)


def analyze_coin_pure(
    symbol: str,
    price: float,
    df_4h,  # Raw OHLCV DataFrame
    regime_data: dict = None,
    liquidity_intel: dict = None,
    breakout_data: dict = None,
    btc_correlation: dict = None,
) -> dict:
    """
    🧠 PURE AI market analysis — NO mechanical pre-filtering.
    AI receives raw OHLCV data and performs its own multi-school analysis.
    
    No strategy signals, no pre-digested indicators — just raw price action.
    """
    # ─── Compute basic market stats from raw OHLCV (NOT signals) ───
    if df_4h is None or len(df_4h) < 20:
        return {
            "decision": "SKIP", "direction": "NEUTRAL", "confidence": 0,
            "entry": price, "stop_loss": price * 0.95, "targets": [],
            "risk_level": "HIGH",
            "reason": "بيانات غير كافية للتحليل", "schools_agreeing": 0, "key_signal": ""
        }
    
    closes = list(df_4h["close"].values)
    highs = list(df_4h["high"].values)
    lows = list(df_4h["low"].values)
    volumes = list(df_4h["volume"].values) if "volume" in df_4h.columns else []
    
    n = len(closes)
    
    # ─── Price statistics ───
    sma20 = sum(closes[-20:]) / 20 if n >= 20 else price
    sma50 = sum(closes[-50:]) / 50 if n >= 50 else price
    
    # ATR approximation (14-period)
    tr_values = []
    for i in range(1, min(15, n)):
        hl = highs[-i] - lows[-i]
        hc = abs(highs[-i] - closes[-i-1]) if i < n else 0
        lc = abs(lows[-i] - closes[-i-1]) if i < n else 0
        tr_values.append(max(hl, hc, lc))
    atr = sum(tr_values) / len(tr_values) if tr_values else price * 0.02
    
    # Volume change (last 5 vs last 20 periods)
    vol_recent = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else sum(volumes) / max(len(volumes), 1)
    vol_hist = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else vol_recent
    vol_ratio = vol_recent / vol_hist if vol_hist > 0 else 1.0
    
    # Price changes
    chg_4c = ((closes[-1] - closes[-4]) / closes[-4] * 100) if n >= 4 else 0
    chg_20c = ((closes[-1] - closes[-20]) / closes[-20] * 100) if n >= 20 else 0
    
    # Key levels
    recent_high = max(highs[-20:]) if n >= 20 else max(highs)
    recent_low = min(lows[-20:]) if n >= 20 else min(lows)
    
    # Market regime
    regime = regime_data.get("regime", "?") if regime_data else "?"
    entry_filter = regime_data.get("entry_filter", "?") if regime_data else "?"
    
    # ─── Enrichment context ───
    liq_context = ""
    if liquidity_intel and liquidity_intel.get("status") != "insufficient_data":
        liq_bias = liquidity_intel.get("bias", "NEUTRAL")
        liq_score = liquidity_intel.get("liquidity_score", 50)
        liq_context = f"💧 سيولة: {liq_score}/100 ({liq_bias})"
    
    brk_context = ""
    if breakout_data and breakout_data.get("status") != "insufficient_data":
        brk_score = breakout_data.get("breakout_score", 30)
        brk_context = f"🎯 اختراق: {brk_score}/100"
    
    # ─── Build PURE prompt — compact raw data, no emoji noise ───
    vol_desc = "مرتفع" if vol_ratio > 1.5 else "عادي" if vol_ratio > 0.7 else "منخفض"
    regime_str = f"{regime} ({entry_filter})" if regime_data else "?"
    
    user_prompt = f"""🔍 تحليل {symbol}
━━━━━━━━━━━━━━━━━━━━━
السعر: ${price:.4f}
SMA20: ${sma20:.4f}
SMA50: ${sma50:.4f}
ATR: ${atr:.2f} ({atr/price*100:.2f}% من السعر)
القمة 24h: ${recent_high:.4f}
القاع 24h: ${recent_low:.4f}
التغير 4 شمعات: {chg_4c:+.2f}%
التغير 20 شمعة: {chg_20c:+.2f}%
الحجم: {vol_desc} (x{vol_ratio:.1f})
السوق: {regime_str}
{liq_context} {brk_context}

حلل بالمدارس الستة وحدد:
1. هل ندخل ENTER أو SKIP؟
2. هل الاتجاه BUY أم SELL؟
3. الثقة من 0-100؟
4. سعر وقف الخسارة بالدولار (رقم محدد)
5. 3 أهداف سعرية بالدولار (أرقام محددة)
6. المدة المتوقعة لتحقيق أول هدف: كم ساعة؟ (رقم فقط، لا تكتب "ساعة")
7. سبب التحليل بجملة عربية مختصرة

🛑 تذكر: المدة رقم فقط. وقف الخسارة سعر محدد بالدولار. الأهداف أسعار محددة بالدولار."""

    response = _call_ai(AI_ANALYST_PURE_SYSTEM, user_prompt, max_tokens=2500)
    
    if not response:
        return {
            "decision": "SKIP", "direction": "NEUTRAL", "confidence": 0,
            "entry": price, "stop_loss": price * 0.95, "targets": [],
            "risk_level": "HIGH",
            "reason": "AI غير متاح — تحليل يدوي", "schools_agreeing": 0, "key_signal": ""
        }
    
    return _extract_arabic_decision(response, symbol, price)


def _extract_arabic_decision(text: str, symbol: str, price: float) -> dict:
    """
    استخراج القرار من تحليل AI بالعربية.
    يستخرج من التنسيق: القرار: الاتجاه: الثقة: أو من تحليل النص.
    """
    import re
    
    lines = text.split('\n')
    
    decision = "SKIP"
    direction = "NEUTRAL"
    confidence = 0
    stop_loss = price * 0.95
    targets = []
    reason = text[:500]
    
    # ─── Phase 1: Extract from formatted decision section ───
    for line in lines:
        line = line.strip()
        if not line or 'أو' in line or ('سعر' in line and 'وقف' not in line):
            continue
        
        # Strip markdown ** from line for matching
        clean = line.replace('**', '')
        
        m = re.search(r'القرار\s*[:\-=]\s*(ENTER|SKIP|دخول|تجاهل)', clean, re.IGNORECASE)
        if m:
            raw = m.group(1).upper()
            if raw in ('ENTER', 'دخول'):
                decision = 'ENTER'
            else:
                decision = 'SKIP'
        
        m = re.search(r'الاتجاه\s*[:\-=]\s*(BUY|SELL|شراء|بيع|صاعد|هابط|هبوطي)', clean, re.IGNORECASE)
        if m:
            raw = m.group(1).upper()
            if raw in ('BUY', 'شراء', 'صاعد'):
                direction = 'BUY'
            elif raw in ('SELL', 'بيع', 'هابط', 'هبوطي'):
                direction = 'SELL'
        
        m = re.search(r'الثقة\s*[:\-=]\s*(\d+)', clean)
        if m:
            confidence = min(int(m.group(1)), 100)
        
        m = re.search(r'وقف\s*(الخسارة)?\s*[:\-=]\s*([\d.]+)', clean)
        if m:
            try:
                stop_loss = float(m.group(2))
            except Exception:
                stop_loss = price * 0.95  # fallback
        
        m = re.search(r'الأهداف\s*[:\-=]\s*([\d.\s,،]+)', clean)
        if m:
            nums = re.findall(r'[\d.]+', m.group(1))
            targets = [float(n) for n in nums[:3] if n]
        
        m = re.search(r'السبب\s*[:\\-]\s*(.+)', clean)
        if m:
            candidate = m.group(1).strip()
            if 'كلمة' not in candidate and len(candidate) > 10:
                reason = candidate

    # ─── Extract duration from AI analysis ───
    duration_hours = None
    for line in lines:
        clean = line.replace('**', '').strip()
        m = re.search(r'المدة\s*[:\-]?\s*(\d+)', clean)
        if m:
            duration_hours = min(int(m.group(1)), 168)
            break
    
    # ─── Phase 2: If formatted extraction failed, scan analysis text ───
    if direction == "NEUTRAL" or confidence == 0:
        # Score the text for bullish/bearish sentiment
        text_lower = text.lower()
        
        bullish_words = ['صاعد', 'bull', 'شراء', 'buy', 'قوي', 'إيجابي', 'اختراق', 'مقاومة', 'ارتفاع', 'صعود', 'أعلى']
        bearish_words = ['هابط', 'هبوطي', 'bear', 'بيع', 'sell', 'ضعيف', 'سلبي', 'دعم', 'انخفاض', 'هبوط', 'تصحيح', 'أدنى']
        
        bull_score = sum(1 for w in bullish_words if w in text_lower)
        bear_score = sum(1 for w in bearish_words if w in text_lower)
        
        if bull_score > bear_score + 1:
            direction = 'BUY'
            confidence = min(50 + bull_score * 8, 95)
        elif bear_score > bull_score + 1:
            direction = 'SELL'
            confidence = min(50 + bear_score * 8, 95)
        
        # Extract stop loss from text with number
        sl_text = re.findall(r'وقف[^0-9]*([\d.]+)', text)
        if sl_text:
            try:
                v = float(sl_text[-1])
                if price * 0.5 < v < price * 1.5:
                    stop_loss = v
            except Exception:
                stop_loss = price * 0.98  # fallback
        
        # Extract targets
        tp_text = re.findall(r'هدف[^0-9]*([\d.]+)', text)
        if tp_text and len(targets) == 0:
            targets = [float(t) for t in tp_text[:3] if price * 0.5 < float(t) < price * 1.5]
        
        # If reason is still the default, use last paragraph
        if 'كلمة' in reason or len(reason) < 10:
            paragraphs = [p.strip() for p in text.split('\n\n') if len(p.strip()) > 50]
            if paragraphs:
                reason = paragraphs[-1][:500]
            else:
                reason = text[-500:]
    
    # ─── Final validation ───
    if direction == "NEUTRAL" or confidence < 20:
        return {
            "decision": "SKIP", "direction": "NEUTRAL", "confidence": 0,
            "entry": price, "stop_loss": price * 0.95,
            "targets": [], "risk_level": "HIGH",
            "reason": reason[:500], "schools_agreeing": 0, "key_signal": "",
            "duration_hours": duration_hours or 24,
        }
    
    if direction == "SELL" and stop_loss < price:
        stop_loss = price * 1.02
    elif direction == "BUY" and stop_loss > price:
        stop_loss = price * 0.98
    
    risk = "LOW" if confidence > 70 else "MEDIUM" if confidence > 45 else "HIGH"
    
    return {
        "decision": decision,
        "direction": direction,
        "confidence": confidence,
        "entry": price,
        "stop_loss": round(stop_loss, 8),
        "targets": [round(t, 8) for t in targets[:3]],
        "risk_level": risk,
        "reason": reason[:500],
        "schools_agreeing": 1,
        "key_signal": "",
        "duration_hours": duration_hours or 24,
    }


def _parse_ai_response(response: str, symbol: str, price: float, signals: list) -> dict:
    """Parse AI response, extracting JSON or falling back to text analysis."""
    # 🆕 Try extracting from ```json code block first (MiniMax format)
    json_str = None
    if "```json" in response:
        start = response.find("```json") + 7
        end = response.find("```", start)
        if end > start:
            json_str = response[start:end].strip()
    
    # Fallback: find any JSON object
    if not json_str:
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            json_str = response[start:end]
    
    if json_str:
        try:
            data = json.loads(json_str)
            entry_val = data.get("entry", price)
            if entry_val is None:
                entry_val = price
            elif isinstance(entry_val, str):
                try:
                    entry_val = float(entry_val)
                except Exception:
                    entry_val = price  # fallback
            sl_val = data.get("stop_loss", price * 0.95)
            if sl_val is None:
                sl_val = price * 0.95
            elif isinstance(sl_val, str):
                try:
                    sl_val = float(sl_val)
                except Exception:
                    sl_val = price * 0.95  # fallback
            targets = data.get("targets", [])
            if isinstance(targets, list) and len(targets) > 0:
                targets = [float(t) if not isinstance(t, str) or t.replace('.','').replace('-','').isdigit() 
                          else price * (1.01 + i*0.01) for i, t in enumerate(targets[:3])]
            else:
                targets = []
            return {
                "decision": str(data.get("decision", "SKIP")).upper(),
                "direction": str(data.get("direction", "NEUTRAL")).upper(),
                "confidence": int(float(data.get("confidence", 50))),
                "entry": float(entry_val),
                "stop_loss": float(sl_val),
                "targets": targets,
                "risk_level": data.get("risk_level", "MEDIUM"),
                "reason": data.get("reason", response[:200]),
                "schools_agreeing": int(data.get("schools_agreeing", 0)),
                "key_signal": data.get("key_signal", ""),
                "ai_raw": response[:500],
            }
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.debug(f"JSON parse failed: {e} — trying text fallback")

    # Fallback: extract decision from text
    return _fallback_analysis(symbol, price, signals, {"regime": "?"}, response)


def _fallback_analysis(symbol: str, price: float, signals: list,
                        regime_data: dict = None, ai_text: str = "") -> dict:
    """Fallback when AI fails — use vote count or extract from text."""
    
    # ─── If signals available, use vote count ───
    buys = sum(1 for s in signals if s.signal == "BUY")
    sells = sum(1 for s in signals if s.signal == "SELL")
    total = buys + sells
    
    if total > 0:
        direction = "BUY" if buys > sells else "SELL"
        agreement = max(buys, sells) / total
        confidence = agreement * 50
        sl = price * 0.95 if direction == "BUY" else price * 1.05
        return {
            "decision": "ENTER" if agreement > 0.6 else "SKIP",
            "direction": direction,
            "confidence": round(confidence, 1),
            "entry": price,
            "stop_loss": round(sl, 8),
            "targets": [],
            "risk_level": "LOW" if agreement > 0.8 else "MEDIUM" if agreement > 0.6 else "HIGH",
            "reason": ai_text[:200] or f"تصويت: {buys} شراء vs {sells} بيع",
            "schools_agreeing": max(buys, sells),
            "key_signal": "",
        }
    
    # ─── Pure AI mode — no signals, try extracting from AI text ───
    if ai_text:
        text = ai_text.lower()
        
        # Extract decision (ENTER vs SKIP)
        has_enter = any(w in text for w in ["enter", "دخول", "شراء", "buy"])
        has_skip = any(w in text for w in ["skip", "تجاهل", "انتظار", "لا تدخل", "لا يوجد"])
        decision = "ENTER" if has_enter and not has_skip else "SKIP"
        
        # Extract direction (BUY vs SELL)
        has_buy = any(w in text for w in ["buy", "شراء", "bull", "صاعد", "طويل"])
        has_sell = any(w in text for w in ["sell", "بيع", "bear", "هابط", "قصير"])
        direction = "BUY" if has_buy and not has_sell else "SELL" if has_sell and not has_buy else "NEUTRAL"
        
        # Extract confidence (look for numbers near confidence words)
        conf = 0
        import re
        conf_patterns = [
            r"confidence[:\s]+(\d+)",
            r"ثقة[:\s]+(\d+)",
            r"(\d+)\s*%",
        ]
        for pat in conf_patterns:
            m = re.search(pat, text)
            if m:
                conf = min(int(m.group(1)), 100)
                break
        
        # If decision is SKIP or we have no useful signal, still SKIP but with reason
        if decision == "SKIP" or direction == "NEUTRAL" or conf < 20:
            return {
                "decision": "SKIP", "direction": "NEUTRAL", "confidence": 0,
                "entry": price, "stop_loss": price * 0.95,
                "targets": [], "risk_level": "HIGH",
                "reason": ai_text[:200], "schools_agreeing": 0, "key_signal": "",
            }
        
        sl = price * 0.95 if direction == "BUY" else price * 1.05
        return {
            "decision": decision,
            "direction": direction,
            "confidence": conf,
            "entry": price,
            "stop_loss": round(sl, 8),
            "targets": [],
            "risk_level": "LOW" if conf > 70 else "MEDIUM" if conf > 45 else "HIGH",
            "reason": ai_text[:200],
            "schools_agreeing": 1,
            "key_signal": "",
        }
    
    # ─── Truly nothing available ───
    return {"decision": "SKIP", "direction": "NEUTRAL", "confidence": 0,
            "entry": price, "stop_loss": price * 0.95,
            "targets": [], "risk_level": "HIGH",
            "reason": "AI غير متاح — لا إشارات", "schools_agreeing": 0, "key_signal": ""}


def compare_opportunities(
    candidates: list,
    regime_data: dict = None,
    max_recommendations: int = 2,
) -> dict:
    """
    AI compares multiple coin opportunities and ranks them.

    Args:
        candidates: list of dicts with symbol, price, confidence, direction, reason
                    optionally: liquidity_score, breakout_score, btc_corr
        max_recommendations: max coins to recommend

    Returns:
        dict with recommendations, summary, best_pick
    """
    if not candidates:
        return {"recommendations": [], "summary": "لا توجد فرص للمقارنة", "best_pick": ""}

    if len(candidates) == 1:
        c = candidates[0]
        return {
            "recommendations": [{"symbol": c["symbol"], "action": "ENTER_NOW", "priority": 1}],
            "summary": f"فرصة وحيدة: {c['symbol']}",
            "best_pick": c["symbol"],
        }

    lines = ["قارن بين الفرص التالية واختر الأفضل (مرتب حسب الأولوية):", ""]
    for i, c in enumerate(candidates[:5], 1):
        sym = c.get("symbol", f"COIN{i}")
        conf = c.get("confidence", 0)
        direction = c.get("direction", "NEUTRAL")
        reason = c.get("reason", "")[:80]
        liq = c.get("liquidity_score", None)
        brk = c.get("breakout_score", None)
        corr = c.get("btc_corr", None)

        line = f"{i}. **{sym}** {direction} | ثقة:{conf:.0f}%"
        if reason:
            line += f" | {reason}"
        if liq is not None:
            line += f" | سيولة:{liq}"
        if brk is not None and brk > 50:
            line += f" | اختراق:{brk}"
        if corr is not None:
            if corr > 0.7:
                corr_cls = "تابعة"
            elif corr < 0.4:
                corr_cls = "مستقلة"
            else:
                corr_cls = "شبه تابعة"
            line += f" | BTC:{corr_cls}"
        lines.append(line)

    lines.append("")
    lines.append("أعطي قرارك: أي عملة تدخلها الآن؟ أي تنتظر؟ أي تتجاهل؟")

    user_prompt = "\n".join(lines)

    system = """أنت مدير محفظة عملات رقمية. تقارن بين فرص متعددة وتختار الأفضل.

قواعد الاختيار:
- الأفضل = أعلى ثقة + سيولة إيجابية + اختراق وشيك
- لا تختار أكثر من عملتين في نفس القطاع

المخرجات (JSON فقط):
{
  "recommendations": [
    {"symbol": "BTC", "action": "ENTER_NOW", "priority": 1, "reason": "سبب"},
    {"symbol": "ETH", "action": "WAIT", "priority": 2, "reason": "سبب"}
  ],
  "summary": "ملخص القرار بالعربي (30-50 كلمة)",
  "best_pick": "BTC"
}"""

    response = _call_ai(system, user_prompt, max_tokens=800)

    if not response:
        candidates.sort(key=lambda c: c.get("confidence", 0), reverse=True)
        best = candidates[0]
        recs = [{"symbol": c["symbol"], "action": "ENTER_NOW" if i == 0 else "WAIT", "priority": i + 1}
                for i, c in enumerate(candidates[:max_recommendations])]
        return {
            "recommendations": recs,
            "summary": f"AI غير متاح — تم اختيار {best['symbol']} (أعلى ثقة: {best.get('confidence',0):.0f}%)",
            "best_pick": best["symbol"],
        }

    try:
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(response[start:end])
            return {
                "recommendations": data.get("recommendations", []),
                "summary": data.get("summary", response[:200]),
                "best_pick": data.get("best_pick", ""),
            }
    except Exception as e:
        logger.debug(f"Key failure: {e}")
        pass  # key failure non-fatal

    candidates.sort(key=lambda c: c.get("confidence", 0), reverse=True)
    return {
        "recommendations": [{"symbol": c["symbol"], "action": "ENTER_NOW", "priority": i + 1}
                          for i, c in enumerate(candidates[:max_recommendations])],
        "summary": "AI استجابة غير واضحة — تم اختيار الأعلى ثقة",
        "best_pick": candidates[0]["symbol"] if candidates else "",
    }


def enrich_with_modules(symbol: str, df: "pd.DataFrame", cvd=None) -> dict:
    """
    Run all 4 new modules on a coin and return combined data.

    Args:
        symbol: e.g., 'BTCUSDT'
        df: OHLCV DataFrame

    Returns:
        dict with liquidity_intel, breakout_data
    """
    result = {}

    try:
        from engine.liquidity_intel import gather_liquidity_intel
        result["liquidity_intel"] = gather_liquidity_intel(df, cvd=cvd, symbol=symbol)
    except Exception as e:
        logger.debug(f"Liquidity intel failed for {symbol}: {e}")
        result["liquidity_intel"] = None

    try:
        from engine.breakout_hunter import hunt_breakouts
        result["breakout_data"] = hunt_breakouts(df, symbol=symbol)
    except Exception as e:
        logger.debug(f"Breakout hunt failed for {symbol}: {e}")
        result["breakout_data"] = None

    return result
