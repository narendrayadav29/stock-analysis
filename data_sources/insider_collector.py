from __future__ import annotations

"""
Insider transaction sentiment via Finnhub free tier.
Free tier: 60 requests/minute. Skipped gracefully if no key is set.
https://finnhub.io/docs/api/insider-sentiment
"""

import logging
from datetime import date, timedelta
import requests
from config import FINNHUB_KEY

logger = logging.getLogger(__name__)
BASE = "https://finnhub.io/api/v1"
TIMEOUT = 10


def get_insider_data(ticker: str, lookback_days: int = 180) -> dict:
    if not FINNHUB_KEY:
        logger.debug("FINNHUB_KEY not set — skipping insider data for %s", ticker)
        return _empty(ticker)

    today     = date.today()
    from_date = (today - timedelta(days=lookback_days)).isoformat()
    to_date   = today.isoformat()

    try:
        # Insider sentiment (MSPR = Monthly Share Purchase Ratio)
        r = requests.get(
            f"{BASE}/stock/insider-sentiment",
            params={"symbol": ticker, "from": from_date, "to": to_date, "token": FINNHUB_KEY},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json().get("data", [])

        if not data:
            return _empty(ticker)

        mspr_values  = [d["mspr"]  for d in data if d.get("mspr")  is not None]
        change_values = [d["change"] for d in data if d.get("change") is not None]

        avg_mspr   = round(sum(mspr_values)   / len(mspr_values),   3) if mspr_values   else None
        net_change = sum(change_values) if change_values else None
        signal     = _mspr_signal(avg_mspr)

        # Recent individual transactions
        r2 = requests.get(
            f"{BASE}/stock/insider-transactions",
            params={"symbol": ticker, "token": FINNHUB_KEY},
            timeout=TIMEOUT,
        )
        r2.raise_for_status()
        txns = r2.json().get("data", [])[:10]
        recent = [
            {
                "name":   t.get("name", ""),
                "action": "BUY" if (t.get("change", 0) > 0) else "SELL",
                "shares": abs(t.get("change", 0)),
                "date":   t.get("transactionDate", ""),
            }
            for t in txns if t.get("change") is not None
        ]

        buys  = sum(1 for t in recent if t["action"] == "BUY")
        sells = sum(1 for t in recent if t["action"] == "SELL")

        return {
            "ticker":            ticker,
            "avg_mspr":          avg_mspr,      # >0 = net buying, <0 = net selling
            "mspr_signal":       signal,
            "net_shares_change": net_change,
            "recent_buys":       buys,
            "recent_sells":      sells,
            "recent_transactions": recent[:5],
            "available":         True,
        }
    except Exception as exc:
        logger.warning("Insider data error for %s: %s", ticker, exc)
        return _empty(ticker)


def _mspr_signal(mspr: float | None) -> str:
    if mspr is None:  return "unknown"
    if mspr > 0.3:    return "strong_buying"
    if mspr > 0.0:    return "net_buying"
    if mspr < -0.3:   return "strong_selling"
    if mspr < 0.0:    return "net_selling"
    return "neutral"


def _empty(ticker: str) -> dict:
    return {
        "ticker":              ticker,
        "avg_mspr":            None,
        "mspr_signal":         None,
        "net_shares_change":   None,
        "recent_buys":         None,
        "recent_sells":        None,
        "recent_transactions": [],
        "available":           False,
    }
