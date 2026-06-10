from __future__ import annotations

"""
Polygon.io collector — real-time/previous-close quote, OHLCV bars, options flow.
Docs: https://polygon.io/docs
Free tier: end-of-day data. Starter ($29/mo): real-time + options.
"""

import logging
from datetime import date, timedelta
import requests
from config import POLYGON_KEY

logger = logging.getLogger(__name__)
BASE    = "https://api.polygon.io"
TIMEOUT = 12


def _get(path: str, params: dict | None = None) -> dict:
    if not POLYGON_KEY:
        return {}
    p = {"apiKey": POLYGON_KEY, **(params or {})}
    try:
        r = requests.get(f"{BASE}{path}", params=p, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning("Polygon error %s: %s", path, exc)
        return {}


def get_snapshot(ticker: str) -> dict:
    """
    Full snapshot: current price, day OHLCV, prev close, minute bars.
    On free tier returns previous day's data. On paid: real-time.
    """
    data = _get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}")
    snap = data.get("ticker", {})
    if not snap:
        return {"ticker": ticker, "available": False}

    day  = snap.get("day", {})
    prev = snap.get("prevDay", {})
    min_ = snap.get("min", {})

    return {
        "ticker":          ticker,
        "available":       True,
        "price":           snap.get("lastTrade", {}).get("p") or day.get("c"),
        "day_open":        day.get("o"),
        "day_high":        day.get("h"),
        "day_low":         day.get("l"),
        "day_close":       day.get("c"),
        "day_volume":      day.get("v"),
        "day_vwap":        day.get("vw"),
        "prev_close":      prev.get("c"),
        "change_pct":      snap.get("todaysChangePerc"),
        "change":          snap.get("todaysChange"),
        "min_close":       min_.get("c"),    # most recent minute bar
        "min_volume":      min_.get("v"),
        "updated":         snap.get("updated"),
    }


def get_daily_bars(ticker: str, days: int = 90) -> list[dict]:
    """OHLCV daily bars for the last N days — for custom technical analysis."""
    today = date.today()
    from_  = (today - timedelta(days=days)).isoformat()
    to_    = today.isoformat()
    data   = _get(
        f"/v2/aggs/ticker/{ticker}/range/1/day/{from_}/{to_}",
        {"adjusted": "true", "sort": "desc", "limit": days}
    )
    bars = []
    for b in data.get("results", []):
        bars.append({
            "date":   b.get("t"),   # unix ms timestamp
            "open":   b.get("o"),
            "high":   b.get("h"),
            "low":    b.get("l"),
            "close":  b.get("c"),
            "volume": b.get("v"),
            "vwap":   b.get("vw"),
            "trades": b.get("n"),
        })
    return bars


def get_options_flow(ticker: str, limit: int = 20) -> dict:
    """
    Recent options contracts — large calls vs puts signals smart-money direction.
    Requires paid Starter tier or above.
    """
    data = _get(
        f"/v3/reference/options/contracts",
        {"underlying_ticker": ticker, "limit": limit, "sort": "expiration_date"}
    )
    contracts = data.get("results", [])
    if not contracts:
        return {"ticker": ticker, "available": False}

    calls = [c for c in contracts if c.get("contract_type") == "call"]
    puts  = [c for c in contracts if c.get("contract_type") == "put"]
    pc_ratio = round(len(puts) / max(len(calls), 1), 2)

    return {
        "ticker":             ticker,
        "available":          True,
        "total_contracts":    len(contracts),
        "call_count":         len(calls),
        "put_count":          len(puts),
        "put_call_ratio":     pc_ratio,
        "options_signal":     (
            "bearish_hedge"  if pc_ratio > 1.5 else
            "bullish_sweep"  if pc_ratio < 0.5 else
            "neutral"
        ),
        "sample_strikes":     [
            {"type": c.get("contract_type"), "strike": c.get("strike_price"),
             "expiry": c.get("expiration_date")}
            for c in contracts[:6]
        ],
    }


def get_all(ticker: str) -> dict:
    """Convenience: snapshot + options flow."""
    snap    = get_snapshot(ticker)
    options = get_options_flow(ticker)
    return {
        "ticker":    ticker,
        "snapshot":  snap,
        "options":   options,
        "available": snap.get("available", False),
    }
