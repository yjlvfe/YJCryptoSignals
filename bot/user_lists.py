"""
👤 User Watchlists — كل مستخدم له قائمته الشخصية

يضيف عملات من /signals إلى /list
يتلقى التنبيهات فقط للعملات اللي ضافها
"""
import json
import time
import threading
import logging
from pathlib import Path

logger = logging.getLogger("crypto-signal-userlists")

DATA_DIR = Path("/root/.crypto-signal-bot")
LISTS_FILE = DATA_DIR / "user_lists.json"        # {user_id: ["BTCUSDT", ...]}
SUBS_FILE = DATA_DIR / "trade_subscribers.json"   # {"BTCUSDT": [user_id, ...]}

_lists_lock = threading.Lock()
_subs_lock = threading.Lock()


# ═══════════════════════════════════════
# User Lists — قوائم المستخدمين
# ═══════════════════════════════════════

def _load_lists() -> dict:
    """تحميل قوائم المستخدمين"""
    try:
        if LISTS_FILE.exists():
            return json.loads(LISTS_FILE.read_text())
    except Exception as e:
        logger.debug(f"JSON file read failed: {e}")
    return {}


def _save_lists(data: dict):
    """حفظ قوائم المستخدمين"""
    try:
        LISTS_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Failed to save user lists: {e}")


def get_user_list(user_id: int) -> list:
    """قائمة العملات اللي ضافها المستخدم"""
    with _lists_lock:
        data = _load_lists()
        return data.get(str(user_id), [])


def add_to_user_list(user_id: int, symbol: str) -> bool:
    """إضافة عملة لقائمة المستخدم"""
    with _lists_lock:
        data = _load_lists()
        uid = str(user_id)
        if uid not in data:
            data[uid] = []
        if symbol in data[uid]:
            return False  # موجودة أصلاً
        data[uid].append(symbol)
        _save_lists(data)
        return True


def remove_from_user_list(user_id: int, symbol: str) -> bool:
    """إزالة عملة من قائمة المستخدم"""
    with _lists_lock:
        data = _load_lists()
        uid = str(user_id)
        if uid not in data:
            return False
        if symbol not in data[uid]:
            return False
        data[uid].remove(symbol)
        _save_lists(data)
        return True


def is_in_user_list(user_id: int, symbol: str) -> bool:
    """هل العملة في قائمة المستخدم؟"""
    lst = get_user_list(user_id)
    return symbol in lst


ENTRY_PRICES_FILE = DATA_DIR / "user_entry_prices.json"  # {user_id: {"BTCUSDT": 1.00}}


def _load_entry_prices() -> dict:
    """تحميل أسعار دخول المستخدمين"""
    try:
        if ENTRY_PRICES_FILE.exists():
            return json.loads(ENTRY_PRICES_FILE.read_text())
    except Exception as e:
        logger.debug(f"Entry prices load failed: {e}")
    return {}


def _save_entry_prices(data: dict):
    """حفظ أسعار دخول المستخدمين"""
    try:
        ENTRY_PRICES_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Failed to save entry prices: {e}")


def set_user_entry_price(user_id: int, symbol: str, entry_price: float):
    """حفظ سعر دخول المستخدم لعملة معينة"""
    with _lists_lock:
        data = _load_entry_prices()
        uid = str(user_id)
        if uid not in data:
            data[uid] = {}
        data[uid][symbol] = entry_price
        _save_entry_prices(data)


def get_user_entry_price(user_id: int, symbol: str) -> float:
    """الحصول على سعر دخول المستخدم لعملة"""
    data = _load_entry_prices()
    uid = str(user_id)
    if uid in data and symbol in data[uid]:
        return data[uid][symbol]
    return 0.0


def get_all_user_entry_prices(user_id: int) -> dict:
    """الحصول على كل أسعار دخول المستخدم"""
    data = _load_entry_prices()
    return data.get(str(user_id), {})


def cleanup_user_entry_price(symbol: str):
    """حذف سعر دخول المستخدمين بعد إغلاق الصفقة"""
    with _lists_lock:
        data = _load_entry_prices()
        changed = False
        for uid in list(data.keys()):
            if symbol in data[uid]:
                del data[uid][symbol]
                changed = True
        if changed:
            _save_entry_prices(data)


# ═══════════════════════════════════════
# Trade Subscribers — مشتركي كل صفقة
# ═══════════════════════════════════════

def _load_subs() -> dict:
    """تحميل مشتركي الصفقات"""
    try:
        if SUBS_FILE.exists():
            return json.loads(SUBS_FILE.read_text())
    except Exception as e:
        logger.debug(f"JSON file read failed: {e}")
    return {}


def _save_subs(data: dict):
    """حفظ مشتركي الصفقات"""
    try:
        SUBS_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Failed to save trade subscribers: {e}")


def subscribe_to_trade(symbol: str, user_id: int):
    """اشتراك مستخدم في تنبيهات صفقة"""
    with _subs_lock:
        data = _load_subs()
        if symbol not in data:
            data[symbol] = []
        uid = str(user_id)
        if uid not in data[symbol]:
            data[symbol].append(uid)
        _save_subs(data)


def unsubscribe_from_trade(symbol: str, user_id: int):
    """إلغاء اشتراك مستخدم من صفقة"""
    with _subs_lock:
        data = _load_subs()
        uid = str(user_id)
        if symbol in data and uid in data[symbol]:
            data[symbol].remove(uid)
            if not data[symbol]:
                del data[symbol]
            _save_subs(data)


def get_trade_subscribers(symbol: str) -> list:
    """قائمة المستخدمين المشتركين في صفقة"""
    with _subs_lock:
        data = _load_subs()
        uids = data.get(symbol, [])
        return [int(u) for u in uids]


def remove_trade_subscribers(symbol: str):
    """حذف كل مشتركي صفقة (بعد الإغلاق)"""
    with _subs_lock:
        data = _load_subs()
        if symbol in data:
            del data[symbol]
            _save_subs(data)


# ═══════════════════════════════════════
# إدارة القوائم بعد أحداث الصفقة
# ═══════════════════════════════════════

def cleanup_closed_trade(symbol: str):
    """
    بعد إغلاق/إلغاء الصفقة:
    - حذف من trade_subscribers
    - حذف من قوائم كل المستخدمين
    - حذف أسعار الدخول المخصصة
    """
    # حذف المشتركين
    remove_trade_subscribers(symbol)
    
    # حذف من قوائم المستخدمين
    with _lists_lock:
        data = _load_lists()
        changed = False
        for uid in list(data.keys()):
            if symbol in data[uid]:
                data[uid].remove(symbol)
                changed = True
        if changed:
            _save_lists(data)
    
    # حذف أسعار الدخول المخصصة
    cleanup_user_entry_price(symbol)
    
    logger.info(f"🧹 Cleaned up {symbol} from all user lists & subscribers")


def get_users_with_symbol(symbol: str) -> list:
    """كل المستخدمين اللي ضافوا هذه العملة"""
    with _lists_lock:
        data = _load_lists()
        users = []
        for uid, syms in data.items():
            if symbol in syms:
                users.append(int(uid))
        return users


# ═══════════════════════════════════════
# 🎯 User Target Tracking — لكل مستخدم عدد الأهداف اللي يتابعها
# ═══════════════════════════════════════

TRACKING_FILE = DATA_DIR / "user_tracking.json"
# {user_id: {symbol: {"target_count": 2, "tracking_status": "active", "targets_hit": [0]}}}

def _load_tracking() -> dict:
    try:
        if TRACKING_FILE.exists():
            return json.loads(TRACKING_FILE.read_text())
    except Exception as e:
        logger.debug(f"Tracking load failed: {e}")
    return {}

def _save_tracking(data: dict):
    try:
        TRACKING_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Failed to save tracking: {e}")

def set_user_target_count(user_id: int, symbol: str, target_count: int, targets: list = None, entry_price: float = None):
    """عدد الأهداف اللي المستخدم يبغى يتتبعها لهذه الصفقة"""
    with _lists_lock:
        data = _load_tracking()
        uid = str(user_id)
        if uid not in data:
            data[uid] = {}
        if symbol not in data[uid]:
            data[uid][symbol] = {}
        data[uid][symbol]["target_count"] = target_count
        data[uid][symbol]["tracking_status"] = "active"
        data[uid][symbol]["targets_hit"] = []
        if targets:
            data[uid][symbol]["targets"] = targets
        if entry_price:
            data[uid][symbol]["entry_price"] = entry_price
        _save_tracking(data)
        logger.info(f"🎯 {user_id} → {symbol}: targets={target_count}")

def get_user_target_count(user_id: int, symbol: str) -> int:
    """كم هدف المستخدم يبغى يتتبع"""
    data = _load_tracking()
    uid = str(user_id)
    if uid in data and symbol in data[uid]:
        return data[uid][symbol].get("target_count", 1)
    return 1  # قديم (بدون تتبع) → سلوك قديم: أول هدف = نهاية

def has_tracking_data(user_id: int, symbol: str) -> bool:
    """هل للمستخدم بيانات تتبع نشطة لهذه العملة؟"""
    data = _load_tracking()
    uid = str(user_id)
    if uid not in data or symbol not in data[uid]:
        return False
    return data[uid][symbol].get("tracking_status") == "active"

def get_user_targets_hit(user_id: int, symbol: str) -> list:
    """الأهداف اللي حققها المستخدم (سوّى تم البيع عليها)"""
    data = _load_tracking()
    uid = str(user_id)
    if uid in data and symbol in data[uid]:
        return data[uid][symbol].get("targets_hit", [])
    return []

def is_tracking_active(user_id: int, symbol: str) -> bool:
    """هل التتبع لسى نشط لهذا المستخدم لهذه الصفقة"""
    data = _load_tracking()
    uid = str(user_id)
    if uid in data and symbol in data[uid]:
        return data[uid][symbol].get("tracking_status") == "active"
    return True  # افتراضي: نشط

def mark_user_tracking_complete(user_id: int, symbol: str):
    """إنهاء تتبع المستخدم لهذه الصفقة (حقق هدفه الأخير)"""
    with _lists_lock:
        data = _load_tracking()
        uid = str(user_id)
        if uid in data and symbol in data[uid]:
            data[uid][symbol]["tracking_status"] = "completed"
            _save_tracking(data)

def mark_user_target_hit(user_id: int, symbol: str, target_idx: int):
    """تسجيل أن هدف معين تحقق للمستخدم — ينشئ بيانات التتبع لو ما موجودة"""
    with _lists_lock:
        data = _load_tracking()
        uid = str(user_id)
        if uid not in data:
            data[uid] = {}
        if symbol not in data[uid]:
            # إذا ما في tracking data, ننشئها بـ target_count=1 (سلوك قديم)
            data[uid][symbol] = {
                "target_count": 1,
                "tracking_status": "active",
                "targets_hit": [],
            }
        hits = data[uid][symbol].get("targets_hit", [])
        if target_idx not in hits:
            hits.append(target_idx)
            data[uid][symbol]["targets_hit"] = hits
            _save_tracking(data)

def get_active_trackers_for_symbol(symbol: str) -> list:
    """المستخدمين اللي لسى يتتبعون هذه الصفقة"""
    data = _load_tracking()
    active = []
    for uid, syms in data.items():
        if symbol in syms and syms[symbol].get("tracking_status") == "active":
            active.append(int(uid))
    return active

def cleanup_user_tracking(symbol: str):
    """حذف بيانات التتبع بعد إغلاق الصفقة"""
    with _lists_lock:
        data = _load_tracking()
        changed = False
        for uid in list(data.keys()):
            if symbol in data[uid]:
                del data[uid][symbol]
                changed = True
            if not data[uid]:
                del data[uid]
        if changed:
            _save_tracking(data)


# ═══════════════════════════════════════
# 💰 User Sales History — أرباح البيع الفعلية
# ═══════════════════════════════════════

SALES_FILE = DATA_DIR / "user_sales.json"
# {user_id: [{symbol, entry_price, sale_price, target_hit, pnl_pct, timestamp}]}

def _load_sales() -> dict:
    try:
        if SALES_FILE.exists():
            return json.loads(SALES_FILE.read_text())
    except Exception as e:
        logger.debug(f"Sales load failed: {e}")
    return {}

def _save_sales(data: dict):
    try:
        SALES_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Failed to save sales: {e}")

def record_sale(user_id: int, symbol: str, entry_price: float, sale_price: float, target_idx: int):
    """تسجيل عملية بيع (تم البيع)"""
    with _lists_lock:
        data = _load_sales()
        uid = str(user_id)
        if uid not in data:
            data[uid] = []
        pnl_pct = round((sale_price - entry_price) / entry_price * 100, 2)
        data[uid].append({
            "symbol": symbol,
            "entry_price": entry_price,
            "sale_price": sale_price,
            "target_hit": target_idx,
            "pnl_pct": pnl_pct,
            "timestamp": time.time(),
            "date": time.strftime("%Y-%m-%d %H:%M"),
        })
        _save_sales(data)
        logger.info(f"💰 Sale recorded: {user_id} {symbol} @ ${sale_price} (pnl: {pnl_pct:+.2f}%)")
        return pnl_pct

def get_user_sales(user_id: int) -> list:
    """كل عمليات البيع المسجلة للمستخدم"""
    data = _load_sales()
    return data.get(str(user_id), [])

def get_user_sales_summary(user_id: int) -> dict:
    """ملخص أرباح المستخدم من جميع عمليات البيع"""
    sales = get_user_sales(user_id)
    if not sales:
        return {"total_pnl": 0, "wins": 0, "losses": 0, "total": 0, "win_rate": 0}
    total_pnl = sum(s["pnl_pct"] for s in sales)
    wins = len([s for s in sales if s["pnl_pct"] > 0])
    losses = len([s for s in sales if s["pnl_pct"] < 0])
    return {
        "total_pnl": round(total_pnl, 2),
        "wins": wins,
        "losses": losses,
        "total": len(sales),
        "win_rate": round(wins / max(len(sales), 1) * 100),
    }
