"""
📱 Telegram Report — English, clean, simple format
"""
import re
import numpy as np


def fmt_price(p: float) -> str:
    """تنسيق السعر بطريقة مقروءة — للأسعار الصغيرة جداً يستخدم أسلوب مختصر"""
    if p <= 0:
        return "0"
    if p >= 1:
        d = 6 if p < 100 else 4 if p < 1000 else 2
        return f"{p:.{d}f}".rstrip('0').rstrip('.')
    
    # عدد الأصفار بعد الفاصلة
    import math
    s = f"{p:.12f}"
    frac = s.split('.')[1] if '.' in s else ''
    zeros = len(frac) - len(frac.lstrip('0'))
    
    if zeros >= 6:
        # أسلوب مختصر: 0.0₇4 (7 أصفار ثم 4)
        sig = frac[zeros:zeros+4].rstrip('0')  # 4 أرقام معنوية بدون أصفار زايدة
        if not sig:
            sig = '0'
        # Unicode subscript map
        sub_map = {ord(k): v for k, v in zip('0123456789', '₀₁₂₃₄₅₆₇₈₉')}
        sub = str(zeros).translate(sub_map)
        return f"0.0{sub}{sig}"
    else:
        d = zeros + 4
        d = min(d, 10)
        result = f"{p:.{d}f}"
        return result.rstrip('0').rstrip('.')


def escape_md(text: str) -> str:
    """Escape Telegram Markdown special characters in text.
    Prevents _ * [ ] ` from breaking formatting."""
    # Order matters: escape \ first, then individual chars
    for char in ['_', '*', '[', ']', '`']:
        text = text.replace(char, '\\' + char)
    return text


def estimate_duration(timeframe: str = "4h", atr_normalized: float = None, target_pct: float = None) -> str:
    """
    تقدير المدة بالاعتماد على ATR + مسافة الهدف.
    النتيجة: رقم محدد مثل "ساعتين" أو "4 ساعات"
    """
    candle_hours = {"15m": 0.25, "1h": 1, "4h": 4, "1d": 24, "1w": 168}.get(timeframe, 4)

    if atr_normalized is not None and atr_normalized > 0 and target_pct is not None and target_pct > 0:
        # مدة واقعية = مسافة الهدف / ATR لكل شمعة * ساعات الشمعة
        hours = (target_pct / atr_normalized) * candle_hours
        hours = max(2, min(round(hours), 168))  # حد أدنى 2 ساعة، حد أقصى أسبوع
    elif atr_normalized is not None:
        # ATR only — without target distance: ATR-based estimate
        if atr_normalized > 5:   hours = 2
        elif atr_normalized > 3:   hours = 4
        elif atr_normalized > 1.5: hours = 8
        elif atr_normalized > 0.5: hours = 16
        else: hours = 24
    else:
        # ثابت حسب الفريم لو ما في ATR
        tf_map = {"15m": 1, "1h": 4, "4h": 12, "1d": 48, "1w": 168}
        hours = tf_map.get(timeframe, 12)

    # تحويل الأرقام إلى نص عربي
    hour_str = {
        1: "ساعة", 2: "ساعتين", 3: "3 ساعات", 4: "4 ساعات",
        6: "6 ساعات", 8: "8 ساعات", 12: "12 ساعة", 16: "16 ساعة",
        24: "24 ساعة", 48: "يومين", 168: "أسبوع",
    }.get(hours, f"{hours} ساعة")

    return hour_str


def format_signal_report(result, mtf_data: dict = None, ai_result: dict = None) -> str:
    """
    Full English report — detailed school analysis, used by /analyze and /max
    Now with AI-powered analysis section
    """
    return _format_signal_report_full(result, mtf_data, ai_result)


def _format_signal_report_full(result, mtf_data: dict = None, ai_result: dict = None) -> str:
    """
    Full English report — key info first, school analysis after
    Now with 🧠 AI Deep Analysis section
    """
    a = result.aggregated
    symbol = result.symbol.replace("USDT", "")
    symbol_safe = escape_md(symbol)  # 🔧 Prevent Markdown breakage
    price = result.price
    sr = getattr(result, "sr", {"supports": [], "resistances": [], "ma20": price, "ma50": price, "ma200": price})

    price_str = f"${fmt_price(price)}"

    is_buy = a["direction"] == "BUY"
    dir_emoji = "🟢 BUY" if is_buy else ("🔴 SELL" if a["direction"] == "SELL" else "⚪ NEUTRAL")
    confidence = a.get("confidence", 0)

    # ─── MTF Alignment ───
    mtf_line = ""
    alignment = 0
    total_tfs = 3
    if mtf_data:
        from engine.multi_analyzer import build_mtf_alignment_line
        mtf_line = build_mtf_alignment_line(mtf_data)
        alignment = mtf_data.get("alignment", 0)
        total_tfs = mtf_data.get("total", 3)

    msg = []

    # ═══ HEADER ═══
    msg.append(f"━━━ 📊 **{symbol_safe}** ━━━")
    msg.append(f"**{dir_emoji}** • *${fmt_price(price)}*")
    msg.append("")

    # ═══ CORE (entry, targets, stop) ═══
    msg.append(f"📥 **Entry:** ${fmt_price(a['entry'])}" if a["entry"] else "")
    if a["targets"]:
        t_parts = []
        for i, t in enumerate(a["targets"][:3]):
            if a["direction"] == "BUY":
                gain = (t - a["entry"]) / a["entry"] * 100 if a["entry"] else 0
            elif a["direction"] == "SELL":
                gain = (a["entry"] - t) / a["entry"] * 100 if a["entry"] else 0
            else:
                gain = (t - a["entry"]) / a["entry"] * 100 if a["entry"] else 0
            t_parts.append(f"T{i+1} ${fmt_price(t)} ({gain:+.1f}%)")
        msg.append(f"🎯 **Targets:** {' | '.join(t_parts)}")
    if a["stop_loss"]:
        entry_for_sl = a["entry"] if a["entry"] else price
        loss = (a["stop_loss"] - entry_for_sl) / entry_for_sl * 100 * (-1 if is_buy else 1)
        msg.append(f"🛑 **Stop:** ${fmt_price(a['stop_loss'])} ({abs(loss):.1f}% loss)")
    
    # Alignment line
    if mtf_line:
        msg.append("")
        msg.append(f"⚡ **Alignment:** {mtf_line}")
    else:
        msg.append(f"⚡ **Confidence:** {confidence:.0f}%")
    
    msg.append(f"💪 **Strength:** {a['strength']:.0f}% | ✅ {a['buy_count']} buy / 🔻 {a['sell_count']} sell / ⚪ {15 - a['buy_count'] - a['sell_count']} neutral")
    msg.append(f"📌 **TF:** {result.timeframe}")
    msg.append("")

    # ═══ SCHOOL ANALYSIS ═══
    msg.append("━━━ **Indicators** ━━━")

    all_signals = getattr(result, "signals", [])
    if all_signals:
        for s in all_signals:
            emoji = "🟢" if s.signal == "BUY" else ("🔴" if s.signal == "SELL" else "⚪")
            if s.signal != "NEUTRAL":
                msg.append(f"{emoji} **{s.name}** — {s.signal}")

    msg.append("")

    # ═══ DURATION ═══
    atr_val = None
    for s in all_signals:
        if hasattr(s, 'name') and 'ATR' in s.name:
            try:
                import re
                m = re.search(r'ATR=([\d.]+)%', s.reason)
                if m:
                    atr_val = float(m.group(1))
            except Exception as e:
                logger.debug(f"ATR parse failed: {e}")
                pass
            break

    if atr_val is not None:
        if atr_val > 5: duration = "~2h"
        elif atr_val > 3: duration = "~4h"
        elif atr_val > 1.5: duration = "~8h"
        elif atr_val > 0.5: duration = "~16h"
        else: duration = "~24h"
    else:
        duration = "~4-24h"
    msg.append(f"⏱ **Duration:** {duration}")

    # ═══ S/R ═══
    supports = sr.get("supports", [])
    resistances = sr.get("resistances", [])
    if supports or resistances:
        msg.append("")
        msg.append("━━━ **Levels** ━━━")
        if supports:
            s_parts = [f"🥇 ${fmt_price(s)}" for s in supports[:2]]
            msg.append(f"🟢 Support: {' | '.join(s_parts)}")
        if resistances:
            r_parts = [f"🥇 ${fmt_price(r)}" for r in resistances[:2]]
            msg.append(f"🔴 Resistance: {' | '.join(r_parts)}")

    # ═══ MOVING AVGS ═══
    ma20 = sr.get("ma20", price)
    ma50 = sr.get("ma50", price)
    ma200 = sr.get("ma200", price)
    ma20_emoji = "🟢" if price >= ma20 else "🔴"
    ma50_emoji = "🟢" if price >= ma50 else "🔴"
    ma200_emoji = "🟢" if price >= ma200 else "🔴"
    msg.append(f"📊 MA20 {ma20_emoji} ${fmt_price(ma20)} | MA50 {ma50_emoji} ${fmt_price(ma50)} | MA200 {ma200_emoji} ${fmt_price(ma200)}")

    # ═══ RISK ═══
    msg.append("")
    msg.append("━━━ **Risk** ━━━")
    msg.append("⚠️ Never risk >2% of your portfolio")
    msg.append("📊 Take partial profits at each target")
    msg.append("💡 Stick to your stop loss")

    # ═══ 🧠 AI DEEP ANALYSIS ═══
    if ai_result and ai_result.get("decision"):
        msg.append("")
        msg.append("━━━ 🧠 **AI Deep Analysis** ━━━")
        ai_decision = ai_result.get("decision", "?")
        ai_direction = ai_result.get("direction", "?")
        ai_conf = ai_result.get("confidence", 0)
        ai_risk = ai_result.get("risk_level", "?")
        ai_schools = ai_result.get("schools_agreeing", 0)
        ai_key = ai_result.get("key_signal", "")
        ai_reason_text = ai_result.get("reason", "")
        
        decision_emoji = "🟢" if ai_decision == "ENTER" else ("🔴" if ai_decision == "SKIP" else "⚪")
        msg.append(f"{decision_emoji} **Decision:** {ai_decision} ({ai_direction})")
        msg.append(f"⭐ **Confidence:** {ai_conf}%  |  ⚠️ **Risk:** {ai_risk}")
        msg.append(f"🏫 **Schools:** {ai_schools}/6 agree")
        if ai_key:
            msg.append(f"🔑 **Key Signal:** {ai_key}")
        if ai_reason_text:
            reason_short = ai_reason_text[:180]
            msg.append(f"💬 **AI Reasoning:** {reason_short}")
        
        # AI-provided levels
        ai_entry = ai_result.get("entry")
        ai_sl = ai_result.get("stop_loss")
        ai_targets = ai_result.get("targets", [])
        if ai_entry or ai_sl or ai_targets:
            msg.append("")
            msg.append("🎯 **AI Smart Levels:**")
            if ai_entry:
                msg.append(f"  📥 Entry: ${fmt_price(ai_entry)}")
            if ai_sl:
                sl_dist = abs(ai_sl - ai_entry) / ai_entry * 100 if ai_entry else 0
                msg.append(f"  🛑 Stop: ${fmt_price(ai_sl)} (-{sl_dist:.1f}%)")
            if ai_targets:
                t_parts = []
                for i, t in enumerate(ai_targets[:3]):
                    gain = (t - ai_entry) / ai_entry * 100 if ai_entry else 0
                    t_parts.append(f"T{i+1} ${fmt_price(t)} ({gain:+.1f}%)")
                msg.append(f"  🎯 Targets: {' | '.join(t_parts)}")

    msg.append("")
    msg.append(f"⏱️ {result.timeframe} | 🤖 CryptoSignal Bot")

    return "\n".join(msg)


def format_scan_summary(candidates, timeframes: list = None) -> str:
    """Market scan summary — English"""
    if timeframes is None:
        timeframes = ["4h"]
    tf = timeframes[0]

    if not candidates:
        return f"🔍 **Market Scan** ({tf})\n\nNo clear buy opportunities right now. Market is quiet ⚪"

    buy_candidates = [c for c in candidates if c.aggregated["direction"] == "BUY"]
    if not buy_candidates:
        return f"🔍 **Market Scan** ({tf})\n\nNo suitable buy opportunities. Wait for liquidity to enter."

    msg = [f"🔍 **Market Scan** — {tf}", f"Found **{len(buy_candidates)}** buy opportunities", ""]

    for i, c in enumerate(buy_candidates[:5]):
        a = c.aggregated
        sym = c.symbol.replace("USDT", "")
        entry_s = f"${fmt_price(a['entry'])}"
        t1_s = f"${fmt_price(a['targets'][0])}" if a['targets'] else "—"
        sl_s = f"${fmt_price(a['stop_loss'])}" if a['stop_loss'] else "—"
        msg.append(
            f"{i+1}. 🟢 **{sym}** — {a['confidence']:.0f}% | 💪 {a['strength']:.0f}%"
        )
        msg.append(f"   📥 {entry_s} 🎯 T1 {t1_s} 🛑 {sl_s}")

    msg.append("")
    msg.append("🤘 For detailed analysis: `/analyze COIN`")

    return "\n".join(msg)


# ═══════════════════════════════════
# 🇸🇦 Arabic Simple — for /analysis command (beginners)
# ═══════════════════════════════════
def format_signal_report_arabic_simple(result, mtf_data: dict = None, is_signal: bool = False,
                                        regime_str: str = "", kronos_score: float = 0,
                                        layer_agreement: str = "", buy_strategies: list = None,
                                        ai_result: dict = None, label: str = "توصية") -> str:
    """
    قالب عربي مختصر — AI-driven
    label: "توصية" للتوصيات، "تحليل" للتحليل اليدوي
    """
    a = result.aggregated
    symbol = result.symbol.replace("USDT", "")
    symbol_safe = escape_md(symbol)
    price = result.price

    # ─── Entry ───
    if ai_result and ai_result.get("entry") and ai_result.get("confidence", 0) > 40:
        entry_price = ai_result["entry"]
    else:
        entry_price = a["entry"] if a["entry"] else price

    # ─── Stop Loss ───
    if ai_result and ai_result.get("stop_loss") and ai_result.get("confidence", 0) > 40:
        stop_price = ai_result["stop_loss"]
    else:
        stop_price = a["stop_loss"] if a["stop_loss"] else price * 0.95
    if stop_price >= entry_price:
        stop_price = entry_price * 0.98

    sl_loss = abs(entry_price - stop_price) / entry_price * 100

    # ─── Targets ───
    # ✅ ATR-based targets are now blended upstream (smart_targets.py)
    # No hardcoded fallback percentages — use what's provided
    if ai_result and ai_result.get("targets") and len(ai_result["targets"]) >= 2 and ai_result.get("confidence", 0) > 40:
        targets = [t for t in ai_result["targets"][:3] if t > entry_price]
        if len(targets) < 2:
            targets = [t for t in (a["targets"] or []) if t > entry_price]
    else:
        targets = [t for t in (a["targets"] or []) if t > entry_price]
    
    if not targets:
        targets = [entry_price * 1.01]  # minimal fallback (1%), ATR will handle upstream

    gains = [(t - entry_price) / entry_price * 100 for t in targets]

    # ─── Entry label ───
    entry_type = a.get("smart_entry_type", "now")
    entry_diff_pct = abs(entry_price - price) / price * 100 if price > 0 else 0
    if entry_type == "limit" or entry_diff_pct > 0.3:
        entry_label = f"أمر معلق @ ${fmt_price(entry_price)}"
        if a.get("cancel_level"):
            entry_label += f" (يلغى > ${fmt_price(a['cancel_level'])})"
    else:
        entry_label = "فوري الان"

    # ─── Risk ───
    if sl_loss <= 1.0: risk_level = "🟢 منخفضة"
    elif sl_loss <= 2.0: risk_level = "🟡 متوسطة"
    elif sl_loss <= 4.0: risk_level = "🟠 مرتفعة"
    else: risk_level = "🔴 عالية جداً"

    # ─── Duration ───
    if ai_result and ai_result.get("duration_hours"):
        hours = ai_result["duration_hours"]
        hour_str = {
            1: "ساعة", 2: "ساعتين", 3: "3 ساعات", 4: "4 ساعات",
            6: "6 ساعات", 8: "8 ساعات", 12: "12 ساعة", 16: "16 ساعة",
            24: "24 ساعة", 48: "يومين", 72: "3 أيام", 168: "أسبوع",
        }.get(hours, f"{hours} ساعة")
        duration = hour_str
    else:
        duration = "~4-24 ساعة"

    # ─── Confidence/Strength ───
    if ai_result and ai_result.get("reason"):
        ai_conf = ai_result.get("confidence", a.get("confidence", 50))
        display_conf = max(a.get("confidence", 0), ai_conf)
        display_strength = max(a.get("strength", 0), ai_conf * 0.85)
    else:
        display_conf = a.get("confidence", 50)
        display_strength = a.get("strength", 0)

    success_rate = min(a['confidence'] * 0.85 + kronos_score * 0.15, 95)

    # ─── BUILD ───
    msg = []
    msg.append(f"━━━ 📋 {label} ━━━")
    msg.append("")
    msg.append(f"〽️ العملة: **{symbol_safe}**")
    msg.append(f"✨ السعر الحالي: ${fmt_price(price)}")
    msg.append("")
    msg.append("━━━ 📋 تفاصيل ━━━")
    msg.append("")
    msg.append(f"✅ الدخول : {entry_label}")
    msg.append(f"⚠️ الوقف : ${fmt_price(stop_price)} (-{sl_loss:.1f}%)")
    msg.append("")
    msg.append("🎯 الاهداف:")
    msg.append("")
    t_labels = ["🥇 الاول", "🥈 الثاني", "🥉 الثالث"]
    for i, (t, g) in enumerate(zip(targets[:3], gains[:3])):
        msg.append(f"{t_labels[i]}: ${fmt_price(t)} ({g:+.1f}%)")
    msg.append("")
    msg.append("━━━ 📋 توقعات ━━━")
    msg.append("")
    msg.append(f"✅ نسبة النجاح: {success_rate:.0f}%")
    msg.append(f"🌟 الثقه: {display_conf:.0f}%")
    msg.append(f"💪 القوة: {display_strength:.0f}%")
    msg.append(f"⏱ المدة المتوقعة: {duration}")
    msg.append(f"⚖️ المخاطرة: {risk_level}")

    return "\n".join(msg)
