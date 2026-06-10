"""
Macro & market data from free sources:
  - FRED (Federal Reserve)  → GDP, CPI, Fed Funds, 10Y yield, unemployment, PCE
  - yfinance                → S&P 500, NASDAQ, VIX, sector ETFs
  - Nasdaq Data Link (opt.) → additional FRED series if NASDAQ_DATA_LINK_KEY set
"""
from __future__ import annotations

import logging
import os
import warnings
from datetime import date, datetime
from io import StringIO

import pandas as pd
import requests
import yfinance as yf

warnings.filterwarnings("ignore")
logger  = logging.getLogger(__name__)
TIMEOUT = 15

# ── FRED series definitions ───────────────────────────────────────────────────

FRED_SERIES = {
    # Growth
    "gdp":               ("GDP",       "Gross Domestic Product (B$)",    "quarterly"),
    "gdp_growth":        ("A191RL1Q225SBEA", "Real GDP Growth Rate (%)", "quarterly"),
    # Inflation
    "cpi":               ("CPIAUCSL",  "CPI All Urban (Index)",          "monthly"),
    "pce":               ("PCEPI",     "PCE Price Index",                "monthly"),
    "core_cpi":          ("CPILFESL",  "Core CPI ex Food & Energy",      "monthly"),
    # Rates
    "fed_funds":         ("FEDFUNDS",  "Fed Funds Rate (%)",             "monthly"),
    "treasury_10y":      ("GS10",      "10-Year Treasury Yield (%)",     "monthly"),
    "treasury_2y":       ("GS2",       "2-Year Treasury Yield (%)",      "monthly"),
    "treasury_30y":      ("GS30",      "30-Year Treasury Yield (%)",     "monthly"),
    # Labor
    "unemployment":      ("UNRATE",    "Unemployment Rate (%)",          "monthly"),
    "nonfarm_payrolls":  ("PAYEMS",    "Nonfarm Payrolls (000s)",        "monthly"),
    # Consumer / credit
    "consumer_sentiment":("UMCSENT",   "U. Michigan Consumer Sentiment", "monthly"),
    "credit_spread":     ("BAMLH0A0HYM2", "HY Credit Spread (bps)",     "daily"),
}


def get_fred_series(series_id: str, limit: int = 24) -> list[dict]:
    """Fetch N most-recent data points for a FRED series. No key required."""
    try:
        r = requests.get(
            "https://fred.stlouisfed.org/graph/fredgraph.csv",
            params={"id": series_id},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text), parse_dates=[0])
        df.columns = ["date", "value"]
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna().sort_values("date").tail(limit)
        return [{"date": row["date"].strftime("%Y-%m-%d"), "value": round(float(row["value"]), 4)}
                for _, row in df.iterrows()]
    except Exception as exc:
        logger.warning("FRED error %s: %s", series_id, exc)
        return []


def get_macro_snapshot() -> dict:
    """
    Pull latest values + 24-month history for all key FRED series.
    One function call; results cached in the returned dict.
    """
    result = {"date": date.today().isoformat(), "series": {}}

    for key, (series_id, label, freq) in FRED_SERIES.items():
        points = get_fred_series(series_id, limit=36)
        result["series"][key] = {
            "id":      series_id,
            "label":   label,
            "freq":    freq,
            "history": points,
            "latest":  points[-1] if points else None,
            "prev":    points[-2] if len(points) >= 2 else None,
        }

    # Yield curve spread (10y - 2y)
    t10 = result["series"].get("treasury_10y", {}).get("latest", {})
    t2  = result["series"].get("treasury_2y",  {}).get("latest", {})
    if t10 and t2:
        result["yield_curve_spread"] = round((t10["value"] - t2["value"]), 3)
        result["yield_curve_inverted"] = result["yield_curve_spread"] < 0

    return result


# ── Market indices via yfinance ───────────────────────────────────────────────

INDEX_TICKERS = {
    "S&P 500":   "^GSPC",
    "NASDAQ 100":"^NDX",
    "VIX":       "^VIX",
    "Russell 2000": "^RUT",
    "Dow Jones": "^DJI",
}

SECTOR_ETFS = {
    "Tech (XLK)":       "XLK",
    "Semis (SOXX)":     "SOXX",
    "Financials (XLF)": "XLF",
    "Energy (XLE)":     "XLE",
    "Healthcare (XLV)": "XLV",
    "Consumer (XLY)":   "XLY",
}


def get_market_indices(period: str = "1y") -> dict:
    """
    Download price history for major indices and sector ETFs.
    Returns normalized (base=100) series for relative comparison.
    """
    all_tickers = {**INDEX_TICKERS, **SECTOR_ETFS}
    result = {}

    for name, sym in all_tickers.items():
        try:
            hist = yf.Ticker(sym).history(period=period)
            if hist.empty:
                continue
            close = hist["Close"].dropna()
            base  = float(close.iloc[0])
            result[name] = {
                "symbol":     sym,
                "current":    round(float(close.iloc[-1]), 2),
                "change_1d":  round(float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100), 2) if len(close) >= 2 else None,
                "change_ytd": round(float((close.iloc[-1] - close.iloc[0])  / close.iloc[0]  * 100), 2),
                "normalized": [
                    {"date": idx.strftime("%Y-%m-%d"), "value": round(float(v / base * 100), 2)}
                    for idx, v in close.items()
                ],
            }
        except Exception as exc:
            logger.warning("Index error %s: %s", sym, exc)

    return result


# ── Nasdaq Data Link overlay (optional) ───────────────────────────────────────

def get_ndl_macro(series_key: str = "FRED/GDP", rows: int = 20) -> list[dict]:
    """
    Pull macro data via Nasdaq Data Link API.
    Works without a key for FRED series; other datasets may need a key.
    Add NASDAQ_DATA_LINK_KEY to .env for premium access.
    """
    key = os.getenv("NASDAQ_DATA_LINK_KEY", "")
    params = {"rows": rows}
    if key:
        params["api_key"] = key

    try:
        r = requests.get(
            f"https://data.nasdaq.com/api/v3/datasets/{series_key}.json",
            params=params,
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        ds = r.json().get("dataset", {})
        cols = ds.get("column_names", [])
        data = ds.get("data", [])
        return [dict(zip(cols, row)) for row in data]
    except Exception as exc:
        logger.warning("NDL error %s: %s", series_key, exc)
        return []
