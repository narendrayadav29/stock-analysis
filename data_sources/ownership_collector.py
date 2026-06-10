"""
Ownership & flow data — three free sources:
  1. yfinance        → institutional holders, mutual fund holders, major_holders, insider txns
  2. SEC EDGAR       → Form 4 filing count + CIK lookup (transaction details via yfinance)
  3. Quiver Quant    → Congress trading disclosures (free public endpoint, no key)
"""
from __future__ import annotations

import logging
import warnings
from datetime import date, timedelta

import requests
import yfinance as yf

warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)
TIMEOUT = 12

# ── yfinance institutional & insider ──────────────────────────────────────────

def get_institutional_holders(ticker: str) -> dict:
    try:
        t  = yf.Ticker(ticker)
        ih = t.institutional_holders
        mf = t.mutualfund_holders
        mh = t.major_holders

        inst_rows = []
        if ih is not None and not ih.empty:
            for _, row in ih.iterrows():
                inst_rows.append({
                    "holder":      str(row.get("Holder", "")),
                    "shares":      int(row["Shares"])      if "Shares"      in row and row["Shares"] == row["Shares"] else None,
                    "value":       int(row["Value"])       if "Value"       in row and row["Value"]  == row["Value"]  else None,
                    "pct_held":    float(row["pctHeld"])   if "pctHeld"     in row and row["pctHeld"]== row["pctHeld"] else None,
                    "pct_change":  float(row["pctChange"]) if "pctChange"   in row and row["pctChange"]==row["pctChange"] else None,
                    "date_reported": str(row.get("Date Reported", "")),
                    "holder_type": "institution",
                })

        mf_rows = []
        if mf is not None and not mf.empty:
            for _, row in mf.iterrows():
                mf_rows.append({
                    "holder":      str(row.get("Holder", "")),
                    "shares":      int(row["Shares"])      if "Shares"      in row and row["Shares"] == row["Shares"] else None,
                    "value":       int(row["Value"])       if "Value"       in row and row["Value"]  == row["Value"]  else None,
                    "pct_held":    float(row["pctHeld"])   if "pctHeld"     in row and row["pctHeld"]== row["pctHeld"] else None,
                    "pct_change":  float(row["pctChange"]) if "pctChange"   in row and row["pctChange"]==row["pctChange"] else None,
                    "date_reported": str(row.get("Date Reported", "")),
                    "holder_type": "mutual_fund",
                })

        insiders_pct = None
        institutions_pct = None
        float_pct = None
        if mh is not None and not mh.empty:
            for _, row in mh.iterrows():
                label = str(row.get("Breakdown", "")).lower()
                val   = row.get("Value")
                if "insider" in label:
                    insiders_pct = float(val) if val == val else None
                elif "institutionspercentheld" == label.replace(" ", ""):
                    institutions_pct = float(val) if val == val else None
                elif "float" in label:
                    float_pct = float(val) if val == val else None

        return {
            "ticker":            ticker,
            "available":         True,
            "insiders_pct":      insiders_pct,
            "institutions_pct":  institutions_pct,
            "float_pct":         float_pct,
            "top_institutions":  inst_rows[:15],
            "top_mutual_funds":  mf_rows[:10],
        }
    except Exception as exc:
        logger.warning("Institutional holders error %s: %s", ticker, exc)
        return {"ticker": ticker, "available": False, "top_institutions": [], "top_mutual_funds": []}


def get_insider_transactions(ticker: str) -> dict:
    """yfinance Form 4 style insider transactions."""
    try:
        t   = yf.Ticker(ticker)
        it  = t.insider_transactions
        ipu = t.insider_purchases

        txn_rows = []
        if it is not None and not it.empty:
            for _, row in it.iterrows():
                try:
                    shares_val = row.get("Shares")
                    value_val  = row.get("Value")
                    txn_rows.append({
                        "insider":   str(row.get("Insider", "") or ""),
                        "position":  str(row.get("Position", "") or ""),
                        "date":      str(row.get("Start Date", "") or ""),
                        "shares":    int(shares_val) if shares_val is not None and str(shares_val) not in ("nan","<NA>","None") else None,
                        "value":     int(value_val)  if value_val  is not None and str(value_val)  not in ("nan","<NA>","None") else None,
                        "text":      str(row.get("Text", "") or "")[:200],
                        "transaction": "SELL" if "sale" in str(row.get("Text","")).lower() else "BUY",
                    })
                except Exception:
                    continue

        # 6-month purchase summary
        summary = {}
        if ipu is not None and not ipu.empty:
            for _, row in ipu.iterrows():
                label = str(row.get("Insider Purchases Last 6m", "")).strip()
                val   = row.get("Shares")
                if label and val == val:
                    summary[label] = val

        return {
            "ticker":        ticker,
            "available":     bool(txn_rows),
            "transactions":  txn_rows[:20],
            "six_month_summary": summary,
        }
    except Exception as exc:
        logger.warning("Insider txn error %s: %s", ticker, exc)
        return {"ticker": ticker, "available": False, "transactions": [], "six_month_summary": {}}


# ── Quiver Quantitative — Congress trades (free endpoint) ─────────────────────

_CONGRESS_CACHE: list[dict] | None = None
_CONGRESS_CACHE_DATE: str | None = None


def _fetch_congress_all() -> list[dict]:
    global _CONGRESS_CACHE, _CONGRESS_CACHE_DATE
    today = date.today().isoformat()
    if _CONGRESS_CACHE is not None and _CONGRESS_CACHE_DATE == today:
        return _CONGRESS_CACHE
    try:
        r = requests.get(
            "https://api.quiverquant.com/beta/live/congresstrading",
            headers={"Accept": "application/json"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        _CONGRESS_CACHE = r.json()
        _CONGRESS_CACHE_DATE = today
        return _CONGRESS_CACHE
    except Exception as exc:
        logger.warning("Quiver congress error: %s", exc)
        return []


def get_congress_trades(ticker: str | None = None, days: int = 90) -> list[dict]:
    """
    Congress trades from Quiver Quant free endpoint.
    ticker=None returns all recent trades (for dashboard feed).
    """
    all_trades = _fetch_congress_all()
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    results = []
    for t in all_trades:
        txn_date = t.get("TransactionDate") or t.get("ReportDate") or ""
        if txn_date < cutoff:
            continue
        if ticker and t.get("Ticker", "").upper() != ticker.upper():
            continue
        results.append({
            "ticker":           t.get("Ticker", ""),
            "representative":   t.get("Representative", ""),
            "party":            t.get("Party", ""),
            "house":            t.get("House", ""),
            "transaction":      t.get("Transaction", ""),
            "amount":           t.get("Range") or t.get("Amount", ""),
            "transaction_date": txn_date,
            "report_date":      t.get("ReportDate", ""),
        })

    return sorted(results, key=lambda x: x["transaction_date"], reverse=True)


# ── Combined entry point ───────────────────────────────────────────────────────

def get_ownership(ticker: str) -> dict:
    """Full ownership snapshot for one ticker."""
    return {
        "ticker":       ticker,
        "institutional": get_institutional_holders(ticker),
        "insider":       get_insider_transactions(ticker),
        "congress":      get_congress_trades(ticker, days=180),
    }
