#!/bin/bash
set -e
PROJECT_ROOT=$(pwd)

echo "# 🔍 DEEP INDEXING & DIAGNOSTICS" > "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
echo "التاريخ: $(date)" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
echo "" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"

# ── 1. قراءة آخر أخطاء Logs ──
echo "## 📋 1. آخر أخطاء السجلات" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
find "$PROJECT_ROOT" -name "*.log" -not -path "*/report_fix/*" -not -path "*/venv/*" 2>/dev/null \
     | while read logfile; do
         echo "### $logfile" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
         ERRORS=$(grep -ciE "ERROR|CRITICAL|Exception|Traceback|FATAL" "$logfile" 2>/dev/null)
         echo "- عدد الأخطاء: $ERRORS" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
         echo "- آخر 10 أخطاء:" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
         grep -iE "ERROR|CRITICAL|Exception|Traceback|FATAL" "$logfile" 2>/dev/null \
              | tail -10 >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
         echo "" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
       done

# ── 2. استثناءات صامتة (E) ──
echo "## 🟠 2. استثناءات صامتة (except: pass)" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
grep -rn "except:\s*$\|except Exception:\s*$\|except Exception as.*:$\|except BaseException" \
     "$PROJECT_ROOT" --include="*.py" \
     -not -path "*/report_fix/*" -not -path "*/__pycache__/*" \
     -not -path "*/venv/*" 2>/dev/null \
     >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"

# ── 3. كود قديم (F) ──
echo "" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
echo "## 🟡 3. كود قديم (TODO/FIXME/DEPRECATED)" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
grep -rn "TODO\|FIXME\|HACK\|XXX\|REMOVE\|DEPRECATED\|OLD\|DEAD\|DISABLED\|TEMP\|TEMPORARY" \
     "$PROJECT_ROOT" --include="*.py" --include="*.js" --include="*.ts" \
     -not -path "*/report_fix/*" -not -path "*/__pycache__/*" \
     -not -path "*/venv/*" -not -path "*/node_modules/*" 2>/dev/null \
     | head -50 >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"

# ── 4. أسرار مكشوفة (J) ──
echo "" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
echo "## 🔴 4. أسرار / مفاتيح مكشوفة (تحذير أمني)" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
grep -rnE "sk-[A-Za-z0-9]{20,}|api[_-]?key=|apikey=|secret[_-]?key=|token\s*=" \
     "$PROJECT_ROOT" --include="*.py" --include="*.js" --include="*.ts" \
     --include="*.env" --include="*.yaml" --include="*.json" \
     -not -path "*/report_fix/*" -not -path "*/__pycache__/*" \
     -not -path "*/venv/*" -not -path "*/node_modules/*" -not -path "*/.git/*" 2>/dev/null \
     | grep -v "example\|test\|sample\|YOUR_\|#" | head -30 \
     >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"

# ── 5. ملفات مكررة (C) ──
echo "" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
echo "## 🔵 5. ملفات مكررة / متعارضة" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
find "$PROJECT_ROOT" -type f -name "*.py" -o -name "*.js" -o -name "*.ts" \
     -not -path "*/report_fix/*" -not -path "*/__pycache__/*" \
     -not -path "*/venv/*" -not -path "*/node_modules/*" 2>/dev/null \
     | xargs basename 2>/dev/null \
     | sed 's/_v[0-9]\+\././g; s/_old\././g; s/_backup\././g; s/\.bak\././g' \
     | sort | uniq -d | sort \
     >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"

# ── 6. Syntax Check لكل ملفات Python ──
echo "" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
echo "## 🔴 6. أخطاء الـ Syntax" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
find "$PROJECT_ROOT" -name "*.py" -not -path "*/report_fix/*" \
     -not -path "*/__pycache__/*" -not -path "*/venv/*" 2>/dev/null \
     | while read pyfile; do
         result=$(python3 -m py_compile "$pyfile" 2>&1)
         if [ $? -ne 0 ]; then
             echo "🔴 $pyfile" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
             echo "$result" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
         fi
       done

# ── 7. العمليات الجارية + services ──
echo "" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
echo "## العمليات الجارية (ذات صلة)" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
ps aux | grep -E "python|node|npm|go|ruby|php" 2>/dev/null | grep -v grep \
     >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"

echo "" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
echo "## خدمات systemd الفاشلة" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
systemctl list-units --state=failed --no-pager 2>/dev/null \
     >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"

echo "" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"
echo "✅ PHASE 1 COMPLETE — $(date)" >> "$PROJECT_ROOT/report_fix/01_DIAGNOSTICS.md"

echo "✅ Phase 1 — تم. راجع التقرير ثم انتقل لـ Phase 2"