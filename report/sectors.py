"""
📊 Sector Rotation Report — English
Full report: liquidity flow + coin analysis + recommendations
"""
from sectors.categories import SECTORS, get_sector_for_coin


def _format_liquidity_bar(value, max_val, length=10):
    """Liquidity bar visualization"""
    filled = max(0, min(length, int((value / max(max_val, 1)) * length)))
    return "█" * filled + "░" * (length - filled)


def _signal_icon(direction, strength=0):
    """Signal icon based on direction and strength"""
    if direction == "BUY":
        if strength >= 70:
            return "🟢🔥"
        elif strength >= 50:
            return "🟢"
        return "🟡"
    elif direction == "SELL":
        return "🔴"
    return "⚪"


def _coin_analysis_str(symbol: str, price: float, change: float) -> str:
    """Format coin with change — no analysis (quick)"""
    sym = symbol.replace("USDT", "")
    emoji = "🟢" if change > 0 else "🔴"
    return f"{emoji} **{sym}** {change:+.2f}% | ${price:.4f}"


def format_sector_report(sector_data: dict, opportunities: list, coin_analysis: dict = None) -> str:
    """
    Full sector report with capital rotation opportunities.
    
    coin_analysis: dict {symbol: {"direction": str, "confidence": float, "strength": float, "entry": float}}
    """
    msg = ["🔍 **Sector Scan — Liquidity Analysis**", ""]

    # ═══ Sector ranking by liquidity strength ═══
    msg.append("━━━ 🔥 **Sector Rankings by Liquidity** ━━━")
    msg.append("")

    max_volume = max(
        (opp.get("volume", 0) for opp in opportunities),
        default=1
    )
    max_score = max(
        (opp.get("score", 1) for opp in opportunities),
        default=1
    )

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, opp in enumerate(opportunities[:5]):
        sector = opp.get("sector", "Unknown")
        emoji = opp.get("momentum", "➡️")
        change = opp.get("avg_change", 0)
        volume = opp.get("volume", 0)
        score = opp.get("score", 0)
        opp_type = opp.get("type", "➡️ Quiet")

        liq_bar = _format_liquidity_bar(volume, max_volume)
        activity_pct = min(100, (score / max(max_score, 1)) * 100)
        activity_bar = _format_liquidity_bar(activity_pct, 100)

        medal = medals[i] if i < len(medals) else f"{i+1}."
        msg.append(f"{medal} {emoji} **{sector}**")
        msg.append(f"   📊 Change: {change:+.2f}% | Vol: `${volume:,.0f}`")
        msg.append(f"   💧 Liquidity: `{liq_bar}` | Activity: `{activity_bar}` {activity_pct:.0f}%")
        msg.append(f"   🏷️ {opp_type}")

        if opp.get("top_gainers"):
            msg.append(f"   **🏆 Coins:**")
            for c in opp["top_gainers"][:3]:
                sym = c["symbol"].replace("USDT", "")
                c_change = c.get("change_24h", 0)
                c_volume = c.get("volume", 0)
                c_price = c.get("price", 0)

                analysis_str = ""
                if coin_analysis and c["symbol"] in coin_analysis:
                    ca = coin_analysis[c["symbol"]]
                    if ca["direction"] == "BUY":
                        analysis_str = f" 🟢 BUY (conf {ca['confidence']:.0f}% | str {ca['strength']:.0f}%)"
                    elif ca["direction"] == "SELL":
                        analysis_str = f" 🔴 Bearish"
                    else:
                        analysis_str = f" ⚪ Neutral"

                msg.append(f"      • {sym}: {c_change:+.2f}% | Vol `${c_volume:,.0f}`{analysis_str}")
        msg.append("")

    # ═══ All sectors summary ═══
    msg.append("━━━ 📊 **All Sectors — Summary** ━━━")
    msg.append("")
    max_change = max(abs(s.get("avg_change_24h", 1)) for s in sector_data.values() if s.get("active_coins",0)>0) or 1
    for sector, data in sorted(sector_data.items(),
                                key=lambda x: abs(x[1].get("avg_change_24h", 0)),
                                reverse=True):
        if data.get("active_coins", 0) == 0:
            continue
        direction = "🟢" if data.get("avg_change_24h", 0) > 0 else "🔴"
        change = data.get("avg_change_24h", 0)
        active = data.get("active_coins", 0)
        total = data.get("coin_count", 0)
        vol = data.get("total_volume", 0)
        up = data.get("up_count", 0)
        down = data.get("down_count", 0)

        bar = _format_liquidity_bar(abs(change), max_change, 8)
        msg.append(f"{direction} **{sector}** `{bar}` {change:+.2f}% | Vol `${vol:,.0f}`")
        msg.append(f"   🟢 Up: {up} | 🔴 Down: {down} | Active: {active}/{total}")
    msg.append("")

    # ═══ Best buy opportunities ═══
    buy_opportunities = []
    if coin_analysis:
        buy_opportunities = [
            (sym, info) for sym, info in coin_analysis.items()
            if info["direction"] == "BUY" and info.get("strength", 0) >= 40
        ]
        buy_opportunities.sort(key=lambda x: x[1]["strength"], reverse=True)

        if buy_opportunities:
            msg.append("━━━ 🔥 **Best Buy Opportunities Now** ━━━")
            msg.append("")
            for i, (sym, info) in enumerate(buy_opportunities[:5]):
                sym_clean = sym.replace("USDT", "")
                sector = get_sector_for_coin(sym)
                msg.append(
                    f"{i+1}. 🟢 **{sym_clean}** — {sector}"
                )
                msg.append(f"   📥 Entry: `${info['entry']:.{info.get('dec', 4)}f}` | Conf {info['confidence']:.0f}% | Str {info['strength']:.0f}%")
            msg.append("")
            msg.append("💡 `/analyze COIN` for full breakdown")
        else:
            msg.append("━━━ 🔥 **Buy Opportunities** ━━━")
            msg.append("")
            msg.append("⚪ No strong buy opportunities right now. Low liquidity.")
            msg.append("")

    # ═══ General recommendation ═══
    msg.append("━━━ 💡 **Recommendation** ━━━")
    msg.append("")
    
    if opportunities:
        best = opportunities[0]
        best_dir = "Bullish 🔥" if best.get("avg_change", 0) > 0 else "Bearish 🔻"
        msg.append(f"🎯 **Strongest sector:** {best['sector']} ({best_dir})")
        msg.append(f"💰 **Largest volume:** ${best.get('volume', 0):,.0f}")
        
        if buy_opportunities:
            msg.append("✅ **Buy opportunities available** — focus on green coins above")
        else:
            msg.append("⏳ **No clear buy opportunities** — wait for liquidity to enter")
    
    msg.append("")
    msg.append("🤖 **Warning:** Market is volatile. Never risk >2-5% in a single trade.")
    msg.append(f"⏱️ **Analysis on 4h timeframe** | 🤖 CryptoSignal Bot")

    return "\n".join(msg)


def format_sector_detail(sector_name: str, data: dict, coin_analysis: dict = None) -> str:
    """Detailed report for one sector with coin analysis"""
    msg = [
        f"📊 **{sector_name}** — {data.get('name', '')}",
        f"_{data.get('description', '')}_",
        "",
        f"📈 24h Change: **{data.get('avg_change_24h', 0):+.2f}%**",
        f"💰 Total Volume: **${data.get('total_volume', 0):,.0f}**",
        f"📊 Active Coins: **{data.get('active_coins', 0)}/{data.get('coin_count', 0)}**",
        f"🟢 Up: {data.get('up_count', 0)} | 🔴 Down: {data.get('down_count', 0)}",
        "",
    ]

    if data.get("top_gainers"):
        msg.append("🏆 **Top Performers:**")
        for i, c in enumerate(data["top_gainers"][:5]):
            sym = c['symbol'].replace('USDT', '')
            c_change = c.get('change_24h', 0)
            c_vol = c.get('volume', 0)
            c_price = c.get('price', 0)
            
            analysis_str = ""
            if coin_analysis and c["symbol"] in coin_analysis:
                ca = coin_analysis[c["symbol"]]
                if ca["direction"] == "BUY":
                    analysis_str = f" 🟢 BUY conf {ca['confidence']:.0f}%"
                elif ca["direction"] == "SELL":
                    analysis_str = f" 🔴 Bearish"
                else:
                    analysis_str = f" ⚪ Neutral"

            emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i]
            msg.append(
                f"  {emoji} **{sym}** — {c_change:+.2f}% | Vol ${c_vol:,.0f}{analysis_str}"
            )

    return "\n".join(msg)
