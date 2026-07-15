#!/usr/bin/env python3
"""
🤖 CryptoSignal Bot Monitor — يشوف سجلات البوت كل 10 دقائق
يكتشف الأخطاء ويحلل التوصيات ويبلغ المستخدم
"""
import os, sys, json, time, re, logging
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

LOG_FILE = "/var/log/crypto-signal.log"
DATA_DIR = Path("/root/.crypto-signal-bot")
MONITOR_STATE = DATA_DIR / "monitor_state.json"

# Last position in log we checked
def load_state():
    try:
        if MONITOR_STATE.exists():
            return json.loads(MONITOR_STATE.read_text())
    except Exception as e:
        logger.debug(f"Monitor state load failed: {e}")
    return {"last_size": 0, "last_check": time.time(), "cycles_checked": 0, "errors_found": 0}

def save_state(state):
    MONITOR_STATE.parent.mkdir(parents=True, exist_ok=True)
    MONITOR_STATE.write_text(json.dumps(state, indent=2))

def count_errors_in_range(filepath, start_byte=0, end_byte=None):
    """Count ERROR lines AND traceback/exception patterns in a byte range.
    Returns (structured_error_count, total_error_count, list_of_unique_error_types)."""
    try:
        if not os.path.exists(filepath):
            return 0, 0, []
        size = os.path.getsize(filepath)
        if end_byte is None or end_byte > size:
            end_byte = size
        if start_byte >= end_byte:
            return 0, 0, []
        
        structured_count = 0
        raw_count = 0
        error_types = set()
        in_traceback = False
        with open(filepath, 'r', errors='replace') as f:
            f.seek(start_byte)
            to_read = end_byte - start_byte
            content = f.read(to_read)
        
        for line in content.split('\n'):
            # Detect structured [ERROR] lines
            if '[ERROR]' in line:
                structured_count += 1
                raw_count += 1
                m = re.search(r'\[ERROR\]\s*(.+?)(?:\s*[-\d:]+\s*)?$', line)
                if m:
                    error_types.add(m.group(1).strip()[:60])
            
            # Detect raw tracebacks (unstructured exceptions outside logging)
            elif 'Traceback (most recent call last)' in line:
                in_traceback = True
                raw_count += 1
                error_types.add("RawPythonTraceback")
            
            # Detect exception type lines within tracebacks
            elif in_traceback and re.search(r'^\w+(Error|Exception|Warning|Failure):', line):
                raw_count += 1
                err_name = line.split(':')[0].strip()[:60]
                error_types.add(f"RawException:{err_name}")
                in_traceback = False
            
            # Detect standalone exception/error lines (not in traceback, not [ERROR])
            elif re.search(r'\b(ModuleNotFoundError|ImportError|ConnectionError|TimeoutError|KeyError|ValueError|TypeError|AttributeError|IndexError|RuntimeError|OSError|PermissionError)\b', line):
                if 'Traceback' not in line and '[ERROR]' not in line and 'ERROR[' not in line:
                    raw_count += 1
                    m = re.search(r'\b(ModuleNotFoundError|ImportError|ConnectionError|TimeoutError|KeyError|ValueError|TypeError|AttributeError|IndexError|RuntimeError|OSError|PermissionError)\b', line)
                    if m:
                        error_types.add(f"RawException:{m.group(1)}")
                    in_traceback = False
            else:
                in_traceback = False
        
        # Return structured, total, unique types
        return structured_count, raw_count, sorted(error_types)
    except Exception as e:
        logger.error(f"Error counting errors: {e}", exc_info=True)
        return 0, 0, []

def check_bot_health():
    """Check if the bot process is running via systemd."""
    try:
        import subprocess
        r = subprocess.run(["systemctl", "is-active", "crypto-signal.service"],
                         capture_output=True, text=True, timeout=5)
        status = r.stdout.strip()
        if status == "active":
            return "🟢 نشط"
        elif status == "inactive":
            return "🔴 متوقف"
        elif status == "failed":
            return "🔴 فشل"
        else:
            return f"🟡 {status}"
    except Exception as e:
        return f"🟡 يصعب التحقق ({e})"

def check_log():
    state = load_state()
    errors = []
    issues = []
    report_parts = []

    try:
        if not os.path.exists(LOG_FILE):
            return ["⚠️ ملف السجلات غير موجود. يمكن البوت ما شغل."]

        current_size = os.path.getsize(LOG_FILE)
        
        # If log got rotated (smaller than last check) or first run
        if current_size < state["last_size"]:
            state["last_size"] = 0
        
        # ─── Backfill validation ───
        # If state says 0 errors but errors exist in the already-read portion,
        # do a one-time backfill to get an accurate count
        if state.get("errors_found", 0) == 0 and state["last_size"] > 0:
            hist_struct, hist_total, hist_types = count_errors_in_range(LOG_FILE, 0, state["last_size"])
            if hist_total > 0:
                state["errors_found"] = hist_total
                # Don't re-add to errors list to avoid duplicate alerts
        
        # Also backfill cycles if 0 but log has cycles
        if state.get("cycles_checked", 0) == 0 and state["last_size"] > 0:
            with open(LOG_FILE, 'r', errors='replace') as f:
                content = f.read(state["last_size"])
            cycle_count = 0
            for line in content.split('\n'):
                if '📊 Cycle' in line and '[INFO]' in line:
                    cycle_count += 1
            if cycle_count > 0:
                state["cycles_checked"] = cycle_count
        
        # ─── Read new content ───
        if current_size == state["last_size"]:
            # Build summary from state even when no new content
            summary = build_summary(state, errors, issues, report_parts)
            return summary

        with open(LOG_FILE, 'r', errors='replace') as f:
            if state["last_size"] > 0:
                f.seek(state["last_size"])
            new_content = f.read()

        lines = new_content.strip().split('\n')
        state["last_size"] = current_size
        skip_until_full_read = (state.get("_first_full_read_done") is not True)

        # Analyze each line
        for line in lines:
            if not line.strip():
                continue
            
            # Detect errors — with better extraction
            is_critical_poll = "Poll error" in line and ("401" in line or "403" in line or "Unauthorized" in line or "Forbidden" in line)
            
            # Also detect raw tracebacks and exception patterns (no [ERROR] prefix)
            is_traceback_line = False
            if 'Traceback (most recent call last)' in line:
                is_traceback_line = True
                if not any("Traceback" in i for i in issues):
                    issues.append("🔴 تم اكتشاف Traceback غير معالج — قد يكون خطأ استيراد أو استثناء غير متوقع")
                state["errors_found"] = state.get("errors_found", 0) + 1
                errors.append("Raw Python traceback detected — check log for details")
            
            if re.search(r'(ModuleNotFoundError|ImportError|ConnectionError|TimeoutError):', line) and '[ERROR]' not in line and 'Traceback' not in line:
                is_traceback_line = True
                m = re.search(r'(ModuleNotFoundError|ImportError|ConnectionError|TimeoutError):\s*(.*)', line)
                err_name = m.group(1) if m else "UnknownError"
                err_detail = m.group(2).strip()[:60] if m else ""
                if not any(f"{err_name}" in i for i in issues):
                    issues.append(f"🔴 خطأ: {err_name} — {err_detail}")
                state["errors_found"] = state.get("errors_found", 0) + 1
                if err_detail:
                    errors.append(f"Raw{err_name}: {err_detail}")
                else:
                    errors.append(f"Raw{err_name}")
            
            if "[ERROR]" in line or "] ERROR " in line:
                # Skip transient network errors (poll timeouts, connection issues that self-resolve)
                if "Poll error" in line and not is_critical_poll:
                    pass  # Skip transient network errors
                else:
                    # Extract error message cleanly
                    m = re.search(r'\[ERROR\]\s*(.*)', line)
                    if m:
                        error_msg = m.group(1).strip()
                    else:
                        error_msg = line.split("ERROR")[-1].strip().lstrip("] ")
                    errors.append(error_msg)
                    state["errors_found"] = state.get("errors_found", 0) + 1
                    
                    # Classify issues
                    if "No module named" in error_msg:
                        issues.append(f"🔴 خطأ استيراد: {error_msg[:80]}")
                    elif "Unauthorized" in error_msg or "401" in error_msg:
                        if not any("توكن" in i for i in issues):
                            issues.append("🔴🔴🔴 توكن البوت مرفوض! يحتاج تصحيح فوري!")
                    elif "timeout" in error_msg.lower() or "time out" in error_msg.lower():
                        if not any("مهلة" in i for i in issues):
                            issues.append(f"🟡 مهلة API: {error_msg[:60]}")
                    elif "5xx" in error_msg or "500" in error_msg or "502" in error_msg or "503" in error_msg:
                        if not any("خادم" in i for i in issues):
                            issues.append(f"🔴 خطأ خادم: {error_msg[:60]}")
            
            # Detect poll conflicts
            if "Poll conflict" in line:
                if not any("تعارض" in i for i in issues):
                    issues.append("🟡 تعارض في الـ Poll —可能有بوت مكرر!")
            
            # Detect cycles
            if "📊 Cycle" in line and "[INFO]" in line:
                state["cycles_checked"] += 1
            
            # Detect broadcasts
            if "Broadcast sent" in line:
                msg = line.split("[INFO]")[-1].strip() if "[INFO]" in line else line
                report_parts.append("📨 " + msg)
            
            # Detect trade alerts
            if "Trade alert" in line:
                msg = line.split("[INFO]")[-1].strip() if "[INFO]" in line else line
                report_parts.append("📊 " + msg)
            
            # Track commands
            if "Command:" in line:
                cmd = line.split("Command:")[-1].split("from")[0].strip()
                report_parts.append(f"👤 أمر: {cmd}")
            
            # Track analysis runs
            if "Running multi-TF analysis" in line:
                coin = line.split("for")[-1].strip()
                report_parts.append(f"🔍 تحليل: {coin}")
            
            if "Multi-TF analyze completed" in line:
                pass  # Skip redundancy
        
        state["_first_full_read_done"] = True
        save_state(state)
        
        # Build summary
        summary = build_summary(state, errors, issues, report_parts)
        return summary

    except Exception as e:
        return [f"❌ خطأ في فحص السجلات: {e}"]

def build_summary(state, errors, issues, report_parts):
    """Build the final report summary. Returns [] if nothing new."""
    now = datetime.now().strftime("%H:%M:%S")
    summary = []

    # ─── Nothing new? Stay SILENT ───
    if not errors and not issues:
        # Check if there's anything meaningful to report
        meaningful = [p for p in report_parts if any(k in p for k in ["📨", "📊 Trade", "📊 **Trade", "🔄 **CryptoSignal Bot Restarted", "✅ **Bot", "🔴", "🟢 **Trade"])]
        if not meaningful:
            return []  # No output = no message sent

    if errors:
        # Group similar errors
        error_groups = {}
        for e in errors:
            # Simplify to error type
            base = e.split(":")[0].strip() if ":" in e else e[:50]
            error_groups[base] = error_groups.get(base, 0) + 1
        
        error_lines = []
        for base, cnt in sorted(error_groups.items(), key=lambda x: -x[1]):
            if cnt > 1:
                error_lines.append(f"  • `{base}` (×{cnt})")
            else:
                error_lines.append(f"  • `{base}`")
        
        summary.append(f"🔴 **{len(errors)} أخطاء** منذ آخر فحص ({now}):")
        summary.extend(error_lines[:5])  # Show top 5 error groups
        if len(error_lines) > 5:
            summary.append(f"  ... و{len(error_lines) - 5} أنواع أخطاء أخرى")
    else:
        summary.append(f"🟢 **لا توجد أخطاء جديدة** — آخر فحص: {now}")

    if issues:
        # Deduplicate issues
        seen_issues = set()
        unique_issues = []
        for iss in issues:
            if iss not in seen_issues:
                seen_issues.add(iss)
                unique_issues.append(iss)
        
        summary.append("")
        summary.append("**🔧 مشاكل تم اكتشافها:**")
        for iss in unique_issues:
            summary.append(f"  {iss}")

    if report_parts:
        # Deduplicate and limit
        seen = set()
        unique_parts = []
        for p in report_parts:
            if p not in seen:
                seen.add(p)
                unique_parts.append(p)
        
        summary.append("")
        summary.append("**📋 آخر النشاطات:**")
        for p in unique_parts[-10:]:
            summary.append(f"  {p}")

    summary.append("")
    summary.append(f"⏱️ إجمالي الدورات: {state.get('cycles_checked', 0)} | الأخطاء الكلية: {state.get('errors_found', 0)}")
    
    return summary

if __name__ == "__main__":
    result = check_log()
    if result:
        print("\n".join(result))
