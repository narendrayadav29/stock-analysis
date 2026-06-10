"""
SQLite schema — designed so every column maps 1-to-1 to a Postgres column later.
Migration path: swap sqlite3 for psycopg2 + change AUTOINCREMENT → SERIAL.
"""

SCHEMA = """
-- One row per analysis run (daily job invocation)
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date      TEXT    NOT NULL,          -- YYYY-MM-DD
    run_timestamp TEXT    NOT NULL,          -- ISO-8601 datetime
    total_stocks  INTEGER DEFAULT 0,
    model         TEXT,
    notes         TEXT,
    created_at    TEXT    DEFAULT (datetime('now'))
);

-- One row per stock per run
CREATE TABLE IF NOT EXISTS analyses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL REFERENCES runs(id),
    run_date      TEXT    NOT NULL,
    ticker        TEXT    NOT NULL,
    company_name  TEXT,
    sector        TEXT,
    industry      TEXT,

    -- Claude verdict
    verdict       TEXT,                      -- STRONG BUY / BUY / HOLD / REDUCE / AVOID
    conviction    TEXT,                      -- HIGH / MEDIUM / LOW
    target_low    REAL,
    target_high   REAL,
    catalyst      TEXT,
    summary       TEXT,

    -- Price snapshot at time of analysis
    price_at_analysis REAL,

    -- Key metric snapshot (for backtesting / feature engineering)
    revenue_growth    REAL,
    fwd_pe            REAL,
    peg_ratio         REAL,
    rsi_14            REAL,
    market_cap        REAL,
    fear_greed_score  REAL,
    news_sentiment    REAL,
    macd_signal       TEXT,
    obv_trend         TEXT,
    trend             TEXT,

    -- Actual price outcomes (filled by track_actuals.py after N days)
    price_1d      REAL,
    price_7d      REAL,
    price_30d     REAL,
    price_90d     REAL,
    return_1d     REAL,                      -- % change vs price_at_analysis
    return_7d     REAL,
    return_30d    REAL,
    return_90d    REAL,
    hit_target_7d  INTEGER DEFAULT 0,        -- 1 if price touched target range within 7d
    hit_target_30d INTEGER DEFAULT 0,
    hit_target_90d INTEGER DEFAULT 0,

    -- Full Claude analysis text
    full_analysis TEXT,

    created_at    TEXT DEFAULT (datetime('now')),

    UNIQUE(run_date, ticker)                 -- one analysis per ticker per day
);

-- Portfolio ranking reports
CREATE TABLE IF NOT EXISTS portfolio_rankings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES runs(id),
    run_date    TEXT    NOT NULL UNIQUE,
    report_text TEXT,
    top_picks   TEXT,                        -- JSON array of top 10 tickers
    created_at  TEXT DEFAULT (datetime('now'))
);

-- Lightweight daily sentiment pulls (no Claude required)
CREATE TABLE IF NOT EXISTS sentiment_pulls (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    pull_date         TEXT    NOT NULL,         -- YYYY-MM-DD
    pull_timestamp    TEXT    NOT NULL,
    ticker            TEXT    NOT NULL,
    news_score        REAL,                     -- Alpha Vantage score (-1 to +1)
    news_label        TEXT,
    news_articles     INTEGER DEFAULT 0,
    price_change_pct  REAL,                     -- today's % change (yfinance)
    volume            REAL,                     -- today's volume
    avg_volume        REAL,                     -- 3-month avg volume
    volume_ratio      REAL,                     -- today / avg
    price             REAL,
    fear_greed_score  INTEGER,
    fear_greed_rating TEXT,
    fear_greed_trend  TEXT,
    created_at        TEXT DEFAULT (datetime('now')),
    UNIQUE(pull_date, ticker)
);

-- Institutional & mutual fund holders snapshot per ticker per pull date
CREATE TABLE IF NOT EXISTS institutional_holdings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pull_date       TEXT    NOT NULL,
    ticker          TEXT    NOT NULL,
    holder          TEXT    NOT NULL,
    holder_type     TEXT    NOT NULL,   -- 'institution' | 'mutual_fund'
    shares          INTEGER,
    value           INTEGER,
    pct_held        REAL,
    pct_change      REAL,               -- QoQ change in position
    date_reported   TEXT,               -- as-of date from yfinance
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(pull_date, ticker, holder, holder_type)
);

-- Congress trading disclosures (STOCK Act filings)
CREATE TABLE IF NOT EXISTS congress_trades (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_date TEXT    NOT NULL,
    report_date      TEXT,
    ticker           TEXT    NOT NULL,
    representative   TEXT    NOT NULL,
    party            TEXT,
    house            TEXT,               -- 'Senate' | 'Representatives'
    txn_type         TEXT,               -- 'Purchase' | 'Sale'
    amount           TEXT,               -- range string e.g. "$1,001 - $15,000"
    created_at       TEXT DEFAULT (datetime('now')),
    UNIQUE(transaction_date, ticker, representative, txn_type)
);

-- EDGAR quarterly fundamentals per ticker
CREATE TABLE IF NOT EXISTS edgar_fundamentals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pull_date       TEXT    NOT NULL,
    ticker          TEXT    NOT NULL,
    quarter_end     TEXT    NOT NULL,   -- YYYY-MM-DD
    metric          TEXT    NOT NULL,   -- revenue | net_income | eps_diluted | ...
    value           REAL,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(ticker, quarter_end, metric)
);

-- FRED macro snapshots (one row per series per date)
CREATE TABLE IF NOT EXISTS macro_data (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pull_date   TEXT NOT NULL,
    series_key  TEXT NOT NULL,          -- fed_funds | cpi | gdp | ...
    series_id   TEXT NOT NULL,          -- FRED series ID
    data_date   TEXT NOT NULL,          -- date of the observation
    value       REAL,
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(series_key, data_date)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_analyses_ticker        ON analyses(ticker);
CREATE INDEX IF NOT EXISTS idx_analyses_run_date      ON analyses(run_date);
CREATE INDEX IF NOT EXISTS idx_analyses_verdict       ON analyses(verdict);
CREATE INDEX IF NOT EXISTS idx_sentiment_ticker       ON sentiment_pulls(ticker);
CREATE INDEX IF NOT EXISTS idx_sentiment_pull_date    ON sentiment_pulls(pull_date);
CREATE INDEX IF NOT EXISTS idx_holdings_ticker        ON institutional_holdings(ticker);
CREATE INDEX IF NOT EXISTS idx_holdings_date          ON institutional_holdings(pull_date);
CREATE INDEX IF NOT EXISTS idx_congress_ticker        ON congress_trades(ticker);
CREATE INDEX IF NOT EXISTS idx_congress_date          ON congress_trades(transaction_date);
CREATE INDEX IF NOT EXISTS idx_edgar_ticker           ON edgar_fundamentals(ticker);
CREATE INDEX IF NOT EXISTS idx_macro_key              ON macro_data(series_key);
"""
