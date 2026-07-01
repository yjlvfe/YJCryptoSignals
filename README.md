# YJCryptoSignals 🚀

**بوت إشارات تداول العملات الرقمية** — تحليل فني متقدم متعدد الأطر الزمنية مع ذكاء اصطناعي، يعمل على تيليجرام.

---

## ✨ المميزات

- 🔍 **ماسح متعدد للمنصات** — MEXC, OKX, Gate.io, KuCoin, Bitget
- 🧠 **تحليل AI** — تحليل SMC (CHOCH, BOS, Order Blocks, FVG) على فريم 4H
- 📊 **16 استراتيجية فنية** — RSI, MACD, CVD, VWAP, Divergence, Market Structure, SMC, OBV/CMF
- 🛡️ **جدران حماية** — SL < 3%, R:R ≥ 1:1، رفض الصفقات الضعيفة
- 🎯 **أهداف ذكية** — 3 أهداف + ستوب لوز من التحليل فقط (بدون توليد تلقائي)
- 📈 **هرم المحللين** — layers متعددة (Weight, Multi-TF, Volume, Breakout, Liquidity)
- 🧬 **تحسين وراثي** — genetic optimizer لضبط أوزان الاستراتيجيات
- 📉 **اختبار رجعي** — backtesting engine لتحسين الأداء
- 📊 **تقارير تيليجرام** — تقارير يومية مع صافي الربح بنسبة الدخول
- 🔥 **منافسة يومية** — تقرير أفضل/أسوأ عملات الـ 24 ساعة

---

## 📋 المتطلبات

- **Python:** 3.10+
- **OS:** Linux (Ubuntu 22.04+)

---

## 🚀 التشغيل

```bash
git clone https://github.com/yjlvfe/YJCryptoSignals.git
cd YJCryptoSignals
pip install -r requirements.txt
```

انسخ `.env.example` إلى `.env` وعبّئ المتغيرات المطلوبة:

```bash
cp .env.example .env
```

تشغيل السكانر:

```bash
python run_scanner.py
```

تشغيل البوت:

```bash
python bot/main.py
```

---

## 🏗️ هيكل المشروع

```
YJCryptoSignals/
├── bot/                    # بوت تيليجرام
│   ├── config.py           # إعدادات البوت والثوابت
│   ├── handlers.py         # معالجات الأوامر
│   ├── trading.py          # إدارة الصفقات
│   ├── tracker.py          # تتبع الأداء وPnL
│   ├── keyboard.py         # لوحة المفاتيح
│   ├── custom_emoji.py     # رموز تعبيرية مخصصة
│   ├── main.py             # نقطة الدخول
│   └── user_lists.py       # قوائم المستخدمين
├── engine/                 # محرك التحليل
│   ├── ai_analyst.py       # محلل AI للتحليل الفني
│   ├── analyzer.py         # محلل فني أساسي
│   ├── multi_analyzer.py   # تحليل متعدد الأطر الزمنية
│   ├── universal_scanner.py# ماسح شامل
│   ├── universal_hunter.py # صياد الفرص
│   ├── breakout_hunter.py  # صياد الاختراقات
│   ├── scanner.py          # ماسح السوق
│   ├── regime.py           # تحديد حالة السوق
│   ├── safety_walls.py     # جدران الحماية
│   ├── smart_targets.py    # أهداف ذكية
│   ├── weights.py          # أوزان الاستراتيجيات
│   └── ...                 # محركات إضافية
├── strategies/             # الاستراتيجيات الفنية
│   ├── smc.py              # Smart Money Concepts
│   ├── rsi_strategy.py     # RSI
│   ├── macd_strategy.py    # MACD
│   ├── market_structure.py # بنية السوق
│   ├── divergence.py       # الديفرجنس
│   └── ...                 # استراتيجيات إضافية
├── data/                   # جلب البيانات
│   ├── exchanges.py        # واجهات المنصات
│   └── fetcher.py          # جلب بيانات الشموع
├── report/                 # التقارير
├── sectors/                # تصنيف القطاعات
├── scripts/                # سكربتات مساعدة
├── run_scanner.py           # تشغيل السكانر
├── health_check.py         # فحص صحة النظام
├── cryptosignal-ctl        # أداة تحكم CLI
└── requirements.txt        # مكتبات Python
```

---

## ⚙️ الإعدادات

يتم التحكم بالإعدادات عبر ملف `.env`:

| المتغير | الوصف |
|---------|-------|
| `BOT_TOKEN` | توكن بوت تيليجرام |
| `DATA_DIR` | مجلد البيانات |
| `AI_API_KEY` | مفتاح API للذكاء الاصطناعي |
| `AI_BASE_URL` | رابط API |
| `AI_MODEL` | نموذج AI |

---

## 📄 الرخصة

MIT License — انظر ملف [LICENSE](LICENSE)

---

## 🤝 المؤلف

**YJLVFE** — [github.com/yjlvfe](https://github.com/yjlvfe)
