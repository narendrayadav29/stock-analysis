# Stock Analysis AI

An AI-powered growth stock analyzer that pulls data from multiple free and paid sources, runs each stock through Claude, and surfaces verdicts, price targets, and catalysts in a Streamlit dashboard.

![Python](https://img.shields.io/badge/python-3.9%2B-blue) ![Streamlit](https://img.shields.io/badge/streamlit-1.35%2B-red) ![Claude](https://img.shields.io/badge/Claude-claude--sonnet--4--6-blueviolet)

---

## Features

- **Claude AI verdicts** — STRONG BUY / BUY / HOLD / REDUCE / AVOID with conviction score, price targets, and catalyst summary
- **7-page Streamlit dashboard** — Sentiment timeline, fundamentals, ownership & flows, macro & markets, prediction accuracy
- **Multi-source data pipeline** — yfinance, Alpha Vantage, FMP, Finnhub, SEC EDGAR, FRED, Quiver Congress trades
- **Prediction tracking** — Automatically fills in actual prices at 1d/7d/30d/90d to measure model accuracy
- **Daily scheduler** — launchd plist for automated macOS runs with native notifications

---

## Data Sources

| Source | Data | Cost |
|--------|------|------|
| yfinance | Price, fundamentals, institutional holders, insider txns | Free |
| Alpha Vantage | News sentiment (batched, 25 req/day) | Free |
| SEC EDGAR XBRL | Quarterly financials (revenue, EPS, assets) | Free |
| FRED (Federal Reserve) | GDP, CPI, Fed funds, Treasury yields, unemployment | Free |
| Quiver Quant | Congress STOCK Act trading disclosures | Free |
| Fear & Greed Index | Market-wide sentiment score | Free |
| Finnhub | Insider transactions, earnings calendar | Free tier |
| Financial Modeling Prep | Fundamentals, income statements, profiles | Paid |
| Polygon.io | Real-time prices, options flow | Paid |
| Nasdaq Data Link | Sharadar SF1 fundamentals overlay | Paid (~$30/mo) |

---

## Quickstart

### 1. Clone & install

```bash
git clone https://github.com/npab29/stock-analysis.git
cd stock-analysis
pip install -r requirements.txt
```

### 2. Configure API keys

```bash
cp .env.example .env
# Edit .env and fill in your keys
```

At minimum you need free keys from [Alpha Vantage](https://www.alphavantage.co/support/#api-key) and [Finnhub](https://finnhub.io/register). Everything else is optional.

### 3. Run an analysis

```bash
# Full run — top 50 growth stocks
python3 main.py

# Quick test with 5 stocks
python3 main.py --limit 5

# Specific tickers
python3 main.py --tickers NVDA,AMD,TSLA

# Collect data only, skip Claude (dry run)
python3 main.py --limit 5 --dry-run
```

### 4. Pull sentiment & ownership data

```bash
# Daily sentiment (news + Fear & Greed + price/volume)
python3 pull_sentiment.py --limit 20

# Ownership, Congress trades, SEC EDGAR, macro (FRED + indices)
python3 pull_ownership_macro.py --limit 30

# Macro only
python3 pull_ownership_macro.py --macro-only
```

### 5. Launch the dashboard

```bash
streamlit run dashboard.py
# → http://localhost:8501
```

---

## Dashboard Pages

| Page | Contents |
|------|----------|
| Overview | Today's picks ranked by verdict and conviction |
| Sentiment Timeline | News sentiment scores and Fear & Greed over time |
| Fundamentals | Revenue growth, margins, PE, PEG by ticker |
| Ownership & Flows | Institutional holders, Congress trades, insider activity |
| Macro & Markets | FRED series (GDP, CPI, rates), index performance, yield curve |
| Claude Verdicts | Full AI analysis text per ticker |
| Prediction Accuracy | Hit rate and return attribution by verdict type |

---

## Automated Daily Runs (macOS)

```bash
# Install the launchd scheduler (runs daily at 7 AM)
cp com.stockanalyzer.daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.stockanalyzer.daily.plist

# Or run manually
./run_daily.sh
```

Logs are written to `logs/daily_YYYY-MM-DD.log`. macOS notifications fire on completion.

---

## Project Structure

```
stock-analysis/
├── main.py                      # Main analysis runner
├── pull_sentiment.py            # Daily sentiment pull
├── pull_ownership_macro.py      # Ownership, EDGAR, macro pull
├── dashboard.py                 # Streamlit dashboard
├── config.py                    # API keys and runtime config
├── run_daily.sh                 # Shell wrapper for scheduler
├── com.stockanalyzer.daily.plist # macOS launchd schedule
├── analyzer/
│   ├── claude_analyzer.py       # Claude verdict + target generation
│   └── portfolio_ranker.py      # Cross-stock portfolio ranking
├── data_sources/
│   ├── stock_universe.py        # Top 50 growth stock list
│   ├── fundamentals_collector.py
│   ├── technicals_collector.py
│   ├── sentiment_collector.py   # Fear & Greed
│   ├── news_collector.py        # Alpha Vantage news sentiment
│   ├── insider_collector.py     # Finnhub insider data
│   ├── fmp_collector.py         # Financial Modeling Prep
│   ├── polygon_collector.py     # Polygon.io
│   ├── ownership_collector.py   # yfinance 13F + Quiver Congress
│   ├── edgar_collector.py       # SEC EDGAR XBRL fundamentals
│   └── macro_collector.py       # FRED + yfinance indices
├── database/
│   ├── schema.py                # SQLite table definitions
│   ├── db.py                    # Data access layer
│   └── track_actuals.py         # Backfill actual prices
└── requirements.txt
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ALPHA_VANTAGE_KEY` | Yes | News sentiment (free, 25 req/day) |
| `FINNHUB_KEY` | Yes | Insider transactions (free tier) |
| `FMP_KEY` | Optional | Financial Modeling Prep fundamentals |
| `POLYGON_KEY` | Optional | Real-time prices and options flow |
| `NASDAQ_DATA_LINK_KEY` | Optional | Sharadar SF1 premium fundamentals |
| `CLAUDE_MODEL` | No | Default: `claude-sonnet-4-6` |
| `RATE_LIMIT_DELAY` | No | Seconds between analyses (default: 2) |

---

## License

MIT
