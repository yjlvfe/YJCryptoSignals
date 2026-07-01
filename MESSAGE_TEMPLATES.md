# 📋 قوالب رسائل CryptoSignal Bot — دليل الترجمة

> جميع القوالب الحالية بالعربية. للترجمة إلى الإنجليزية، استبدل النص العربي مع الاحتفاظ بالمتغيرات (f-string variables) والأيموجي.

## الملفات المصدر للقوالب:
- `bot/config.py` — رسائل الترحيب والمساعدة
- `bot/handlers.py` — معالجة الأوامر وإرسال الرسائل
- `bot/tracker.py` — تقارير الصفقات والتنبيهات
- `bot/trading.py` — تقارير التحليل
- `report/telegram.py` — تنسيق التقارير العربية/الإنجليزية
- `bot/keyboard.py` — تفاصيل التوصية
- `engine/self_learning_v2.py` — تقرير التعلم الذاتي

---

## ═══════════════════════════════════════
## 1. أوامر عامة (أي شخص)
## ═══════════════════════════════════════

### 1.1 /start — مشترك جديد بدون مقعد (غير مسموح له)

**الملف:** `bot/handlers.py:944`
```
🚫 **تم حظرك!**

استخدم /start أولاً للاشتراك.
```

### 1.2 /start — المالك (OWNER_ID)

**الملف:** `bot/config.py:177`
```
🚀 **CryptoSignal Bot — Master YJ**

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

🤖 Powered by CryptoSignal Engine v2
```

### 1.3 /start — مشترك عادي

**الملف:** `bot/config.py:203`
```
👋 **مرحباً بك في CryptoSignal Bot**

✅ تم تفعيل حسابك بنجاح!

📌 **الأوامر المتاحة لك:**
/analysis BTC — تحليل عربي مبسط
/max BTC — English full report
/list — قائمة التوصيات النشطة
/stop — إيقاف الإرسال
/start — إعادة التفعيل
/help — الأوامر

🔒 كل تحليل يستهلك طلب من رصيدك.
للاستفسار: تواصل مع المشرف.
```

### 1.4 /signals — لا توجد توصيات

**الملف:** `bot/handlers.py:982`
```
📡 **لا توجد توصيات نشطة حالياً**
```

### 1.5 /signals — قائمة الاختيار (مع أزرار)

**الملف:** `bot/handlers.py:987`
```
📡 **اختر نوع التوصيات**

✅ {active_count} نشطة | ⏳ {pending_count} معلقة

اختر النوع لعرض القائمة:
```
**الأزرار:**
- `🟢 نشطه ({active_count})` → callback: `signals_active`
- `⏳ معلقه ({pending_count})` → callback: `signals_pending`

### 1.6 /list — قائمة فارغة

**الملف:** `bot/handlers.py:1008`
```
📋 **قائمتك الشخصية**

لا توجد عملات مضافة.

استخدم /signals لعرض التوصيات ثم اضغط ➕ أضف إلى قائمتي.
```

### 1.7 /list — جميع العملات انتهت

**الملف:** `bot/handlers.py:1015`
```
📋 **قائمتك الشخصية**

العملات اللي ضفتها لم تعد نشطة (حققت هدف/ألغيت/ضربت وقف).
استخدم /signals للبحث عن فرص جديدة.
```

### 1.8 /list — مع توصيات (مع أزرار)

**الملف:** `bot/handlers.py:1020`
```
📋 **قائمتك الشخصية** ({len(my_trades)} عملة) — ص 1/{total_pages}
اختر عملة للتفاصيل:
```

### 1.9 /portfolio — فارغ

**الملف:** `bot/handlers.py:1033`
```
📊 **محفظتك**

لا توجد عملات مضافة.

استخدم /signals ثم ➕ أضف إلى قائمتي.
```

### 1.10 /portfolio — لا توجد صفقات نشطة

**الملف:** `bot/handlers.py:1040`
```
📊 **محفظتك**

لا توجد صفقات نشطة حالياً في قائمتك.
```

### 1.11 /portfolio — مع بيانات

**الملف:** `bot/handlers.py:1044-1068`
```
📊 **محفظتك الشخصية**

{emoji} **{sym}** {status_icon} {pnl:+.2f}% | دخول ${entry:.{dec}f}
...
━━━━━━━━━━━━━━━
{total_emoji} **إجمالي:** {total_pnl:+.2f}% | متوسط: {avg_pnl:+.2f}%
📋 عدد العملات: {len(my_trades)}
```

### 1.12 /report — لا توجد صفقات اليوم

**الملف:** `bot/handlers.py:1079`
```
📊 **لا تصفقات مغلقة اليوم**
```

### 1.13 /report — خطأ

**الملف:** `bot/handlers.py:1082`
```
⚠️ حدث خطأ أثناء إنشاء التقرير.
```

### 1.14 /report — التقرير اليومي

**الملف:** `bot/tracker.py:505-597`
```
📊 **التقرير اليومي**
📅 {report_date_str} (UTC+3)

🌊 السوق: {regime_emoji} {regime}
   فلتر: {entry_filter}
😱 الخوف والطمع: {fg_emoji} {val} ({label})
{ai_calibration_summary}

✅ ناجحة: {len(wins)} | ❌ خاسرة: {len(losses)}
🚫 ملغية: {len(cancelled)}
⏳ معلقة: {pending_count} | ✅ نشطة: {active_count}
📋 إجمالي: {len(recent)} | 🎯 نسبة النجاح: {win_rate}%

━━━━━━━━━━━━━━━

{pnl_emoji} **{sym}** ({nth}) » {label:+.2f}%
...

━━━━━━━━━━━━━━━

{total_emoji} **صافي » {total_pnl:+.2f}%**
```

### 1.15 /stop

**الملف:** `bot/handlers.py:1103`
```
🔴 **تم إلغاء الاشتراك وتحرير مقعدك**

للرجوع: /start
```

### 1.16 /help — للمالك

**الملف:** `bot/config.py:218`
```
📖 **CryptoSignal Bot — Owner Guide**

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
📊 Take partial profits at each target
```

### 1.17 /help — للمشترك العادي

**الملف:** `bot/config.py:250`
```
📖 **الأوامر المتاحة لك:**

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
💡 اضغط ➕ أضف إلى قائمتي على التوصية عشان توصلك تنبيهاتها
```

### 1.18 /analysis — خطأ في الاستخدام

**الملف:** `bot/handlers.py:1116`
```
⚠️ **استخدم:** `/analysis BTC`
مثال: `/analysis BTC`
```

### 1.19 /analysis — تجاوز الحد المسموح

**الملف:** `bot/handlers.py:1126`
```
❌ استنفذت طلباتك. حاول بعد {rl['reset_in']}.
```

### 1.20 /analysis — جاري التحليل

**الملف:** `bot/handlers.py:1131`
```
🔍 **جاري تحليل {symbol.upper()}...** ⏳
```

### 1.21 /analysis — تحذير الحد المسموح

**الملف:** `bot/handlers.py:1146`
```
⚠️ تبقت {remaining} طلبة فقط. يتجدد بعد {reset_sec // 60} دقيقة.
```

### 1.22 سبام /list

**الملف:** `bot/config.py:110`
```
🚫 **ليس لديك صلاحيات**

بإمكانك استعمال /list لعرض التوصيات
أو انتظار رسالة التوصية التي ترسل عبر البوت.
(السبب: إرسال متكرر — حاول بعد {remaining // 60} دقيقة)
```

**الملف:** `bot/config.py:124`
```
🚫 **ليس لديك صلاحيات**

بإمكانك استعمال /signals لعرض التوصيات
أو انتظار رسالة التوصية التي ترسل عبر البوت.
(السبب: إرسال متكرر جداً — حاول بعد 5 دقائق)
```

### 1.23 /analysis — تقرير عربي (مبسط)

**الملف:** `report/telegram.py:372-397`
```
━━━ 📋 {label} ━━━

〽️ العملة: **{symbol_safe}**
✨ السعر الحالي: ${fmt_price(price)}

━━━ 📋 تفاصيل ━━━

✅ الدخول : {entry_label}
⚠️ الوقف : ${fmt_price(stop_price)} (-{sl_loss:.1f}%)

🎯 الاهداف:

🥇 الاول: ${fmt_price(t1)} ({g1:+.1f}%)
🥈 الثاني: ${fmt_price(t2)} ({g2:+.1f}%)
🥉 الثالث: ${fmt_price(t3)} ({g3:+.1f}%)

━━━ 📋 توقعات ━━━

✅ نسبة النجاح: {success_rate:.0f}%
🌟 الثقه: {display_conf:.0f}%
💪 القوة: {display_strength:.0f}%
⏱ المدة المتوقعة: {duration}
⚖️ المخاطرة: {risk_level}
```
حيث `label` = "توصية" للتوصيات التلقائية، "تحليل" للتحليل اليدوي

### 1.24 /max or /analyze — تقرير إنجليزي كامل

**الملف:** `report/telegram.py:107-252`
```
━━━ 📊 **{symbol}** ━━━
**{dir_emoji} BUY/SELL** • *${price}*

📥 **Entry:** ${entry}
🎯 **Targets:** T1 ${t1} (+X.X%) | T2 ${t2} (+X.X%) | T3 ${t3} (+X.X%)
🛑 **Stop:** ${stop} (X.X% loss)

⚡ **Alignment:** {mtf_line}  أو  ⚡ **Confidence:** {conf}%
💪 **Strength:** {str}% | ✅ {buy} buy / 🔻 {sell} sell / ⚪ {neutral} neutral
📌 **TF:** {timeframe}

━━━ **Indicators** ━━━
🟢 **SMC** — BUY
🔴 **MACD** — SELL
...

⏱ **Duration:** ~{duration}

━━━ **Levels** ━━━
🟢 Support: 🥇 ${s1} | 🥈 ${s2}
🔴 Resistance: 🥇 ${r1} | 🥈 ${r2}
📊 MA20 🟢 ${ma20} | MA50 🔴 ${ma50} | MA200 🟢 ${ma200}

━━━ **Risk** ━━━
⚠️ Never risk >2% of your portfolio
📊 Take partial profits at each target
💡 Stick to your stop loss

━━━ 🧠 **AI Deep Analysis** ━━━
{decision_emoji} **Decision:** {decision} ({direction})
⭐ **Confidence:** {conf}%  |  ⚠️ **Risk:** {risk}
🏫 **Schools:** {agree}/6 agree
🔑 **Key Signal:** {key_signal}
💬 **AI Reasoning:** {reason}

🎯 **AI Smart Levels:**
  📥 Entry: ${entry}
  🛑 Stop: ${stop} (-X.X%)
  🎯 Targets: T1 ${t1} (+X.X%) | T2 ${t2} (+X.X%)

⏱️ {timeframe} | 🤖 CryptoSignal Bot
```

---

## ═══════════════════════════════════════
## 2. أوامر الإدارة (المالك والمشرفين فقط)
## ═══════════════════════════════════════

### 2.1 أمر غير معروف للمشترك

**الملف:** `bot/handlers.py:1292`
```
⚠️ **أمر غير معروف:** `{cmd}`
استخدم /help لعرض الأوامر المتاحة.
```

### 2.2 /allow — خطأ في الاستخدام

**الملف:** `bot/handlers.py:1158`
```
⚠️ **استخدم:** `/allow NUMBER`
مثال: `/allow 5`
```

### 2.3 /allow — تم التعديل

**الملف:** `bot/handlers.py:140`
```
✅ تم تعديل المساحة: {old} → {number}
```

### 2.4 /broadcast — خطأ في الاستخدام

**الملف:** `bot/handlers.py:1171`
```
⚠️ **استخدم:** `/broadcast نص الرسالة`

تقدر ترسل رسالة متعددة الأسطر مع ايموجيز متحركة 🎉
```

### 2.5 /broadcast — نص فارغ

**الملف:** `bot/handlers.py:1175`
```
⚠️ نص الرسالة فارغ.
```

### 2.6 /broadcast — نتيجة الإرسال

**الملف:** `bot/handlers.py:1182`
```
✅ **تم الإرسال:** {success}/{len(subs)} مشترك
```

### 2.7 /test — خطأ في الاستخدام

**الملف:** `bot/handlers.py:1188`
```
⚠️ **استخدم:** `/test نص الرسالة`

نفس نظام البث لكن لك فقط للاختبار.
```

### 2.8 /test — نص فارغ

**الملف:** `bot/handlers.py:1192`
```
⚠️ نص الرسالة فارغ.
```

### 2.9 /test — نجاح

**الملف:** `bot/handlers.py:1196`
```
✅ **تم الإرسال لك فقط** (msg_id={mid})
```

### 2.10 /test — فشل

**الملف:** `bot/handlers.py:1198`
```
❌ **فشل الإرسال**
```

### 2.11 /adduser — خطأ في الاستخدام

**الملف:** `bot/handlers.py:1203`
```
⚠️ **استخدم:** `/adduser UID`
مثال: `/adduser 123456789`
```

### 2.12 /adduser — نتائج

**الملف:** `bot/handlers.py:114-152`
```
⚠️ `{uid}` لديه مقعد بالفعل.
✅ تم إعطاء مقعد لـ `{uid}`.
```

### 2.13 /admin — خطأ في الاستخدام

**الملف:** `bot/handlers.py:1217`
```
⚠️ **استخدم:** `/admin UID`
مثال: `/admin 123456789`
```

### 2.14 /admin — نتائج

**الملف:** `bot/handlers.py:35-38`
```
⚠️ `{uid}` مشرف بالفعل.
✅ تم رفع `{uid}` مشرف.
```

### 2.15 /request — خطأ في الاستخدام

**الملف:** `bot/handlers.py:1231`
```
⚠️ **استخدم:** `/request 4h 5`
مثال: `/request 4h 5` (5 طلبات كل 4 ساعات)
```

### 2.16 /status

**الملف:** `bot/handlers.py:1248-1254`
```
🪑 **المساحة:** {active}/{max_s} مستخدم
📋 **المشتركين:** {len(subs)}
👑 **المالك:** `{OWNER_ID}` (غير محسوب)
👤 **المستخدمين النشطين:** {len(active)}
📊 **الحد:** {max_per_window} طلب / {win_min} دقيقة
🪪 **المعرف:** `{OWNER_ID}`

{exchange_status}
```

### 2.17 /scan — جاري المسح

**الملف:** `bot/handlers.py:1263`
```
🔍 **Scanning market...** ⏳
```

### 2.18 /sectors — جاري التحليل

**الملف:** `bot/handlers.py:1269`
```
📊 **Analyzing sectors...** ⏳
```

### 2.19 /matrix — جاري المسح

**الملف:** `bot/handlers.py:1275`
```
🔬 **Scanning strength matrix (30 coins × 3 TFs)...** (30-60s) ⏳
```

### 2.20 /analyze — خطأ استخدام

**الملف:** `bot/handlers.py:1282`
```
⚠️ **استخدم:** `/analyze BTC`
```

### 2.21 /analyze — جاري

**الملف:** `bot/handlers.py:1285`
```
🔍 **Analyzing {symbol.upper()} across 3 TFs...** ⏳
```

---

## ═══════════════════════════════════════
## 3. تنبيهات الصفقات (ترسل تلقائياً)
## ═══════════════════════════════════════

### 3.1 TP1 — أول هدف (إغلاق الصفقة)

**الملف:** `bot/tracker.py:278-288`
```
📊 **اشعار توصيه**

🟢 **{sym}** » اول هدف ✅
الربح » +{gain:.2f}%
سعر الهدف » `${target:.{dec}f}`
السعر الحالي » `${cp:.{dec}f}`
مده التوصيه » {duration}
🧠 ثقة AI » {ai_conf:.0f}% | 🎯 فوري/📉 معلق
⚠️ متابعه العمله منتهيه لتحقيقها اول هدف
```

### 3.2 TP2/TP3 — أهداف إضافية

**الملف:** `bot/tracker.py:293-297`
```
📈 **{sym}** » هدف T{i+1} ✅
الربح » +{gain:.2f}%
السعر » `${cp:.{dec}f}`
```

### 3.3 TP1 بعد تراجع من الهدف

**الملف:** `bot/tracker.py:327-336`
```
📊 **اشعار توصيه**

🟢 **{sym}** » اول هدف ✅ (وصل {first_tp:.{dec}f} ثم تراجع)
الربح » +{gain:.2f}%
اعلى سعر » `${highest:.{dec}f}`
مده التوصيه » {duration}
🧠 ثقة AI » {ai_conf:.0f}% | 🎯 فوري/📉 معلق
⚠️ متابعه العمله منتهيه لتحقيقها اول هدف
```

### 3.4 وقف خسارة — SL

**الملف:** `bot/tracker.py:345-354`
```
📊 **اشعار توصيه**

🔴 **{sym}** » وقف خساره ❌
الخساره » {loss:.2f}%
اغلقت بسعر » `${stop:.{dec}f}`
مده التوصيه » {duration}
🧠 ثقة AI » {ai_conf:.0f}% | 🎯 فوري/📉 معلق
⚠️ متابعه العمله منتهيه لضرب وقف الخساره
```

### 3.5 إلغاء صفقة

**الملف:** `bot/tracker.py:ล — (نفس قالب SL تقريباً)`

---

## ═══════════════════════════════════════
## 4. إشارة توصية جديدة (تُبث لكل المشتركين)
## ═══════════════════════════════════════

### 4.1 إشارة AI — القالب العربي

**الملف:** `report/telegram.py:372-397` + `engine/universal_scanner.py:511-519`
```
━━━ 📋 توصية ━━━

〽️ العملة: **{symbol}**
✨ السعر الحالي: ${price}

━━━ 📋 تفاصيل ━━━

✅ الدخول : {entry_label}
⚠️ الوقف : ${stop} (-{sl_loss:.1f}%)

🎯 الاهداف:

🥇 الاول: ${t1} ({g1:+.1f}%)
🥈 الثاني: ${t2} ({g2:+.1f}%)
🥉 الثالث: ${t3} ({g3:+.1f}%)

━━━ 📋 توقعات ━━━

✅ نسبة النجاح: {success_rate:.0f}%
🌟 الثقه: {conf:.0f}%
💪 القوة: {strength:.0f}%
⏱ المدة المتوقعة: {duration}
⚖️ المخاطرة: {risk_level}
```
**الزر:** `➕ أضف إلى قائمتي` → callback: `add_{symbol}`

---

## ═══════════════════════════════════════
## 5. تفاصيل التوصية (زر — صفحة منفصلة)
## ═══════════════════════════════════════

### 5.1 صفقة نشطة

**الملف:** `bot/keyboard.py:169-223`
```
━━━ 📊 **{sym}** ━━━

〽️ **العملة:** {sym}
{pnl_emoji} **الحالة:** 🟢 ربح أو 🔴 خسارة ({pnl:+.2f}%)

📥 **الدخول:** ${entry:.{dec}f}
📊 **الحالي:** ${cp:.{dec}f}
⏱️ **مده التوصيه:** {duration}

🎯 **الأهداف:**
   T1: ${t1:.{dec}f} ({gain1:+.2f}%) ✅
   T2: ${t2:.{dec}f} ({gain2:+.2f}%)
   T3: ${t3:.{dec}f} ({gain3:+.2f}%)

🛑 **الوقف:** ${sl:.{dec}f} ({sl_pct:.2f}%)

✅ **نسبة النجاح:** {conf:.0f}%
💪 **القوة:** {strength:.0f}%
📅 **تاريخ التوصيه:** {date}
```

### 5.2 صفقة معلقة

**الملف:** `bot/keyboard.py:176-188`
```
━━━ 📊 **{sym}** ━━━

〽️ **العملة:** {sym}
⏳ **الحالة:** معلقة — بانتظار التنفيذ
   السعر الحالي: ${cp:.{dec}f}
   ينتظر النزول إلى: ${limit:.{dec}f}

📥 **أمر الدخول:** ${limit:.{dec}f}
🛑 **الوقف:** ${sl:.{dec}f}
🚫 **يلغى إذا تجاوز:** ${cancel:.{dec}f}
⏱️ **مده التوصيه:** {duration}
```

---

## ═══════════════════════════════════════
## 6. Slot System (نظام المقاعد)
## ═══════════════════════════════════════

### 6.1 المقاعد ممتلئة

**الملف:** `bot/handlers.py:115`
```
⚠️ المقاعد ممتلئة ({max_slots}/{max_slots})
أقدم مقعد محجوز منذ {ago_str}
سيتم إشعارك عند توفر مقعد.
```

### 6.2 تم توفر مقعد

**الملف:** `bot/handlers.py:200`
```
🪑 **تم توفر مقعد!**

المقاعد: {active_count}/{max_s}
استخدم /start للحجز.
```

---

## ═══════════════════════════════════════
## 7. تقارير التحليل (Scan / Sectors / Matrix)
## ═══════════════════════════════════════

### 7.1 Scan — لا توجد فرص

**الملف:** `report/telegram.py:262`
```
🔍 **Market Scan** ({tf})

No clear buy opportunities right now. Market is quiet ⚪
```

### 7.2 Scan — لا توجد فرص شراء

**الملف:** `report/telegram.py:266`
```
🔍 **Market Scan** ({tf})

No suitable buy opportunities. Wait for liquidity to enter.
```

### 7.3 Scan — النتائج

**الملف:** `report/telegram.py:268-283`
```
🔍 **Market Scan** — {tf}
Found **{len(buy_candidates)}** buy opportunities

1. 🟢 **{sym}** — {conf:.0f}% | 💪 {strength:.0f}%
   📥 {entry} 🎯 T1 {t1} 🛑 {sl}
2. ...

🤘 For detailed analysis: `/analyze COIN`
```

### 7.4 Sectors — لا توجد بيانات

**الملف:** `bot/trading.py:52`
```
⚠️ Insufficient sector data right now.
```

### 7.5 Sectors — لا توجد فرص قوية

**الملف:** `bot/trading.py:102`
```
⚪ No strong buy opportunities right now.
Market is quiet, wait for liquidity.
```

### 7.6 /analyze — خطأ

**الملف:** `bot/trading.py:122`
```
⚠️ Error analyzing {symbol}: {error}
```

### 7.7 /analyze — بيانات غير كافية

**الملف:** `bot/trading.py:131`
```
⚠️ Insufficient data for {symbol}
```

### 7.8 /analyze — خطأ عام

**الملف:** `bot/trading.py:171`
```
❌ Error analyzing {symbol}: {error}
```

### 7.9 Top Picks — Header

**الملف:** `bot/trading.py:194`
```
━━━ 🔥 **Top Picks — Full Analysis** ━━━
```

---

## ═══════════════════════════════════════
## 8. التعلم الذاتي (Self-Learning Report)
## ═══════════════════════════════════════

### 8.1 لا توجد بيانات كافية

**الملف:** `engine/self_learning_v2.py:388`
```
📚 **التعلم الذاتي**: لا توجد بيانات كافية بعد — يحتاج ٥ صفقات على الأقل لكل نظام سوق.
```

### 8.2 تقرير التعلم

**الملف:** `engine/self_learning_v2.py:390-416`
```
📚 **تقرير التعلم — {regime}**

📊 **إحصائيات {regime}:**
   صفقات: {total}
   فوز: {wins} ({avg_profit:.0f}%)

🟢 **أفضل الاستراتيجيات:**
   ✅ {strategy1}
   ✅ {strategy2}

🔴 **أسوأ الاستراتيجيات (تجنب):**
   ❌ {strategy1}

⚖️ **حجم المركز الموصى:** {mult:.0%} من الحجم الأساسي
```

---

## ═══════════════════════════════════════
## 9. أخطاء وتحذيرات
## ═══════════════════════════════════════

### 9.1 خطأ تحليل عام

**الملف:** `bot/trading.py:171`
```
❌ Error analyzing {symbol}: {error}
```

### 9.2 فشل المسح

**الملف:** `bot/trading.py:45`
```
❌ Scan error: {error}
```

### 9.3 خطأ تحليل القطاعات

**الملف:** `bot/trading.py:107`
```
❌ Sector analysis error: {error}
```

### 9.4 خطأ Matrix

**الملف:** `bot/trading.py:212`
```
❌ Matrix error: {error}
```

---

## ═══════════════════════════════════════
## 10. قوائم أوامر البوت (Command Scopes)
## ═══════════════════════════════════════

### 10.1 الأوامر العامة (للكل)

**الملف:** `bot/config.py:167-169`
```
start - Subscribe to signals
signals - View all active signals
list - Your personal watchlist
portfolio - Your portfolio & P&L
report - Daily trade report
```

### 10.2 أوامر المشترك

**الملف:** `bot/config.py:145-152`
```
start - إعادة تفعيل الاستقبال
analysis - تحليل عملة (عربي)
max - Full English report
signals - جميع التوصيات
list - قائمتك الشخصية
portfolio - محفظتك
report - التقرير اليومي
stop - إيقاف الإرسال
help - عرض الأوامر
```

### 10.3 أوامر المشرف

**الملف:** `bot/config.py:155-165`
```
...كل أوامر المشترك +
analysis - تحليل عربي
max - Full report
signals - View signals
list - Your list
portfolio - Portfolio
report - Daily report
scan - Quick market scan
sectors - Sector rotation
matrix - Strength matrix
analyze - Full analysis
stop - Unsubscribe
help - Help
allow - Set user slots
request - Set rate limit
status - Bot status
exchanges - Exchange status
broadcast - Broadcast to all
test - Test broadcast
adduser - Add user to slots
admin - Add admin
```

### 10.4 أوامر المالك

**الملف:** `bot/config.py:171`
```
Same as admin commands.
```
