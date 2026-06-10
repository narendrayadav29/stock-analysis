"""
Database access layer — SQLite now, Postgres-ready later.
All public functions take plain dicts so callers don't import sqlite3 directly.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from database.schema import SCHEMA

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "database/stocks.db")


# ── Connection ─────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")   # safe for concurrent reads
    return con


def init_db():
    """Create tables if they don't exist. Safe to call on every startup."""
    with _connect() as con:
        con.executescript(SCHEMA)
    logger.info("DB initialised at %s", DB_PATH)


# ── Runs ───────────────────────────────────────────────────────────────────────

def create_run(model: str, notes: str = "") -> int:
    """Insert a new run row. Returns the run_id."""
    now = datetime.now()
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO runs (run_date, run_timestamp, model, notes) VALUES (?,?,?,?)",
            (now.strftime("%Y-%m-%d"), now.isoformat(timespec="seconds"), model, notes),
        )
        return cur.lastrowid


def finish_run(run_id: int, total_stocks: int):
    with _connect() as con:
        con.execute(
            "UPDATE runs SET total_stocks=? WHERE id=?",
            (total_stocks, run_id),
        )


# ── Analyses ───────────────────────────────────────────────────────────────────

def save_analysis(run_id: int, result: dict, collected_data: dict):
    """
    Persist one stock analysis.
    result       — from analyzer.claude_analyzer.analyze_stock()
    collected_data — the raw dict from main.collect_data()
    """
    fund   = collected_data.get("fundamentals", {})
    tech   = collected_data.get("technicals", {})
    sent   = collected_data.get("sentiment", {})
    news   = collected_data.get("news", {})
    fmp    = collected_data.get("fmp", {})

    # Best available price: FMP quote → technicals → None
    price = (fmp.get("quote") or {}).get("price") or tech.get("current_price")

    row = {
        "run_id":          run_id,
        "run_date":        datetime.now().strftime("%Y-%m-%d"),
        "ticker":          result["ticker"],
        "company_name":    result.get("company_name") or fund.get("company_name"),
        "sector":          fund.get("sector"),
        "industry":        fund.get("industry"),
        "verdict":         result.get("verdict"),
        "conviction":      result.get("conviction"),
        "target_low":      result.get("target_low"),
        "target_high":     result.get("target_high"),
        "catalyst":        result.get("catalyst"),
        "summary":         result.get("summary"),
        "price_at_analysis": price,
        "revenue_growth":  fund.get("revenue_growth_yoy"),
        "fwd_pe":          fund.get("pe_forward"),
        "peg_ratio":       fund.get("peg_ratio"),
        "rsi_14":          tech.get("rsi_14"),
        "market_cap":      fund.get("market_cap"),
        "fear_greed_score":sent.get("market_fg_score"),
        "news_sentiment":  news.get("avg_sentiment_score"),
        "macd_signal":     tech.get("macd_signal"),
        "obv_trend":       tech.get("obv_trend"),
        "trend":           tech.get("trend"),
        "full_analysis":   result.get("analysis"),
    }

    cols   = ", ".join(row.keys())
    marks  = ", ".join("?" * len(row))
    values = list(row.values())

    with _connect() as con:
        con.execute(
            f"INSERT OR REPLACE INTO analyses ({cols}) VALUES ({marks})",
            values,
        )
    logger.debug("Saved analysis: %s %s", result["ticker"], result.get("verdict"))


# ── Portfolio rankings ─────────────────────────────────────────────────────────

def save_portfolio_ranking(run_id: int, report_text: str, analyses: list[dict]):
    """Persist the portfolio ranking report and extract top-10 tickers."""
    top_picks = [
        a["ticker"] for a in analyses
        if a.get("verdict") in ("STRONG BUY", "BUY")
    ][:10]

    with _connect() as con:
        con.execute(
            """INSERT OR REPLACE INTO portfolio_rankings
               (run_id, run_date, report_text, top_picks)
               VALUES (?,?,?,?)""",
            (run_id,
             datetime.now().strftime("%Y-%m-%d"),
             report_text,
             json.dumps(top_picks)),
        )


# ── Actual price tracking ──────────────────────────────────────────────────────

def update_actuals(ticker: str, run_date: str, period: str, actual_price: float):
    """
    Fill in the actual price N days after the prediction.
    period: '1d' | '7d' | '30d' | '90d'
    Called by track_actuals.py on a schedule.
    """
    with _connect() as con:
        row = con.execute(
            "SELECT price_at_analysis, target_low, target_high FROM analyses WHERE ticker=? AND run_date=?",
            (ticker, run_date),
        ).fetchone()
        if not row:
            return

        base  = row["price_at_analysis"]
        t_lo  = row["target_low"]
        t_hi  = row["target_high"]

        ret = round((actual_price - base) / base * 100, 2) if base else None
        hit = int(bool(t_lo and t_hi and t_lo <= actual_price <= t_hi))

        con.execute(
            f"""UPDATE analyses
                SET price_{period}=?, return_{period}=?, hit_target_{period}=?
                WHERE ticker=? AND run_date=?""",
            (actual_price, ret, hit, ticker, run_date),
        )


# ── Query helpers ──────────────────────────────────────────────────────────────

def get_history(ticker: str, limit: int = 30) -> list[dict]:
    """All predictions for a ticker, newest first."""
    with _connect() as con:
        rows = con.execute(
            """SELECT run_date, verdict, conviction, target_low, target_high,
                      price_at_analysis, return_7d, return_30d, return_90d,
                      hit_target_30d, summary, catalyst
               FROM analyses
               WHERE ticker=?
               ORDER BY run_date DESC
               LIMIT ?""",
            (ticker, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_todays_picks(run_date: str | None = None) -> list[dict]:
    """All analyses for a specific date (default: today)."""
    date = run_date or datetime.now().strftime("%Y-%m-%d")
    with _connect() as con:
        rows = con.execute(
            """SELECT ticker, company_name, verdict, conviction,
                      target_low, target_high, price_at_analysis,
                      rsi_14, revenue_growth, fear_greed_score,
                      catalyst, summary
               FROM analyses WHERE run_date=?
               ORDER BY
                 CASE verdict
                   WHEN 'STRONG BUY' THEN 1
                   WHEN 'BUY'        THEN 2
                   WHEN 'HOLD'       THEN 3
                   WHEN 'REDUCE'     THEN 4
                   WHEN 'AVOID'      THEN 5
                   ELSE 6
                 END, conviction DESC""",
            (date,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_accuracy_summary() -> list[dict]:
    """Aggregate accuracy stats per verdict type."""
    with _connect() as con:
        rows = con.execute(
            """SELECT verdict,
                      COUNT(*) as total,
                      AVG(return_7d)     as avg_return_7d,
                      AVG(return_30d)    as avg_return_30d,
                      AVG(return_90d)    as avg_return_90d,
                      SUM(hit_target_30d) * 100.0 / COUNT(*) as hit_rate_30d
               FROM analyses
               WHERE price_at_analysis IS NOT NULL
               GROUP BY verdict
               ORDER BY avg_return_30d DESC""",
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_runs() -> list[dict]:
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM runs ORDER BY run_timestamp DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ── Sentiment pulls ────────────────────────────────────────────────────────────

def save_sentiment_pull(pull_date: str, fear_greed: dict, stocks: list[dict]):
    """
    Persist one daily sentiment pull.
    stocks: list of {ticker, news:{score, label, articles}, polygon:{change_pct, volume}}
    """
    now = datetime.now().isoformat(timespec="seconds")
    fg_score  = fear_greed.get("score")
    fg_rating = fear_greed.get("rating")
    fg_trend  = fear_greed.get("trend")

    with _connect() as con:
        for s in stocks:
            ticker = s["ticker"]
            news   = s.get("news", {})
            poly   = s.get("polygon", {})
            yf_    = s.get("yfinance", {})

            price_chg  = yf_.get("change_pct") or poly.get("change_pct")
            vol        = yf_.get("volume") or poly.get("volume")
            avg_vol    = yf_.get("avg_volume")
            vol_ratio  = round(vol / avg_vol, 2) if vol and avg_vol else None
            price      = yf_.get("price") or poly.get("price")

            con.execute(
                """INSERT OR REPLACE INTO sentiment_pulls
                   (pull_date, pull_timestamp, ticker,
                    news_score, news_label, news_articles,
                    price_change_pct, volume, avg_volume, volume_ratio, price,
                    fear_greed_score, fear_greed_rating, fear_greed_trend)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pull_date, now, ticker,
                 news.get("score"), news.get("label"), news.get("articles") or 0,
                 price_chg, vol, avg_vol, vol_ratio, price,
                 fg_score, fg_rating, fg_trend),
            )
    logger.info("Saved sentiment pull: %s (%d stocks)", pull_date, len(stocks))


def get_sentiment_history(tickers: list[str] | None = None, days: int = 90) -> list[dict]:
    """All sentiment_pulls rows for given tickers, newest first."""
    with _connect() as con:
        if tickers:
            all_rows = []
            for ticker in tickers:
                rows = con.execute(
                    """SELECT * FROM sentiment_pulls
                       WHERE ticker=?
                       ORDER BY pull_date DESC LIMIT ?""",
                    (ticker, days),
                ).fetchall()
                all_rows.extend(rows)
            return sorted([dict(r) for r in all_rows],
                          key=lambda x: x["pull_date"], reverse=True)
        else:
            rows = con.execute(
                "SELECT * FROM sentiment_pulls ORDER BY pull_date DESC LIMIT ?",
                (days * 50,),
            ).fetchall()
        return [dict(r) for r in rows]


# ── Institutional holdings ─────────────────────────────────────────────────────

def save_institutional_holdings(pull_date: str, ticker: str, data: dict):
    with _connect() as con:
        for row in data.get("top_institutions", []) + data.get("top_mutual_funds", []):
            con.execute(
                """INSERT OR REPLACE INTO institutional_holdings
                   (pull_date, ticker, holder, holder_type, shares, value,
                    pct_held, pct_change, date_reported)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (pull_date, ticker,
                 row.get("holder"), row.get("holder_type"),
                 row.get("shares"), row.get("value"),
                 row.get("pct_held"), row.get("pct_change"),
                 row.get("date_reported")),
            )


def get_institutional_holdings(ticker: str | None = None) -> list[dict]:
    with _connect() as con:
        if ticker:
            rows = con.execute(
                """SELECT * FROM institutional_holdings WHERE ticker=?
                   ORDER BY pull_date DESC, pct_held DESC""", (ticker,)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM institutional_holdings ORDER BY pull_date DESC, pct_held DESC"
            ).fetchall()
        return [dict(r) for r in rows]


# ── Congress trades ────────────────────────────────────────────────────────────

def save_congress_trades(trades: list[dict]):
    with _connect() as con:
        for t in trades:
            con.execute(
                """INSERT OR IGNORE INTO congress_trades
                   (transaction_date, report_date, ticker, representative,
                    party, house, txn_type, amount)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (t.get("transaction_date"), t.get("report_date"),
                 t.get("ticker"), t.get("representative"),
                 t.get("party"), t.get("house"),
                 t.get("transaction"), t.get("amount")),
            )


def get_congress_trades(ticker: str | None = None, days: int = 90) -> list[dict]:
    cutoff = (datetime.now().date() - timedelta(days=days)).isoformat()
    with _connect() as con:
        if ticker:
            rows = con.execute(
                """SELECT * FROM congress_trades
                   WHERE ticker=? AND transaction_date >= ?
                   ORDER BY transaction_date DESC""",
                (ticker, cutoff),
            ).fetchall()
        else:
            rows = con.execute(
                """SELECT * FROM congress_trades
                   WHERE transaction_date >= ?
                   ORDER BY transaction_date DESC""",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]


# ── EDGAR fundamentals ────────────────────────────────────────────────────────

def save_edgar_fundamentals(pull_date: str, ticker: str, facts: dict):
    with _connect() as con:
        for metric, series in facts.get("quarterly", {}).items():
            for point in series:
                con.execute(
                    """INSERT OR REPLACE INTO edgar_fundamentals
                       (pull_date, ticker, quarter_end, metric, value)
                       VALUES (?,?,?,?,?)""",
                    (pull_date, ticker, point["date"], metric, point["value"]),
                )


def get_edgar_fundamentals(ticker: str, metric: str | None = None) -> list[dict]:
    with _connect() as con:
        if metric:
            rows = con.execute(
                """SELECT * FROM edgar_fundamentals
                   WHERE ticker=? AND metric=? ORDER BY quarter_end""",
                (ticker, metric),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM edgar_fundamentals WHERE ticker=? ORDER BY quarter_end",
                (ticker,),
            ).fetchall()
        return [dict(r) for r in rows]


# ── Macro data ────────────────────────────────────────────────────────────────

def save_macro_data(pull_date: str, macro: dict):
    with _connect() as con:
        for key, series in macro.get("series", {}).items():
            series_id = series.get("id", key)
            for point in series.get("history", []):
                con.execute(
                    """INSERT OR REPLACE INTO macro_data
                       (pull_date, series_key, series_id, data_date, value)
                       VALUES (?,?,?,?,?)""",
                    (pull_date, key, series_id, point["date"], point["value"]),
                )


def get_macro_series(series_key: str, limit: int = 60) -> list[dict]:
    with _connect() as con:
        rows = con.execute(
            """SELECT data_date, value FROM macro_data
               WHERE series_key=? ORDER BY data_date DESC LIMIT ?""",
            (series_key, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]
