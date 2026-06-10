#!/usr/bin/env python3
"""
Fetches actual prices for past predictions and fills in return columns.
Run this daily (or add to cron) to build the accuracy dataset over time.

Usage:
  python -m database.track_actuals           # fill all pending actuals
  python -m database.track_actuals --date 2026-06-04  # specific date only
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import warnings
from datetime import date, datetime, timedelta

warnings.filterwarnings("ignore")
import yfinance as yf

from database.db import _connect, update_actuals

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

PERIODS = {
    "1d":  1,
    "7d":  7,
    "30d": 30,
    "90d": 90,
}


def _fetch_price_on_date(ticker: str, target_date: date) -> float | None:
    """Return the closing price on or just after target_date using yfinance."""
    try:
        start = target_date.isoformat()
        end   = (target_date + timedelta(days=5)).isoformat()  # buffer for weekends/holidays
        df    = yf.Ticker(ticker).history(start=start, end=end)
        if df.empty:
            return None
        return round(float(df["Close"].iloc[0]), 2)
    except Exception as exc:
        logger.warning("Price fetch failed for %s on %s: %s", ticker, target_date, exc)
        return None


def fill_actuals(run_date_filter: str | None = None):
    """
    For every analysis row where price_at_analysis exists but some return columns
    are still NULL and enough time has passed, fetch and store actual prices.
    """
    today = date.today()

    with _connect() as con:
        query = """
            SELECT ticker, run_date, price_at_analysis,
                   price_1d, price_7d, price_30d, price_90d
            FROM analyses
            WHERE price_at_analysis IS NOT NULL
        """
        params = []
        if run_date_filter:
            query += " AND run_date = ?"
            params.append(run_date_filter)

        rows = con.execute(query, params).fetchall()

    updated = 0
    for row in rows:
        ticker   = row["ticker"]
        run_date = date.fromisoformat(row["run_date"])

        for period, days in PERIODS.items():
            col = f"price_{period}"
            if row[col] is not None:
                continue  # already filled

            target_date = run_date + timedelta(days=days)
            if target_date > today:
                continue  # not enough time has passed yet

            price = _fetch_price_on_date(ticker, target_date)
            if price is None:
                continue

            update_actuals(ticker, row["run_date"], period, price)
            logger.info("Updated %s %s %s → $%.2f", ticker, row["run_date"], period, price)
            updated += 1

    logger.info("Done. Updated %d price data points.", updated)
    return updated


def print_accuracy_report():
    """Print a summary of prediction accuracy from the DB."""
    with _connect() as con:
        rows = con.execute("""
            SELECT verdict,
                   COUNT(*) as n,
                   ROUND(AVG(return_7d), 1)  as avg_7d,
                   ROUND(AVG(return_30d), 1) as avg_30d,
                   ROUND(AVG(return_90d), 1) as avg_90d,
                   ROUND(SUM(hit_target_30d) * 100.0 / MAX(COUNT(*), 1), 0) as hit_pct_30d
            FROM analyses
            WHERE price_at_analysis IS NOT NULL
            GROUP BY verdict
            ORDER BY CASE verdict
                WHEN 'STRONG BUY' THEN 1 WHEN 'BUY' THEN 2
                WHEN 'HOLD' THEN 3 WHEN 'REDUCE' THEN 4
                WHEN 'AVOID' THEN 5 ELSE 6 END
        """).fetchall()

    if not rows:
        print("No accuracy data yet — run again after 7+ days.")
        return

    print(f"\n{'Verdict':<12} {'N':>4}  {'7d%':>6}  {'30d%':>6}  {'90d%':>6}  {'Hit30d%':>8}")
    print("─" * 52)
    for r in rows:
        print(
            f"{(r['verdict'] or 'N/A'):<12} {r['n']:>4}  "
            f"{(str(r['avg_7d'])+'%') if r['avg_7d'] else 'N/A':>6}  "
            f"{(str(r['avg_30d'])+'%') if r['avg_30d'] else 'N/A':>6}  "
            f"{(str(r['avg_90d'])+'%') if r['avg_90d'] else 'N/A':>6}  "
            f"{(str(int(r['hit_pct_30d']))+'%') if r['hit_pct_30d'] else 'N/A':>8}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fill in actual prices for past predictions")
    parser.add_argument("--date", help="Only process analyses from this date (YYYY-MM-DD)")
    parser.add_argument("--report", action="store_true", help="Print accuracy summary and exit")
    args = parser.parse_args()

    if args.report:
        print_accuracy_report()
    else:
        fill_actuals(args.date)
        print_accuracy_report()
