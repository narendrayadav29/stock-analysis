"""
Builds the per-stock prompt, calls Claude, and parses the structured verdict block.
"""

import os
import re
import logging
import shutil
import subprocess
from config import CLAUDE_MODEL

logger = logging.getLogger(__name__)

_CLAUDE_BIN = shutil.which("claude") or "/opt/homebrew/bin/claude"


def _call_claude(prompt: str, system: str, max_tokens: int = 1400) -> str:
    """
    Call Claude via the Anthropic SDK when ANTHROPIC_API_KEY is set (CI/cloud),
    otherwise fall back to the local Claude CLI (local dev with Claude Code auth).
    """
    if os.getenv("ANTHROPIC_API_KEY"):
        import anthropic
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()

    # Local fallback: Claude CLI
    full_prompt = f"{system}\n\n---\n\n{prompt}"
    result = subprocess.run(
        [_CLAUDE_BIN, "-p", full_prompt],
        capture_output=True, text=True, timeout=180,
        env=os.environ,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "claude CLI returned non-zero exit")
    return result.stdout.strip()

SYSTEM_PROMPT = """You are an elite equity analyst with deep expertise in growth investing,
behavioral finance, and quantitative analysis. You synthesize fundamental data, retail
sentiment, technical price action, earnings trends, news, and insider activity into
clear, actionable investment theses.

Your style:
- Data-driven and direct. No filler sentences.
- Surface non-obvious insights that aren't visible from any single data source.
- Call out divergences (e.g. bullish sentiment vs. deteriorating fundamentals).
- Verdicts must be decisive: STRONG BUY / BUY / HOLD / REDUCE / AVOID.

Always end your response with a STRUCTURED OUTPUT block in exactly this format:
---STRUCTURED OUTPUT---
VERDICT: <STRONG BUY|BUY|HOLD|REDUCE|AVOID>
CONVICTION: <HIGH|MEDIUM|LOW>
TARGET_LOW: <number, no $ sign>
TARGET_HIGH: <number, no $ sign>
CATALYST: <one short phrase>
SUMMARY: <one sentence thesis>
---END---"""


def _fmt(val, pct: bool = False, dollar: bool = False, decimals: int = 1) -> str:
    """Format a numeric value cleanly, returning 'N/A' for None/NaN."""
    if val is None:
        return "N/A"
    try:
        f = float(val)
        if dollar:
            return f"${f:,.0f}" if abs(f) >= 1000 else f"${f:.2f}"
        if pct:
            return f"{f*100:.{decimals}f}%"
        return f"{f:.{decimals}f}"
    except (TypeError, ValueError):
        return str(val)


def _build_prompt(ticker: str, d: dict) -> str:
    fund   = d.get("fundamentals", {})
    earn   = d.get("earnings", {})
    tech   = d.get("technicals", {})
    sent   = d.get("sentiment", {})
    news   = d.get("news", {})
    inside = d.get("insider", {})
    fmp    = d.get("fmp", {})
    poly   = d.get("polygon", {})

    # ── Revenue trend: prefer FMP (cleaner), fall back to yfinance ────────────
    fmp_rev = fmp.get("rev_trend_fmp") or []
    yf_rev  = fund.get("quarterly_revenue") or []
    rev_src = fmp_rev if fmp_rev else yf_rev
    q_rev_str = " → ".join(f"${v/1e9:.2f}B" for v in rev_src) if rev_src else "N/A"

    # ── FMP income statement (most recent year) ────────────────────────────────
    inc = (fmp.get("income_stmts") or [{}])[0]
    fmp_est  = fmp.get("estimates") or {}
    fmp_tgt  = fmp.get("price_targets") or {}
    poly_snap = poly.get("snapshot") or {}
    poly_opts = poly.get("options") or {}

    messages_block = (
        "\n".join(f'  • "{m[:120]}"' for m in sent["sample_messages"][:10])
        if sent.get("sample_messages") else "  (StockTwits data not available)"
    )
    headlines_block = (
        "\n".join(f"  • {h}" for h in news["top_headlines"][:6])
        if news.get("top_headlines") else "  (News data not available)"
    )
    insider_txns = ""
    for t in (inside.get("recent_transactions") or [])[:4]:
        insider_txns += f"  • {t.get('date','')} {t.get('name','')} {t.get('action','')} {t.get('shares',0):,} shares\n"
    if not insider_txns:
        insider_txns = "  (Insider data not available)"

    return f"""
Analyze {ticker} ({fund.get('company_name', ticker)}) as a growth stock investment.

═══ COMPANY FUNDAMENTALS ═══
Sector / Industry : {fund.get('sector', 'N/A')} / {fund.get('industry', 'N/A')}
Market Cap        : {_fmt(fund.get('market_cap'), dollar=True)}
Employees         : {fund.get('employees') and f"{fund['employees']:,}" or 'N/A'} (if known)

Revenue Growth YoY : {_fmt(fund.get('revenue_growth_yoy'), pct=True)}
Earnings Growth YoY: {_fmt(fund.get('earnings_growth_yoy'), pct=True)}
Quarterly Rev Trend: {q_rev_str}  (most recent first)
Revenue TTM        : {_fmt(fund.get('revenue_ttm'), dollar=True)}

Gross Margin    : {_fmt(fund.get('gross_margin'), pct=True)}
Operating Margin: {_fmt(fund.get('operating_margin'), pct=True)}
Net Margin      : {_fmt(fund.get('net_margin'), pct=True)}
EBITDA          : {_fmt(fund.get('ebitda'), dollar=True)}
Free Cash Flow  : {_fmt(fund.get('free_cash_flow'), dollar=True)}

P/E Trailing: {_fmt(fund.get('pe_trailing'))} | Forward P/E: {_fmt(fund.get('pe_forward'))}
PEG Ratio   : {_fmt(fund.get('peg_ratio'))} | P/S: {_fmt(fund.get('ps_ratio'))}
P/B Ratio   : {_fmt(fund.get('pb_ratio'))} | EV/EBITDA: {_fmt(fund.get('ev_to_ebitda'))}
Debt/Equity : {_fmt(fund.get('debt_to_equity'))} | Current Ratio: {_fmt(fund.get('current_ratio'))}
ROE: {_fmt(fund.get('roe'), pct=True)} | ROA: {_fmt(fund.get('roa'), pct=True)}

Analyst Consensus : {fund.get('analyst_consensus', 'N/A')} (n={fund.get('analyst_count', 'N/A')})
Analyst Targets   : Low {_fmt(fund.get('analyst_low'), dollar=True)} / Mean {_fmt(fund.get('analyst_target'), dollar=True)} / High {_fmt(fund.get('analyst_high'), dollar=True)}

Business: {fund.get('description', 'N/A')}

═══ EARNINGS ═══
Next Earnings Date : {earn.get('next_earnings_date', 'N/A')}
EPS Estimate (next): {_fmt(earn.get('eps_estimate'), dollar=True)}
EPS Actual (last Q): {_fmt(earn.get('eps_actual_last'), dollar=True)}
Last Q Surprise    : {_fmt(earn.get('surprise_pct_last'), pct=True)}
Beat Rate (4Q)     : {_fmt(earn.get('beat_rate_4q'), pct=True)}

═══ TECHNICAL PICTURE ═══
Current Price : ${_fmt(tech.get('current_price'))}
MA20 / MA50 / MA200: ${_fmt(tech.get('ma20'))} / ${_fmt(tech.get('ma50'))} / ${_fmt(tech.get('ma200'))}
Price vs MA50 : {_fmt(tech.get('price_vs_ma50_pct'))}% | vs MA200: {_fmt(tech.get('price_vs_ma200_pct'))}%
Trend         : {tech.get('trend', 'N/A')}
RSI (14)      : {_fmt(tech.get('rsi_14'))}
MACD Histogram: {_fmt(tech.get('macd_histogram'), decimals=4)} | Signal: {tech.get('macd_signal', 'N/A')}
Bollinger %B  : {_fmt(tech.get('bb_pct_b'))} (0=lower, 1=upper band)
Volume Ratio  : {_fmt(tech.get('volume_ratio_20d'))}x vs 20d avg
OBV Trend     : {tech.get('obv_trend', 'N/A')}
ATR%          : {_fmt(tech.get('atr_pct'))}% (daily volatility)
52W High / Low: ${_fmt(tech.get('high_52w'))} / ${_fmt(tech.get('low_52w'))}
% From 52W High: {_fmt(tech.get('pct_from_52w_high'))}%

═══ RETAIL SENTIMENT ═══
— StockTwits (API currently closed, may be unavailable) —
Messages Analyzed: {sent.get('total_messages', 0)}
Bullish / Bearish: {sent.get('bullish_count', 'N/A')} ({_fmt(sent.get('bull_ratio'), pct=True)}) / {sent.get('bearish_count', 'N/A')} ({_fmt(sent.get('bear_ratio'), pct=True)})
Watchlist Count  : {sent.get('watchlist_count') and f"{sent['watchlist_count']:,}" or 'N/A'}
Sample Messages  :
{messages_block}

— Reddit (r/wallstreetbets + r/stocks + r/investing) —
Mentions (7 days): {sent.get('reddit_mentions', 0)}
Total Upvotes    : {sent.get('reddit_upvotes') and f"{sent['reddit_upvotes']:,}" or 'N/A'}
Reddit Sentiment : {sent.get('reddit_sentiment', 'N/A')}
{chr(10).join(f'  • [{p.get("subreddit")}] {p.get("title","")} (↑{p.get("score",0):,})' for p in ((sent.get('reddit') or {}).get('top_posts') or [])[:4])}

— CNN Fear & Greed Index (market-wide) —
Score  : {_fmt(sent.get('market_fg_score'))} / 100  ({sent.get('market_fg_rating', 'N/A')})
Trend  : {((sent.get('fear_greed') or {}).get('trend', 'N/A'))}

═══ NEWS SENTIMENT ═══
Score     : {_fmt(news.get('avg_sentiment_score'))} ({news.get('sentiment_label', 'N/A')})
Articles  : {news.get('articles_analyzed', 'N/A')}
Headlines :
{headlines_block}

═══ INSIDER ACTIVITY (last 180 days) ═══
MSPR (avg)  : {_fmt(inside.get('avg_mspr'))} → {inside.get('mspr_signal', 'N/A')}
Recent Buys / Sells: {inside.get('recent_buys', 'N/A')} / {inside.get('recent_sells', 'N/A')}
Transactions:
{insider_txns}

═══ FMP FUNDAMENTALS (cross-check) ═══
Annual Revenue Trend (FMP): {" → ".join(f"${v/1e9:.1f}B" for v in fmp_rev[:4]) if fmp_rev else "N/A"}
Latest Annual Revenue : {_fmt(inc.get('revenue'), dollar=True)}
Latest Gross Margin   : {_fmt(inc.get('gross_margin'), pct=True)}
Latest Net Margin     : {_fmt(inc.get('net_margin'), pct=True)}
Latest EPS (diluted)  : {_fmt(inc.get('eps_diluted'), dollar=True)}
R&D Spend             : {_fmt(inc.get('r_and_d'), dollar=True)}
FMP CEO               : {fmp.get('ceo', 'N/A')}
FMP Beta              : {_fmt(fmp.get('beta'))}
Est. EPS Next Q (FMP) : {_fmt(fmp_est.get('est_eps_avg'), dollar=True)} (low {_fmt(fmp_est.get('est_eps_low'), dollar=True)} / high {_fmt(fmp_est.get('est_eps_high'), dollar=True)})
Est. Revenue Next Q   : {_fmt(fmp_est.get('est_revenue_avg'), dollar=True)}
FMP Price Targets     : Low {_fmt(fmp_tgt.get('target_low'), dollar=True)} / Mean {_fmt(fmp_tgt.get('target_mean'), dollar=True)} / High {_fmt(fmp_tgt.get('target_high'), dollar=True)}

═══ POLYGON REAL-TIME DATA ═══
Live Price     : {_fmt(poly_snap.get('price'), dollar=True)} (prev close: {_fmt(poly_snap.get('prev_close'), dollar=True)})
Today Change   : {_fmt(poly_snap.get('change_pct'))}% (${_fmt(poly_snap.get('change'))})
Day Range      : ${_fmt(poly_snap.get('day_low'))} – ${_fmt(poly_snap.get('day_high'))}
Day Volume     : {poly_snap.get('day_volume') and f"{int(poly_snap['day_volume']):,}" or 'N/A'}
Day VWAP       : {_fmt(poly_snap.get('day_vwap'), dollar=True)}
Options Signal : {poly_opts.get('options_signal', 'N/A')} (P/C ratio: {_fmt(poly_opts.get('put_call_ratio'))})
Calls / Puts   : {poly_opts.get('call_count', 'N/A')} / {poly_opts.get('put_count', 'N/A')}

═══ REQUIRED OUTPUT FORMAT ═══
Provide exactly these sections, then the STRUCTURED OUTPUT block:

## 1. FUNDAMENTAL QUALITY
(2-3 sentences: revenue growth trajectory, margin trend, FCF generation)

## 2. VALUATION
(1-2 sentences: cheap/fair/expensive relative to growth rate, compare PEG/PS to peers)

## 3. RETAIL SENTIMENT SIGNAL
(1-2 sentences: interpret StockTwits data — is crowd overcrowded or under-followed?)

## 4. TECHNICAL STRUCTURE
(1-2 sentences: trend, momentum, volume/OBV buying or selling pressure)

## 5. EARNINGS TRAJECTORY
(1-2 sentences: beat history, guidance quality, upcoming catalyst risk)

## 6. NEWS & INSIDER SIGNALS
(1-2 sentences: what is smart money and news flow signaling?)

## 7. KEY RISKS
- Risk 1
- Risk 2
- Risk 3
- Risk 4 (max 4)

Then end with the STRUCTURED OUTPUT block exactly as specified.
""".strip()


def analyze_stock(ticker: str, data: dict) -> dict:
    """
    Call Claude with all collected data. Returns a dict with the full analysis
    text and parsed structured fields.
    """
    prompt = _build_prompt(ticker, data)
    try:
        text = _call_claude(prompt, SYSTEM_PROMPT, max_tokens=1400)
    except Exception as exc:
        logger.error("Claude API error for %s: %s", ticker, exc)
        return {"ticker": ticker, "analysis": f"Error: {exc}", "verdict": "ERROR"}

    parsed = _parse_structured(text)
    return {
        "ticker":        ticker,
        "company_name":  data.get("fundamentals", {}).get("company_name", ticker),
        "analysis":      text,
        **parsed,
    }


def _parse_structured(text: str) -> dict:
    """Extract fields from the ---STRUCTURED OUTPUT--- block."""
    defaults = {
        "verdict":    "HOLD",
        "conviction": "MEDIUM",
        "target_low":  None,
        "target_high": None,
        "catalyst":   "",
        "summary":    "",
    }
    block_match = re.search(r"---STRUCTURED OUTPUT---(.+?)---END---", text, re.DOTALL)
    if not block_match:
        # Fallback: scan whole text for verdict keyword
        for v in ["STRONG BUY", "BUY", "HOLD", "REDUCE", "AVOID"]:
            if v in text.upper():
                defaults["verdict"] = v
                break
        return defaults

    block = block_match.group(1)
    fields = {}
    for line in block.strip().splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fields[key.strip()] = val.strip()

    def num(k):
        try:
            return float(fields[k])
        except (KeyError, ValueError, TypeError):
            return None

    return {
        "verdict":    fields.get("VERDICT",    defaults["verdict"]),
        "conviction": fields.get("CONVICTION", defaults["conviction"]),
        "target_low":  num("TARGET_LOW"),
        "target_high": num("TARGET_HIGH"),
        "catalyst":   fields.get("CATALYST",  ""),
        "summary":    fields.get("SUMMARY",   ""),
    }
