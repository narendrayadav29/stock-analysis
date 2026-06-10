"""
SEC EDGAR XBRL API — free, no key required.
Provides quarterly fundamental data directly from official SEC filings.

Also supports Nasdaq Data Link (Quandl) as an optional overlay when
NASDAQ_DATA_LINK_KEY is set (gives access to Sharadar premium fundamentals).
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime
from pathlib import Path

import requests

logger  = logging.getLogger(__name__)
TIMEOUT = 15
CACHE_DIR = Path("database/.edgar_cache")

# ── Ticker → CIK lookup ───────────────────────────────────────────────────────

_CIK_MAP: dict[str, str] | None = None
_CIK_MAP_DATE: str | None = None


def _load_cik_map() -> dict[str, str]:
    """Download/cache the SEC ticker→CIK mapping (refreshed weekly)."""
    global _CIK_MAP, _CIK_MAP_DATE
    today = date.today().isoformat()
    cache_file = CACHE_DIR / "cik_map.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Use in-memory cache for the session
    if _CIK_MAP is not None and _CIK_MAP_DATE == today:
        return _CIK_MAP

    # Use disk cache if fresh (within 7 days)
    if cache_file.exists():
        age_days = (datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)).days
        if age_days < 7:
            _CIK_MAP = json.loads(cache_file.read_text())
            _CIK_MAP_DATE = today
            return _CIK_MAP

    try:
        r = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": "narendra29@gmail.com"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        raw = r.json()
        # {0: {cik_str, ticker, title}, ...} → {TICKER: "0001234567"}
        mapping = {
            v["ticker"].upper(): str(v["cik_str"]).zfill(10)
            for v in raw.values()
        }
        cache_file.write_text(json.dumps(mapping))
        _CIK_MAP = mapping
        _CIK_MAP_DATE = today
        return mapping
    except Exception as exc:
        logger.warning("CIK map load error: %s", exc)
        return {}


def get_cik(ticker: str) -> str | None:
    mapping = _load_cik_map()
    return mapping.get(ticker.upper())


# ── EDGAR XBRL company facts ──────────────────────────────────────────────────

_XBRL_METRICS = {
    # Revenue
    "revenue":           ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                          "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "gross_profit":      ["GrossProfit"],
    "operating_income":  ["OperatingIncomeLoss"],
    "net_income":        ["NetIncomeLoss"],
    "rd_expense":        ["ResearchAndDevelopmentExpense"],
    "eps_diluted":       ["EarningsPerShareDiluted"],
    "eps_basic":         ["EarningsPerShareBasic"],
    # Balance sheet
    "total_assets":      ["Assets"],
    "total_liabilities": ["Liabilities"],
    "cash":              ["CashAndCashEquivalentsAtCarryingValue",
                          "CashCashEquivalentsAndShortTermInvestments"],
    "long_term_debt":    ["LongTermDebt", "LongTermDebtNoncurrent"],
    # Shares
    "shares_outstanding":["CommonStockSharesOutstanding"],
}


def get_company_facts(ticker: str) -> dict:
    """
    Pull XBRL company facts from SEC EDGAR.
    Returns last 8 quarters of key metrics.
    """
    cik = get_cik(ticker)
    if not cik:
        logger.warning("CIK not found for %s", ticker)
        return {"ticker": ticker, "available": False}

    cache_file = CACHE_DIR / f"{ticker}_facts.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Cache XBRL response for 24h (large payload ~1-2MB)
    if cache_file.exists():
        age_h = (datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)).total_seconds() / 3600
        if age_h < 24:
            try:
                return json.loads(cache_file.read_text())
            except Exception:
                pass

    try:
        r = requests.get(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
            headers={"User-Agent": "narendra29@gmail.com"},
            timeout=TIMEOUT,
        )
        if r.status_code == 429:
            time.sleep(10)
            r = requests.get(
                f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                headers={"User-Agent": "narendra29@gmail.com"},
                timeout=TIMEOUT,
            )
        r.raise_for_status()
        raw = r.json()
    except Exception as exc:
        logger.warning("EDGAR facts error %s: %s", ticker, exc)
        return {"ticker": ticker, "available": False}

    gaap    = raw.get("facts", {}).get("us-gaap", {})
    company = raw.get("entityName", ticker)
    result  = {"ticker": ticker, "available": False, "company": company, "quarterly": {}}

    for metric_name, candidates in _XBRL_METRICS.items():
        for candidate in candidates:
            node = gaap.get(candidate)
            if not node:
                continue
            units = node.get("units", {})
            # Revenue/income in USD; EPS in USD/shares; shares in shares
            unit_key = "USD/shares" if "PerShare" in candidate else ("shares" if "Shares" in candidate else "USD")
            entries  = units.get(unit_key, [])
            if not entries:
                continue

            # Filter to 10-Q (quarterly) filings, deduplicate by end date
            quarterly = {}
            for e in entries:
                if e.get("form") in ("10-Q", "10-K") and e.get("end"):
                    quarterly[e["end"]] = e["val"]

            # Last 8 quarters sorted
            sorted_q = sorted(quarterly.items(), key=lambda x: x[0], reverse=True)[:8]
            if sorted_q:
                result["quarterly"][metric_name] = [
                    {"date": d, "value": v} for d, v in reversed(sorted_q)
                ]
                break   # found a valid candidate

    result["available"] = bool(result["quarterly"])

    # Derive YoY growth from revenue if available
    rev_series = result["quarterly"].get("revenue", [])
    if len(rev_series) >= 5:
        latest   = rev_series[-1]["value"]
        year_ago = rev_series[-5]["value"] if len(rev_series) >= 5 else None
        result["revenue_yoy_growth"] = round((latest - year_ago) / abs(year_ago), 4) if year_ago else None
        result["latest_revenue"]     = latest
        result["latest_quarter"]     = rev_series[-1]["date"]

    cache_file.write_text(json.dumps(result))
    return result


# ── Nasdaq Data Link (optional overlay) ───────────────────────────────────────

def get_ndl_fundamentals(ticker: str) -> dict:
    """
    Nasdaq Data Link Sharadar SF1 fundamentals.
    Requires NASDAQ_DATA_LINK_KEY in .env — falls back gracefully if not set.
    Free tier gives FRED macro; Sharadar requires paid subscription (~$30/mo).
    """
    key = os.getenv("NASDAQ_DATA_LINK_KEY", "")
    if not key:
        return {"ticker": ticker, "available": False, "reason": "no_key"}

    try:
        import nasdaqdatalink as ndl
        ndl.ApiConfig.api_key = key

        df = ndl.get_table(
            "SHARADAR/SF1",
            ticker=ticker,
            dimension="ARQ",       # As-reported quarterly
            qopts={"columns": ["ticker","calendardate","revenue","netinc","eps",
                               "grossmargin","operatingmargin","fcf","debt","assets",
                               "equity","pe","pb","ps","evebitda"]},
            paginate=True,
        )
        if df.empty:
            return {"ticker": ticker, "available": False}

        df = df.sort_values("calendardate", ascending=False)
        latest = df.iloc[0].to_dict()
        history = df.head(8).to_dict(orient="records")
        return {
            "ticker":    ticker,
            "available": True,
            "source":    "sharadar",
            "latest":    latest,
            "history":   history,
        }
    except Exception as exc:
        logger.warning("NDL Sharadar error %s: %s", ticker, exc)
        return {"ticker": ticker, "available": False, "reason": str(exc)}
