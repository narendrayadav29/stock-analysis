from __future__ import annotations

"""
Defines the growth stock universe and screens for the top 50 by composite score.
Composite score weights: 40% revenue growth, 30% 52-week momentum, 30% forward value.
"""

import logging
import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

# ~80-stock seed universe of known growth names across sectors
_UNIVERSE = [
    # AI / Semiconductors
    "NVDA", "AMD", "AVGO", "ARM", "SMCI", "ALAB", "MRVL", "QCOM", "TSM", "ASML",
    # Cloud / SaaS
    "MSFT", "AMZN", "GOOGL", "META", "CRM", "NOW", "SNOW", "DDOG", "MDB", "NET",
    "CRWD", "ZS", "HUBS", "GTLB", "BILL", "VEEV", "TTD", "PLTR",
    # Consumer tech / E-commerce
    "AAPL", "TSLA", "SHOP", "MELI", "ABNB", "UBER", "LYFT", "RBLX", "SPOT",
    "NFLX", "PINS", "SNAP", "DUOL",
    # Fintech / Crypto
    "SQ", "AFRM", "UPST", "SOFI", "NU", "COIN", "HOOD",
    # Biotech / Health
    "MRNA", "REGN", "ISRG", "DXCM", "ILMN", "RXRX",
    # Energy transition
    "ENPH", "FSLR", "PLUG", "RUN", "ARRY",
    # Other high-growth
    "CELH", "DECK", "ONON", "APP", "AXON",
]


def _score_ticker(info: dict) -> float:
    rev_growth   = info.get("revenueGrowth") or 0.0
    fwd_pe       = info.get("forwardPE") or 999.0
    low_52w      = info.get("fiftyTwoWeekLow") or 1.0
    current      = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
    momentum_52w = (current - low_52w) / max(low_52w, 0.01)
    value_score  = 1.0 / max(fwd_pe, 1.0)
    return rev_growth * 0.40 + momentum_52w * 0.30 + value_score * 0.30


def get_stock_universe(tickers: list[str] | None = None, top_n: int = 50) -> list[str]:
    """
    Return a list of up to top_n tickers ranked by composite growth score.
    Pass explicit tickers to skip screening (e.g. from --tickers CLI flag).
    """
    candidates = tickers if tickers else _UNIVERSE
    rows = []
    for ticker in candidates:
        try:
            info = yf.Ticker(ticker).fast_info
            # fast_info doesn't have everything; fall back to full info for scoring
            full = yf.Ticker(ticker).info
            score = _score_ticker(full)
            rows.append({"ticker": ticker, "score": score})
        except Exception as exc:
            logger.debug("Universe screen skipped %s: %s", ticker, exc)

    if not rows:
        return candidates[:top_n]

    df = (
        pd.DataFrame(rows)
        .sort_values("score", ascending=False)
        .drop_duplicates("ticker")
        .head(top_n)
    )
    return df["ticker"].tolist()
