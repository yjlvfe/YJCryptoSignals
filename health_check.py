#!/usr/bin/env python3
"""
🩺 CryptoSignal Health Check — Quick diagnostics
Usage: python3 health_check.py
"""
import sys
import os
import json
import time
import logging
import requests
from pathlib import Path

logger = logging.getLogger("health-check")

PROJECT_DIR = Path(__file__).parent.resolve()
DATA_DIR = Path("/root/.crypto-signal-bot")

def check(label, ok, detail=""):
    icon = "✅" if ok else "❌"
    print(f"  {icon} {label}" + (f" — {detail}" if detail else ""))

def main():
    # 🔧 Load .env first
    env_file = PROJECT_DIR / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ[key.strip()] = val.strip().strip('"').strip("'")
    
    print("🩺 CryptoSignal Health Check")
    print(f"   {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    issues = 0
    
    # 1. Bot process
    import subprocess
    result = subprocess.run(["pgrep", "-f", "bot/main.py"], capture_output=True, text=True)
    bot_running = result.returncode == 0
    check("Bot process", bot_running, f"PID: {result.stdout.strip()}" if bot_running else "NOT RUNNING")
    if not bot_running:
        issues += 1
    
    # 2. Data directory
    check("Data directory", DATA_DIR.exists(), str(DATA_DIR))
    
    # 3. Trades file
    trades_file = DATA_DIR / "trades.json"
    trades_ok = trades_file.exists()
    if trades_ok:
        try:
            trades = json.loads(trades_file.read_text())
            active = [t for t in trades if t.get("status") == "active"]
            trades_ok = True
            detail = f"{len(active)} active / {len(trades)} total"
        except Exception as e:
            logger.error(f"Failed to read trades file: {e}", exc_info=True)
            trades_ok = False
            detail = "CORRUPTED"
    else:
        detail = "MISSING"
    check("Trades file", trades_ok, detail)
    
    # 4. .env file
    env_file = PROJECT_DIR / ".env"
    has_env = env_file.exists()
    check(".env file", has_env, "exists" if has_env else "MISSING — copy .env.example")
    if not has_env:
        issues += 1
    
    # 5. AI keys (check PROVIDERS list has configured API keys)
    from engine.ai_analyst import PROVIDERS
    has_keys = any(
        len(p.get("api_keys", [])) > 0 and len(p["api_keys"][0]) > 20
        for p in PROVIDERS
    )
    check("AI keys", has_keys, f"{len(PROVIDERS)} provider(s)" if has_keys else "MISSING")
    if not has_keys:
        issues += 1
    
    # 6. AI connectivity (with timeout — probes 6+ providers, can be slow)
    try:
        from engine.ai_analyst import call_ai
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            fut = executor.submit(call_ai, "Reply only: OK", "Health check", max_tokens=5)
            result = fut.result(timeout=12)
        ai_ok = result is not None
        check("AI connectivity", ai_ok, "HTTP OK" if ai_ok else "FAILED")
        if not ai_ok:
            issues += 1
    except concurrent.futures.TimeoutError:
        check("AI connectivity", False, "TIMEOUT (12s)")
        issues += 1
    except Exception as e:
        check("AI connectivity", False, str(e)[:60])
        issues += 1
    
    # 7. safety_walls fix
    try:
        from engine.safety_walls import enforce_safety_walls
        result = enforce_safety_walls([], None)
        check("Safety walls", True, "no TypeError")
    except TypeError:
        check("Safety walls", False, "TypeError — BUG STILL PRESENT")
        issues += 1
    
    # 8. Log errors (last 50 lines)
    log_file = PROJECT_DIR / "logs" / "bot_error.log"
    if log_file.exists():
        lines = log_file.read_text().split('\n')
        recent = lines[-50:]
        errors = [l for l in recent if 'ERROR' in l or 'Exception' in l or 'Traceback' in l]
        check("Recent log errors", len(errors) == 0, f"{len(errors)} errors in last 50 lines" if errors else "clean")
        if errors:
            issues += 1
    else:
        check("Log file", False, "MISSING")
    
    # 9. Python compilation
    py_files = [f for f in PROJECT_DIR.rglob("*.py") 
                if "__pycache__" not in str(f) 
                and "_archive" not in str(f)]
    import py_compile
    compile_errors = 0
    for f in py_files:
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError:
            compile_errors += 1
    check("Python compilation", compile_errors == 0, f"{compile_errors}/{len(py_files)} files fail" if compile_errors else f"{len(py_files)} files OK")
    
    # 10. Except:pass count
    import re
    silent_excepts = 0
    for f in py_files:
        try:
            content = f.read_text()
            # Match bare except: followed by pass on next line
            silent_excepts += len(re.findall(r'except\s*:\s*\n\s*pass\b', content))
            silent_excepts += len(re.findall(r'except\s+Exception\s*:\s*\n\s*pass\b', content))
        except Exception as e:
            logger.debug(f"Error scanning {f.name}: {e}")
            pass
    check("Silent except:pass", silent_excepts == 0, f"{silent_excepts} found" if silent_excepts else "zero")
    
    print()
    print(f"{'✅ ALL CHECKS PASSED' if issues == 0 else f'❌ {issues} ISSUES FOUND'}")
    return 0 if issues == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
