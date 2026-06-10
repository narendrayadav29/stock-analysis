from __future__ import annotations

"""
StockTwits API v2 — public endpoints (no token required).
Registration is closed for new developers, so we use the unauthenticated
public stream which returns up to 30 messages per call with sentiment labels.
Rate limit: ~200 requests/hour without auth.
"""

import logging
import time
import requests
from config import STOCKTWITS_TOKEN, STOCKTWITS_SENTIMENT_LIMIT

logger = logging.getLogger(__name__)
BASE    = "https://api.stocktwits.com/api/2"
TIMEOUT = 12


def _get(path: str, params: dict | None = None) -> dict:
    p = params or {}
    if STOCKTWITS_TOKEN:
        p["access_token"] = STOCKTWITS_TOKEN
    for attempt in range(3):
        try:
            r = requests.get(f"{BASE}{path}", params=p, timeout=TIMEOUT)
            if r.status_code == 429:
                wait = 20 * (attempt + 1)
                logger.warning("StockTwits rate limit hit — waiting %ds", wait)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            if attempt == 2:
                raise
            time.sleep(5)
    return {}


def get_sentiment(ticker: str) -> dict:
    """
    Fetch recent messages + bull/bear sentiment for a ticker.
    Works without a token via the public stream endpoint.
    """
    try:
        data = _get(f"/streams/symbol/{ticker}.json", {"limit": STOCKTWITS_SENTIMENT_LIMIT})
    except Exception as exc:
        logger.warning("StockTwits error for %s: %s", ticker, exc)
        return _empty(ticker)

    if data.get("response", {}).get("status") != 200:
        logger.warning("StockTwits bad status for %s: %s", ticker, data.get("response"))
        return _empty(ticker)

    messages = data.get("messages", [])
    bull = sum(
        1 for m in messages
        if (m.get("entities") or {}).get("sentiment", {}).get("basic") == "Bullish"
    )
    bear = sum(
        1 for m in messages
        if (m.get("entities") or {}).get("sentiment", {}).get("basic") == "Bearish"
    )
    total = len(messages)
    sample = [m["body"].strip() for m in messages if m.get("body")][:15]

    sym = data.get("symbol") or {}
    return {
        "ticker":          ticker,
        "total_messages":  total,
        "bullish_count":   bull,
        "bearish_count":   bear,
        "neutral_count":   total - bull - bear,
        "bull_ratio":      round(bull / max(total, 1), 3),
        "bear_ratio":      round(bear / max(total, 1), 3),
        "watchlist_count": sym.get("watchlist_count", 0),
        "sample_messages": sample,
        "available":       True,
    }


def get_trending_symbols(limit: int = 30) -> list[str]:
    """Trending tickers on StockTwits — works without auth."""
    try:
        data = _get("/trending/symbols.json", {"limit": limit})
        return [s["symbol"] for s in data.get("symbols", [])]
    except Exception as exc:
        logger.warning("StockTwits trending error: %s", exc)
        return []


def _empty(ticker: str) -> dict:
    return {
        "ticker": ticker, "total_messages": 0, "bullish_count": 0,
        "bearish_count": 0, "neutral_count": 0, "bull_ratio": None,
        "bear_ratio": None, "watchlist_count": None,
        "sample_messages": [], "available": False,
    }
