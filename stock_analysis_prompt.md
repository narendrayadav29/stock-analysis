# Complete Stock Analysis System: Claude + StockTwits + Multi-Source Pipeline

## Architecture Overview

```
Data Sources → Aggregator → Claude Analysis Engine → Report
     ↓
StockTwits (sentiment)
Yahoo Finance (fundamentals, price)
SEC EDGAR (filings, earnings)
Alpha Vantage / Polygon (technicals)
Reddit / News (macro sentiment)
```

---

## PART 1: DATA COLLECTION PIPELINE (Python)

### Install dependencies
```bash
pip install requests yfinance pandas anthropic sec-edgar-downloader \
            finnhub-python python-dotenv schedule rich tabulate
```

### Environment variables (.env)
```
ANTHROPIC_API_KEY=your_key
STOCKTWITS_ACCESS_TOKEN=your_token      # free at stocktwits.com/developers
ALPHA_VANTAGE_KEY=your_key              # free at alphavantage.co
FINNHUB_KEY=your_key                    # free at finnhub.io
POLYGON_KEY=your_key                    # paid, starts $29/mo
FMP_KEY=your_key                        # financialmodelingprep.com free tier
```

---

## PART 2: STOCK UNIVERSE — TOP 50 GROWTH STOCKS

### data_sources/stock_universe.py
```python
import yfinance as yf
import pandas as pd

GROWTH_STOCK_UNIVERSE = [
    # Mega-cap growth
    "NVDA", "META", "AMZN", "GOOGL", "MSFT", "AAPL", "TSLA",
    # High-growth tech
    "PLTR", "SNOW", "CRWD", "NET", "DDOG", "MDB", "MELI",
    "SHOP", "ABNB", "UBER", "LYFT", "RBLX", "COIN",
    # AI / Semiconductors
    "AMD", "AVGO", "ARM", "SMCI", "ALAB", "MRVL", "QCOM",
    # Biotech / Healthcare growth
    "MRNA", "REGN", "ISRG", "DXCM", "VEEV",
    # Fintech
    "SQ", "AFRM", "UPST", "SOFI", "NU",
    # Consumer / Media
    "NFLX", "SPOT", "PINS", "SNAP", "DUOL",
    # Energy transition
    "ENPH", "FSLR", "PLUG", "RUN",
    # Emerging growth
    "TTD", "ZS", "HUBS", "GTLB", "BILL"
]

def screen_top_50_growth(universe=GROWTH_STOCK_UNIVERSE):
    """Return top 50 by revenue growth + momentum score."""
    ranked = []
    for ticker in universe:
        try:
            info = yf.Ticker(ticker).info
            rev_growth = info.get("revenueGrowth", 0) or 0
            fwd_pe = info.get("forwardPE", 999) or 999
            mkt_cap = info.get("marketCap", 0) or 0
            price_change_52w = (
                (info.get("currentPrice", 0) - info.get("fiftyTwoWeekLow", 1))
                / max(info.get("fiftyTwoWeekLow", 1), 1)
            )
            score = (rev_growth * 0.4) + (price_change_52w * 0.3) + (1/max(fwd_pe,1) * 0.3)
            ranked.append({
                "ticker": ticker,
                "revenue_growth": rev_growth,
                "fwd_pe": fwd_pe,
                "market_cap": mkt_cap,
                "momentum_52w": price_change_52w,
                "composite_score": score
            })
        except Exception:
            continue
    df = pd.DataFrame(ranked).sort_values("composite_score", ascending=False)
    return df.head(50)
```

---

## PART 3: DATA COLLECTORS

### data_sources/stocktwits_collector.py
```python
import requests, os

BASE = "https://api.stocktwits.com/api/2"
TOKEN = os.getenv("STOCKTWITS_ACCESS_TOKEN")

def get_sentiment(ticker: str, limit: int = 100) -> dict:
    """Fetch recent messages + sentiment for a ticker."""
    url = f"{BASE}/streams/symbol/{ticker}.json"
    params = {"access_token": TOKEN, "limit": limit, "filter": "all"}
    r = requests.get(url, params=params, timeout=10)
    data = r.json()

    messages = data.get("messages", [])
    bull = sum(1 for m in messages if m.get("entities", {}).get("sentiment", {}).get("basic") == "Bullish")
    bear = sum(1 for m in messages if m.get("entities", {}).get("sentiment", {}).get("basic") == "Bearish")
    total = len(messages)

    return {
        "ticker": ticker,
        "total_messages": total,
        "bullish_count": bull,
        "bearish_count": bear,
        "neutral_count": total - bull - bear,
        "bull_ratio": bull / max(total, 1),
        "bear_ratio": bear / max(total, 1),
        "recent_messages": [m["body"] for m in messages[:20]],  # top 20 for Claude
        "watchers": data.get("symbol", {}).get("watchlist_count", 0),
    }

def get_trending_symbols(limit: int = 30) -> list:
    """Get currently trending tickers on StockTwits."""
    url = f"{BASE}/trending/symbols.json"
    params = {"access_token": TOKEN, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    return [s["symbol"] for s in r.json().get("symbols", [])]
```

### data_sources/fundamentals_collector.py
```python
import yfinance as yf
import requests, os

FMP_KEY = os.getenv("FMP_KEY")

def get_fundamentals(ticker: str) -> dict:
    """Aggregate fundamental data from yfinance + FMP."""
    t = yf.Ticker(ticker)
    info = t.info
    fin = t.financials
    bs = t.balance_sheet
    cf = t.cashflow

    # Revenue trend (last 4 quarters)
    try:
        q_rev = t.quarterly_financials.loc["Total Revenue"].head(4).tolist()
    except Exception:
        q_rev = []

    # Free cash flow
    try:
        fcf = cf.loc["Free Cash Flow"].iloc[0] if "Free Cash Flow" in cf.index else None
    except Exception:
        fcf = None

    return {
        "ticker": ticker,
        "company_name": info.get("longName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": info.get("marketCap"),
        "revenue_growth_yoy": info.get("revenueGrowth"),
        "earnings_growth_yoy": info.get("earningsGrowth"),
        "gross_margin": info.get("grossMargins"),
        "operating_margin": info.get("operatingMargins"),
        "net_margin": info.get("profitMargins"),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "peg_ratio": info.get("pegRatio"),
        "ps_ratio": info.get("priceToSalesTrailing12Months"),
        "pb_ratio": info.get("priceToBook"),
        "debt_to_equity": info.get("debtToEquity"),
        "current_ratio": info.get("currentRatio"),
        "roe": info.get("returnOnEquity"),
        "roa": info.get("returnOnAssets"),
        "revenue_ttm": info.get("totalRevenue"),
        "ebitda": info.get("ebitda"),
        "free_cash_flow": fcf,
        "quarterly_revenue_trend": q_rev,
        "analyst_target_price": info.get("targetMeanPrice"),
        "analyst_recommendation": info.get("recommendationKey"),
        "num_analyst_opinions": info.get("numberOfAnalystOpinions"),
        "eps_next_year": info.get("forwardEps"),
        "description": info.get("longBusinessSummary", "")[:800],
    }

def get_earnings_calendar(ticker: str) -> dict:
    """Get upcoming earnings date and estimates."""
    t = yf.Ticker(ticker)
    cal = t.calendar
    history = t.earnings_history
    return {
        "next_earnings_date": str(cal.get("Earnings Date", [None])[0]) if cal else None,
        "eps_estimate": cal.get("EPS Estimate") if cal else None,
        "eps_actual_last": history["epsActual"].iloc[0] if history is not None and len(history) else None,
        "surprise_pct_last": history["epsSurprisePct"].iloc[0] if history is not None and len(history) else None,
    }
```

### data_sources/technicals_collector.py
```python
import yfinance as yf
import pandas as pd

def get_technicals(ticker: str, period: str = "6mo") -> dict:
    """Compute key technical indicators."""
    df = yf.Ticker(ticker).history(period=period)
    if df.empty:
        return {}

    close = df["Close"]
    volume = df["Volume"]

    # Moving averages
    ma20 = close.rolling(20).mean().iloc[-1]
    ma50 = close.rolling(50).mean().iloc[-1]
    ma200 = close.rolling(200, min_periods=100).mean().iloc[-1]
    current = close.iloc[-1]

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi = (100 - 100 / (1 + rs)).iloc[-1]

    # Volume trend
    avg_vol_20 = volume.rolling(20).mean().iloc[-1]
    vol_today = volume.iloc[-1]
    vol_ratio = vol_today / max(avg_vol_20, 1)

    # MACD
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9).mean()
    macd_hist = (macd_line - signal).iloc[-1]

    # Institutional buy/sell pressure (OBV trend)
    obv = (volume * (close.diff() > 0).astype(int) - volume * (close.diff() < 0).astype(int)).cumsum()
    obv_trend = "rising" if obv.iloc[-1] > obv.iloc[-20] else "falling"

    return {
        "ticker": ticker,
        "current_price": round(current, 2),
        "ma20": round(ma20, 2),
        "ma50": round(ma50, 2),
        "ma200": round(float(ma200), 2) if not pd.isna(ma200) else None,
        "price_vs_ma50_pct": round((current - ma50) / ma50 * 100, 1),
        "rsi_14": round(rsi, 1),
        "macd_histogram": round(macd_hist, 3),
        "volume_ratio_vs_20d_avg": round(vol_ratio, 2),
        "obv_trend": obv_trend,
        "week_52_high": round(df["High"].max(), 2),
        "week_52_low": round(df["Low"].min(), 2),
        "pct_from_52w_high": round((current - df["High"].max()) / df["High"].max() * 100, 1),
    }
```

---

## PART 4: THE CLAUDE ANALYSIS PROMPT

### analyzer/claude_prompt.py
```python
import anthropic, json

client = anthropic.Anthropic()

SYSTEM_PROMPT = """You are an elite quantitative equity analyst and behavioral finance expert.
You analyze growth stocks by synthesizing: company fundamentals, retail investor sentiment,
technical price action, earnings trajectory, and macro trends.

Your analysis framework:
1. FUNDAMENTAL QUALITY — Is the business growing revenue/earnings durably? Are margins expanding?
2. VALUATION CONTEXT — Is the market pricing in achievable growth? PEG, PS, FCF yield.
3. SENTIMENT SIGNAL — What is retail crowd positioning? Extreme bull/bear divergence matters.
4. TECHNICAL STRUCTURE — Is price above key MAs? Is momentum building or decaying?
5. EARNINGS TRAJECTORY — Beat/miss history, forward estimates, guidance tone.
6. RISK ASSESSMENT — Key threats: competition, valuation compression, macro sensitivity.
7. COMPOSITE VERDICT — Conviction-weighted BUY / HOLD / REDUCE / AVOID with target range.

Be concise, data-driven, and direct. Avoid generic filler. Call out non-obvious insights."""


def build_analysis_prompt(ticker: str, fundamentals: dict, sentiment: dict,
                           technicals: dict, earnings: dict) -> str:
    return f"""
Analyze {ticker} ({fundamentals.get('company_name', ticker)}) as a growth stock opportunity.

## FUNDAMENTALS
- Sector: {fundamentals.get('sector')} | Industry: {fundamentals.get('industry')}
- Market Cap: ${fundamentals.get('market_cap', 0):,.0f}
- Revenue Growth YoY: {fundamentals.get('revenue_growth_yoy', 'N/A')}
- Earnings Growth YoY: {fundamentals.get('earnings_growth_yoy', 'N/A')}
- Gross Margin: {fundamentals.get('gross_margin', 'N/A')} | Operating Margin: {fundamentals.get('operating_margin', 'N/A')}
- P/E (trailing): {fundamentals.get('pe_ratio', 'N/A')} | Forward P/E: {fundamentals.get('forward_pe', 'N/A')}
- PEG Ratio: {fundamentals.get('peg_ratio', 'N/A')} | P/S: {fundamentals.get('ps_ratio', 'N/A')}
- ROE: {fundamentals.get('roe', 'N/A')} | Debt/Equity: {fundamentals.get('debt_to_equity', 'N/A')}
- Free Cash Flow: ${fundamentals.get('free_cash_flow', 0):,.0f}
- Quarterly Revenue Trend: {fundamentals.get('quarterly_revenue_trend', [])}
- Analyst Consensus: {fundamentals.get('analyst_recommendation', 'N/A')} (n={fundamentals.get('num_analyst_opinions', 0)})
- Analyst Price Target: ${fundamentals.get('analyst_target_price', 'N/A')}
- Business: {fundamentals.get('description', '')}

## STOCKTWITS RETAIL SENTIMENT
- Total Recent Messages: {sentiment.get('total_messages', 0)}
- Bullish: {sentiment.get('bullish_count', 0)} ({sentiment.get('bull_ratio', 0):.1%})
- Bearish: {sentiment.get('bearish_count', 0)} ({sentiment.get('bear_ratio', 0):.1%})
- Watchlist Count: {sentiment.get('watchers', 0):,}
- Sample Retail Messages:
{chr(10).join(f'  - "{m[:120]}"' for m in (sentiment.get('recent_messages') or [])[:10])}

## TECHNICAL PICTURE
- Current Price: ${technicals.get('current_price', 'N/A')}
- MA20: ${technicals.get('ma20')} | MA50: ${technicals.get('ma50')} | MA200: ${technicals.get('ma200')}
- Price vs MA50: {technicals.get('price_vs_ma50_pct', 'N/A')}%
- RSI(14): {technicals.get('rsi_14', 'N/A')}
- MACD Histogram: {technicals.get('macd_histogram', 'N/A')}
- Volume Ratio vs 20d Avg: {technicals.get('volume_ratio_vs_20d_avg', 'N/A')}x
- OBV Trend: {technicals.get('obv_trend', 'N/A')}
- 52-Week High: ${technicals.get('week_52_high')} | Low: ${technicals.get('week_52_low')}
- % From 52W High: {technicals.get('pct_from_52w_high', 'N/A')}%

## EARNINGS
- Next Earnings Date: {earnings.get('next_earnings_date', 'N/A')}
- EPS Estimate (next): ${earnings.get('eps_estimate', 'N/A')}
- Last Quarter EPS Actual: ${earnings.get('eps_actual_last', 'N/A')}
- Last Quarter Surprise: {earnings.get('surprise_pct_last', 'N/A')}%

---
Provide analysis with these sections:
1. **FUNDAMENTAL QUALITY** (2-3 sentences — growth durability, margin trend, FCF)
2. **VALUATION** (1-2 sentences — cheap/fair/expensive vs growth rate)
3. **RETAIL SENTIMENT SIGNAL** (1-2 sentences — interpret the StockTwits data)
4. **TECHNICAL STRUCTURE** (1-2 sentences — trend, momentum, buy/sell pressure)
5. **EARNINGS TRAJECTORY** (1-2 sentences — beat history, upcoming catalyst)
6. **KEY RISKS** (bullet list, max 4 items)
7. **VERDICT**: [STRONG BUY / BUY / HOLD / REDUCE / AVOID] — Conviction: [HIGH/MEDIUM/LOW]
   - 12-month target range: $X – $Y
   - Key catalyst to watch: ...
"""


def analyze_stock(ticker: str, fundamentals: dict, sentiment: dict,
                  technicals: dict, earnings: dict) -> str:
    prompt = build_analysis_prompt(ticker, fundamentals, sentiment, technicals, earnings)
    response = client.messages.create(
        model="claude-opus-4-7",        # use Opus for deep analysis
        max_tokens=1200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def rank_portfolio(analyses: list[dict]) -> str:
    """Have Claude rank all analyzed stocks into a portfolio."""
    summary_table = "\n".join(
        f"{a['ticker']}: verdict={a['verdict']}, conviction={a['conviction']}, "
        f"target={a['target']}, rev_growth={a['revenue_growth']}, rsi={a['rsi']}"
        for a in analyses
    )
    prompt = f"""
You have analyzed these {len(analyses)} growth stocks:

{summary_table}

Now produce:
1. **TOP 10 PICKS** — ranked by risk-adjusted return potential
2. **AVOID LIST** — stocks with poor setups right now
3. **WATCHLIST** — good businesses, better entry point needed
4. **SECTOR THEMES** — 2-3 macro themes driving these picks
5. **PORTFOLIO ALLOCATION** (% weights for the top 10, summing to 100%)

Be direct and decisive. This is actionable intelligence, not a disclaimer.
"""
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text
```

---

## PART 5: MAIN ORCHESTRATOR

### main.py
```python
import json, time
from rich.console import Console
from rich.progress import track
from data_sources.stock_universe import screen_top_50_growth
from data_sources.stocktwits_collector import get_sentiment
from data_sources.fundamentals_collector import get_fundamentals, get_earnings_calendar
from data_sources.technicals_collector import get_technicals
from analyzer.claude_prompt import analyze_stock, rank_portfolio

console = Console()

def run_analysis():
    console.print("[bold cyan]Step 1: Screening top 50 growth stocks...[/]")
    df = screen_top_50_growth()
    tickers = df["ticker"].tolist()
    console.print(f"[green]Universe: {tickers}[/]")

    all_analyses = []

    for ticker in track(tickers, description="Analyzing stocks..."):
        try:
            fundamentals = get_fundamentals(ticker)
            sentiment = get_sentiment(ticker)
            technicals = get_technicals(ticker)
            earnings = get_earnings_calendar(ticker)

            analysis_text = analyze_stock(ticker, fundamentals, sentiment, technicals, earnings)

            # Parse verdict from text (simple extraction)
            verdict = "HOLD"
            for v in ["STRONG BUY", "BUY", "REDUCE", "AVOID", "HOLD"]:
                if v in analysis_text.upper():
                    verdict = v
                    break

            all_analyses.append({
                "ticker": ticker,
                "analysis": analysis_text,
                "verdict": verdict,
                "revenue_growth": fundamentals.get("revenue_growth_yoy"),
                "rsi": technicals.get("rsi_14"),
                "conviction": "HIGH" if "HIGH" in analysis_text else "MEDIUM",
                "target": "see analysis",
            })

            # Save individual report
            with open(f"reports/{ticker}_analysis.md", "w") as f:
                f.write(f"# {ticker} Analysis\n\n{analysis_text}\n")

            time.sleep(1.5)  # respect API rate limits

        except Exception as e:
            console.print(f"[red]Error on {ticker}: {e}[/]")
            continue

    console.print("\n[bold cyan]Generating portfolio ranking...[/]")
    portfolio_report = rank_portfolio(all_analyses)

    with open("reports/PORTFOLIO_RANKING.md", "w") as f:
        f.write("# Growth Stock Portfolio Ranking\n\n")
        f.write(portfolio_report)

    console.print("[bold green]Done! Reports saved to ./reports/[/]")

if __name__ == "__main__":
    import os
    os.makedirs("reports", exist_ok=True)
    run_analysis()
```

---

## PART 6: DATA SOURCES — FREE vs PAID

### FREE TIER (production-viable)

| Source | What You Get | Limits |
|--------|-------------|--------|
| **StockTwits API** | Retail sentiment, message streams, trending symbols | 200 req/hr (auth) |
| **yfinance (Yahoo)** | Fundamentals, price history, earnings | Unofficial, generous |
| **Alpha Vantage** | Price, technicals, earnings, news sentiment | 25 req/day free |
| **Finnhub** | Fundamentals, earnings, insider trades, news | 60 req/min free |
| **SEC EDGAR** | 10-K/10-Q filings, real earnings data | Unlimited |
| **FRED API** | Macro data (rates, GDP, inflation) | Unlimited |
| **Financial Modeling Prep** | Income stmt, DCF, analyst estimates | 250 req/day free |
| **Reddit API (PRAW)** | r/wallstreetbets, r/investing sentiment | Free, rate limited |
| **NewsAPI** | Financial news headlines | 100 req/day free |
| **OpenBB** | Open-source Bloomberg alternative, aggregates above | Free |

### PAID (high-signal, institutional-grade)

| Source | Cost | Why Worth It |
|--------|------|-------------|
| **Polygon.io Starter** | $29/mo | Real-time + historical tick data, options flow |
| **Finnhub Premium** | $49/mo | Insider transactions, institutional holdings 13F |
| **Financial Modeling Prep Premium** | $29/mo | Full DCF models, 30yr history, real-time earnings |
| **Tiingo** | $10/mo | Clean fundamentals API, no scraping issues |
| **Seeking Alpha API** | $75/mo | Premium analyst ratings, quant ratings |
| **Unusual Whales** | $50/mo | Options flow, dark pool prints — best signal |
| **Quandl/Nasdaq Data Link** | $50+/mo | Institutional-grade macro + alt data |
| **SimilarWeb/Apptopia** | $200+/mo | Web traffic + app downloads as leading indicator |
| **Bloomberg B-PIPE** | $2,000+/mo | Institutional standard, real-time everything |

### RECOMMENDED STACK (best ROI)

**Budget (~$0/mo):** yfinance + StockTwits + Finnhub free + SEC EDGAR + Alpha Vantage  
**Smart (~$80/mo):** Add Polygon.io + FMP Premium → real-time price + clean fundamentals  
**Power (~$180/mo):** Add Unusual Whales → options flow is the single highest-alpha signal  

---

## PART 7: ADDITIONAL ANALYSIS SIGNALS (add to Claude prompt)

### Options Flow Signal (Unusual Whales API)
```python
def get_options_flow(ticker: str) -> dict:
    """High put/call ratio = bearish hedge. Unusual call sweeps = smart money buying."""
    # Polygon.io options endpoint or Unusual Whales API
    pass  # wire in your paid key
```

### Insider Transactions (Finnhub)
```python
import finnhub, os

fc = finnhub.Client(api_key=os.getenv("FINNHUB_KEY"))

def get_insider_sentiment(ticker: str) -> dict:
    data = fc.stock_insider_sentiment(ticker, _from="2024-01-01", to="2025-12-31")
    mspr = data.get("data", [{}])[-1].get("mspr", 0)  # Monthly Share Purchase Ratio
    return {"insider_buying_signal": mspr > 0, "mspr": mspr}
```

### News Sentiment (Alpha Vantage)
```python
def get_news_sentiment(ticker: str) -> dict:
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": ticker,
        "apikey": os.getenv("ALPHA_VANTAGE_KEY"),
        "limit": 20,
    }
    r = requests.get(url, params=params).json()
    feeds = r.get("feed", [])
    avg_sentiment = sum(
        float(f.get("overall_sentiment_score", 0)) for f in feeds
    ) / max(len(feeds), 1)
    return {"news_sentiment_score": avg_sentiment, "articles_analyzed": len(feeds)}
```

---

## PART 8: SCHEDULING (run daily pre-market)

```bash
# Add to crontab: run Mon-Fri at 8:30am ET
30 8 * * 1-5 cd /path/to/stocktwit && python main.py >> logs/daily.log 2>&1
```

Or use Claude Code scheduled routines:
```
/schedule "Run growth stock analysis daily at 8:30am ET weekdays"
```

---

## QUICK START

```bash
git clone ... && cd stocktwit
cp .env.example .env       # fill in your API keys
pip install -r requirements.txt
mkdir reports
python main.py             # runs full analysis, saves to ./reports/
```
