#!/usr/bin/env python3
"""
Pull today's sentiment & crowd reaction data for growth stocks.

Data sources:
  - Alpha Vantage NEWS_SENTIMENT  → per-stock news sentiment score (25 req/day free)
  - Fear & Greed Index (alt.me)   → market-wide mood
  - Polygon snapshot              → volume, price change, day OHLCV
  - StockTwits                    → attempted; falls back gracefully on 403

Usage:
  python pull_sentiment.py                      # top 20 from universe
  python pull_sentiment.py --tickers NVDA,TSLA  # specific tickers
  python pull_sentiment.py --limit 10           # quick run
  python pull_sentiment.py --trending           # add trending symbols
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import requests
import logging
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.progress import Progress, SpinnerColumn, TextColumn

sys.path.insert(0, str(Path(__file__).parent))

from config import ALPHA_VANTAGE_KEY, POLYGON_KEY, STOCKTWITS_TOKEN, STOCKTWITS_SENTIMENT_LIMIT
from data_sources.sentiment_collector import get_fear_greed
from data_sources.stocktwits_collector import get_trending_symbols
from data_sources.stock_universe import _UNIVERSE
from database.db import init_db, save_sentiment_pull

console = Console()
logger  = logging.getLogger(__name__)
TIMEOUT = 12

# ── Alpha Vantage news sentiment — batched (one API call for all tickers) ──────

def get_av_news_batch(tickers: list[str]) -> dict[str, dict]:
    """
    Fetch news sentiment for all tickers in ONE API call.
    Alpha Vantage NEWS_SENTIMENT accepts comma-separated tickers.
    Free tier: 25 requests/day, 5/min — one batch call costs 1 credit.
    Returns dict keyed by ticker.
    """
    empty = {t: {"ticker": t, "available": False, "score": None, "label": None,
                 "articles": 0, "headlines": []} for t in tickers}
    if not ALPHA_VANTAGE_KEY:
        return empty
    try:
        r = requests.get(
            "https://www.alphavantage.co/query",
            params={"function": "NEWS_SENTIMENT",
                    "tickers":  ",".join(tickers),
                    "limit":    200,
                    "apikey":   ALPHA_VANTAGE_KEY},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if "Note" in data or "Information" in data:
            console.print(f"[yellow]Alpha Vantage rate limit: {data.get('Note') or data.get('Information')}[/]")
            return empty

        feeds = data.get("feed", [])
        # Accumulate per-ticker
        scores_by: dict[str, list[float]] = {t: [] for t in tickers}
        headlines_by: dict[str, list[str]] = {t: [] for t in tickers}
        art_count: dict[str, int] = {t: 0 for t in tickers}

        for article in feeds:
            title = article.get("title", "").strip()
            for ts in article.get("ticker_sentiment", []):
                t = ts.get("ticker", "").upper()
                if t in scores_by:
                    try:
                        scores_by[t].append(float(ts["ticker_sentiment_score"]))
                        art_count[t] += 1
                        if title and title not in headlines_by[t]:
                            headlines_by[t].append(title)
                    except (KeyError, ValueError):
                        pass

        results = {}
        for t in tickers:
            sc = scores_by[t]
            avg = round(sum(sc) / len(sc), 3) if sc else None
            results[t] = {
                "ticker":    t,
                "available": bool(sc),
                "score":     avg,
                "label":     _score_label(avg) if avg is not None else ("Neutral" if sc else None),
                "articles":  art_count[t],
                "headlines": headlines_by[t][:5],
            }
        return results
    except Exception as exc:
        logger.warning("AV batch error: %s", exc)
        return empty


def _score_label(s: float | None) -> str:
    if s is None: return "Neutral"
    if s >= 0.35:  return "Bullish"
    if s >= 0.10:  return "Somewhat-Bullish"
    if s <= -0.35: return "Bearish"
    if s <= -0.10: return "Somewhat-Bearish"
    return "Neutral"


# ── Polygon snapshot (volume, price change) ───────────────────────────────────

def get_polygon_snapshot(ticker: str) -> dict:
    if not POLYGON_KEY:
        return {"ticker": ticker, "available": False}
    try:
        r = requests.get(
            f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}",
            params={"apiKey": POLYGON_KEY},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        snap = r.json().get("ticker", {})
        if not snap:
            return {"ticker": ticker, "available": False}
        day  = snap.get("day", {})
        prev = snap.get("prevDay", {})
        return {
            "ticker":     ticker,
            "available":  True,
            "price":      snap.get("lastTrade", {}).get("p") or day.get("c"),
            "change_pct": snap.get("todaysChangePerc"),
            "volume":     day.get("v"),
            "vwap":       day.get("vw"),
            "prev_close": prev.get("c"),
        }
    except Exception as exc:
        logger.warning("Polygon error %s: %s", ticker, exc)
        return {"ticker": ticker, "available": False}


# ── StockTwits (best-effort) ──────────────────────────────────────────────────

def get_stocktwits_sentiment(ticker: str) -> dict:
    params = {"limit": STOCKTWITS_SENTIMENT_LIMIT}
    if STOCKTWITS_TOKEN:
        params["access_token"] = STOCKTWITS_TOKEN
    try:
        r = requests.get(
            f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json",
            params=params, timeout=TIMEOUT,
        )
        if r.status_code in (401, 403):
            return {"available": False}
        r.raise_for_status()
        msgs  = r.json().get("messages", [])
        bull  = sum(1 for m in msgs if (m.get("entities") or {}).get("sentiment", {}).get("basic") == "Bullish")
        bear  = sum(1 for m in msgs if (m.get("entities") or {}).get("sentiment", {}).get("basic") == "Bearish")
        total = len(msgs)
        return {
            "available":      True,
            "total_messages": total,
            "bull_ratio":     round(bull / max(total, 1), 3),
            "bear_ratio":     round(bear / max(total, 1), 3),
            "bullish_count":  bull,
            "bearish_count":  bear,
            "sample":         [m["body"].strip() for m in msgs if m.get("body")][:3],
        }
    except Exception:
        return {"available": False}


# ── yfinance price + volume (free, no key) ────────────────────────────────────

def get_yfinance_data(tickers: list[str]) -> dict[str, dict]:
    try:
        import yfinance as yf
        import warnings
        warnings.filterwarnings("ignore")
    except ImportError:
        return {t: {"available": False} for t in tickers}

    results = {}
    for t in tickers:
        try:
            fi = yf.Ticker(t).fast_info
            price     = getattr(fi, "last_price", None)
            prev      = getattr(fi, "previous_close", None)
            today_vol = getattr(fi, "last_volume", None)
            avg_vol   = getattr(fi, "three_month_average_volume", None)
            low52     = getattr(fi, "fifty_two_week_low", None)
            high52    = getattr(fi, "fifty_two_week_high", None)
            chg_pct   = ((price - prev) / prev * 100) if price and prev else None
            pos52     = ((price - low52) / (high52 - low52) * 100) if price and low52 and high52 and high52 != low52 else None
            results[t] = {
                "available":  bool(price),
                "price":      price,
                "change_pct": round(chg_pct, 2) if chg_pct is not None else None,
                "volume":     today_vol,
                "avg_volume": avg_vol,
                "pos_52w":    round(pos52, 1) if pos52 is not None else None,
            }
        except Exception:
            results[t] = {"available": False}
    return results


# ── Collection loop ───────────────────────────────────────────────────────────

def collect_all(tickers: list[str]) -> list[dict]:
    console.print("[dim]Fetching news sentiment (1 batch API call)...[/]")
    av_batch = get_av_news_batch(tickers)

    console.print("[dim]Fetching price & volume (yfinance)...[/]")
    yf_data = get_yfinance_data(tickers)

    results = []
    with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"),
                  console=console, transient=True) as prog:
        task = prog.add_task("Fetching market data...", total=len(tickers))
        for ticker in tickers:
            prog.update(task, description=f"[cyan]{ticker} (StockTwits)")
            st = get_stocktwits_sentiment(ticker)
            results.append({
                "ticker":     ticker,
                "news":       av_batch.get(ticker, {"ticker": ticker, "available": False,
                                                    "score": None, "label": None,
                                                    "articles": 0, "headlines": []}),
                "polygon":    get_polygon_snapshot(ticker),
                "yfinance":   yf_data.get(ticker, {"available": False}),
                "stocktwits": st,
            })
            prog.advance(task)
    return results


# ── Display ───────────────────────────────────────────────────────────────────

_LABEL_COLORS = {
    "Bullish":          "bold green",
    "Somewhat-Bullish": "green",
    "Neutral":          "yellow",
    "Somewhat-Bearish": "orange3",
    "Bearish":          "bold red",
}


def _score_bar(score: float | None, width: int = 18) -> str:
    """Horizontal bar: green = bullish half, red = bearish half, pivot at 0."""
    if score is None:
        return "[dim]── no data ─[/]"
    norm  = max(-1.0, min(1.0, score))
    pos   = int(round(((norm + 1.0) / 2.0) * width))
    bar   = "░" * pos + "│" + "░" * (width - pos)
    pivot = width // 2
    left  = bar[:pivot]
    mid   = bar[pivot]
    right = bar[pivot + 1:]
    return f"[red]{left}[/][white]{mid}[/][green]{right}[/]"


def _fg_label(score: int | None) -> str:
    if score is None: return "?"
    if score >= 75: return f"[bold green]Extreme Greed ({score})[/]"
    if score >= 55: return f"[green]Greed ({score})[/]"
    if score >= 45: return f"[yellow]Neutral ({score})[/]"
    if score >= 25: return f"[orange3]Fear ({score})[/]"
    return f"[bold red]Extreme Fear ({score})[/]"


def print_results(results: list[dict], fg: dict):
    # Fear & Greed banner
    trend_sym = {"rising": "↑", "falling": "↓", "flat": "→"}.get(fg.get("trend"), "")
    prev = fg.get("prev_score", "?")
    console.print(Panel(
        f"Market Fear & Greed: {_fg_label(fg.get('score'))}  "
        f"[dim](yesterday: {prev} {trend_sym})[/]",
        title="[bold white]CNN Fear & Greed Index[/]",
        expand=False,
    ))

    # Sort by news sentiment score descending (None last)
    sorted_r = sorted(results, key=lambda x: x["news"].get("score") or -99, reverse=True)

    table = Table(
        title=f"News Sentiment & Crowd Reaction  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        box=box.ROUNDED, show_lines=True, header_style="bold cyan",
    )
    table.add_column("Ticker",  style="bold white", width=7)
    table.add_column("Score",   width=6)
    table.add_column("Sentiment Bar (−1 … +1)", width=21)
    table.add_column("Label",   width=17)
    table.add_column("Art.",    width=4)
    table.add_column("Chg%",    width=7)
    table.add_column("Volume",  width=11)
    table.add_column("ST Bull", width=8)
    table.add_column("Top Headline", width=58)

    for r in sorted_r:
        news = r["news"]
        poly = r["polygon"]
        st   = r["stocktwits"]

        score = news.get("score")
        score_str = f"{score:+.3f}" if score is not None else "—"
        label = news.get("label") or "—"
        color = _LABEL_COLORS.get(label, "white")
        label_rich = f"[{color}]{label}[/]"

        yf_ = r.get("yfinance", {})
        chg = yf_.get("change_pct") or poly.get("change_pct")
        chg_str = f"{chg:+.1f}%" if chg is not None else "—"
        chg_color = "green" if (chg or 0) > 0 else "red" if (chg or 0) < 0 else "white"

        vol = yf_.get("volume") or poly.get("volume")
        vol_str = f"{vol/1_000_000:.1f}M" if vol and vol >= 1_000_000 else (f"{vol:,}" if vol else "—")

        bull_r = st.get("bull_ratio")
        bull_str = f"{bull_r*100:.0f}%" if bull_r is not None else "—"

        headline = (news.get("headlines") or [""])[:1]
        top_h = headline[0][:58] if headline else ""

        table.add_row(
            r["ticker"],
            score_str,
            _score_bar(score),
            label_rich,
            str(news.get("articles") or "—"),
            f"[{chg_color}]{chg_str}[/]",
            vol_str,
            bull_str,
            f"[dim]{top_h}[/]",
        )

    console.print()
    console.print(table)


def print_top_headlines(results: list[dict]):
    """Print top headlines grouped by ticker for quick scanning."""
    console.print("\n[bold cyan]Top Headlines by Ticker[/]")
    for r in results:
        headlines = r["news"].get("headlines", [])
        if not headlines:
            continue
        score = r["news"].get("score")
        label = r["news"].get("label") or "Neutral"
        color = _LABEL_COLORS.get(label, "white")
        console.print(
            f"\n[bold white]{r['ticker']}[/]  "
            f"[{color}]{label}[/]"
            + (f" [dim]({score:+.3f})[/]" if score is not None else "")
        )
        for h in headlines[:3]:
            console.print(f"  [dim]•[/] {h}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Pull today's sentiment & crowd reaction data")
    parser.add_argument("--tickers",   type=str, help="Comma-separated tickers")
    parser.add_argument("--limit",     type=int, default=20, help="Stocks to scan (default: 20)")
    parser.add_argument("--trending",  action="store_true", help="Include trending StockTwits symbols")
    parser.add_argument("--headlines", action="store_true", help="Also print top headlines per ticker")
    parser.add_argument("--no-save",   action="store_true", help="Skip JSON output")
    args = parser.parse_args()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = list(_UNIVERSE)[: args.limit]

    if args.trending:
        trending = get_trending_symbols(limit=20)
        new_ones = [t for t in trending if t not in tickers]
        tickers  = (tickers + new_ones)[: args.limit]
        if new_ones:
            console.print(f"[cyan]Added {len(new_ones)} trending: {', '.join(new_ones)}[/]")

    console.print(Panel.fit(
        f"[bold cyan]Sentiment Pull[/]  |  [green]{len(tickers)} stocks[/]  |  "
        f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M')}[/]",
        title="[bold white]News Sentiment + Volume + Fear & Greed[/]"
    ))

    fg      = get_fear_greed()
    results = collect_all(tickers)

    print_results(results, fg)

    if args.headlines:
        print_top_headlines(results)

    # Summary counts
    bullish = sum(1 for r in results if r["news"].get("label") in ("Bullish", "Somewhat-Bullish"))
    bearish = sum(1 for r in results if r["news"].get("label") in ("Bearish", "Somewhat-Bearish"))
    neutral = sum(1 for r in results if r["news"].get("label") == "Neutral")
    no_data = sum(1 for r in results if not r["news"].get("available"))
    console.print(
        f"\n[green]Bullish ({bullish})[/]  [yellow]Neutral ({neutral})[/]  "
        f"[red]Bearish ({bearish})[/]  [dim]No data ({no_data})[/]"
        f"  [dim]|  F&G: {fg.get('score','?')} — {fg.get('rating','')}[/]"
    )

    has_any_data = any(r["news"].get("available") for r in results)
    if not args.no_save and has_any_data:
        # Save to DB
        init_db()
        today = datetime.now().strftime("%Y-%m-%d")
        save_sentiment_pull(today, fg, results)
        console.print(f"[dim]Saved to database (sentiment_pulls)[/]")
    elif not args.no_save:
        console.print("[yellow]Skipped DB save — no news data available (rate limit?)[/]")

        # Also save JSON for raw reference
        Path("results").mkdir(exist_ok=True)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = {"date": datetime.now().isoformat(), "fear_greed": fg, "stocks": results}
        path = f"results/sentiment_{ts}.json"
        with open(path, "w") as f:
            json.dump(out, f, indent=2, default=str)
        console.print(f"[dim]JSON  → {path}[/]")


if __name__ == "__main__":
    main()
