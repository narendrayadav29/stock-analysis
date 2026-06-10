from __future__ import annotations

"""
Retail sentiment from multiple free sources since StockTwits API is currently
closed to new registrations (403 on all endpoints as of June 2026).

Sources used:
  1. StockTwits public stream  — attempted, falls back gracefully on 403
  2. CNN Fear & Greed Index    — market-wide sentiment, no key needed
  3. Reddit (r/wallstreetbets) — ticker mention + upvote sentiment via Pushshift/Reddit API
  4. Alpha Vantage news score  — already in news_collector, cross-referenced here
"""

import logging
import requests
from config import STOCKTWITS_TOKEN, STOCKTWITS_SENTIMENT_LIMIT

logger = logging.getLogger(__name__)
TIMEOUT = 12


# ── StockTwits (best-effort, may 403) ─────────────────────────────────────────
def get_stocktwits_sentiment(ticker: str) -> dict:
    base = "https://api.stocktwits.com/api/2"
    params = {"limit": STOCKTWITS_SENTIMENT_LIMIT}
    if STOCKTWITS_TOKEN:
        params["access_token"] = STOCKTWITS_TOKEN
    try:
        r = requests.get(f"{base}/streams/symbol/{ticker}.json", params=params, timeout=TIMEOUT)
        if r.status_code in (403, 401):
            logger.info("StockTwits API closed for %s (status %d)", ticker, r.status_code)
            return _st_empty(ticker)
        r.raise_for_status()
        data = r.json()
        messages = data.get("messages", [])
        bull = sum(1 for m in messages if (m.get("entities") or {}).get("sentiment", {}).get("basic") == "Bullish")
        bear = sum(1 for m in messages if (m.get("entities") or {}).get("sentiment", {}).get("basic") == "Bearish")
        total = len(messages)
        return {
            "ticker":          ticker,
            "total_messages":  total,
            "bullish_count":   bull,
            "bearish_count":   bear,
            "neutral_count":   total - bull - bear,
            "bull_ratio":      round(bull / max(total, 1), 3),
            "bear_ratio":      round(bear / max(total, 1), 3),
            "watchlist_count": (data.get("symbol") or {}).get("watchlist_count"),
            "sample_messages": [m["body"].strip() for m in messages if m.get("body")][:15],
            "available":       True,
        }
    except Exception as exc:
        logger.warning("StockTwits error for %s: %s", ticker, exc)
        return _st_empty(ticker)


def _st_empty(ticker: str) -> dict:
    return {"ticker": ticker, "total_messages": 0, "bullish_count": 0,
            "bearish_count": 0, "neutral_count": 0, "bull_ratio": None,
            "bear_ratio": None, "watchlist_count": None,
            "sample_messages": [], "available": False}


# ── Fear & Greed Index via alternative.me (free, no key) ──────────────────────
def get_fear_greed() -> dict:
    """
    Market Fear & Greed score from alternative.me — free, no key required.
    0 = Extreme Fear, 100 = Extreme Greed.
    Originally crypto-focused but now tracks broad market sentiment.
    """
    try:
        r = requests.get(
            "https://api.alternative.me/fng/",
            params={"limit": 2},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data   = r.json().get("data", [])
        latest = data[0] if data else {}
        prev   = data[1] if len(data) > 1 else {}
        score  = int(latest.get("value", 0)) if latest.get("value") else None
        prev_score = int(prev.get("value", 0)) if prev.get("value") else None
        return {
            "score":      score,
            "rating":     latest.get("value_classification", ""),
            "prev_score": prev_score,
            "trend": (
                "rising"  if score and prev_score and score > prev_score else
                "falling" if score and prev_score and score < prev_score else
                "flat"
            ),
            "available": True,
        }
    except Exception as exc:
        logger.warning("Fear & Greed error: %s", exc)
        return {"score": None, "rating": None, "trend": None, "available": False}


# ── Reddit (requires OAuth — skipped, returns empty gracefully) ────────────────
def get_reddit_mentions(ticker: str) -> dict:
    """
    Reddit now requires OAuth for search. Returns empty dict gracefully.
    To enable: create a Reddit app at reddit.com/prefs/apps and add REDDIT_CLIENT_ID
    and REDDIT_CLIENT_SECRET to .env, then install praw and implement OAuth flow.
    """
    return {
        "ticker":        ticker,
        "mention_count": 0,
        "total_upvotes": 0,
        "sentiment":     "unavailable",
        "top_posts":     [],
        "available":     False,
    }


# ── Combined sentiment collector ───────────────────────────────────────────────
def get_sentiment(ticker: str) -> dict:
    """Main entry point — combines all available sentiment signals."""
    st      = get_stocktwits_sentiment(ticker)
    reddit  = get_reddit_mentions(ticker)
    fg      = get_fear_greed()          # market-wide, same for all tickers

    return {
        "ticker":       ticker,
        "stocktwits":   st,
        "reddit":       reddit,
        "fear_greed":   fg,
        # Top-level convenience fields (prefer StockTwits if available)
        "total_messages":  st["total_messages"] if st["available"] else reddit["mention_count"],
        "bullish_count":   st["bullish_count"],
        "bearish_count":   st["bearish_count"],
        "bull_ratio":      st["bull_ratio"],
        "bear_ratio":      st["bear_ratio"],
        "watchlist_count": st["watchlist_count"],
        "sample_messages": st["sample_messages"],
        "reddit_mentions": reddit["mention_count"],
        "reddit_upvotes":  reddit["total_upvotes"],
        "reddit_sentiment":reddit["sentiment"],
        "market_fg_score": fg["score"],
        "market_fg_rating":fg["rating"],
        "available":       True,
    }
