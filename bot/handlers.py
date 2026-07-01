"""CryptoSignal Bot — Telegram Handlers + User Management"""
import sys, os, json, time, threading, re, logging
from pathlib import Path
import requests
from bot.config import *
from bot.tracker import get_active_trades, add_trade, check_trades, load_trades, save_trades, format_trades_list, update_current_prices, cleanup_trades, MAX_TRADES
from bot.keyboard import build_list_keyboard, build_detail_keyboard, build_back_keyboard, format_trade_detail_text, analyze_support_levels
from bot.user_lists import get_user_list, add_to_user_list, remove_from_user_list, subscribe_to_trade, unsubscribe_from_trade, get_trade_subscribers, cleanup_closed_trade, get_all_user_entry_prices, get_user_entry_price, set_user_entry_price, set_user_target_count, get_user_target_count, has_tracking_data, is_tracking_active, mark_user_tracking_complete, mark_user_target_hit, get_active_trackers_for_symbol, cleanup_user_tracking, record_sale, get_user_sales, get_user_sales_summary

logger = logging.getLogger("crypto-signal-bot")

def _read_admins() -> set:
    try:
        if ADMINS_FILE.exists():
            data = json.loads(ADMINS_FILE.read_text())
            return set(data.get("admins", [OWNER_ID])) | {OWNER_ID}
    except Exception as e:
        logger.debug(f"load_owners failed: {e}")
    return {OWNER_ID}

def _write_admins(admins: set):
    try:
        ADMINS_FILE.write_text(json.dumps({"admins": list(admins)}, indent=2))
    except Exception as e:
        logger.error(f"Failed to save admins: {e}")

def load_admins() -> set:
    with ADMINS_LOCK:
        return _read_admins()

def add_admin(uid: int) -> str:
    with ADMINS_LOCK:
        admins = _read_admins()
        if uid in admins:
            return f"⚠️ `{uid}` مشرف بالفعل."
        admins.add(uid)
        _write_admins(admins)
        return f"✅ تم رفع `{uid}` مشرف."


def _read_subs() -> list:
    """داخلي — يقرأ الملف بدون قفل (المتصل يملك القفل)"""
    try:
        if SUBS_FILE.exists():
            return json.loads(SUBS_FILE.read_text())
    except Exception as e:
        logger.debug(f"load_slots failed: {e}")
    return []

def load_subscribers() -> list:
    with SUBS_LOCK:
        return _read_subs()

def save_subscribers(subs: list):
    with SUBS_LOCK:
        try:
            SUBS_FILE.write_text(json.dumps(subs))
        except Exception as e:
            logger.error(f"Failed to save subscribers: {e}")

def add_subscriber(chat_id: int, username: str = "", first_name: str = ""):
    with SUBS_LOCK:
        subs = _read_subs()
        if chat_id not in subs:
            subs.append(chat_id)
            try:
                SUBS_FILE.write_text(json.dumps(subs))
            except Exception as e:
                logger.error(f"Failed to save subscribers: {e}")
            logger.info(f"New subscriber: {chat_id} (@{username})")

# ─── Allow Slots (thread-safe) ───
SLOTS_LOCK = threading.Lock()

def _read_slots() -> dict:
    """{max_slots: 5, active: [chat_id1, chat_id2, ...]}"""
    try:
        if ALLOW_SLOTS_FILE.exists():
            return json.loads(ALLOW_SLOTS_FILE.read_text())
    except Exception as e:
        logger.debug(f"load_allow_slots failed: {e}")
    return {"max_slots": 0, "active": []}

def save_slots(data: dict):
    try:
        ALLOW_SLOTS_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Failed to save slots: {e}")

def try_assign_slot(chat_id: int) -> tuple:
    """
    Try to assign a user to an available slot.
    Returns (success: bool, message: str)
    - Already in slots → True
    - Slots available → True, assign
    - Slots full → False
    """
    with SLOTS_LOCK:
        data = _read_slots()
        active = data.get("active", [])
        max_slots = data.get("max_slots", 0)
        timestamps = data.get("assigned_at", {})
        
        if str(chat_id) in active_str(active):
            return True, "موجود"
        
        if max_slots <= 0:
            return False, "المساحة مقفولة حالياً. تواصل مع المشرف."
        
        if len(active) >= max_slots:
            # Calculate how long ago the oldest slot was taken
            oldest_ts = min(timestamps.values()) if timestamps else time.time()
            ago_min = int((time.time() - oldest_ts) / 60)
            ago_str = f"{ago_min} دقيقة" if ago_min < 60 else f"{ago_min // 60} ساعة"
            return False, f"⚠️ المقاعد ممتلئة ({max_slots}/{max_slots})\nأقدم مقعد محجوز منذ {ago_str}\nسيتم إشعارك عند توفر مقعد."
        
        active.append(chat_id)
        timestamps[str(chat_id)] = time.time()
        data["active"] = active
        data["assigned_at"] = timestamps
        save_slots(data)
        logger.info(f"✅ Slot assigned: {chat_id} ({len(active)}/{max_slots})")
        return True, "تم التفعيل ✅"

def active_str(active: list) -> list:
    """Convert all active IDs to strings for comparison"""
    return [str(a) for a in active]

def set_max_slots(number: int) -> str:
    """Admin sets max slots"""
    with SLOTS_LOCK:
        data = _read_slots()
        old = data.get("max_slots", 0)
        data["max_slots"] = number
        # Trim excess if reducing
        active = data.get("active", [])
        if len(active) > number:
            data["active"] = active[:number]
        save_slots(data)
        return f"✅ تم تعديل المساحة: {old} → {number}"

def add_uid_to_slots(uid: int) -> str:
    """Admin adds a specific user to slots"""
    with SLOTS_LOCK:
        data = _read_slots()
        active = data.get("active", [])
        if uid in active:
            return f"⚠️ `{uid}` لديه مقعد بالفعل."
        active.append(uid)
        data["active"] = active
        save_slots(data)
        return f"✅ تم إعطاء مقعد لـ `{uid}`."

def get_slots_status() -> str:
    """Get current slot usage with full details"""
    data = _read_slots()
    max_s = data.get("max_slots", 0)
    active = data.get("active", [])
    subs = load_subscribers()
    info = [
        f"🪑 **المساحة:** {len(active)}/{max_s} مستخدم",
        f"📋 **المشتركين:** {len(subs)}",
        f"👑 **المالك:** `{OWNER_ID}` (غير محسوب)",
    ]
    if active:
        info.append(f"👤 **المستخدمين النشطين:** {len(active)}")
    return "\n".join(info)

def remove_slot(chat_id: int) -> bool:
    """Remove a user from slots. Returns True if slot was freed."""
    with SLOTS_LOCK:
        data = _read_slots()
        active = data.get("active", [])
        max_s = data.get("max_slots", 0)
        timestamps = data.get("assigned_at", {})
        was_full = (len(active) >= max_s and max_s > 0)
        
        if chat_id in active:
            active.remove(chat_id)
            timestamps.pop(str(chat_id), None)
            data["active"] = active
            data["assigned_at"] = timestamps
            save_slots(data)
            logger.info(f"🪑 Slot removed: {chat_id} ({len(active)}/{max_s} remaining)")
            
            # Only notify if was full → now has exactly 1 slot available
            if was_full and len(active) == max_s - 1:
                _notify_one_slot_opened(max_s, len(active))
            return True
    return False

def _notify_one_slot_opened(max_s: int, active_count: int):
    """Notify subscribers without slots that exactly 1 slot opened"""
    subs = load_subscribers()
    active = _read_slots().get("active", [])
    admins = load_admins()
    for cid in subs:
        if cid not in active and cid not in admins:
            try:
                send_msg(cid, f"🪑 **تم توفر مقعد!**\n\nالمقاعد: {active_count}/{max_s}\nاستخدم /start للحجز.")
                time.sleep(0.3)
            except Exception as e:
                logger.debug(f"Slot notify failed for {cid}: {e}")


# ─── Rate Limiting (thread-safe) ───
RATE_LOCK = threading.Lock()

def parse_time_window(s: str) -> int:
    """Parse '4h', '30m', '1m', '1d' to seconds"""
    s = s.strip().lower()
    if s.endswith('h'):
        return int(s[:-1]) * 3600
    elif s.endswith('m'):
        return int(s[:-1]) * 60
    elif s.endswith('d'):
        return int(s[:-1]) * 86400
    elif s.endswith('s'):
        return int(s[:-1])
    return 3600  # default 1h

def check_rate_limit(chat_id: int) -> dict:
    """
    Returns: {"allowed": bool, "remaining": int, "reset_in": str, "warning": str}
    """
    now = time.time()
    data = read_rate_config()
    window = data.get("window_seconds", 3600)
    max_req = data.get("max_per_window", 5)
    per_user = data.get("per_user", {})
    
    sid = str(chat_id)
    user_data = per_user.get(sid, {"count": 0, "window_start": now})
    
    # Check if window expired
    if now - user_data.get("window_start", 0) > window:
        user_data = {"count": 0, "window_start": now}
    
    used = user_data.get("count", 0)
    remaining = max(0, max_req - used)
    allowed = remaining > 0
    
    # Warning message
    warning = ""
    if used > 0 and max_req > 0:
        pct = used / max_req * 100
        if pct >= 80:
            reset_sec = int(window - (now - user_data.get("window_start", now)))
            warning = f"⚠️ تبقت {remaining} طلبة فقط. يتجدد بعد {reset_sec // 60} دقيقة."
    
    reset_in_sec = int(window - (now - user_data.get("window_start", now)))
    if reset_in_sec < 0:
        reset_in_sec = 0
    
    return {
        "allowed": allowed,
        "remaining": remaining,
        "reset_in": f"{reset_in_sec // 60} دقيقة",
        "warning": warning,
        "user_data": user_data,
        "sid": sid,
    }

def consume_rate_limit(chat_id: int):
    """Increment rate counter for a user"""
    now = time.time()
    with RATE_LOCK:
        data = read_rate_config()
        window = data.get("window_seconds", 3600)
        per_user = data.get("per_user", {})
        sid = str(chat_id)
        user_data = per_user.get(sid, {"count": 0, "window_start": now})
        
        if now - user_data.get("window_start", 0) > window:
            user_data = {"count": 0, "window_start": now}
        
        user_data["count"] = user_data.get("count", 0) + 1
        per_user[sid] = user_data
        data["per_user"] = per_user
        save_rate_config(data)

# ─── Pending entry price input ───
PENDING_ENTRY = {}  # {chat_id: {"symbol": str, "sym_clean": str, "trade": dict, "msg_id": int, "phase": "price"|"target"}}
PENDING_ENTRY_LOCK = threading.Lock()

def get_pending_entry(chat_id: int) -> dict:
    with PENDING_ENTRY_LOCK:
        return PENDING_ENTRY.get(chat_id)

def set_pending_entry(chat_id: int, data: dict):
    with PENDING_ENTRY_LOCK:
        PENDING_ENTRY[chat_id] = data

def clear_pending_entry(chat_id: int):
    with PENDING_ENTRY_LOCK:
        PENDING_ENTRY.pop(chat_id, None)

# ─── Pending sale price input (تم البيع) ───
PENDING_SALE = {}  # {chat_id: {"symbol": str, "sym_clean": str, "entry_price": float, "target_price": float, "target_idx": int, "msg_id": int}}
PENDING_SALE_LOCK = threading.Lock()

def get_pending_sale(chat_id: int) -> dict:
    with PENDING_SALE_LOCK:
        return PENDING_SALE.get(chat_id)

def set_pending_sale(chat_id: int, data: dict):
    with PENDING_SALE_LOCK:
        PENDING_SALE[chat_id] = data

def clear_pending_sale(chat_id: int):
    with PENDING_SALE_LOCK:
        PENDING_SALE.pop(chat_id, None)

# ─── Anti-spam for /list ───

# ═══════════════ Global Rate Tracker — 429 prevention ═══════════════
_broadcast_timestamps = {}
_BROADCAST_INTERVAL = 0.5        # ثانية بين كل رسالة
_GLOBAL_MAX_MSG = 20              # أقصى 20 رسالة
_GLOBAL_WINDOW = 30               # في آخر 30 ثانية
_global_send_times = []           # طابع زمني لكل إرسال
_global_rate_lock = threading.Lock()

def _check_global_rate() -> bool:
    """التحقق: هل تجاوزنا الـ 20 رسالة في آخر 30 ثانية؟"""
    global _global_send_times
    now = time.time()
    with _global_rate_lock:
        # إزالة الإرسالات الأقدم من 30 ثانية
        _global_send_times = [t for t in _global_send_times if now - t < _GLOBAL_WINDOW]
        if len(_global_send_times) >= _GLOBAL_MAX_MSG:
            oldest = _global_send_times[0] if _global_send_times else now
            wait = _GLOBAL_WINDOW - (now - oldest)
            if wait > 0:
                logger.warning(f"⏳ Global rate limit reached ({len(_global_send_times)}/{_GLOBAL_WINDOW}s) — waiting {wait:.1f}s")
                time.sleep(wait)
        _global_send_times.append(now)
    return True

def broadcast(text: str, reply_markup: dict = None, return_msg_ids: bool = False):
    """إرسال لجميع المشتركين — يدعم أزرار، الآن مع إيموجي Premium متحرك"""
    subs = load_subscribers()
    sent = 0
    msg_ids = {} if return_msg_ids else None
    for cid in subs:
        try:
            # 🛡️ Global rate limit: enforce max 20 msgs / 30s window
            _check_global_rate()

            mid = send_msg_premium(cid, text, reply_markup=reply_markup)
            if mid:
                sent += 1
                if return_msg_ids:
                    msg_ids[cid] = mid
            time.sleep(_BROADCAST_INTERVAL)  # 0.5s بين كل رسالة
        except Exception as e:
            logger.debug(f"Broadcast send error: {e}")
    if sent > 0:
        logger.info(f"Broadcast sent to {sent}/{len(subs)} subscribers")
    return msg_ids if return_msg_ids else None


def send_msg(chat_id, text, parse_mode="Markdown", reply_markup: dict = None, reply_to_msg_id: int = None):
    """إرسال رسالة تليجرام مع fallback إذا فشل Markdown — يدعم أزرار
    Returns: message_id (int) on success, None on failure.
    يدعم reply_to_msg_id للرد على رسالة سابقة."""
    try:
        if len(text) > 4000:
            text = text[:3990] + "\n\n... (مختصر)"

        payload = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if reply_to_msg_id:
            payload["reply_to_message_id"] = reply_to_msg_id

        # المحاولة الأولى مع Markdown
        if parse_mode:
            resp = requests.post(
                f"{API_BASE}/sendMessage",
                json=payload,
                timeout=15
            )
            data = resp.json()
            if data.get("ok"):
                return data["result"].get("message_id")

            # إذا فشل بسبب Markdown — حاول بدون parse_mode
            error = data.get("description", "")
            if "parse" in error.lower() or "can't parse" in error.lower() or "markdown" in error.lower():
                logger.warning(f"Markdown error, retrying without parse_mode: {error[:100]}")
                payload.pop("parse_mode", None)
                resp = requests.post(
                    f"{API_BASE}/sendMessage",
                    json=payload,
                    timeout=15
                )
                data = resp.json()
                if data.get("ok"):
                    return data["result"].get("message_id")
                logger.error(f"Send still failed without markdown: {data}")
                return None

        # المحاولة بدون parse_mode
        payload.pop("parse_mode", None)
        resp = requests.post(
            f"{API_BASE}/sendMessage",
            json=payload,
            timeout=15
        )
        result = resp.json()
        if result.get("ok"):
            return result["result"].get("message_id")

        # 🛡️ 429 Rate Limited — انتظار تلقائي وإعادة المحاولة
        if result.get("error_code") == 429:
            retry_after = result.get("parameters", {}).get("retry_after", 5)
            logger.warning(f"⏳ 429 rate limited (send_msg) — retry after {retry_after}s")
            time.sleep(retry_after)
            resp = requests.post(f"{API_BASE}/sendMessage", json=payload, timeout=15)
            retry_data = resp.json()
            if retry_data.get("ok"):
                return retry_data["result"].get("message_id")
            error_desc = retry_data.get('description', 'unknown')
        else:
            error_desc = result.get('description', 'unknown')
        if "Unauthorized" in error_desc:
            try:
                reg_resp = requests.get(f"{API_BASE}/getMe", timeout=10)
                if reg_resp.ok:
                    logger.info(f"🔑 Token re-registered during send — retrying...")
                    resp2 = requests.post(
                        f"{API_BASE}/sendMessage",
                        json=payload,
                        timeout=15
                    )
                    resp2_data = resp2.json()
                    if resp2_data.get("ok"):
                        return resp2_data["result"].get("message_id")
                    error_desc = resp2_data.get('description', 'unknown')
            except Exception as e:
                logger.debug(f"Telegram send error: {e}")
        if "blocked by the user" in error_desc.lower():
            subs = load_subscribers()
            if chat_id in subs:
                subs.remove(chat_id)
                save_subscribers(subs)
                logger.warning(f"Removed blocked user {chat_id} from subscribers")
            freed = remove_slot(chat_id)
            if freed:
                logger.info(f"🪑 Slot freed from blocked user {chat_id}")
        logger.error(f"Send error: {error_desc}")
        return None
    except Exception as e:
        logger.error(f"Send error: {e}")
        return None


# ═══════════════════════════════════════
# 📱 HTML send — مثالية للأيموجي المميز
# ═══════════════════════════════════════

def md_to_html(text: str) -> str:
    """تحويل Markdown بسيط إلى HTML
    **bold** → <b>bold</b>
    *italic* → <i>italic</i>
    `code` → <code>code</code>
    ```block``` → <pre>block</pre>
    """
    # Code blocks first (```...```) — نحميها من التعديل
    text = re.sub(r'```(\w*)\n?(.*?)```', r'<pre>\2</pre>', text, flags=re.DOTALL)
    # Inline code
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # Italic (single *)
    text = re.sub(r'(?<!\*)\*([^*\n]+?)\*(?!\*)', r'<i>\1</i>', text)
    # Links [text](url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    return text


def html_escape(text: str) -> str:
    """Escape HTML special characters — يحمي النص من كسر HTML"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_msg_premium(chat_id, text, parse_mode=None, reply_markup: dict = None, reply_to_msg_id: int = None):
    """إرسال رسالة مع إيموجي متحرك (Premium) عبر entities.
    يحول Markdown + custom emoji إلى entities ويُرسل بدون parse_mode.
    """
    from bot.custom_emoji import get_all_mappings, build_entities

    try:
        if len(text) > 4000:
            text = text[:3990] + "\n\n... (مختصر)"

        emoji_map = get_all_mappings()
        clean_text, entities = build_entities(text, emoji_map)

        payload = {"chat_id": chat_id, "text": clean_text}
        if entities:
            payload["entities"] = entities
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if reply_to_msg_id:
            payload["reply_to_message_id"] = reply_to_msg_id

        # جرب مع entities (بدون parse_mode)
        resp = requests.post(f"{API_BASE}/sendMessage", json=payload, timeout=15)
        data = resp.json()
        if data.get("ok"):
            return data["result"].get("message_id")

        # 🛡️ 429 Rate Limited — انتظار تلقائي
        if data.get("error_code") == 429:
            retry_after = data.get("parameters", {}).get("retry_after", 5)
            logger.warning(f"⏳ 429 rate limited (premium) — retry after {retry_after}s")
            time.sleep(retry_after)
            resp = requests.post(f"{API_BASE}/sendMessage", json=payload, timeout=15)
            data = resp.json()
            if data.get("ok"):
                return data["result"].get("message_id")

        # فشل بسبب entities — حاول بدون entities (نص عادي)
        error = data.get("description", "")
        logger.warning(f"Premium entities error ({error[:80]}), retrying plain text...")
        payload.pop("entities", None)
        resp = requests.post(f"{API_BASE}/sendMessage", json=payload, timeout=15)
        data = resp.json()
        if data.get("ok"):
            return data["result"].get("message_id")

        # 🛡️ 429 Rate Limited — بعد entities retry
        if data.get("error_code") == 429:
            retry_after = data.get("parameters", {}).get("retry_after", 5)
            logger.warning(f"⏳ 429 rate limited (premium plain) — retry after {retry_after}s")
            time.sleep(retry_after)
            resp = requests.post(f"{API_BASE}/sendMessage", json=payload, timeout=15)
            data = resp.json()
            if data.get("ok"):
                return data["result"].get("message_id")

        logger.error(f"Send premium failed: {data}")
        return None
    except Exception as e:
        logger.error(f"Send premium error: {e}")
        return None


def send_msg_html(chat_id, text, reply_markup: dict = None, reply_to_msg_id: int = None):
    """إرسال رسالة تليجرام بصيغة HTML"""
    try:
        if len(text) > 4000:
            text = text[:3990] + "\n\n... (مختصر)"

        html_text = md_to_html(text)

        payload = {"chat_id": chat_id, "text": html_text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if reply_to_msg_id:
            payload["reply_to_message_id"] = reply_to_msg_id

        resp = requests.post(f"{API_BASE}/sendMessage", json=payload, timeout=15)
        data = resp.json()
        if data.get("ok"):
            return data["result"].get("message_id")

        error = data.get("description", "")
        logger.warning(f"HTML send error, retrying without parse_mode: {error[:100]}")
        payload.pop("parse_mode", None)
        resp = requests.post(f"{API_BASE}/sendMessage", json=payload, timeout=15)
        data = resp.json()
        if data.get("ok"):
            return data["result"].get("message_id")
        logger.error(f"Send still failed without html: {data}")
        return None

    except Exception as e:
        logger.error(f"Send HTML error: {e}")
        return None



def _api_set_commands(commands: list, scope: dict) -> bool:
    """استدعاء setMyCommands في تيليجرام — بدون language_code عشان يظهر للكل."""
    try:
        payload = [{"command": c, "description": d} for c, d in commands]
        resp = requests.post(
            f"{API_BASE}/setMyCommands",
            json={"commands": payload, "scope": scope},
            timeout=10
        )
        return resp.json().get("ok", False)
    except Exception as e:
        logger.error(f"setMyCommands failed: {e}")
        return False


def _api_delete_commands(scope: dict) -> bool:
    """استدعاء deleteMyCommands — مسح الأوامر القديمة."""
    try:
        resp = requests.post(
            f"{API_BASE}/deleteMyCommands",
            json={"scope": scope},
            timeout=10
        )
        return resp.json().get("ok", False)
    except Exception as e:
        logger.error(f"deleteMyCommands failed: {e}")
        return False


def set_user_commands(chat_id: int, role: str) -> bool:
    """تعيين أوامر البوت لمستخدم محدد حسب رتبته.
    
    يستخدم BotCommandScopeChat(chat_id=X) — كل مستخدم يشوف أوامره فقط.
    
    الأدوار: owner | admin | premium | member
    الزوار (public) لا يُستخدم لهم هذا الاستدعاء — يعتمدون على default scope.
    """
    role_map = {
        "member": MEMBER_COMMAND_LIST,
        "premium": PREMIUM_COMMAND_LIST,
        "admin": ADMIN_COMMAND_LIST,
        "owner": OWNER_COMMAND_LIST,
    }
    cmds = role_map.get(role)
    if not cmds:
        logger.warning(f"Unknown role '{role}' for {chat_id}")
        return False
    
    scope = {"type": "chat", "chat_id": chat_id}
    ok = _api_set_commands(cmds, scope)
    if ok:
        logger.info(f"📋 Commands set — {chat_id} ({role}): {len(cmds)} commands")
    else:
        logger.warning(f"⚠️ Failed to set commands for {chat_id} ({role})")
    return ok


def init_all_commands():
    """
    تُستدعى عند بدء التشغيل فقط.
    1. يمسح الأوامر القديمة من default scope.
    2. يعيّن الأوامر العامة (default) ليظهر 5 أوامر للزوار الجدد.
    3. يعيد تعيين أوامر كل مشترك / مشرف / مالك حسب scope الخاص به.
    """
    logger.info("📋 Initializing bot commands...")
    
    # 1️⃣ امسح الأوامر القديمة من default scope (بدون لغة + لغة ar القديمة)
    _api_delete_commands({"type": "default"})
    try:
        requests.post(f"{API_BASE}/deleteMyCommands",
                     json={"scope": {"type": "default"}, "language_code": "ar"},
                     timeout=10)
    except Exception as e:
        logger.debug(f"Old AR commands cleanup: {e}")  # تنظيف الأوامر القديمة
    
    # 2️⃣ عيّن الأوامر العامة — لكل الزوار
    _api_set_commands(PUBLIC_COMMAND_LIST, {"type": "default"})
    logger.info(f"  ✅ Default scope: {len(PUBLIC_COMMAND_LIST)} public commands")
    
    # 3️⃣ أعِد تعيين أوامر كل المشتركين
    admins = load_admins()
    subs = load_subscribers()
    done = set()
    
    # المالك أولاً
    set_user_commands(OWNER_ID, "owner")
    done.add(OWNER_ID)
    
    # المشرفين
    for uid in admins:
        if uid not in done:
            set_user_commands(uid, "admin")
            done.add(uid)
    
    # باقي المشتركين
    for uid in subs:
        if uid not in done:
            set_user_commands(uid, "member")
            done.add(uid)
    
    logger.info(f"📋 Commands initialized: {len(done)} users total")

def send_trade_alert_to_subscribers(alert: str):
    """
    إرسال تنبيه صفقة فقط للمستخدمين المضافين للصفقة + المالك دايم.
    - المشتركون العاديون: يستلمون التنبيه فقط إذا أضافوا العملة لقائمتهم عبر /list
    - المالك (OWNER_ID): يستقبل كل التنبيهات بدون الحاجة لإضافة العملة
    - الأدمنز: لا يستلمون تنبيهات إلا إذا أضافوا العملة لقائمتهم (مثل أي مشترك)
    
    إذا كان التنبيه عن تحقيق هدف، يضيف زر "تم البيع" تلقائياً.
    """
    import re
    # استخراج الرمز من التنبيه — الصيغة: **SYMBOL**
    match = re.search(r'\*\*(\w+)\*\*', alert)
    if not match:
        # إذا ما قدرنا نستخرج الرمز، نرسل للمالك فقط
        safe_send(OWNER_ID, alert)
        return
    
    sym_clean = match.group(1)
    symbol = sym_clean + "USDT" if not sym_clean.endswith("USDT") else sym_clean
    
    # نجيب المشتركين فقط + المالك دايم
    # الأدمنز ما يستلمون تنبيهات الصفقات إلا إذا أضافوا العملة لقائمتهم
    subscribed = get_trade_subscribers(symbol)
    recipients = set(subscribed) | {OWNER_ID}  # المالك دايم موجود
    
    # 🎯 هل هذا التنبيه عن تحقيق هدف؟ (أضف زر "تم البيع")
    is_target_hit = any(kw in alert for kw in ["هدف ✅", "هدف T", "اول هدف", "هدف تحقق"])
    reply_markup = None
    if is_target_hit:
        # استخراج رقم الهدف من نص التنبيه
        tgt = 0  # افتراضي: هدف أول
        m = re.search(r'هدف T(\d)', alert)
        if m:
            tgt = int(m.group(1)) - 1  # T2→1, T3→2
        reply_markup = {
            "inline_keyboard": [
                [{"text": "💰 تم البيع", "callback_data": f"sold_{tgt}_{symbol}"}]
            ]
        }
    
    sent = 0
    for uid in recipients:
        try:
            show_sold = False
            user_alert = alert
            
            if is_target_hit:
                if has_tracking_data(uid, symbol):
                    user_target_count = get_user_target_count(uid, symbol)
                    is_last_target = (tgt + 1) >= user_target_count
                    
                    if is_last_target:
                        # 🔚 هذا آخر هدف — لا زر, رسالة منتهية + تسجيل تلقائي
                        show_sold = False
                        target_labels = {
                            0: "الهدف",
                            1: "الهدف الثاني",
                            2: "الهدف الثالث",
                        }
                        label = target_labels.get(tgt, f"الهدف {tgt+1}")
                        
                        # استبدال سطر "سجل ربحك" بـ "متابعه منتهيه"
                        for marker in ["💡 سجل ربحك", "\u2066💡 سجل ربحك"]:
                            if marker in user_alert:
                                idx = user_alert.find(marker)
                                line_start = user_alert.rfind('\n', 0, idx)
                                if line_start >= 0:
                                    user_alert = user_alert[:line_start] + f'\n⚠️ متابعه العمله منتهيه لتحقيقها {label}'
                                else:
                                    user_alert = f'⚠️ متابعه العمله منتهيه لتحقيقها {label}'
                                break
                        
                        # 🎯 تسجيل البيع تلقائياً
                        try:
                            entry_price = get_user_entry_price(uid, symbol)
                            if entry_price > 0:
                                price_match = re.search(r'سعر الهدف » [`]*\$?([\d.]+)', alert)
                                if not price_match:
                                    price_match = re.search(r'السعر » [`]*\$?([\d.]+)', alert)
                                if price_match:
                                    target_price = float(price_match.group(1))
                                    record_sale(uid, symbol, entry_price, target_price, tgt)
                                    mark_user_target_hit(uid, symbol, tgt)
                                    mark_user_tracking_complete(uid, symbol)
                                    remove_from_user_list(uid, symbol)
                                    unsubscribe_from_trade(symbol, uid)
                                    logger.info(f"  💰 Auto-sale: {uid} {sym_clean} @ {target_price} (T{tgt+1})")
                        except Exception as e:
                            logger.debug(f"Auto-sale failed for {uid}: {e}")
                    else:
                        # 🖐️ هذا هدف وسيط — أظهر الزر
                        show_sold = True
                else:
                    # 👤 بدون تتبع (مالك/زائر بدون قائمة) — رسالة معلومات فقط
                    show_sold = False
                    for marker in ["💡 سجل ربحك", "\u2066💡 سجل ربحك"]:
                        if marker in user_alert:
                            idx = user_alert.find(marker)
                            line_start = user_alert.rfind('\n', 0, idx)
                            if line_start >= 0:
                                user_alert = user_alert[:line_start] + '\n📊 الهدف الأول تحقق بنجاح'
                            else:
                                user_alert = '📊 الهدف الأول تحقق بنجاح'
                            break
                    
            if show_sold:
                msg_id = send_msg_premium(uid, user_alert, reply_markup=reply_markup)
            else:
                msg_id = send_msg(uid, user_alert)
            if msg_id:
                sent += 1
            time.sleep(0.08)
        except Exception as e:
            logger.debug(f"Alert send failed to {uid}: {e}")
    
    logger.info(f"  📨 {sym_clean} alert → {sent}/{len(recipients)} recipients (owner always)")
    
    # 🧹 إذا التنبيه إغلاق (TP/SL/إلغاء) — نظف القوائم + التتبع
    if any(kw in alert for kw in ["منتهيه", "خساره", "إلغاء", "ملغيه", "انتهت"]):
        cleanup_closed_trade(symbol)
        cleanup_user_tracking(symbol)


def _send_to_admins(text: str):
    """إرسال رسالة للأدمنز فقط"""
    admins = load_admins()
    for uid in admins:
        try:
            send_msg_premium(uid, text)
        except Exception as e:
            logger.debug(f"Admin notify failed for {uid}: {e}")



def safe_send(chat_id, text):
    """Send with premium emoji support — إيموجي متحرك لمستخدم Premium"""
    success = send_msg_premium(chat_id, text)
    if not success:
        # Try without entities
        clean = text.replace("**", "").replace("`", "").replace("*", "")
        success = send_msg(chat_id, clean, parse_mode=None)
    return success

# ─── Commands ───
def handle_callback(cb: dict):
    """Handle button press callbacks"""
    try:
        data = cb.get("data", "")
        chat_id = cb.get("message", {}).get("chat", {}).get("id")
        msg_id = cb.get("message", {}).get("message_id")
        
        # Remove loading indicator
        requests.post(f"{API_BASE}/answerCallbackQuery",
                      json={"callback_query_id": cb["id"], "text": ""},
                      timeout=10)
        
        if not chat_id:
            return
        
        trades = get_active_trades()
        
        # ─── Ignore placeholder ───
        if data == "nav_ignore":
            return
        
        # ─── Signals: Show active (filtered, sorted by PnL desc) ───
        if data == "signals_active":
            filtered = [t for t in trades if t.get("status") == "active"]
            # ترتيب من الأعلى ربحاً إلى الأعلى خسارة (مع حماية من None)
            def _pnl_key(t):
                entry = t.get("entry_price") or 0
                cur = t.get("current_price") or entry
                if entry == 0:
                    return 0.0
                return (cur - entry) / entry * 100
            filtered.sort(key=_pnl_key, reverse=True)
            if not filtered:
                text = "🟢 **لا توجد توصيات نشطة حالياً**\n\nكل التوصيات معلقة أو منتهية."
                keyboard = {"inline_keyboard": [[{"text": "🔄 الرجوع", "callback_data": "back_signals"}]]}
            else:
                keyboard = build_list_keyboard(filtered, page=1, mode="signals", filter_type="active")
                total_pages = max(1, (len(filtered) + 9) // 10)
                text = f"🟢 **التوصيات النشطة** ({len(filtered)}) — ص 1/{total_pages}\nاختر عملة للتفاصيل:"
            requests.post(f"{API_BASE}/editMessageText", json={
                "chat_id": chat_id, "message_id": msg_id,
                "text": text, "reply_markup": keyboard,
                "parse_mode": "Markdown"
            }, timeout=10)
            return

        # ─── Signals: Show pending (filtered) ───
        if data == "signals_pending":
            filtered = [t for t in trades if t.get("status") == "pending"]
            if not filtered:
                text = "⏳ **لا توجد توصيات معلقة حالياً**\n\nكل التوصيات نشطة أو منتهية."
                keyboard = {"inline_keyboard": [[{"text": "🔄 الرجوع", "callback_data": "back_signals"}]]}
            else:
                keyboard = build_list_keyboard(filtered, page=1, mode="signals", filter_type="pending")
                total_pages = max(1, (len(filtered) + 9) // 10)
                text = f"⏳ **التوصيات المعلقة** ({len(filtered)}) — ص 1/{total_pages}\nاختر عملة للتفاصيل:"
            requests.post(f"{API_BASE}/editMessageText", json={
                "chat_id": chat_id, "message_id": msg_id,
                "text": text, "reply_markup": keyboard,
                "parse_mode": "Markdown"
            }, timeout=10)
            return

        # ─── Signals: Filtered page nav ───
        if data.startswith("signals_active_page_"):
            page = int(data.replace("signals_active_page_", ""))
            filtered = [t for t in trades if t.get("status") == "active"]
            # ترتيب من الأعلى ربحاً إلى الأعلى خسارة (مع حماية من None)
            def _pnl_key(t):
                entry = t.get("entry_price") or 0
                cur = t.get("current_price") or entry
                if entry == 0:
                    return 0.0
                return (cur - entry) / entry * 100
            filtered.sort(key=_pnl_key, reverse=True)
            keyboard = build_list_keyboard(filtered, page=page, mode="signals", filter_type="active")
            total_pages = max(1, (len(filtered) + 9) // 10)
            text = f"🟢 **التوصيات النشطة** ({len(filtered)}) — ص {page}/{total_pages}\nاختر عملة للتفاصيل:"
            requests.post(f"{API_BASE}/editMessageText", json={
                "chat_id": chat_id, "message_id": msg_id,
                "text": text, "reply_markup": keyboard,
                "parse_mode": "Markdown"
            }, timeout=10)
            return

        if data.startswith("signals_pending_page_"):
            page = int(data.replace("signals_pending_page_", ""))
            filtered = [t for t in trades if t.get("status") == "pending"]
            keyboard = build_list_keyboard(filtered, page=page, mode="signals", filter_type="pending")
            total_pages = max(1, (len(filtered) + 9) // 10)
            text = f"⏳ **التوصيات المعلقة** ({len(filtered)}) — ص {page}/{total_pages}\nاختر عملة للتفاصيل:"
            requests.post(f"{API_BASE}/editMessageText", json={
                "chat_id": chat_id, "message_id": msg_id,
                "text": text, "reply_markup": keyboard,
                "parse_mode": "Markdown"
            }, timeout=10)
            return

        # ─── Page navigation: signals ───
        if data.startswith("signals_page_"):
            page = int(data.replace("signals_page_", ""))
            trades = get_active_trades()
            keyboard = build_list_keyboard(trades, page=page, mode="signals")
            active_count = len([t for t in trades if t.get("status") == "active"])
            pending_count = len([t for t in trades if t.get("status") == "pending"])
            total_pages = max(1, (len(trades) + 9) // 10)
            text = f"📡 **التوصيات النشطة** ({len(trades)}) — ص {page}/{total_pages}\n✅ {active_count} نشطة"
            if pending_count > 0:
                text += f" | ⏳ {pending_count} معلقة"
            text += "\nاختر عملة للتفاصيل:"
            requests.post(f"{API_BASE}/editMessageText", json={
                "chat_id": chat_id, "message_id": msg_id,
                "text": text, "reply_markup": keyboard,
                "parse_mode": "Markdown"
            }, timeout=10)
            return
        
        # ─── Page navigation: my list ───
        if data.startswith("mylist_page_"):
            page = int(data.replace("mylist_page_", ""))
            user_symbols = get_user_list(chat_id)
            all_trades = get_active_trades()
            my_trades = [t for t in all_trades if t["symbol"] in user_symbols]
            keyboard = build_list_keyboard(my_trades, page=page, mode="list")
            total_pages = max(1, (len(my_trades) + 9) // 10)
            text = f"📋 **قائمتك الشخصية** ({len(my_trades)} عملة) — ص {page}/{total_pages}\nاختر عملة للتفاصيل:"
            requests.post(f"{API_BASE}/editMessageText", json={
                "chat_id": chat_id, "message_id": msg_id,
                "text": text, "reply_markup": keyboard,
                "parse_mode": "Markdown"
            }, timeout=10)
            return
        
        # ─── Back to signals filter ───
        if data in ("back_list", "back_signals"):
            trades = get_active_trades()
            if not trades:
                requests.post(f"{API_BASE}/editMessageText", json={
                    "chat_id": chat_id, "message_id": msg_id,
                    "text": "📡 **لا توجد توصيات حالياً**",
                    "parse_mode": "Markdown"
                }, timeout=10)
                return
            active_count = len([t for t in trades if t.get("status") == "active"])
            pending_count = len([t for t in trades if t.get("status") == "pending"])
            text = f"📡 **اختر نوع التوصيات**\n\n✅ {active_count} نشطة | ⏳ {pending_count} معلقة\n\nاختر النوع لعرض القائمة:"
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": f"🟢 نشطه ({active_count})", "callback_data": "signals_active"},
                        {"text": f"⏳ معلقه ({pending_count})", "callback_data": "signals_pending"},
                    ]
                ]
            }
            requests.post(f"{API_BASE}/editMessageText", json={
                "chat_id": chat_id, "message_id": msg_id,
                "text": text, "reply_markup": keyboard,
                "parse_mode": "Markdown"
            }, timeout=10)
            return
        
        # ─── Back to my list ───
        if data == "back_mylist":
            user_symbols = get_user_list(chat_id)
            all_trades = get_active_trades()
            my_trades = [t for t in all_trades if t["symbol"] in user_symbols]
            keyboard = build_list_keyboard(my_trades, page=1, mode="list")
            text = f"📋 **قائمتك الشخصية** ({len(my_trades)} عملة)\nاختر عملة للتفاصيل:"
            requests.post(f"{API_BASE}/editMessageText", json={
                "chat_id": chat_id, "message_id": msg_id,
                "text": text, "reply_markup": keyboard,
                "parse_mode": "Markdown"
            }, timeout=10)
            return
        
        # ─── 🎯 Target selection (premium users) ───
        if data.startswith("target_"):
            # data format: target_1_SYMBOL → target_{count}_{symbol}
            parts = data.split("_", 2)  # max split = 2 → ["target", "1", "SYMBOL"]
            if len(parts) < 3:
                return
            count = int(parts[1])
            symbol = parts[2]
            sym_clean = symbol.replace("USDT", "")
            
            pending = get_pending_entry(chat_id)
            if not pending or pending.get("phase") != "target":
                requests.post(f"{API_BASE}/answerCallbackQuery", json={
                    "callback_query_id": cb["id"], "text": "انتهت صلاحية الطلب، استخدم /signals من جديد"
                }, timeout=10)
                return
            
            user_entry = pending.get("entry_price", pending.get("original_entry"))
            
            # Add to list with target count
            clear_pending_entry(chat_id)
            added = add_to_user_list(chat_id, symbol)
            subscribe_to_trade(symbol, chat_id)
            
            if added:
                set_user_entry_price(chat_id, symbol, user_entry)
                # تخزين أهداف الصفقة في التتبع للمراقبة بعد إغلاق الصفقة العالمية
                trade_targets = pending.get("trade", {}).get("targets", [])
                set_user_target_count(chat_id, symbol, count, targets=trade_targets, entry_price=user_entry)
                
                target_text = {1: "هدف واحد 🎯", 2: "هدفين 🎯🎯", 3: "3 أهداف 🎯🎯🎯"}.get(count, f"{count} أهداف")
                text = (
                    f"✅ **{sym_clean}** أضيفت إلى قائمتك!\n\n"
                    f"📥 سعر دخولك: **${user_entry}**\n"
                    f"🎯 المتابعة: {target_text}\n"
                    f"ستصلك تنبيهات لكل هدف يتحقق\n\n"
                    f"📋 /list | 📊 /portfolio"
                )
            else:
                text = f"ℹ️ **{sym_clean}** موجودة فعلاً في قائمتك."
            
            requests.post(f"{API_BASE}/editMessageText", json={
                "chat_id": chat_id, "message_id": msg_id,
                "text": text,
                "parse_mode": "Markdown",
            }, timeout=10)
            return
        
        # ─── 💰 تم البيع button ───
        if data.startswith("sold_"):
            # Format: sold_{target_idx}_{symbol} (جديد) أو sold_{symbol} (قديم)
            parts = data.split("_", 2)
            if len(parts) < 2:
                return
            if len(parts) == 2:
                # صيغة قديمة: sold_SYMBOL → توافق عكسي
                target_idx = 0
                symbol = parts[1]
            else:
                # صيغة جديدة: sold_TARGET_SYMBOL
                try:
                    target_idx = int(parts[1])
                except ValueError:
                    target_idx = 0
                symbol = parts[2]
            sym_clean = symbol.replace("USDT", "")
            
            # Get user's entry price for this symbol
            entry_price = get_user_entry_price(chat_id, symbol)
            if entry_price <= 0:
                requests.post(f"{API_BASE}/answerCallbackQuery", json={
                    "callback_query_id": cb["id"], "text": "لم نعثر على سعر الدخول!"
                }, timeout=10)
                return
            
            set_pending_sale(chat_id, {
                "symbol": symbol,
                "sym_clean": sym_clean,
                "entry_price": entry_price,
                "target_idx": target_idx,
                "msg_id": msg_id,
            })
            
            requests.post(f"{API_BASE}/editMessageText", json={
                "chat_id": chat_id, "message_id": msg_id,
                "text": (
                    f"💰 **{sym_clean} — تم البيع**\n\n"
                    f"سعر دخولك: **${entry_price}**\n"
                    f"الرجاء إرسال **سعر البيع الفعلي**:\n"
                    f"(أرسل الرقم فقط)"
                ),
                "parse_mode": "Markdown",
            }, timeout=10)
            return
        
        # ─── Add to personal list — Auto-calculate entry price 🔥 ───
        if data.startswith("add_"):
            symbol = data.replace("add_", "")
            sym_clean = symbol.replace("USDT", "")
            
            # Find the trade
            trade = next((t for t in trades if t["symbol"] == symbol), None)
            if not trade:
                requests.post(f"{API_BASE}/editMessageText", json={
                    "chat_id": chat_id, "message_id": msg_id,
                    "text": f"⚠️ **{sym_clean}** لم تعد متاحة.",
                    "parse_mode": "Markdown"
                }, timeout=10)
                return
            
            sig_entry = trade["entry_price"]
            
            # 🔥 Auto-calculate entry price: min(current_price, signal_entry)
            current_price = trade.get("current_price", sig_entry)
            try:
                from data.fetcher import get_fetcher
                prices = get_fetcher().fetch_all_prices()
                live_price = prices.get(symbol)
                if live_price and live_price > 0:
                    current_price = live_price
            except Exception:
                logger.debug("Live price fetch failed, using fallback")
            
            user_entry = min(current_price, sig_entry)
            dec = 8 if user_entry < 1 else 6 if user_entry < 100 else 4
            sig_dec = 8 if sig_entry < 1 else 6 if sig_entry < 100 else 4
            
            role = get_role(chat_id)
            
            # ── Premium/Admin/Owner → ask target count first ──
            if role in ("premium", "admin", "owner"):
                set_pending_entry(chat_id, {
                    "symbol": symbol,
                    "sym_clean": sym_clean,
                    "trade": trade,
                    "phase": "target",
                    "entry_price": user_entry,
                    "original_entry": sig_entry,
                    "current_price": current_price,
                    "msg_id": msg_id,
                })
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "🎯 هدف واحد", "callback_data": f"target_1_{symbol}"}],
                        [{"text": "🎯 هدفين", "callback_data": f"target_2_{symbol}"}],
                        [{"text": "🎯 3 أهداف", "callback_data": f"target_3_{symbol}"}],
                    ]
                }
                requests.post(f"{API_BASE}/editMessageText", json={
                    "chat_id": chat_id, "message_id": msg_id,
                    "text": (
                        f"📝 **كم هدف تريد متابعة {sym_clean} عليه؟**\n\n"
                        f"📥 سعر دخولك التلقائي: **${user_entry:.{dec}f}**\n"
                        f"💡 سعر الإشارة الأصلي: ${sig_entry:.{sig_dec}f}\n"
                        f"📊 السعر الحالي: ${current_price:.{dec}f}\n\n"
                        f"✅ تم احتساب أفضل سعر دخول لك تلقائياً!\n\n"
                        f"اختر عدد الأهداف للمتابعة:"
                    ),
                    "reply_markup": keyboard,
                    "parse_mode": "Markdown",
                }, timeout=10)
                return
            
            # ── Regular member → add directly ──
            clear_pending_entry(chat_id)
            added = add_to_user_list(chat_id, symbol)
            subscribe_to_trade(symbol, chat_id)
            
            if added:
                set_user_entry_price(chat_id, symbol, user_entry)
                cp_dec = 8 if current_price < 1 else 6 if current_price < 100 else 4
                text = (
                    f"✅ **{sym_clean}** أضيفت إلى قائمتك!\n\n"
                    f"📥 سعر دخولك التلقائي: **${user_entry:.{dec}f}**\n"
                    f"💡 سعر الإشارة الأصلي: ${sig_entry:.{sig_dec}f}\n"
                    f"📊 السعر الحالي: ${current_price:.{cp_dec}f}\n"
                    f"🟢 تم احتساب أفضل سعر لك!\n\n"
                    f"📋 /list | 📊 /portfolio"
                )
            else:
                text = f"ℹ️ **{sym_clean}** موجودة فعلاً في قائمتك.\n\n📋 /list | 📊 /portfolio"
            
            requests.post(f"{API_BASE}/editMessageText", json={
                "chat_id": chat_id, "message_id": msg_id,
                "text": text,
                "parse_mode": "Markdown",
            }, timeout=10)
            return
        
        # ─── Remove from personal list ───
        if data.startswith("remove_"):
            symbol = data.replace("remove_", "")
            sym_clean = symbol.replace("USDT", "")
            
            removed = remove_from_user_list(chat_id, symbol)
            unsubscribe_from_trade(symbol, chat_id)
            
            if removed:
                text = f"🗑️ **{sym_clean}** حذفت من قائمتك.\n\nلن تصلك تنبيهاتها بعد الآن.\n\n📡 /signals | 📋 /list"
            else:
                text = f"ℹ️ **{sym_clean}** غير موجودة في قائمتك."
            
            requests.post(f"{API_BASE}/editMessageText", json={
                "chat_id": chat_id, "message_id": msg_id,
                "text": text,
                "parse_mode": "Markdown"
            }, timeout=10)
            return
        
        # ─── View trade details ───
        if data.startswith("trade_"):
            symbol = data.replace("trade_", "")
            trade = next((t for t in trades if t["symbol"] == symbol), None)
            # Detect which mode we're coming from
            user_symbols = get_user_list(chat_id)
            from_mode = "list" if symbol in user_symbols else "signals"
            if trade:
                trade["current_price"] = trade.get("current_price", trade["entry_price"])
                text = format_trade_detail_text(trade)
                keyboard = build_detail_keyboard(symbol, user_id=chat_id, from_mode=from_mode)
            else:
                text = f"⚠️ {symbol.replace('USDT','')} trade no longer exists."
                keyboard = build_back_keyboard("signals")
            
            requests.post(f"{API_BASE}/editMessageText", json={
                "chat_id": chat_id, "message_id": msg_id,
                "text": text, "reply_markup": keyboard,
                "parse_mode": "Markdown"
            }, timeout=10)
            return
        
        # ─── Support analysis for losing trade ───
        if data.startswith("analyze_"):
            symbol = data.replace("analyze_", "")
            logger.info(f"📊 Support analysis requested for {symbol}")
            
            # Detect mode
            user_symbols = get_user_list(chat_id)
            from_mode = "list" if symbol in user_symbols else "signals"
            
            # Waiting message
            requests.post(f"{API_BASE}/editMessageText", json={
                "chat_id": chat_id, "message_id": msg_id,
                "text": f"🔍 Analyzing {symbol.replace('USDT','')}... ⏳",
                "parse_mode": "Markdown"
            }, timeout=10)
            
            # تحليل الدعم
            analysis = analyze_support_levels(symbol)
            keyboard = build_back_keyboard(from_mode)
            
            requests.post(f"{API_BASE}/editMessageText", json={
                "chat_id": chat_id, "message_id": msg_id,
                "text": analysis, "reply_markup": keyboard,
                "parse_mode": "Markdown"
            }, timeout=10)
    
    except Exception as e:
        logger.error(f"Callback error: {e}")
        # ⚠️ Show user an error popup
        try:
            requests.post(f"{API_BASE}/answerCallbackQuery", json={
                "callback_query_id": cb.get("id"),
                "text": "⚠️ حدث خطأ. حاول مرة أخرى.",
                "show_alert": True
            }, timeout=10)
        except Exception:
            logger.debug("Failed to answer callback query（non-critical）")


def handle_update(update: dict):
    # ─── Handle callbacks first ───
    cb = update.get("callback_query")
    if cb:
        try:
            handle_callback(cb)
        except Exception as e:
            logger.error(f"Callback call error: {e}")
            try:
                requests.post(f"{API_BASE}/answerCallbackQuery", json={
                    "callback_query_id": cb.get("id"),
                    "text": "⚠️ حدث خطأ. حاول مرة أخرى.",
                    "show_alert": True
                }, timeout=10)
            except Exception:
                logger.debug("Callback answer alert failed（non-critical）")
        return
    
    msg = update.get("message", {})
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    text = msg.get("text", "").strip()
    username = chat.get("username", "")
    first_name = chat.get("first_name", "")

    if not chat_id or not text:
        return

    args = text.split()
    cmd = args[0].lower()
    logger.info(f"Command: {cmd} from {chat_id}")

    # ─── صلاحيات حسب الرتبة ───
    user_role = get_role(chat_id)
    is_subscribed = user_role is not None  # أي شخص له رتبة
    is_admin_role = is_admin(chat_id)       # مشرف أو مالك
    
    # ═══════════════════════════════════
    # رفض لغير المشتركين فقط
    # ═══════════════════════════════════
    if not is_subscribed and cmd not in PUBLIC_COMMANDS:
        logger.warning(f"🚫 Blocked {chat_id} ({first_name}) — not subscribed")
        safe_send(chat_id, "🚫 **تم حظرك!**\n\nاستخدم /start أولاً للاشتراك.")
        return
    
    try:
        # ═══════════════════════════════════
        # 🎯 Pending entry price — user is adding a coin
        # ═══════════════════════════════════
        pending_entry = get_pending_entry(chat_id)
        if pending_entry and not text.startswith("/"):
            symbol = pending_entry["symbol"]
            sym_clean = pending_entry["sym_clean"]
            trade = pending_entry["trade"]
            low = pending_entry["low"]
            high = pending_entry["high"]
            original_entry = pending_entry["original_entry"]
            msg_id = pending_entry["msg_id"]
            
            # ── If already in "target" phase, this text shouldn't happen ──
            if pending_entry.get("phase") == "target":
                return
            
            try:
                user_entry = float(text.replace(",", "").replace("$", ""))
            except ValueError:
                safe_send(chat_id, f"⚠️ **{sym_clean}** لم تُضف — الرجاء إرسال رقم صحيح.\n\nأرسل السعر مرة أخرى (مثلاً: {original_entry}):")
                return
            
            # Validation: must be within [low, high] range
            if user_entry < low or user_entry > high:
                safe_send(chat_id, (
                    f"⚠️ **{sym_clean}** لم تُضف — سعر الدخول غير صحيح.\n\n"
                    f"السعر المدخل (${user_entry}) لا يتطابق مع نطاق سعر الإشارة.\n"
                    f"الرجاء التأكد من سعر الشراء الفعلي وحاول مرة أخرى.\n"
                    f"سعر الإشارة الأصلي: ${original_entry}\n\n"
                    f"أرسل السعر الصحيح (مثلاً: {original_entry}):"
                ))
                return
            
            # ✅ Validation passed!
            role = get_role(chat_id)
            
            # ── If premium/admin/owner → ask target count first ──
            if role in ("premium", "admin", "owner"):
                set_pending_entry(chat_id, {
                    **pending_entry,
                    "phase": "target",
                    "entry_price": user_entry,
                })
                # Inline keyboard for target selection
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "🎯 هدف واحد", "callback_data": f"target_1_{symbol}"}],
                        [{"text": "🎯 هدفين", "callback_data": f"target_2_{symbol}"}],
                        [{"text": "🎯 3 أهداف", "callback_data": f"target_3_{symbol}"}],
                    ]
                }
                requests.post(f"{API_BASE}/editMessageText", json={
                    "chat_id": chat_id, "message_id": msg_id,
                    "text": (
                        f"📝 **كم هدف تريد متابعة {sym_clean} عليه؟**\n\n"
                        f"✅ سعر الدخول: **${user_entry}**\n"
                        f"اختر عدد الأهداف التي تريد النظام يتتبعها:"
                    ),
                    "reply_markup": keyboard,
                    "parse_mode": "Markdown",
                }, timeout=10)
                return
            
            # ── Regular member → add directly ──
            clear_pending_entry(chat_id)
            added = add_to_user_list(chat_id, symbol)
            subscribe_to_trade(symbol, chat_id)
            
            if added:
                set_user_entry_price(chat_id, symbol, user_entry)
                safe_send(chat_id, (
                    f"✅ **{sym_clean}** أضيفت إلى قائمتك!\n\n"
                    f"📥 سعر دخولك: **${user_entry}**\n"
                    f"ستصلك تنبيهات: تنفيذ الأمر • الأهداف • وقف الخسارة\n\n"
                    f"📋 /list | 📊 /portfolio"
                ))
            else:
                safe_send(chat_id, f"ℹ️ **{sym_clean}** موجودة فعلاً في قائمتك.\n\n📋 /list | 📊 /portfolio")
            return
        
        if pending_entry and text.startswith("/"):
            # User sent a command instead — cancel pending
            clear_pending_entry(chat_id)
        
        # ═══════════════════════════════════
        # 💰 Pending sale — user clicked "تم البيع"
        # ═══════════════════════════════════
        pending_sale = get_pending_sale(chat_id)
        if pending_sale and not text.startswith("/"):
            symbol = pending_sale["symbol"]
            sym_clean = pending_sale["sym_clean"]
            entry_price = pending_sale["entry_price"]
            target_idx = pending_sale["target_idx"]
            msg_id = pending_sale["msg_id"]
            
            try:
                sale_price = float(text.replace(",", "").replace("$", ""))
            except ValueError:
                safe_send(chat_id, f"⚠️ **{sym_clean}** — الرجاء إرسال رقم صحيح.\n\nأرسل سعر البيع (مثلاً: {entry_price}):")
                return
            
            if sale_price <= 0:
                safe_send(chat_id, "⚠️ سعر البيع يجب أن يكون أكبر من 0. أرسل السعر الصحيح:")
                return
            
            clear_pending_sale(chat_id)
            
            # Record the sale
            from bot.user_lists import record_sale, mark_user_target_hit, get_user_target_count, get_user_targets_hit, mark_user_tracking_complete, remove_from_user_list, unsubscribe_from_trade
            pnl_pct = record_sale(chat_id, symbol, entry_price, sale_price, target_idx)
            
            # 🎯 تسجيل الهدف في تتبع المستخدم
            mark_user_target_hit(chat_id, symbol, target_idx)
            
            # 🎯 هل هذا هو آخر هدف للمستخدم؟
            target_count = get_user_target_count(chat_id, symbol)
            targets_hit = get_user_targets_hit(chat_id, symbol)
            
            pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"
            if len(targets_hit) >= target_count:
                # ✅ اكتمل التتبع — نحذف من القائمة ونلغي الاشتراك
                mark_user_tracking_complete(chat_id, symbol)
                remove_from_user_list(chat_id, symbol)
                unsubscribe_from_trade(symbol, chat_id)
                safe_send(chat_id, (
                    f"{pnl_emoji} **{sym_clean} — تم تسجيل البيع!** ✅\n\n"
                    f"📥 سعر الشراء: **${entry_price}**\n"
                    f"💰 سعر البيع: **${sale_price}**\n"
                    f"📊 الربح/الخسارة: **{pnl_pct:+.2f}%**\n\n"
                    f"🎯 اكتمل تتبع {sym_clean} بعدد الأهداف المطلوب ({target_count}).\n"
                    f"📊 /portfolio — لمشاهدة محفظتك"
                ))
            else:
                # ⏳ التتبع مستمر — انتظار الأهداف القادمة
                remaining = target_count - len(targets_hit)
                safe_send(chat_id, (
                    f"{pnl_emoji} **{sym_clean} — تم تسجيل البيع!**\n\n"
                    f"📥 سعر الشراء: **${entry_price}**\n"
                    f"💰 سعر البيع: **${sale_price}**\n"
                    f"📊 الربح/الخسارة: **{pnl_pct:+.2f}%**\n\n"
                    f"📌 تبقي {remaining} هدف/أهداف للمتابعة.\n"
                    f"ستصلك تنبيهات الأهداف القادمة."
                ))
            return
        
        if pending_sale and text.startswith("/"):
            clear_pending_sale(chat_id)
        
        # ═══════════════════════════════════
        # PUBLIC COMMANDS (anyone)
        # ═══════════════════════════════════

        if cmd == "/start":
            # اشتراك + صلاحيات كاملة تلقائي
            add_subscriber(chat_id, username, first_name)
            try_assign_slot(chat_id)  # 🪑 تعيين مقعد تلقائي
            reset_spam(chat_id)
            
            # تعيين الرتبة
            current_role = get_role(chat_id)
            if not current_role or current_role == "member":
                set_role(chat_id, "member")
            
            # تعيين الأوامر حسب الرتبة
            role = get_role(chat_id)
            set_user_commands(chat_id, role)
            
            # رسالة ترحيب حسب الرتبة
            if role == "owner":
                safe_send(chat_id, f"🎉 **Welcome Master YJ!**\n\n{WELCOME_MSG}")
            elif role == "admin":
                safe_send(chat_id, f"🎉 **مرحباً بك أيها المشرف**\n\n{WELCOME_MSG}")
            elif role == "premium":
                safe_send(chat_id, f"🎉 **مرحباً بك أيها المميز**\n\n📊 لديك صلاحية الوصول للتحليلات المتقدمة.\n\n{MEMBER_WELCOME}")
            else:
                safe_send(chat_id, MEMBER_WELCOME)
            return

        elif cmd == "/signals":
            # عرض قائمة اختيار: نشطة vs معلقة
            if not is_admin_role:
                allowed, spam_msg = check_list_spam(chat_id)
                if not allowed:
                    safe_send(chat_id, spam_msg)
                    return

            trades = get_active_trades()
            if not trades:
                safe_send(chat_id, "📡 **لا توجد توصيات نشطة حالياً**")
                return

            active_count = len([t for t in trades if t.get("status") == "active"])
            pending_count = len([t for t in trades if t.get("status") == "pending"])
            text = f"📡 **اختر نوع التوصيات**\n\n✅ {active_count} نشطة | ⏳ {pending_count} معلقة\n\nاختر النوع لعرض القائمة:"
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": f"🟢 نشطه ({active_count})", "callback_data": "signals_active"},
                        {"text": f"⏳ معلقه ({pending_count})", "callback_data": "signals_pending"},
                    ]
                ]
            }
            requests.post(f"{API_BASE}/sendMessage", json={
                "chat_id": chat_id,
                "text": text,
                "reply_markup": keyboard,
                "parse_mode": "Markdown"
            }, timeout=15)
            return

        elif cmd == "/list":
            # قائمة المستخدم الشخصية — مع pagination
            user_symbols = get_user_list(chat_id)
            if not user_symbols:
                safe_send(chat_id, "📋 **قائمتك الشخصية**\n\nلا توجد عملات مضافة.\n\nاستخدم /signals لعرض التوصيات ثم اضغط ➕ أضف إلى قائمتي.")
                return
            
            trades = get_active_trades()
            my_trades = [t for t in trades if t["symbol"] in user_symbols]
            
            if not my_trades:
                safe_send(chat_id, "📋 **قائمتك الشخصية**\n\nالعملات اللي ضفتها لم تعد نشطة (حققت هدف/ألغيت/ضربت وقف).\nاستخدم /signals للبحث عن فرص جديدة.")
                return
            
            keyboard = build_list_keyboard(my_trades, page=1, mode="list")
            total_pages = max(1, (len(my_trades) + 9) // 10)
            text = f"📋 **قائمتك الشخصية** ({len(my_trades)} عملة) — ص 1/{total_pages}\nاختر عملة للتفاصيل:"
            requests.post(f"{API_BASE}/sendMessage", json={
                "chat_id": chat_id,
                "text": text,
                "reply_markup": keyboard,
                "parse_mode": "Markdown"
            }, timeout=15)
            return

        elif cmd == "/portfolio":
            # محفظة المستخدم — ربح/خسارة العملات اللي ضافها
            user_symbols = get_user_list(chat_id)
            if not user_symbols:
                # No active trades — show closed trade history
                try:
                    with open(DATA_DIR / "trades_history.json") as f:
                        history = json.load(f)
                except Exception:
                    history = []
                
                user_history = [h for h in history if h.get("symbol", "").replace("USDT","") in 
                               [s.replace("USDT","") for s in user_symbols]] if user_symbols else []
                
                if not user_history and not user_symbols:
                    safe_send(chat_id, "📊 **محفظتك**\n\nلا توجد عملات مضافة.\n\nاستخدم /signals ثم ➕ أضف إلى قائمتي.")
                    return
                
                if not user_history and user_symbols:
                    safe_send(chat_id, "📊 **محفظتك**\n\nلا توجد صفقات نشطة حالياً في قائمتك.\nكل الصفقات السابقة مغلقة.")
                    return
                
                # Show closed trade history
                wins = [h for h in user_history if h.get("pnl_pct",0) > 0]
                losses = [h for h in user_history if h.get("pnl_pct",0) < 0]
                total_pnl = sum(h.get("pnl_pct",0) for h in user_history)
                win_rate = len(wins) / max(len(wins) + len(losses), 1) * 100
                
                lines = ["📊 **محفظتك — سجل الصفقات**", ""]
                for h in user_history[-10:]:  # Last 10
                    sym = h["symbol"].replace("USDT", "")
                    pnl = h.get("pnl_pct", 0)
                    emoji = "🟢" if pnl > 0 else "🔴"
                    lines.append(f"{emoji} **{sym}** {pnl:+.2f}%")
                
                lines.append("")
                lines.append("━━━━━━━━━━━━━━━")
                total_emoji = "🟢" if total_pnl > 0 else "🔴"
                lines.append(f"{total_emoji} **إجمالي الأرباح:** {total_pnl:+.2f}%")
                lines.append(f"✅ ناجحة: {len(wins)} | ❌ خاسرة: {len(losses)} | 🎯 {win_rate:.0f}%")
                lines.append(f"📋 إجمالي الصفقات: {len(user_history)}")
                
                safe_send(chat_id, "\n".join(lines))
                return
            
            trades = get_active_trades()
            my_trades = [t for t in trades if t["symbol"] in user_symbols]
            
            if not my_trades:
                safe_send(chat_id, "📊 **محفظتك**\n\nلا توجد صفقات نشطة حالياً في قائمتك.\nكل الصفقات السابقة مغلقة — استخدم /report للاطلاع على التقرير اليومي.")
                return
            
            entry_prices = get_all_user_entry_prices(chat_id)
            total_pnl = 0
            lines = ["📊 **محفظتك الشخصية**", ""]
            
            for t in my_trades:
                sym = t["symbol"].replace("USDT", "")
                entry = entry_prices.get(t["symbol"], t["entry_price"])  # Use custom entry if available
                cp = t.get("current_price", entry)
                status = t.get("status", "active")
                pnl_pct = (cp - entry) / entry * 100
                total_pnl += pnl_pct
                
                emoji = "🟢" if pnl_pct > 0 else "🔴" if pnl_pct < 0 else "⚪"
                status_icon = "⏳" if status == "pending" else ""
                
                # Format price with proper decimals
                dec = 8 if entry < 0.01 else 6 if entry < 1 else 4
                entry_label = f"سعرك ${entry:.{dec}f}" if t["symbol"] in entry_prices else f"دخول ${entry:.{dec}f}"
                lines.append(f"{emoji} **{sym}** {status_icon} {pnl_pct:+.2f}% | {entry_label}")
            
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━")
            avg_pnl = total_pnl / len(my_trades) if my_trades else 0
            total_emoji = "🟢" if total_pnl > 0 else "🔴"
            lines.append(f"{total_emoji} **إجمالي:** {total_pnl:+.2f}% | متوسط: {avg_pnl:+.2f}%")
            lines.append(f"📋 عدد العملات: {len(my_trades)}")
            
            safe_send(chat_id, "\n".join(lines))
            return

        elif cmd == "/report":
            # تقرير اليوم الحالي — الصفقات الرابحة والخاسرة وصافي الربح
            try:
                from bot.tracker import generate_daily_report
                report = generate_daily_report()
                if report:
                    safe_send(chat_id, report)
                else:
                    safe_send(chat_id, "📊 **لا توجد صفقات مغلقة اليوم**")
            except Exception as e:
                logger.error(f"Report generation error: {e}")
                safe_send(chat_id, "⚠️ حدث خطأ أثناء إنشاء التقرير.")
            return

        # ═══════════════════════════════════
        # SLOT USER COMMANDS (needs slot, non-owner)
        # ═══════════════════════════════════

        elif cmd == "/stop":
            # Remove from subscribers
            with SUBS_LOCK:
                subs = _read_subs()
                if chat_id in subs:
                    subs.remove(chat_id)
                    try:
                        SUBS_FILE.write_text(json.dumps(subs))
                    except Exception as e:
                        logger.error(f"Failed to save subscribers: {e}")
            # Free slot + broadcast availability (built into remove_slot)
            freed = remove_slot(chat_id)
            if freed:
                logger.info(f"🪑 Slot freed by /stop: {chat_id}")
            safe_send(chat_id, "🔴 **تم إلغاء الاشتراك وتحرير مقعدك**\n\nللرجوع: /start")
            return

        elif cmd == "/help":
            role = get_role(chat_id)
            if role == "owner":
                safe_send(chat_id, HELP_MSG)
            elif role == "admin":
                safe_send(chat_id, ADMIN_HELP)
            elif role == "premium":
                safe_send(chat_id, PREMIUM_HELP)
            else:
                safe_send(chat_id, MEMBER_HELP)
            return
        
        elif cmd in ("/analysis", "/max"):
            # 🛡️ تحقق من الرتبة — فقط المميزين فما فوق
            if not is_premium(chat_id):
                safe_send(chat_id, "⭐ **هذه الميزة للمستخدمين المميزين فقط.**\n\nللاستفسار عن الترقية، تواصل مع المشرف.")
                return
            
            if len(args) < 2:
                usage = "/analysis BTC" if cmd == "/analysis" else "/max BTC"
                safe_send(chat_id, f"⚠️ **استخدم:** `{usage}`\nمثال: `{usage}`")
                return
            
            symbol = args[1]
            is_arabic = (cmd == "/analysis")
            
            # Rate limit for non-admin
            if not is_admin_role:
                rl = check_rate_limit(chat_id)
                if not rl["allowed"]:
                    safe_send(chat_id, f"❌ استنفذت طلباتك. حاول بعد {rl['reset_in']}.")
                    return
                consume_rate_limit(chat_id)
            
            # Send waiting message
            safe_send(chat_id, f"🔍 **جاري تحليل {symbol.upper()}...** ⏳")
            
            # Run in background thread
            from bot.trading import run_analyze
            threading.Thread(
                target=run_analyze,
                args=(chat_id, symbol),
                kwargs=({"full": (not is_arabic), "arabic": is_arabic}),
                daemon=True
            ).start()
            
            # Warning for rate limit
            if not is_admin_role:
                rl = check_rate_limit(chat_id)
                if rl["warning"]:
                    safe_send(chat_id, rl["warning"])
            return

        # ═══════════════════════════════════
        # ADMIN-ONLY COMMANDS (المالك والمشرفين فقط)
        # ═══════════════════════════════════

        if not is_admin_role:
            return

        if cmd == "/allow":
            if len(args) < 2:
                safe_send(chat_id, "⚠️ **استخدم:** `/allow NUMBER`\nمثال: `/allow 5`")
                return
            try:
                num = int(args[1])
                result = set_max_slots(num)
                safe_send(chat_id, result)
            except ValueError:
                safe_send(chat_id, "⚠️ **استخدم:** `/allow NUMBER`")
            return

        if cmd == "/broadcast":
            # إرسال رسالة جماعية لكل المشتركين — مع إيموجي Premium متحرك
            if len(args) < 2:
                safe_send(chat_id, "⚠️ **استخدم:** `/broadcast نص الرسالة`\n\nتقدر ترسل رسالة متعددة الأسطر مع ايموجيز متحركة 🎉")
                return
            msg_text = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
            if not msg_text.strip():
                safe_send(chat_id, "⚠️ نص الرسالة فارغ.")
                return
            subs = load_subscribers()
            success = 0
            for uid in subs:
                if send_msg_premium(uid, msg_text):
                    success += 1
            safe_send(chat_id, f"✅ **تم الإرسال:** {success}/{len(subs)} مشترك")
            return

        elif cmd in ("/test", "/test_broadcast"):
            # إرسال اختباري — نفس نظام البث لكن للمالك فقط + إيموجي Premium
            if len(args) < 2:
                safe_send(chat_id, "⚠️ **استخدم:** `/test نص الرسالة`\n\nنفس نظام البث لكن لك فقط للاختبار.")
                return
            msg_text = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
            if not msg_text.strip():
                safe_send(chat_id, "⚠️ نص الرسالة فارغ.")
                return
            mid = send_msg_premium(chat_id, msg_text)
            if mid:
                safe_send(chat_id, f"✅ **تم الإرسال لك فقط** (msg_id={mid})")
            else:
                safe_send(chat_id, "❌ **فشل الإرسال**")
            return

        elif cmd == "/adduser":
            if len(args) < 2:
                safe_send(chat_id, "⚠️ **استخدم:** `/adduser UID`\nمثال: `/adduser 123456789`")
                return
            try:
                uid = int(args[1])
                # تعيين رتبة مميز + مقعد
                add_uid_to_slots(uid)
                add_subscriber(uid, "", "")
                result = set_role(uid, "premium")
                # 🆕 حدث أوامر المستخدم الجديد
                set_user_commands(uid, "premium")
                safe_send(chat_id, result)
                # إشعار المستخدم
                try:
                    safe_send(uid, "🎉 **تم ترقيتك إلى مستخدم مميز!** ⭐\n\n📊 الآن يمكنك استخدام:\n/analysis BTC — تحليل عربي\n/max BTC — تقرير متقدم\n\nاستخدم /help لعرض جميع الأوامر.")
                except Exception:
                    logger.debug("Failed to notify user of upgrade（user may have blocked bot）")
            except ValueError:
                safe_send(chat_id, "⚠️ **استخدم:** `/adduser UID`")
            return

        elif cmd == "/admin":
            if len(args) < 2:
                safe_send(chat_id, "⚠️ **استخدم:** `/admin UID`\nمثال: `/admin 123456789`")
                return
            try:
                uid = int(args[1])
                result = add_admin(uid)
                set_role(uid, "admin")
                # 🆕 حدث أوامر المشرف الجديد
                set_user_commands(uid, "admin")
                safe_send(chat_id, result)
            except ValueError:
                safe_send(chat_id, "⚠️ **استخدم:** `/admin UID`")
            return

        elif cmd == "/request":
            if len(args) < 3:
                safe_send(chat_id, "⚠️ **استخدم:** `/request 4h 5`\nمثال: `/request 4h 5` (5 طلبات كل 4 ساعات)")
                return
            window_str = args[1]
            try:
                count = int(args[2])
                result = set_rate_limit(window_str, count)
                safe_send(chat_id, result)
            except ValueError:
                safe_send(chat_id, "⚠️ **استخدم:** `/request 4h 5`")
            return

        elif cmd == "/status":
            slots = get_slots_status()
            rate = read_rate_config()
            win_min = rate.get('window_seconds', 3600) // 60
            from data.fetcher import get_fetcher_status
            exchange_status = get_fetcher_status()
            info = (
                f"{slots}\n"
                f"📊 **الحد:** {rate.get('max_per_window', '?')} طلب / {win_min} دقيقة\n"
                f"🪪 **المعرف:** `{OWNER_ID}`\n\n"
                f"{exchange_status}"
            )
            safe_send(chat_id, info)
            return

        elif cmd == "/exchanges":
            from data.fetcher import get_fetcher_status
            safe_send(chat_id, get_fetcher_status())
            return

        elif cmd == "/scan":
            safe_send(chat_id, "🔍 **Scanning market...** ⏳")
            from bot.trading import run_scan
            threading.Thread(target=run_scan, args=(chat_id,), daemon=True).start()
            return

        elif cmd == "/sectors":
            safe_send(chat_id, "📊 **Analyzing sectors...** ⏳")
            from bot.trading import run_sectors
            threading.Thread(target=run_sectors, args=(chat_id,), daemon=True).start()
            return

        elif cmd in ("/matrix", "/top", "/rank"):
            safe_send(chat_id, "🔬 **Scanning strength matrix (30 coins × 3 TFs)...** (30-60s) ⏳")
            from bot.trading import run_matrix
            threading.Thread(target=run_matrix, args=(chat_id,), daemon=True).start()
            return

        elif cmd == "/analyze":
            if len(args) < 2:
                safe_send(chat_id, "⚠️ **استخدم:** `/analyze BTC`")
                return
            symbol = args[1]
            safe_send(chat_id, f"🔍 **Analyzing {symbol.upper()} across 3 TFs...** ⏳")
            from bot.trading import run_analyze
            threading.Thread(target=run_analyze, args=(chat_id, symbol), kwargs={"full": True}, daemon=True).start()
            return

        # ─── Unknown command ───
        # Only owner sees unknown command errors
        safe_send(chat_id, f"⚠️ **أمر غير معروف:** `{cmd}`\nاستخدم /help لعرض الأوامر المتاحة.")

    except Exception as e:
        logger.error(f"Command handler error: {e}", exc_info=True)


# ═══════════════════════════════════════
# 🔄 Telegram Polling Loop
# ═══════════════════════════════════════

def _load_polling_offset() -> int:
    """Load last processed update_id to avoid re-processing."""
    try:
        if POLLING_OFFSET_FILE.exists():
            return json.loads(POLLING_OFFSET_FILE.read_text()).get("offset", 0)
    except Exception:
        logger.debug("Failed to load polling offset, starting from 0")
    return 0


def _save_polling_offset(offset: int):
    """Save last processed update_id."""
    try:
        POLLING_OFFSET_FILE.write_text(json.dumps({"offset": offset}))
    except Exception as e:
        logger.debug(f"Failed to save polling offset: {e}")


_polling_started = False

def start_polling():
    """Start Telegram update polling in a daemon thread."""
    global _polling_started
    if _polling_started:
        logger.warning("⚠️ Polling already started — ignoring duplicate call")
        return
    _polling_started = True
    logger.info("📡 Starting Telegram polling...")
    
    def _poll():
        offset = _load_polling_offset()
        failures = 0
        time.sleep(1)  # ⏳ Short delay to let old Telegram sessions expire
        
        while True:
            try:
                url = f"{API_BASE}/getUpdates?timeout=15&offset={offset + 1}"
                resp = requests.get(url, timeout=20)
                data = resp.json()
                
                if not data.get("ok"):
                    error_code = data.get("error_code", 0)
                    logger.warning(f"getUpdates failed: {data}")
                    failures += 1
                    # 409 = conflict — reset offset + wait for session to die
                    if error_code == 409:
                        offset = _load_polling_offset()  # fresh load
                        _save_polling_offset(max(0, offset - 100))  # big rewind
                        failures = 0
                        logger.info(f"🔄 409 conflict — reset session, sleeping 5s...")
                        time.sleep(5)
                        continue
                    elif error_code == 429:
                        retry_after = (data.get("parameters") or {}).get("retry_after", 10)
                        logger.warning(f"⏳ 429 Rate limited — waiting {retry_after}s...")
                        time.sleep(retry_after)
                        continue
                
                failures = 0
                for update in data.get("result", []):
                    uid = update.get("update_id", 0)
                    if uid > offset:
                        offset = uid
                        # 💾 Save offset every update (critical for avoiding reprocessing)
                        if offset % 5 == 0:
                            _save_polling_offset(offset)
                        threading.Thread(
                            target=handle_update,
                            args=(update,),
                            daemon=True
                        ).start()
                
                # 💾 Always save the last offset after processing a batch
                if data.get("result"):
                    _save_polling_offset(offset)

            except requests.exceptions.Timeout:
                continue  # Normal long-poll timeout
            except Exception as e:
                logger.error(f"Polling error: {e}", exc_info=True)
                failures += 1
                time.sleep(min(failures * 5, 60))
    
    threading.Thread(target=_poll, daemon=True, name="telegram-polling").start()
    logger.info("✅ Telegram polling thread started")
