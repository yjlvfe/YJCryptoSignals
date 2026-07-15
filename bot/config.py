"""CryptoSignal Bot — Configuration, Constants, Messages, Utilities"""
# ZERO dependencies on handlers or trading
import sys, os, json, time, threading, logging
from pathlib import Path
import requests

# ─── تأكيد وجود مسار المشروع في Python Path ───
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(str(PROJECT_ROOT))

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
logger = logging.getLogger("crypto-signal-bot")

# ─── Config ───
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    logger.warning("⚠️ BOT_TOKEN not set in .env — bot will not connect to Telegram")
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
DATA_DIR = Path("/root/.crypto-signal-bot")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# إضافة تسجيل إلى ملف
_log_file = DATA_DIR / "bot_runtime.log"
_fh = logging.FileHandler(str(_log_file))
_fh.setLevel(logging.INFO)
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(_fh)

# Also add to universal-scanner logger
_scanner_logger = logging.getLogger("universal-scanner")
_scanner_logger.addHandler(_fh)
_scanner_logger.setLevel(logging.INFO)
SUBS_FILE = DATA_DIR / "subscribers.json"
SUBS_LOCK = threading.Lock()
ALLOW_SLOTS_FILE = DATA_DIR / "allow_slots.json"
RATE_CONFIG_FILE = DATA_DIR / "rate_config.json"
ADMINS_FILE = DATA_DIR / "admins.json"
OWNER_ID = 528864559

# ─── Position Sizing for PnL Reports ───
# Each trade uses this % of total capital (e.g., 10% = 0.10)
# PnL = sum(pnl_pct × position_size_pct / 100 for each trade)
POSITION_SIZE_PCT = float(os.getenv("POSITION_SIZE_PCT", "10.0"))

# ─── Admins (persistent) ───
ADMINS_LOCK = threading.Lock()


SLOT_COMMANDS = {"/help", "/stop", "/analysis", "/max"}
# Public commands (anyone can use)
PUBLIC_COMMANDS = {"/start", "/signals", "/list", "/portfolio", "/report"}


recently_broadcast = {}
# 🆕 Per-cycle broadcast set — prevents same coin broadcast twice in one cycle
_cycle_broadcast = set()

# ⏱️ [1] Cooldown after SL — {symbol: timestamp} (Phase 5.8)
symbol_cooldown = {}
SL_COOLDOWN_SECONDS = 7200  # ساعتين

# 👑 [2] Adaptive Kronos threshold — sliding window of recent scores
recent_kronos_scores = []  # list of floats, max 50 entries
MAX_KRONOS_HISTORY = 50


def read_rate_config() -> dict:
    """
    {"window_seconds": 14400, "max_per_window": 5, "per_user": {chat_id: {"count": N, "window_start": timestamp}}}
    """
    try:
        if RATE_CONFIG_FILE.exists():
            return json.loads(RATE_CONFIG_FILE.read_text())
    except Exception as e:
        logger.debug(f"load_spam_config failed: {e}")
    return {"window_seconds": 14400, "max_per_window": 5, "per_user": {}}

def save_rate_config(data: dict):
    try:
        RATE_CONFIG_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Failed to save rate config: {e}")

def set_rate_limit(window_str: str, max_count: int):
    """Set rate limit. window_str: '4h', '1m', '30m' etc."""
    seconds = parse_time_window(window_str)
    data = read_rate_config()
    data['window_seconds'] = seconds
    data['max_per_window'] = max_count
    save_rate_config(data)
    logger.info(f"Rate limit set: {max_count} requests per {window_str}")

SPAM_FILE = DATA_DIR / "list_spam.json"
SPAM_LOCK = threading.Lock()

# 5 calls in 60s → 5-min mute on /list
LIST_SPAM_LIMIT = 5
LIST_SPAM_WINDOW = 60       # seconds
LIST_SPAM_BAN = 300          # 5 minutes

def _read_spam() -> dict:
    try:
        if SPAM_FILE.exists():
            return json.loads(SPAM_FILE.read_text())
    except Exception as e:
        logger.debug(f"load_broadcast_cache failed: {e}")
    return {}  # {chat_id: {"timestamps": [], "banned_until": 0}}

def save_spam(data: dict):
    try:
        SPAM_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Failed to save spam: {e}")

def check_list_spam(chat_id: int) -> tuple:
    """
    Returns (allowed: bool, message: str)
    If spam detected, blocks /list for 5 minutes.
    """
    now = time.time()
    with SPAM_LOCK:
        data = _read_spam()
        sid = str(chat_id)
        user = data.get(sid, {"timestamps": [], "banned_until": 0})
        
        # Check if currently banned
        if user.get("banned_until", 0) > now:
            remaining = int(user["banned_until"] - now)
            return False, "🚫 **ليس لديك صلاحيات**\n\nبإمكانك استعمال /list لعرض التوصيات\nأو انتظار رسالة التوصية التي ترسل عبر البوت.\n(السبب: إرسال متكرر — حاول بعد {} دقيقة)".format(remaining // 60)
        
        # Clean old timestamps outside window
        user["timestamps"] = [t for t in user["timestamps"] if now - t < LIST_SPAM_WINDOW]
        
        # Add current timestamp
        user["timestamps"].append(now)
        
        # Check if exceeded limit
        if len(user["timestamps"]) > LIST_SPAM_LIMIT:
            user["banned_until"] = now + LIST_SPAM_BAN
            user["timestamps"] = []
            data[sid] = user
            save_spam(data)
            return False, "🚫 **ليس لديك صلاحيات**\n\nبإمكانك استعمال /signals لعرض التوصيات\nأو انتظار رسالة التوصية التي ترسل عبر البوت.\n(السبب: إرسال متكرر جداً — حاول بعد 5 دقائق)"
        
        data[sid] = user
        save_spam(data)
        return True, ""


def reset_spam(chat_id: int):
    """Remove user's spam record"""
    with SPAM_LOCK:
        data = _read_spam()
        data.pop(str(chat_id), None)
        save_spam(data)


# ─── نظام الرتب (Roles System) ───
ROLES_FILE = DATA_DIR / "user_roles.json"  # {user_id: "member"|"premium"|"admin"|"owner"}
ROLES_LOCK = threading.Lock()
ROLE_NAMES = {"member": "عضو", "premium": "مميز", "admin": "مشرف", "owner": "مالك"}

def _load_roles() -> dict:
    try:
        if ROLES_FILE.exists():
            return json.loads(ROLES_FILE.read_text())
    except Exception as e:
        logger.debug(f"Roles load failed: {e}")
    return {}

def _save_roles(data: dict):
    try:
        ROLES_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Failed to save roles: {e}")

def get_role(user_id: int) -> str:
    """Get user's role. Default: 'member' if subscriber, else None"""
    with ROLES_LOCK:
        data = _load_roles()
        role = data.get(str(user_id))
        if role:
            return role
    # Fallback: check existing systems
    if str(user_id) == str(OWNER_ID):
        return "owner"
    # Lazy import to avoid circular
    from bot.handlers import load_admins
    if user_id in load_admins():
        return "admin"
    # Check if has slot → premium
    from bot.handlers import _read_slots
    slots = _read_slots()
    if user_id in slots.get("active", []):
        return "premium"
    from bot.handlers import load_subscribers
    if user_id in load_subscribers():
        return "member"
    return None

def set_role(user_id: int, role: str) -> str:
    """Set user's role. Returns message."""
    if role not in ROLE_NAMES:
        return f"⚠️ رتبة غير معروفة: {role}"
    with ROLES_LOCK:
        data = _load_roles()
        old_role = data.get(str(user_id), "غير معروف")
        data[str(user_id)] = role
        _save_roles(data)
        logger.info(f"🎖️ Role changed: {user_id} {old_role} → {role}")
        return f"✅ تم تعيين الرتبة `{ROLE_NAMES[role]}` للمستخدم `{user_id}`."

def is_premium(user_id: int) -> bool:
    """Check if user has premium access or higher"""
    role = get_role(user_id)
    return role in ("premium", "admin", "owner")

def is_admin(user_id: int) -> bool:
    """Check if user is admin or owner"""
    role = get_role(user_id)
    return role in ("admin", "owner")

def get_role_name(user_id: int) -> str:
    """Get Arabic role name"""
    role = get_role(user_id)
    return ROLE_NAMES.get(role, "زائر")

# ─── Telegram API ───


# ─── أوامر البوت حسب الرتبة ───

# 🟢 أوامر عامة — BotCommandScopeDefault() — أي زائر يشوفها
PUBLIC_COMMAND_LIST = [
    ("start", "🚀 بدء الاشتراك في البوت"),
    ("signals", "📡 جميع التوصيات النشطة"),
    ("list", "📋 قائمتك الشخصية"),
    ("portfolio", "📊 محفظتك وأرباحك"),
    ("report", "📅 تقرير الصفقات اليومي"),
]

# 🔵 أوامر الأعضاء (المشتركين)
MEMBER_COMMAND_LIST = PUBLIC_COMMAND_LIST + [
    ("help", "❓ مساعدة وأوامر البوت"),
    ("stop", "🔴 إلغاء الاشتراك"),
]

# ⭐ أوامر المميزين (Premium)
PREMIUM_COMMAND_LIST = MEMBER_COMMAND_LIST + [
    ("analysis", "🇸🇦 تحليل عربي مبسط (مثال: /analysis BTC)"),
    ("max", "📊 تقرير احترافي كامل (مثال: /max BTC)"),
]

# 🟠 أوامر المشرفين
ADMIN_COMMAND_LIST = PREMIUM_COMMAND_LIST + [
    ("allow", "🔢 تحديد عدد المقاعد (مثال: /allow 100)"),
    ("adduser", "👤 إضافة مستخدم مميز (مثال: /adduser 123)"),
    ("admin", "👑 رفع مشرف (مثال: /admin 123)"),
    ("broadcast", "📢 رسالة جماعية للمشتركين"),
    ("request", "⏱ تحديد معدل الطلبات (مثال: /request 4h 5)"),
    ("status", "📊 حالة البوت والإحصائيات"),
]

# 👑 أوامر المالك — كل شي
OWNER_COMMAND_LIST = ADMIN_COMMAND_LIST



# ─── Messages ───
WELCOME_MSG = """🚀 **CryptoSignal Bot — Master YJ**

🔍 **Real-time market analysis**
📊 **11 schools** across **3 timeframes** (1h/4h/1d)
💡 **SMC • Market Structure • MACD • RSI • ATR Volatility**
   **CVD Volume • OBV+CMF Flow • VWAP • MA • S/R • Divergence**

━━━━━━━━━━━━━━━━━━━
📌 **Commands:**

/signals — جميع التوصيات النشطة 📡
/list — قائمتك الشخصية 📋
/portfolio — محفظتك وأرباحك 📊
/report — تقرير الصفقات اليومي 📅
/analysis BTC — تحليل عربي مبسط 🇸🇦
/analyze BTC — Full English analysis 🇬🇧
/max BTC — Full professional report 📊
/scan — Quick market scan 🎯
/status — Bot status

━━━━━━━━━━━━━━━━━━━
✅ **Subscribe and get signals automatically!**
💡 اضغط ➕ أضف إلى قائمتي على أي توصية عشان توصلك تنبيهاتها

🤖 Powered by CryptoSignal Engine v2"""

MEMBER_WELCOME = """👋 **مرحباً بك في CryptoSignal Bot**

✅ تم تفعيل حسابك بنجاح!

📌 **الأوامر المتاحة لك:**
/analysis BTC — تحليل عربي مبسط
/max BTC — English full report
/list — قائمة التوصيات النشطة
/stop — إيقاف الإرسال
/start — إعادة التفعيل
/help — الأوامر

🔒 كل تحليل يستهلك طلب من رصيدك.
للاستفسار: تواصل مع المشرف."""

HELP_MSG = """📖 **CryptoSignal Bot — Owner Guide**

━━━ 📊 **Analysis Commands** ━━━
/analysis BTC — تحليل عربي مبسط 🇸🇦
/max BTC — Full professional report 🇬🇧
/analyze BTC — Full English + MTF breakdown 🇬🇧
/list — Active trade list (public)

━━━ 🔬 **Market Scanner** ━━━
/scan — Quick market scan (top 5 buys)
/sectors — Sector rotation + liquidity flow
/matrix — Strength matrix (30 coins × 3 TFs)

━━━ 👑 **Admin Only** ━━━
/allow NUMBER — Set user slots (e.g. /allow 5)
/request 4h 5 — Set rate limit (e.g. 5/4h)
/status — Show bot status, slots, subscribers

━━━ 👤 **User Commands** ━━━
/start — Subscribe to signals
/stop — Unsubscribe
/list — Active trades

━━━ 💡 **Strategy: 11 schools × 3 TFs** ━━━
• SMC, Market Structure, MACD, RSI, ATR
• CVD Volume, OBV+CMF Flow, VWAP, MA, S/R
• Divergence

━━━ 📋 **Risk** ━━━
⚠️ Never risk >2% of your portfolio
📊 Take partial profits at each target"""

USER_HELP = """📖 **الأوامر المتاحة لك:**

━━━ 📊 **التحليل** ━━━
/analysis BTC — تحليل عربي مبسط 🇸🇦
/max BTC — Full English report 🇬🇧

━━━ 📋 **التوصيات** ━━━
/signals — جميع التوصيات النشطة 📡
/list — قائمتك الشخصية 📋
/portfolio — محفظتك وأرباحك 📊

━━━ 📋 **الاشتراك** ━━━
/start — تفعيل الاستقبال
/stop — إيقاف الاستقبال
/help — هذه القائمة

━━━ 💡 **ملاحظة** ━━━
✅ كل تحليل يستهلك طلب من رصيدك.
✅ يرجع الرصيد تلقائياً بعد المدة المحددة.
✅ التوصيات تصلك تلقائياً بدون أمر.
💡 اضغط ➕ أضف إلى قائمتي على التوصية عشان توصلك تنبيهاتها"""

MEMBER_HELP = """📖 **الأوامر المتاحة لك — عضو** 👤

━━━ 📋 **التوصيات** ━━━
/signals — جميع التوصيات النشطة 📡
/list — قائمتك الشخصية 📋
/portfolio — محفظتك وأرباحك 📊
/report — تقرير الصفقات اليومي 📅

━━━ 📋 **الاشتراك** ━━━
/start — تفعيل الاستقبال
/stop — إيقاف الاستقبال
/help — هذه القائمة

━━━ 💡 **ملاحظة** ━━━
✅ التوصيات تصلك تلقائياً بدون أمر.
💡 اضغط ➕ أضف إلى قائمتي على التوصية عشان توصلك تنبيهاتها"""

PREMIUM_HELP = """📖 **الأوامر المتاحة لك — مميز** ⭐

━━━ 📊 **التحليل المتقدم** ━━━
/analysis BTC — تحليل عربي مبسط 🇸🇦
/max BTC — تقرير احترافي كامل 🇬🇧

━━━ 📋 **التوصيات** ━━━
/signals — جميع التوصيات النشطة 📡
/list — قائمتك الشخصية 📋
/portfolio — محفظتك وأرباحك 📊
/report — تقرير الصفقات اليومي 📅

━━━ 📋 **الاشتراك** ━━━
/start — تفعيل الاستقبال
/stop — إيقاف الاستقبال
/help — هذه القائمة

━━━ 💡 **ملاحظة** ━━━
✅ لديك صلاحية الوصول للتحليلات المتقدمة.
✅ كل تحليل يستهلك طلب من رصيدك.
✅ التوصيات تصلك تلقائياً بدون أمر."""

ADMIN_HELP = """📖 **الأوامر المتاحة لك — مشرف** 🛡️

━━━ 📊 **التحليل المتقدم** ━━━
/analysis BTC — تحليل عربي مبسط 🇸🇦
/max BTC — تقرير احترافي كامل 🇬🇧

━━━ 📋 **التوصيات** ━━━
/signals — جميع التوصيات النشطة 📡
/list — قائمتك الشخصية 📋
/portfolio — محفظتك وأرباحك 📊
/report — تقرير الصفقات اليومي 📅

━━━ 👑 **الإدارة** ━━━
/adduser — إضافة مستخدم مميز 👤
/allow — تحديد عدد المقاعد 🔢
/admin — رفع مشرف 👑
/broadcast — رسالة جماعية 📢
/request — تحديد معدل الطلبات ⏱
/status — حالة البوت 📊
/scan — مسح السوق 🎯
/sectors — تحليل القطاعات
/matrix — مصفوفة القوة

━━━ 📋 **الاشتراك** ━━━
/start — تفعيل الاستقبال
/stop — إيقاف الاستقبال
/help — هذه القائمة"""

# ─── Error handler for long messages ───
LAST_REPORT_FILE = DATA_DIR / "last_report.json"
BROADCAST_CACHE_FILE = DATA_DIR / "broadcast_cache.json"
POLLING_OFFSET_FILE = DATA_DIR / "polling_offset.json"

def load_last_report_date() -> str:
    """تحميل تاريخ آخر تقرير من الملف"""
    try:
        if LAST_REPORT_FILE.exists():
            data = json.loads(LAST_REPORT_FILE.read_text())
            return data.get("last_report_date", "")
    except Exception as e:
        logger.debug(f"Report format failed: {e}")
    return ""

def save_last_report_date(date_str: str):
    """حفظ تاريخ آخر تقرير"""
    try:
        LAST_REPORT_FILE.write_text(json.dumps({"last_report_date": date_str}))
    except Exception as e:
        logger.error(f"Failed to save last report date: {e}")

def load_broadcast_cache() -> dict:
    """تحميل سجل التوصيات السابق (نجاة من إعادة التشغيل)"""
    try:
        if BROADCAST_CACHE_FILE.exists():
            data = json.loads(BROADCAST_CACHE_FILE.read_text())
            # تنظيف القديم (أكثر من ساعة)
            cutoff = time.time() - 3600
            return {k: v for k, v in data.items() if v > cutoff}
    except Exception as e:
        logger.debug(f"Sector analysis failed: {e}")
    return {}

def save_broadcast_cache():
    """حفظ سجل التوصيات"""
    try:
        BROADCAST_CACHE_FILE.write_text(json.dumps(recently_broadcast))
    except Exception as e:
        logger.error(f"Failed to save broadcast cache: {e}")
