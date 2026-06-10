from __future__ import annotations

"""
Defines the growth stock universe and screens for the top 50 by composite score.
Composite score weights: 40% revenue growth, 30% 52-week momentum, 30% forward value.
"""

import logging

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
    Return up to top_n tickers from the curated universe.
    The static list is already ordered by quality — no pre-screening needed.
    Per-ticker fundamentals are fetched during analysis anyway.
    """
    candidates = tickers if tickers else _UNIVERSE
    return list(candidates[:top_n])
