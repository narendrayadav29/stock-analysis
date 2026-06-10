from __future__ import annotations

"""
Financial Modeling Prep (FMP) collector.
Uses confirmed-working endpoints on the free/stable plan.
Docs: https://financialmodelingprep.com/stable/
"""

import logging
import requests
from config import FMP_KEY, FMP_BASE

logger = logging.getLogger(__name__)
TIMEOUT = 12


def _get(endpoint: str, params: dict | None = None) -> list | dict:
    if not FMP_KEY:
        return {}
    p = {"apikey": FMP_KEY, **(params or {})}
    try:
        r = requests.get(f"{FMP_BASE}{endpoint}", params=p, timeout=TIMEOUT)
        if r.status_code in (404, 402) or not r.text.strip():
            # 402 = rate limit or plan restriction — skip silently
            return {}
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning("FMP error %s: %s", endpoint, exc)
        return {}


def get_profile(ticker: str) -> dict:
    """Company profile — note: FMP /profile returns a flat dict on stable tier."""
    data = _get("/profile", {"symbol": ticker})
    if not data:
        return {}
    # stable tier returns a dict directly (not a list)
    p = data[0] if isinstance(data, list) else data
    return {
        "company_name": p.get("companyName") or p.get("name"),
        "sector":       p.get("sector"),
        "industry":     p.get("industry"),
        "country":      p.get("country"),
        "exchange":     p.get("exchange") or p.get("exchangeShortName"),
        "employees":    p.get("fullTimeEmployees"),
        "description":  (p.get("description") or p.get("longBusinessSummary") or "")[:600],
        "ceo":          p.get("ceo"),
        "market_cap":   p.get("mktCap") or p.get("marketCap"),
        "beta":         p.get("beta"),
        "ipo_date":     p.get("ipoDate"),
        "website":      p.get("website"),
        "image":        p.get("image"),
    }


def get_quote(ticker: str) -> dict:
    """Real-time quote: price, change, volume, PE, 52-week range."""
    data = _get("/quote", {"symbol": ticker})
    if not data:
        return {}
    q = data[0] if isinstance(data, list) else data
    return {
        "price":       q.get("price"),
        "change_pct":  q.get("changePercentage") or q.get("changesPercentage"),
        "change":      q.get("change"),
        "day_high":    q.get("dayHigh"),
        "day_low":     q.get("dayLow"),
        "volume":      q.get("volume"),
        "avg_volume":  q.get("avgVolume"),
        "pe_ratio":    q.get("pe"),
        "eps":         q.get("eps"),
        "high_52w":    q.get("yearHigh"),
        "low_52w":     q.get("yearLow"),
        "market_cap":  q.get("marketCap"),
        "prev_close":  q.get("previousClose"),
        "open":        q.get("open"),
        "name":        q.get("name"),
    }


def get_income_statement(ticker: str, limit: int = 4) -> list[dict]:
    """Annual income statements — revenue, margins, EPS."""
    data = _get("/income-statement", {"symbol": ticker, "limit": limit})
    if not isinstance(data, list):
        return []
    rows = []
    for d in data:
        rows.append({
            "date":             d.get("date"),
            "revenue":          d.get("revenue"),
            "gross_profit":     d.get("grossProfit"),
            "operating_income": d.get("operatingIncome"),
            "net_income":       d.get("netIncome"),
            "ebitda":           d.get("ebitda"),
            "eps":              d.get("eps"),
            "eps_diluted":      d.get("epsDiluted"),
            "gross_margin":     d.get("grossProfitRatio"),
            "operating_margin": d.get("operatingIncomeRatio"),
            "net_margin":       d.get("netIncomeRatio"),
            "r_and_d":          d.get("researchAndDevelopmentExpenses"),
        })
    return rows


def get_historical_prices(ticker: str, limit: int = 30) -> list[dict]:
    """Recent daily OHLCV prices from FMP."""
    data = _get("/historical-price-eod/full", {"symbol": ticker, "limit": limit})
    if not data:
        return []
    rows = data if isinstance(data, list) else data.get("historical", [])
    return [
        {"date": d.get("date"), "open": d.get("open"), "high": d.get("high"),
         "low": d.get("low"), "close": d.get("close"), "volume": d.get("volume")}
        for d in rows[:limit]
    ]


def get_all(ticker: str) -> dict:
    """Fetch all available FMP data for a ticker."""
    profile = get_profile(ticker)
    quote   = get_quote(ticker)
    income  = get_income_statement(ticker, limit=4)

    rev_trend = [r["revenue"] for r in income if r.get("revenue")]

    return {
        "ticker":        ticker,
        "available":     bool(profile or quote),
        **profile,
        "quote":         quote,
        "income_stmts":  income,
        "rev_trend_fmp": rev_trend,
        # estimates/targets not available on this plan tier — gracefully empty
        "estimates":     {},
        "price_targets": {},
    }
