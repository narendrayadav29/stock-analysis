"""
News sentiment via Alpha Vantage NEWS_SENTIMENT endpoint.
Free tier: 25 requests/day. Skipped gracefully if no key is set.
https://www.alphavantage.co/documentation/#news-sentiment
"""

import logging
import requests
from config import ALPHA_VANTAGE_KEY, NEWS_ARTICLES_LIMIT

logger = logging.getLogger(__name__)
BASE = "https://www.alphavantage.co/query"
TIMEOUT = 12

_SENTIMENT_LABEL = {
    "Bearish":        -1.0,
    "Somewhat-Bearish": -0.5,
    "Neutral":         0.0,
    "Somewhat-Bullish": 0.5,
    "Bullish":         1.0,
}


def get_news_sentiment(ticker: str) -> dict:
    if not ALPHA_VANTAGE_KEY:
        logger.debug("ALPHA_VANTAGE_KEY not set — skipping news for %s", ticker)
        return _empty(ticker)

    try:
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers":  ticker,
            "limit":    NEWS_ARTICLES_LIMIT,
            "apikey":   ALPHA_VANTAGE_KEY,
        }
        r = requests.get(BASE, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()

        if "Note" in data:          # rate limit hit
            logger.warning("Alpha Vantage rate limit: %s", data["Note"])
            return _empty(ticker)

        feeds = data.get("feed", [])
        if not feeds:
            return _empty(ticker)

        scores = []
        headlines = []
        for article in feeds:
            # Per-ticker sentiment score within the article
            for ts in article.get("ticker_sentiment", []):
                if ts.get("ticker") == ticker:
                    try:
                        scores.append(float(ts["ticker_sentiment_score"]))
                    except (KeyError, ValueError):
                        pass
            headline = article.get("title", "").strip()
            if headline:
                headlines.append(headline)

        avg_score = round(sum(scores) / len(scores), 3) if scores else None
        label = _score_to_label(avg_score) if avg_score is not None else "Neutral"

        return {
            "ticker":              ticker,
            "avg_sentiment_score": avg_score,   # -1 (very bearish) to +1 (very bullish)
            "sentiment_label":     label,
            "articles_analyzed":   len(feeds),
            "top_headlines":       headlines[:8],
            "available":           True,
        }
    except Exception as exc:
        logger.warning("News sentiment error for %s: %s", ticker, exc)
        return _empty(ticker)


def _score_to_label(score: float) -> str:
    if score >= 0.35:  return "Bullish"
    if score >= 0.10:  return "Somewhat-Bullish"
    if score <= -0.35: return "Bearish"
    if score <= -0.10: return "Somewhat-Bearish"
    return "Neutral"


def _empty(ticker: str) -> dict:
    return {
        "ticker":              ticker,
        "avg_sentiment_score": None,
        "sentiment_label":     None,
        "articles_analyzed":   0,
        "top_headlines":       [],
        "available":           False,
    }
