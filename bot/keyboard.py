"""
⌨️ CryptoSignal Keyboard Builder — أزرار تفاعلية للصفقات
v2: pagination (10 per page) + add/remove buttons
"""
import time
import logging

logger = logging.getLogger("crypto-signal-keyboard")

PER_PAGE = 10  # 10 أزرار كحد أقصى (5 صفوف × 2)


def _format_duration(added_at: float) -> str:
    """تنسيق المدة بالعربية"""
    seconds = time.time() - added_at
    if seconds < 3600:
        mins = int(seconds / 60)
        return f"{mins} دقيقة" if mins > 0 else "أقل من دقيقة"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        mins = int((seconds % 3600) / 60)
        if mins > 0:
            return f"{hours} ساعة و {mins} دقيقة"
        return f"{hours} ساعة"
    else:
        days = int(seconds / 86400)
        hours = int((seconds % 86400) / 60)
        if hours > 0:
            return f"{days} يوم و {hours} ساعة"
        return f"{days} يوم"


def build_list_keyboard(trades: list, page: int = 1, mode: str = "signals", filter_type: str = None) -> dict:
    """
    بناء أزرار التوصيات مع pagination.
    mode: "signals" | "list"
    filter_type: None (all) | "active" | "pending" — يغير callback pagination
    كل سطر عملتين: اسم + نسبتها.
    """
    total_pages = max(1, (len(trades) + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))
    
    start = (page - 1) * PER_PAGE
    end = start + PER_PAGE
    page_trades = trades[start:end]
    
    keyboard = []
    row = []

    for t in page_trades:
        sym = t["symbol"].replace("USDT", "")
        entry = t.get("entry_price") or 0
        cp = t.get("current_price") or entry
        status = t.get("status", "active")

        if status == "pending":
            label = f"  ⏳ {sym}  "
        else:
            if entry == 0:
                pnl_pct = 0.0
            else:
                pnl_pct = (cp - entry) / entry * 100
            emoji = "🟢" if pnl_pct > 0 else "🔴"
            spacer = "   " if len(sym) <= 3 else "  " if len(sym) <= 5 else " "
            label = f"{spacer}{emoji} {sym} {pnl_pct:+.1f}%{spacer}"

        row.append({
            "text": label,
            "callback_data": f"trade_{t['symbol']}"
        })

        if len(row) == 2:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    # ─── Navigation row ───
    if total_pages > 1:
        nav_row = []
        # prefix يعتمد على filter_type و mode
        if filter_type == "active":
            prefix = "signals_active"
        elif filter_type == "pending":
            prefix = "signals_pending"
        else:
            prefix = "signals" if mode == "signals" else "mylist"
        
        if page > 1:
            nav_row.append({
                "text": "« السابق",
                "callback_data": f"{prefix}_page_{page-1}"
            })
        
        if page < total_pages:
            nav_row.append({
                "text": "التالي »",
                "callback_data": f"{prefix}_page_{page+1}"
            })
        
        if nav_row:
            keyboard.append(nav_row)

    return {
        "inline_keyboard": keyboard,
        "resize_keyboard": True
    }


def build_detail_keyboard(symbol: str, user_id: int = None, from_mode: str = "signals") -> dict:
    """
    بناء أزرار تفاصيل صفقة.
    from_mode: "signals" → زر ➕ إضافة | "list" → زر 🗑️ حذف
    
    إذا user_id محدد، نتحقق إذا العملة في قائمته.
    """
    buttons = []
    
    # تحليل الدعم
    buttons.append({"text": "📊 تحليل الدعم", "callback_data": f"analyze_{symbol}"})
    
    # زر إضافة/حذف حسب القائمة
    if user_id:
        try:
            from bot.user_lists import is_in_user_list
            in_list = is_in_user_list(user_id, symbol)
        except Exception as e:
            logger.debug(f"Keyboard user-list check skipped: {e}")
        
        if in_list:
            buttons.append({"text": "🗑️ حذف من قائمتي", "callback_data": f"remove_{symbol}"})
        else:
            buttons.append({"text": "➕ أضف إلى قائمتي", "callback_data": f"add_{symbol}"})
    else:
        # من signals — زر إضافة
        if from_mode == "signals":
            buttons.append({"text": "➕ أضف إلى قائمتي", "callback_data": f"add_{symbol}"})
        else:
            buttons.append({"text": "🗑️ حذف من قائمتي", "callback_data": f"remove_{symbol}"})
    
    return {
        "inline_keyboard": [
            buttons,
            [{"text": "🔄 الرجوع للقائمة", "callback_data": f"back_{from_mode}"}]
        ],
        "resize_keyboard": True
    }


def build_back_keyboard(from_mode: str = "signals") -> dict:
    """زر الرجوع فقط"""
    return {
        "inline_keyboard": [
            [{"text": "🔄 الرجوع للقائمة", "callback_data": f"back_{from_mode}"}]
        ],
        "resize_keyboard": True
    }


def format_trade_detail_text(trade: dict) -> str:
    """
    قالب عربي لتفاصيل التوصية — يفرق بين معلقة ونشطة
    """
    sym = trade["symbol"].replace("USDT", "")
    entry = trade.get("entry_price") or 0
    cp = trade.get("current_price") or entry
    status = trade.get("status", "active")
    dec = 8 if entry < 1 else 6 if entry < 100 else 4 if entry < 1000 else 2
    duration = _format_duration(trade.get("added_at", time.time()))

    lines = [
        f"━━━ 📊 **{sym}** ━━━",
        "",
        f"〽️ **العملة:** {sym}",
    ]

    if status == "pending":
        # ⏳ معلقة — لم تنفذ بعد
        limit_price = trade.get("limit_price", entry)
        cancel = trade.get("cancel_level")
        lines += [
            f"⏳ **الحالة:** معلقة — بانتظار التنفيذ",
            f"   السعر الحالي: ${cp:.{dec}f}",
            f"   ينتظر النزول إلى: ${limit_price:.{dec}f}",
            "",
            f"📥 **أمر الدخول:** ${limit_price:.{dec}f}",
            f"🛑 **الوقف:** ${trade['stop_loss']:.{dec}f}",
        ]
        if cancel:
            lines.append(f"🚫 **يلغى إذا تجاوز:** ${cancel:.{dec}f}")
    else:
        # نشطة
        if entry == 0:
            pnl_pct = 0.0
        else:
            pnl_pct = (cp - entry) / entry * 100
        pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"
        lines += [
            f"{pnl_emoji} **الحالة:** {'🟢 ربح' if pnl_pct > 0 else '🔴 خسارة'} ({pnl_pct:+.2f}%)",
            "",
            f"📥 **الدخول:** ${entry:.{dec}f}",
            f"📊 **الحالي:** ${cp:.{dec}f}",
        ]

    lines += [
        f"⏱️ **مده التوصيه:** {duration}",
        "",
    ]

    if trade.get("targets"):
        lines.append("🎯 **الأهداف:**")
        for i, t in enumerate(trade["targets"]):
            if entry == 0:
                gain = 0.0
            else:
                gain = (t - entry) / entry * 100
            hit = "✅" if i in trade.get("tp_hit", []) else ""
            lines.append(f"   T{i+1}: ${t:.{dec}f} ({gain:+.2f}%) {hit}")
        lines.append("")

    if status != "pending":
        sl = trade.get("stop_loss", 0) or 0
        if entry == 0 or sl == 0:
            sl_pct = 0.0
        else:
            sl_pct = (sl - entry) / entry * 100
        lines.append(f"🛑 **الوقف:** ${sl:.{dec}f} ({sl_pct:.2f}%)")
        lines.append("")
        lines.append(f"✅ **نسبة النجاح:** {trade.get('confidence', 0):.0f}%")
        lines.append(f"💪 **القوة:** {trade.get('strength', 0):.0f}%")

    lines.append(f"📅 **تاريخ التوصيه:** {trade.get('added_date', '')}")

    return "\n".join(lines)


def analyze_support_levels(symbol: str) -> str:
    """
    تحليل مستويات الدعم للصفقة الخاسرة
    مع تحليل AI عميق من DeepSeek
    """
    sym = symbol.replace("USDT", "")
    sym_safe = sym

    try:
        import sys
        from pathlib import Path
        project_root = Path("/root/projects/crypto-signal")
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from data.fetcher import fetch_klines
        import numpy as np
        from report.telegram import escape_md
        sym_safe = escape_md(sym)

        df = fetch_klines(symbol, "4h", 200)
        if df is None or len(df) < 20:
            return f"⚠️ بيانات غير كافية لتحليل {sym}"

        price = df["close"].iloc[-1]
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values

        supports = []
        window = 10
        for i in range(window, len(lows) - window):
            if all(lows[i] <= lows[i - j] and lows[i] <= lows[i + j] for j in range(1, window + 1)):
                supports.append(lows[i])

        resistances = []
        for i in range(window, len(highs) - window):
            if all(highs[i] >= highs[i - j] and highs[i] >= highs[i + j] for j in range(1, window + 1)):
                resistances.append(highs[i])

        supports_below = sorted([s for s in supports if s < price], reverse=True)[:3]
        resistances_above = sorted([r for r in resistances if r > price])[:3]

        dec = 8 if price < 1 else 6 if price < 100 else 4 if price < 1000 else 2

        ma20 = np.mean(closes[-20:]) if len(closes) >= 20 else price
        ma50 = np.mean(closes[-50:]) if len(closes) >= 50 else price
        ma200 = np.mean(closes[-200:]) if len(closes) >= 200 else price

        msg = [f"━━━ 📊 **{sym_safe} تحليل** ━━━"]
        msg.append(f"💰 **السعر الحالي:** `${price:.{dec}f}`")
        msg.append("")

        msg.append("**🟢 مناطق الدعم:**")
        if supports_below:
            for i, s in enumerate(supports_below):
                dist = (s - price) / price * 100
                emoji = "🥇" if i == 0 else "🥈" if i == 1 else "🥉"
                msg.append(f"  {emoji} **{s:.{dec}f}** ({dist:+.2f}%)")
        else:
            recent_low = np.min(lows[-30:])
            dist = (recent_low - price) / price * 100
            msg.append(f"  📉 قاع 30 شمعة: {recent_low:.{dec}f} ({dist:+.2f}%)")
        msg.append("")

        msg.append("**🔴 المقاومة:**")
        if resistances_above:
            for i, r in enumerate(resistances_above[:3]):
                dist = (r - price) / price * 100
                msg.append(f"  {i+1}. **{r:.{dec}f}** ({dist:+.2f}%)")
        msg.append("")

        msg.append("**📊 المتوسطات:**")
        msg.append(f"  MA20: `${ma20:.{dec}f}`")
        msg.append(f"  MA50: `${ma50:.{dec}f}`")
        if len(closes) >= 200:
            msg.append(f"  MA200: `${ma200:.{dec}f}`")
        msg.append("")

        near_support = supports_below and abs(price - supports_below[0]) / price < 0.03
        near_ma20 = abs(price - ma20) / price < 0.02

        msg.append("**💡 التوصية:**")
        if near_support:
            msg.append("  🟢 السعر قرب الدعم — فرصة شراء محتملة")
        if near_ma20:
            msg.append("  📊 السعر قرب MA20 — ارتداد متوقع")
        if not near_support and not near_ma20:
            msg.append("  ⏳ الأفضل الانتظار — السعر في منطقة غير واضحة")

        if price < ma20 and price < ma50:
            msg.append("  ⚠️ السعر تحت المتوسطات — اتجاه هابط عام")

        msg.append("")
        msg.append("🤖 تحليل على فريم 4 ساعات")

        try:
            from engine.ai_analyst import call_ai
            ai_prompt = f"""تحليل سريع لـ {sym}:
السعر: ${price:.{dec}f}
الدعم: {', '.join([f'${s:.{dec}f}' for s in supports_below]) if supports_below else 'لا يوجد'}
المقاومة: {', '.join([f'${r:.{dec}f}' for r in resistances_above]) if resistances_above else 'لا يوجد'}
MA20: ${ma20:.{dec}f} | MA50: ${ma50:.{dec}f}

أعطي توصية مختصرة (30 كلمة): هل الوقت مناسب للشراء/البيع/الانتظار؟ هل الدعم قوي؟"""
            
            ai_resp = call_ai(
                "محلل عملات محترف — أجب بالعربية باختصار (30 كلمة كحد أقصى).",
                ai_prompt,
                max_tokens=150
            )
            if ai_resp:
                msg.append("")
                msg.append("━━━ 🧠 **تحليل AI** ━━━")
                msg.append(ai_resp[:200])
        except Exception as e:
            logger.debug(f"AI support analysis failed: {e}")

        return "\n".join(msg)

    except Exception as e:
        logger.error(f"Support analysis error for {symbol}: {e}")
        return f"⚠️ خطأ في تحليل {sym}: {str(e)[:80]}"
