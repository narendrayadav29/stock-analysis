from __future__ import annotations

"""
Aggregates all per-stock analyses and calls Claude for a portfolio-level ranking,
allocation, and thematic summary.
"""

import os
import logging
import shutil
import subprocess
from config import CLAUDE_MODEL

logger = logging.getLogger(__name__)

_CLAUDE_BIN = shutil.which("claude") or "/opt/homebrew/bin/claude"


def _call_claude(prompt: str, system: str) -> str:
    full_prompt = f"{system}\n\n---\n\n{prompt}"
    result = subprocess.run(
        [_CLAUDE_BIN, "-p", full_prompt],
        capture_output=True, text=True, timeout=180,
        env=os.environ,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "claude CLI error")
    return result.stdout.strip()

SYSTEM_PROMPT = """You are a portfolio manager constructing a concentrated growth stock portfolio.
You have already done deep due diligence on each stock. Now you must rank them, size positions,
and identify the macro themes. Be decisive and specific — no generic disclaimers."""


def rank_portfolio(analyses: list[dict]) -> str:
    """
    Takes a list of per-stock analysis dicts (from claude_analyzer.analyze_stock)
    and returns a markdown portfolio ranking report.
    """
    # Build a compact summary table for Claude
    rows = []
    for a in analyses:
        rows.append(
            f"| {a['ticker']:6} | {a.get('company_name','')[:25]:25} "
            f"| {a.get('verdict','?'):10} | {a.get('conviction','?'):6} "
            f"| {_target(a):12} | {a.get('summary','')[:80]} |"
        )

    table = (
        "| Ticker | Company                   | Verdict     | Conv   "
        "| Target       | One-line Thesis                                                  |\n"
        "|--------|---------------------------|-------------|--------|"
        "--------------|------------------------------------------------------------------|\n"
        + "\n".join(rows)
    )

    # Also include the individual summaries for richer context
    summaries = "\n\n".join(
        f"**{a['ticker']}** ({a.get('verdict','?')} / {a.get('conviction','?')}): "
        f"{a.get('summary','')}\nCatalyst: {a.get('catalyst','')}"
        for a in analyses
    )

    prompt = f"""
You have analyzed {len(analyses)} growth stocks. Here is the summary:

{table}

Individual theses:
{summaries}

Now produce the following portfolio report in markdown:

## TOP 10 PICKS (Ranked by Risk-Adjusted Return Potential)
For each pick: rank, ticker, verdict, conviction, 12-month target, and 2-sentence rationale.

## STRONG AVOID LIST
Tickers to stay away from right now and why (1 sentence each).

## WATCHLIST (Good Business, Better Entry Needed)
Stocks worth monitoring for a better price (1 sentence each).

## SECTOR / THEMATIC BREAKDOWN
3-4 macro themes driving the top picks (e.g. "AI infrastructure spend," "consumer wallet recovery").

## SUGGESTED PORTFOLIO ALLOCATION
Allocate 100% across the TOP 10 picks as a percentage weight table.
Consider conviction level, risk, and diversification.

## BIGGEST RISKS TO THE PORTFOLIO
3 macro/market risks that could hurt this portfolio as a whole.

Be decisive, specific, and concise. This is an actionable investment brief.
""".strip()

    try:
        return _call_claude(prompt, SYSTEM_PROMPT)
    except Exception as exc:
        logger.error("Portfolio ranking error: %s", exc)
        return f"Portfolio ranking failed: {exc}"


def _target(a: dict) -> str:
    lo = a.get("target_low")
    hi = a.get("target_high")
    if lo and hi:
        return f"${lo:.0f}–${hi:.0f}"
    if hi:
        return f"≤${hi:.0f}"
    return "N/A"
