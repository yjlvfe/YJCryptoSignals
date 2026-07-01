"""
Risk-Adjusted Position Sizing v2 — Crypto Trading Bot
=====================================================
Kelly Criterion + volatility-adjusted position sizing with
conservative defaults and Arabic-language trade advice.

Author:  Hermes Agent
Project: crypto-signal (Arabic-localized)
License: Internal
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Risk defaults
DEFAULT_RISK_PER_TRADE_PCT: float = 2.0       # % of account at risk per trade
MAX_RISK_PER_TRADE_PCT: float = 5.0           # hard cap — never exceed this
MAX_POSITION_PCT: float = 25.0                # max % of account in one position
MIN_POSITION_PCT: float = 1.0                 # min % of account in one position

# Kelly defaults
HALF_KELLY_FRACTION: float = 0.5              # use half-Kelly for safety
KELLY_FLOOR: float = 0.0                      # Kelly fraction can't go negative

# Volatility adjustment bounds
VOL_MULTIPLIER_MIN: float = 0.25
VOL_MULTIPLIER_MAX: float = 1.50
VOL_LOW_THRESHOLD: float = 2.0                # ATR% below this → increase size
VOL_HIGH_THRESHOLD: float = 10.0              # ATR% above this → shrink size
VOL_NEUTRAL: float = 4.0                      # "normal" volatility reference

# Confidence scaling
CONFIDENCE_FLOOR: float = 0.50                # minimum confidence (50%)
CONFIDENCE_CEIL: float = 1.00                 # maximum confidence (100%)
CONFIDENCE_BOOST_MAX: float = 1.25            # max multiplier from confidence
CONFIDENCE_BOOST_MIN: float = 0.75            # min multiplier (low confidence)

# Numerical safeguards
EPSILON: float = 1e-10                        # avoid division by zero
MIN_PRICE_DIFF: float = 1e-8                  # minimum |entry - stop|


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RiskCategory(str, Enum):
    """Risk classification for a position."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class PositionSize:
    """Complete position-sizing result for a single trade signal.

    All monetary values are in USD (or base account currency).
    """

    # -- Trade identifiers ------------------------------------------------
    symbol: str

    # -- Account parameters -----------------------------------------------
    account_size: float                     # total account equity
    risk_per_trade_pct: float               # % of account at risk (e.g., 2.0)

    # -- Trade levels -----------------------------------------------------
    entry: float                            # planned entry price
    stop_loss: float                        # stop-loss price

    # -- Volatility metrics ------------------------------------------------
    atr: float                              # Average True Range (absolute)
    volatility_pct: float                   # ATR as % of entry (annualised / normalised)

    # -- Kelly parameters & results ---------------------------------------
    kelly_fraction: float                   # raw optimal Kelly fraction
    kelly_applied: float                    # Kelly fraction after capping (half-Kelly)

    # -- Position size outputs --------------------------------------------
    position_size_usd: float                # notional position value
    position_size_units: float              # number of coins / contracts

    # -- Meta -------------------------------------------------------------
    confidence: float                       # signal confidence [0.0, 1.0]
    risk_category: RiskCategory             # LOW / MEDIUM / HIGH / EXTREME

    # -- Derived / diagnostic fields (auto-computed) ----------------------
    risk_amount_usd: float = field(init=False)      # $ at risk
    reward_risk_ratio: float = field(init=False)    # R:R (if available)
    position_pct: float = field(init=False)          # position as % of account

    def __post_init__(self) -> None:
        """Derive convenience fields after construction."""
        self.risk_amount_usd = self.account_size * (self.risk_per_trade_pct / 100.0)
        self.position_pct = (
            (self.position_size_usd / self.account_size) * 100.0
            if self.account_size > EPSILON
            else 0.0
        )
        # R:R is a rough estimate using ATR-based take-profit distance
        stop_distance = abs(self.entry - self.stop_loss)
        if stop_distance > MIN_PRICE_DIFF:
            self.reward_risk_ratio = self.atr / stop_distance if self.atr > 0 else 0.0
        else:
            self.reward_risk_ratio = 0.0

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dictionary."""
        return {
            "symbol": self.symbol,
            "account_size": self.account_size,
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "atr": self.atr,
            "volatility_pct": self.volatility_pct,
            "kelly_fraction": self.kelly_fraction,
            "kelly_applied": self.kelly_applied,
            "position_size_usd": self.position_size_usd,
            "position_size_units": self.position_size_units,
            "confidence": self.confidence,
            "risk_category": self.risk_category.value,
            "risk_amount_usd": self.risk_amount_usd,
            "reward_risk_ratio": self.reward_risk_ratio,
            "position_pct": self.position_pct,
        }


# ---------------------------------------------------------------------------
# Core sizing functions
# ---------------------------------------------------------------------------

def compute_kelly_criterion(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
) -> float:
    """Compute the optimal Kelly fraction.

    Formula:
        f* = (p * W - q * L) / (W * L)
    where:
        p  = win probability
        q  = 1 - p (loss probability)
        W  = average win size (absolute, positive)
        L  = average loss size (absolute, positive)

    Parameters
    ----------
    win_rate : float
        Win probability in [0, 1], e.g. 0.55 for 55 %.
    avg_win : float
        Average profit per winning trade (absolute value, > 0).
    avg_loss : float
        Average loss per losing trade (absolute value, > 0).

    Returns
    -------
    float
        Kelly fraction in [0, 1].  Negative / NaN inputs are clamped to 0.
    """
    # Sanitise inputs
    win_rate = float(np.clip(win_rate, 0.0, 1.0))
    avg_win = max(float(avg_win), EPSILON)
    avg_loss = max(float(avg_loss), EPSILON)

    # Edge case: near-100 % win rate with meaningful avg_win
    if win_rate >= 1.0 - EPSILON:
        return 1.0

    # Edge case: near-0 % win rate
    if win_rate <= EPSILON:
        return 0.0

    loss_rate = 1.0 - win_rate

    # Kelly formula: f* = (p * W - q * L) / (W)
    # Alternative common form: f* = p - q / (W/L)
    # We use the expected-value-over-outcome form which is more stable:
    numerator = win_rate * avg_win - loss_rate * avg_loss
    denominator = avg_win

    if denominator < EPSILON:
        return 0.0

    kelly = numerator / denominator

    # Clamp negative values (no bet when EV is negative)
    kelly = max(kelly, KELLY_FLOOR)

    # Hard cap at 1.0 (100 % of bankroll — theoretical max)
    kelly = min(kelly, 1.0)

    return float(kelly)


def compute_volatility_adjustment(atr_pct: float) -> float:
    """Return a position-size multiplier based on ATR% (volatility).

    Logic:
      - Low volatility  (< VOL_LOW_THRESHOLD):  increase size  (up to 1.50×)
      - Normal volatility (≈ VOL_NEUTRAL):       neutral        (≈ 1.00×)
      - High volatility (> VOL_HIGH_THRESHOLD):  shrink size    (down to 0.25×)

    Parameters
    ----------
    atr_pct : float
        ATR expressed as a percentage of the entry price (e.g., 3.5 for 3.5 %).

    Returns
    -------
    float
        Multiplier in [VOL_MULTIPLIER_MIN, VOL_MULTIPLIER_MAX].
    """
    atr_pct = max(float(atr_pct), EPSILON)

    if atr_pct <= VOL_LOW_THRESHOLD:
        # Low vol → favour larger sizes (linear ramp from 1.50 at 0 % down to 1.0 at 2 %)
        t = atr_pct / VOL_LOW_THRESHOLD  # 0 → 1
        multiplier = VOL_MULTIPLIER_MAX - t * (VOL_MULTIPLIER_MAX - 1.0)
    elif atr_pct <= VOL_HIGH_THRESHOLD:
        # Normal range: linear fade from 1.0 → 0.5
        t = (atr_pct - VOL_LOW_THRESHOLD) / (VOL_HIGH_THRESHOLD - VOL_LOW_THRESHOLD)
        multiplier = 1.0 - t * 0.5
    else:
        # High vol: exponential decay toward VOL_MULTIPLIER_MIN
        excess = atr_pct - VOL_HIGH_THRESHOLD
        decay = math.exp(-0.15 * excess)  # gentle exponential tail
        multiplier = max(0.5 * decay, VOL_MULTIPLIER_MIN)

    return float(np.clip(multiplier, VOL_MULTIPLIER_MIN, VOL_MULTIPLIER_MAX))


def compute_confidence_multiplier(confidence: float) -> float:
    """Translate a confidence score [0, 1] into a position-size multiplier.

    - Confidence = 0.50 (neutral) → 1.00×
    - Confidence = 1.00 (max)     → 1.25×
    - Confidence = 0.00 (none)    → 0.75×

    Parameters
    ----------
    confidence : float
        Signal confidence in [0.0, 1.0].

    Returns
    -------
    float
        Multiplier in [CONFIDENCE_BOOST_MIN, CONFIDENCE_BOOST_MAX].
    """
    confidence = float(np.clip(confidence, 0.0, 1.0))

    # Map confidence linearly:
    #   c=0.0  → 0.75
    #   c=0.5  → 1.00
    #   c=1.0  → 1.25
    slope = (CONFIDENCE_BOOST_MAX - CONFIDENCE_BOOST_MIN)  # 0.50
    intercept = CONFIDENCE_BOOST_MIN                       # 0.75
    multiplier = intercept + slope * confidence

    return float(np.clip(multiplier, CONFIDENCE_BOOST_MIN, CONFIDENCE_BOOST_MAX))


def classify_risk(
    position_pct: float,
    volatility_pct: float,
    kelly_fraction: float,
) -> RiskCategory:
    """Classify the position into a risk bucket.

    Heuristic:
      - EXTREME: pos > 20 % OR vol > 15 % OR Kelly > 0.40
      - HIGH:    pos > 12 % OR vol > 10 % OR Kelly > 0.25
      - MEDIUM:  pos > 5 %  OR vol > 5 %  OR Kelly > 0.10
      - LOW:     otherwise
    """
    if position_pct > 20.0 or volatility_pct > 15.0 or kelly_fraction > 0.40:
        return RiskCategory.EXTREME
    if position_pct > 12.0 or volatility_pct > 10.0 or kelly_fraction > 0.25:
        return RiskCategory.HIGH
    if position_pct > 5.0 or volatility_pct > 5.0 or kelly_fraction > 0.10:
        return RiskCategory.MEDIUM
    return RiskCategory.LOW


# ---------------------------------------------------------------------------
# Unified position-sizing function
# ---------------------------------------------------------------------------

def compute_position_size(
    account_size: float,
    entry: float,
    stop_loss: float,
    risk_pct: float = DEFAULT_RISK_PER_TRADE_PCT,
    confidence: float = 0.50,
    win_rate: float = 0.50,
    avg_win: float = 0.0,
    avg_loss: float = 0.0,
    atr_pct: float = 4.0,
    atr_absolute: float = 0.0,
    symbol: str = "UNKNOWN",
) -> PositionSize:
    """Unified position-sizing engine.

    Steps
    -----
    1. **Risk-based** : size = account × risk% ÷ |entry − stop|
    2. **Kelly-adjusted** : multiply by half-Kelly fraction
    3. **Volatility-adjusted** : multiply by vol multiplier
    4. **Confidence-adjusted** : multiply by confidence multiplier
    5. **Clamp** to [MIN_POSITION_PCT, MAX_POSITION_PCT] of account

    Parameters
    ----------
    account_size : float
        Total account equity (USD).
    entry : float
        Planned entry price.
    stop_loss : float
        Stop-loss price.
    risk_pct : float, optional
        % of account to risk per trade (default 2.0, max 5.0).
    confidence : float, optional
        Signal confidence [0, 1] (default 0.50).
    win_rate : float, optional
        Historical / estimated win rate [0, 1] (default 0.50).
    avg_win : float, optional
        Average $ profit per winning trade (default 0 → Kelly skipped).
    avg_loss : float, optional
        Average $ loss per losing trade (default 0 → Kelly skipped).
    atr_pct : float, optional
        ATR as % of entry price (default 4.0).
    atr_absolute : float, optional
        Absolute ATR value in price units (default 0).
    symbol : str, optional
        Trading symbol (default "UNKNOWN").

    Returns
    -------
    PositionSize
        Fully populated sizing result.
    """
    # ---- 0. Sanitise & validate inputs ----------------------------------
    account_size = max(float(account_size), 0.0)
    entry = max(float(entry), EPSILON)
    stop_loss = max(float(stop_loss), EPSILON)
    risk_pct = float(np.clip(risk_pct, 0.0, MAX_RISK_PER_TRADE_PCT))
    confidence = float(np.clip(confidence, 0.0, 1.0))

    # ---- 0a. Edge case: zero / negative account -------------------------
    if account_size < EPSILON:
        return PositionSize(
            symbol=symbol,
            account_size=0.0,
            risk_per_trade_pct=risk_pct,
            entry=entry,
            stop_loss=stop_loss,
            atr=atr_absolute,
            volatility_pct=atr_pct,
            kelly_fraction=0.0,
            kelly_applied=0.0,
            position_size_usd=0.0,
            position_size_units=0.0,
            confidence=confidence,
            risk_category=RiskCategory.LOW,
        )

    # ---- 1. Risk-based sizing -------------------------------------------
    stop_distance = abs(entry - stop_loss)

    # Edge case: stop distance is zero or negligible
    if stop_distance < MIN_PRICE_DIFF:
        # With no meaningful stop we can't size risk-based.
        # Fall back to a tiny position at minimal risk.
        risk_amount = account_size * (risk_pct / 100.0)
        position_size_usd = account_size * (MIN_POSITION_PCT / 100.0)
        position_size_units = position_size_usd / entry if entry > EPSILON else 0.0
        return PositionSize(
            symbol=symbol,
            account_size=account_size,
            risk_per_trade_pct=risk_pct,
            entry=entry,
            stop_loss=stop_loss,
            atr=atr_absolute,
            volatility_pct=atr_pct,
            kelly_fraction=0.0,
            kelly_applied=0.0,
            position_size_usd=position_size_usd,
            position_size_units=position_size_units,
            confidence=confidence,
            risk_category=RiskCategory.EXTREME,
        )

    risk_amount = account_size * (risk_pct / 100.0)
    raw_size_units = risk_amount / stop_distance
    raw_size_usd = raw_size_units * entry

    # ---- 2. Kelly-adjustment --------------------------------------------
    kelly_fraction = 0.0
    kelly_applied = 0.0

    if avg_win > EPSILON and avg_loss > EPSILON:
        kelly_fraction = compute_kelly_criterion(win_rate, avg_win, avg_loss)
        # Apply half-Kelly cap
        kelly_applied = min(kelly_fraction * HALF_KELLY_FRACTION, HALF_KELLY_FRACTION)
        raw_size_usd *= kelly_applied
    else:
        # No Kelly data → neutral (multiplier = 1.0)
        kelly_applied = 1.0

    # ---- 3. Volatility adjustment ---------------------------------------
    vol_multiplier = compute_volatility_adjustment(atr_pct)
    raw_size_usd *= vol_multiplier

    # ---- 4. Confidence adjustment ---------------------------------------
    conf_multiplier = compute_confidence_multiplier(confidence)
    raw_size_usd *= conf_multiplier

    # ---- 5. Clamp to account % bounds -----------------------------------
    min_position_usd = account_size * (MIN_POSITION_PCT / 100.0)
    max_position_usd = account_size * (MAX_POSITION_PCT / 100.0)

    position_size_usd = float(np.clip(raw_size_usd, min_position_usd, max_position_usd))

    # Recalculate units from final USD size
    position_size_units = position_size_usd / entry if entry > EPSILON else 0.0

    # ---- 6. Determine risk category -------------------------------------
    position_pct = (position_size_usd / account_size) * 100.0
    risk_category = classify_risk(position_pct, atr_pct, kelly_fraction)

    # ---- 7. Build & return ----------------------------------------------
    return PositionSize(
        symbol=symbol,
        account_size=account_size,
        risk_per_trade_pct=risk_pct,
        entry=entry,
        stop_loss=stop_loss,
        atr=atr_absolute,
        volatility_pct=atr_pct,
        kelly_fraction=kelly_fraction,
        kelly_applied=kelly_applied,
        position_size_usd=position_size_usd,
        position_size_units=position_size_units,
        confidence=confidence,
        risk_category=risk_category,
    )


# ---------------------------------------------------------------------------
# Arabic formatting
# ---------------------------------------------------------------------------

def format_position_advice(size: PositionSize) -> str:
    """Return an Arabic-language summary of the position-sizing result.

    Parameters
    ----------
    size : PositionSize
        A populated sizing result.

    Returns
    -------
    str
        Multi-line Arabic string ready for display / Telegram.
    """
    risk_labels: dict[RiskCategory, str] = {
        RiskCategory.LOW: "منخفض",
        RiskCategory.MEDIUM: "متوسط",
        RiskCategory.HIGH: "مرتفع",
        RiskCategory.EXTREME: "شديد الخطورة",
    }

    risk_emoji: dict[RiskCategory, str] = {
        RiskCategory.LOW: "🟢",
        RiskCategory.MEDIUM: "🟡",
        RiskCategory.HIGH: "🟠",
        RiskCategory.EXTREME: "🔴",
    }

    cat = size.risk_category
    emoji = risk_emoji.get(cat, "⚪")
    label = risk_labels.get(cat, "غير معروف")

    lines = [
        f"📊 *توصية حجم المركز* — {size.symbol}",
        "",
        f"• *حجم الحساب*: `${size.account_size:,.2f}`",
        f"• *نسبة المخاطرة*: `{size.risk_per_trade_pct:.1f}%`",
        f"• *سعر الدخول*: `${size.entry:,.4f}`",
        f"• *وقف الخسارة*: `${size.stop_loss:,.4f}`",
        f"• *المخاطرة بالدولار*: `${size.risk_amount_usd:,.2f}`",
        "",
        f"• *نسبة التقلب (ATR%)*: `{size.volatility_pct:.2f}%`",
        f"• *معامل كيلي الأصلي*: `{size.kelly_fraction:.3f}`",
        f"• *معامل كيلي المُطبَّق (نصف كيلي)*: `{size.kelly_applied:.3f}`",
        f"• *ثقة الإشارة*: `{size.confidence:.0%}`",
        "",
        f"• *حجم المركز (USD)*: *`${size.position_size_usd:,.2f}`*",
        f"• *عدد الوحدات*: `{size.position_size_units:,.4f}`",
        f"• *نسبة المركز من المحفظة*: `{size.position_pct:.1f}%`",
        "",
        f"{emoji} *تصنيف المخاطرة*: *{label}*",
    ]

    # Add a warning for extreme risk
    if cat == RiskCategory.EXTREME:
        lines.append("")
        lines.append("⚠️ *تحذير*: هذا المركز مرتفع المخاطرة جداً. يُنصح بتقليل الحجم أو تجاهل الصفقة.")

    if cat == RiskCategory.HIGH:
        lines.append("")
        lines.append("⚡ *تنبيه*: مستوى مخاطرة مرتفع. تأكد من إدارة المخاطر قبل الدخول.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Quick helper
# ---------------------------------------------------------------------------

def quick_size(
    account_size: float,
    entry: float,
    stop_loss: float,
    risk_pct: float = DEFAULT_RISK_PER_TRADE_PCT,
    symbol: str = "BTC/USDT",
) -> PositionSize:
    """Convenience wrapper with all-defaults except the essentials.

    Suitable for rapid prototyping or CLI usage.
    """
    return compute_position_size(
        account_size=account_size,
        entry=entry,
        stop_loss=stop_loss,
        risk_pct=risk_pct,
        symbol=symbol,
    )


# ═══════════════════════════════════════════════════════════
# 🔧 P002 FIX: v1-compatible wrapper + sector functions
# Allows main.py to import from v2 without changing call sites.
# ═══════════════════════════════════════════════════════════

# Save original v2 function before creating wrapper
_v2_compute_position_size = compute_position_size

# Coin → sector mapping (copied from v1 for compatibility)
COIN_SECTORS = {
    "BTC": "L1", "ETH": "L1", "SOL": "L1", "BNB": "L1", "AVAX": "L1",
    "SUI": "L1", "APT": "L1", "TIA": "L1", "TON": "L1", "NEAR": "L1",
    "INJ": "L1", "SEI": "L1", "ATOM": "L1", "DOT": "L1",
    "DOGE": "MEME", "SHIB": "MEME", "PEPE": "MEME", "WIF": "MEME",
    "BONK": "MEME", "FLOKI": "MEME", "BABYDOGE": "MEME", "SAMO": "MEME",
    "MEME": "MEME", "ELON": "MEME",
    "UNI": "DEFI", "AAVE": "DEFI", "LDO": "DEFI", "CRV": "DEFI",
    "PERP": "DEFI", "PENDLE": "DEFI", "DYDX": "DEFI", "MKR": "DEFI",
    "COMP": "DEFI", "YFI": "DEFI", "SNX": "DEFI", "SUSHI": "DEFI",
    "AXS": "GAMEFI", "SAND": "GAMEFI", "MANA": "GAMEFI", "GALA": "GAMEFI",
    "ENJ": "GAMEFI", "CHR": "GAMEFI", "IMX": "GAMEFI", "TLM": "GAMEFI",
    "YGG": "GAMEFI", "ILV": "GAMEFI",
    "GT": "CEFI", "CRO": "CEFI", "MX": "CEFI", "OKB": "CEFI",
    "BGB": "CEFI", "LEO": "CEFI",
    "FET": "AI", "AGIX": "AI", "OCEAN": "AI", "RNDR": "AI",
    "TAO": "AI", "WLD": "AI", "ARKM": "AI", "NFP": "AI",
    "ONDO": "RWA", "LINK": "RWA", "CFG": "RWA",
    "LINK": "ORACLE", "FIL": "STORAGE", "AR": "STORAGE",
    "OP": "L2", "ARB": "L2", "STRK": "L2", "MATIC": "L2",
}


def get_coin_sector(symbol: str) -> str:
    """Get sector for a coin symbol (v1-compatible)."""
    clean = symbol.replace("USDT", "").replace("USDC", "").upper()
    return COIN_SECTORS.get(clean, "OTHER")


def compute_sector_exposure(active_trades: list, target_sector: str) -> float:
    """Compute current exposure to a sector as % of portfolio (v1-compatible)."""
    if not active_trades:
        return 0.0
    total_trades = len(active_trades)
    same_sector = 0
    for t in active_trades:
        sym = t.get("symbol", "").replace("USDT", "")
        if get_coin_sector(sym) == target_sector:
            same_sector += 1
    per_trade_weight = min(0.20, 1.0 / max(total_trades, 1))
    return same_sector * per_trade_weight * 100


def compute_position_size_v1(
    entry_price: float,
    stop_loss: float,
    portfolio_value: float = 1000.0,
    atr_pct: float = 2.0,
    quality_score: float = 50.0,
    is_micro_cap: bool = False,
    sector_exposure: float = 0.0,
    sector_cap: float = 25.0,
    current_heat: float = 0.0,
) -> dict:
    """
    🔧 v1-compatible wrapper around v2's compute_position_size.
    
    Maps v1-style parameters to v2's PositionSize engine and
    returns a dict identical to v1's output format.
    """
    # Convert v1 quality_score (0-100) to v2 confidence (0-1)
    confidence = quality_score / 100.0
    
    # Adjust risk_pct based on heat and sector exposure (v1 logic in v2 terms)
    heat_available = max(0, 15.0 - current_heat)
    heat_mult = heat_available / 15.0
    heat_mult = max(0.1, min(1.0, heat_mult))
    sector_available = max(0, sector_cap - sector_exposure)
    sector_mult = sector_available / sector_cap if sector_cap > 0 else 1.0
    sector_mult = max(0.1, min(1.0, sector_mult))
    micro_mult = 0.5 if is_micro_cap else 1.0
    
    risk_pct = 2.0 * heat_mult * sector_mult * micro_mult
    risk_pct = max(0.1, min(5.0, risk_pct))
    
    # Use v2 engine (original, before alias)
    result = _v2_compute_position_size(
        account_size=portfolio_value,
        entry=entry_price,
        stop_loss=stop_loss,
        risk_pct=risk_pct,
        confidence=confidence,
        atr_pct=atr_pct,
        symbol="UNKNOWN",
    )
    
    # Calculate SL distance for v1-compatible output
    if entry_price > 0 and stop_loss > 0:
        sl_distance_pct = abs(entry_price - stop_loss) / entry_price * 100
    else:
        sl_distance_pct = 2.0
    
    risk_amount = portfolio_value * (risk_pct / 100)
    
    return {
        "position_size_usd": round(result.position_size_usd, 2),
        "position_units": round(result.position_size_units, 6),
        "risk_per_trade_pct": round(risk_pct, 2),
        "risk_amount_usd": round(risk_amount, 2),
        "sl_distance_pct": round(sl_distance_pct, 2),
        "sizing_factors": {
            "vol_multiplier": 1.0,
            "micro_multiplier": micro_mult,
            "quality_multiplier": confidence,
            "heat_multiplier": round(heat_mult, 2),
            "sector_multiplier": round(sector_mult, 2),
            "sl_factor": 1.0,
            "atr_pct": round(atr_pct, 2),
            "is_micro_cap": is_micro_cap,
        }
    }


# ═══════════════════════════════════════════════════════════
# Alias for main.py drop-in replacement
# ═══════════════════════════════════════════════════════════
compute_position_size = compute_position_size_v1


# ---------------------------------------------------------------------------
# Self-test / demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Example 1: conservative BTC trade -------------------------------
    size1 = compute_position_size(
        account_size=10_000.0,
        entry=65_000.0,
        stop_loss=63_500.0,
        risk_pct=2.0,
        confidence=0.65,
        win_rate=0.55,
        avg_win=800.0,
        avg_loss=400.0,
        atr_pct=3.2,
        atr_absolute=2_080.0,
        symbol="BTC/USDT",
    )
    print(format_position_advice(size1))
    print("\n" + "=" * 60 + "\n")

    # --- Example 2: high-volatility alt-coin -----------------------------
    size2 = compute_position_size(
        account_size=5_000.0,
        entry=12.50,
        stop_loss=10.00,
        risk_pct=2.0,
        confidence=0.70,
        win_rate=0.45,
        avg_win=300.0,
        avg_loss=200.0,
        atr_pct=8.5,
        atr_absolute=1.06,
        symbol="SOL/USDT",
    )
    print(format_position_advice(size2))
    print("\n" + "=" * 60 + "\n")

    # --- Example 3: extreme edge case (zero stop distance) ---------------
    size3 = compute_position_size(
        account_size=10_000.0,
        entry=1.00,
        stop_loss=1.00,
        symbol="EDGE/USDT",
    )
    print(format_position_advice(size3))
    print("\n" + "=" * 60 + "\n")

    # --- Example 4: low confidence, negative-Kelly trade -----------------
    size4 = compute_position_size(
        account_size=10_000.0,
        entry=100.0,
        stop_loss=95.0,
        risk_pct=2.0,
        confidence=0.35,
        win_rate=0.30,
        avg_win=50.0,
        avg_loss=100.0,
        atr_pct=12.0,
        symbol="LOSER/USDT",
    )
    print(format_position_advice(size4))

    # --- Print dict for API consumers ------------------------------------
    print("\n" + "=" * 60)
    print("\n📦 JSON-ready dict (size1):")
    import json
    print(json.dumps(size1.to_dict(), indent=2, ensure_ascii=False))
