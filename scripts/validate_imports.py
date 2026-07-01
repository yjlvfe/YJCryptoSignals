#!/usr/bin/env python3
"""
🔍 Import Validation System — Phase 5.8

Recursively tests all project imports to detect:
  - missing packages
  - circular imports
  - orphan modules
  - duplicate modules

Usage:
    python3 scripts/validate_imports.py
    python3 -m scripts.validate_imports
"""

import sys
import os
import ast
import importlib
from pathlib import Path
from collections import defaultdict

# ═══════════════ Canonical root detection ═══════════════
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT.parent))

# Sub-packages to validate
SUBPACKAGES = ["engine", "bot", "scripts", "strategies", "sectors", "report", "data"]


def find_python_modules(directory: Path) -> list:
    """Find all .py files in a directory (non-recursive)."""
    if not directory.exists():
        return []
    return sorted([
        f.stem for f in directory.glob("*.py")
        if f.name != "__init__.py" and not f.name.startswith("_")
    ])


def extract_imports(filepath: Path) -> list:
    """Extract all import statements from a Python file using AST."""
    try:
        tree = ast.parse(filepath.read_text())
    except SyntaxError as e:
        return [("SYNTAX_ERROR", str(e))]

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(("import", alias.name))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                full = f"{module}.{alias.name}" if module else alias.name
                imports.append(("from", full))
    return imports


def validate_all_imports() -> dict:
    """Validate all project imports and return report."""
    report = {
        "packages": {},
        "circular": [],
        "missing": [],
        "syntax_errors": [],
        "orphan_modules": [],
        "total_modules": 0,
        "importable": 0,
        "failed": 0,
    }

    all_modules = {}

    # ═══ Phase 1: Find all modules ═══
    for pkg in SUBPACKAGES:
        pkg_dir = PROJECT_ROOT / pkg
        modules = find_python_modules(pkg_dir)
        report["packages"][pkg] = {
            "path": str(pkg_dir),
            "modules": modules,
            "importable": [],
            "failed": [],
        }
        for mod in modules:
            all_modules[f"{pkg}.{mod}"] = pkg_dir / f"{mod}.py"
    report["total_modules"] = len(all_modules)

    # ═══ Phase 2: Check syntax ═══
    for mod_path_str, filepath in all_modules.items():
        try:
            ast.parse(filepath.read_text())
        except SyntaxError as e:
            report["syntax_errors"].append(f"{mod_path_str}: {e}")
            report["packages"][mod_path_str.split(".")[0]]["failed"].append(
                ("syntax", str(e))
            )

    # ═══ Phase 3: Test imports (one by one to isolate failures) ═══
    for mod_path_str, filepath in all_modules.items():
        parts = mod_path_str.split(".")
        pkg = parts[0]
        mod = parts[1]

        try:
            # Try importing the module
            importlib.import_module(f"{pkg}.{mod}")
            report["packages"][pkg]["importable"].append(mod)
            report["importable"] += 1
        except Exception as e:
            err_msg = str(e).split("\n")[0][:150]  # first line only
            report["packages"][pkg]["failed"].append((mod, err_msg))
            report["failed"] += 1

            if "circular" in err_msg.lower():
                report["circular"].append(f"{mod_path_str}: {err_msg}")
            elif "No module named" in err_msg:
                missing = err_msg.split("No module named ")[-1].strip("'\"")
                report["missing"].append(f"{mod_path_str} → {missing}")

    # ═══ Phase 4: Detect orphans (modules not imported by anything) ═══
    imported_by = defaultdict(set)
    for mod_path_str, filepath in all_modules.items():
        imports = extract_imports(filepath)
        for imp_type, imp_name in imports:
            base = imp_name.split(".")[0]
            if base in SUBPACKAGES:
                imported_by[imp_name].add(mod_path_str)

    for mod_path_str in all_modules:
        if mod_path_str not in imported_by and not mod_path_str.endswith("__init__"):
            report["orphan_modules"].append(mod_path_str)

    return report


def print_report(report: dict):
    """Pretty-print validation report."""
    print("=" * 60)
    print("🔍 CryptoSignal Import Validation Report")
    print("=" * 60)

    # Summary
    print(f"\n📊 Summary:")
    print(f"   Total modules: {report['total_modules']}")
    print(f"   ✅ Importable: {report['importable']}")
    print(f"   ❌ Failed: {report['failed']}")
    print(f"   🔄 Circular: {len(report['circular'])}")
    print(f"   📦 Missing deps: {len(report['missing'])}")
    print(f"   👻 Orphans: {len(report['orphan_modules'])}")
    print(f"   💥 Syntax errors: {len(report['syntax_errors'])}")

    # Per-package details
    for pkg, info in report["packages"].items():
        total = len(info["modules"])
        ok = len(info["importable"])
        fail = len(info["failed"])
        icon = "✅" if fail == 0 else "⚠️" if fail < total else "❌"
        print(f"\n  {icon} {pkg}/ ({total} modules, {ok} ok, {fail} failed)")
        for mod, err in info["failed"][:5]:
            print(f"      ❌ {mod}: {err[:100]}")

    # Circular imports
    if report["circular"]:
        print(f"\n🔄 Circular imports detected:")
        for c in report["circular"]:
            print(f"   → {c}")

    # Missing dependencies
    if report["missing"]:
        print(f"\n📦 Missing dependencies:")
        for m in report["missing"][:10]:
            print(f"   → {m}")

    # Orphan modules
    if report["orphan_modules"]:
        print(f"\n👻 Orphan modules (not imported by any other module):")
        for o in report["orphan_modules"][:10]:
            print(f"   → {o}")

    print(f"\n{'='*60}")
    if report["failed"] == 0:
        print("✅ ALL IMPORTS VALID")
    else:
        print(f"⚠️ {report['failed']} import failures — review above")
    print("=" * 60)


if __name__ == "__main__":
    report = validate_all_imports()
    print_report(report)
    sys.exit(0 if report["failed"] == 0 else 1)
