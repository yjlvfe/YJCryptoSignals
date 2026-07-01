"""
CryptoSignal Trading Bot — root package.

Provides canonical project root detection and ensures all subpackages
are importable regardless of execution context (cron, systemd, Hermes, direct).

Usage:
    from crypto_signal import PROJECT_ROOT
    from crypto_signal.engine import portfolio_heat
"""

from pathlib import Path

# ═══════════════ CANONICAL ROOT (works from any cwd) ═══════════════
PROJECT_ROOT = Path(__file__).resolve().parent

# ═══════════════ Inject into sys.path for backward compatibility ═══════════════
import sys as _sys
_root_str = str(PROJECT_ROOT)
if _root_str not in _sys.path:
    _sys.path.insert(0, _root_str)
# Also ensure parent is importable (so 'import crypto_signal' works)
_parent_str = str(PROJECT_ROOT.parent)
if _parent_str not in _sys.path:
    _sys.path.insert(0, _parent_str)

# ═══════════════ Package metadata ═══════════════
__version__ = "5.8.0"
__author__ = "CryptoSignal Bot"
