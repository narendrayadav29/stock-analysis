#!/usr/bin/env python3
from __future__ import annotations

"""
Growth Stock Analyzer — StockTwits + Fundamentals + Claude AI
Usage:
  python main.py                        # full run, top 50 screened stocks
  python main.py --tickers NVDA,AMD,TSLA  # specific tickers only
  python main.py --limit 5              # quick test with 5 stocks
  python main.py --limit 5 --dry-run   # collect data only, skip Claude
  python main.py --resume               # skip stocks already in ./reports/
  python main.py --model claude-opus-4-7  # override model for this run
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table
from rich import box

# ── Project imports ────────────────────────────────────────────────────────────
from config import CLAUDE_MODEL, RATE_LIMIT_DELAY, REPORTS_DIR, LOGS_DIR
from data_sources.stock_universe import get_stock_universe
from data_sources.stocktwits_collector import get_trending_symbols
from data_sources.sentiment_collector import get_sentiment
from data_sources.fundamentals_collector import get_fundamentals, get_earnings
from data_sources.technicals_collector import get_technicals
from data_sources.news_collector import get_news_sentiment
from data_sources.insider_collector import get_insider_data
from data_sources.fmp_collector import get_all as get_fmp_data
from data_sources.polygon_collector import get_all as get_polygon_data
from analyzer.claude_analyzer import analyze_stock
from analyzer.portfolio_ranker import rank_portfolio
from database.db import init_db, create_run, finish_run, save_analysis, save_portfolio_ranking

console = Console()


# ── Logging setup ──────────────────────────────────────────────────────────────
def setup_logging(log_dir: str):
    Path(log_dir).mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"run_{ts}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return log_file


# ── Data collection for a single ticker ───────────────────────────────────────
def collect_data(ticker: str) -> dict:
    return {
        "fundamentals": get_fundamentals(ticker),
        "earnings":     get_earnings(ticker),
        "technicals":   get_technicals(ticker),
        "sentiment":    get_sentiment(ticker),
        "news":         get_news_sentiment(ticker),
        "insider":      get_insider_data(ticker),
        "fmp":          get_fmp_data(ticker),
        "polygon":      get_polygon_data(ticker),
    }


# ── Report helpers ─────────────────────────────────────────────────────────────
def save_stock_report(result: dict, reports_dir: str):
    Path(reports_dir).mkdir(exist_ok=True)
    ticker = result["ticker"]
    path   = os.path.join(reports_dir, f"{ticker}.md")
    with open(path, "w") as f:
        f.write(f"# {ticker} — {result.get('company_name', '')}\n")
        f.write(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n")
        f.write(result.get("analysis", "No analysis generated."))
    return path


def save_json_cache(ticker: str, data: dict, reports_dir: str):
    """Save raw collected data for debugging / re-running analysis."""
    path = os.path.join(reports_dir, f"{ticker}_data.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def already_done(ticker: str, reports_dir: str) -> bool:
    return os.path.exists(os.path.join(reports_dir, f"{ticker}.md"))


# ── Rich summary table ─────────────────────────────────────────────────────────
def print_summary_table(results: list[dict]):
    table = Table(
        title="Stock Analysis Summary",
        box=box.ROUNDED,
        show_lines=True,
        header_style="bold cyan",
    )
    table.add_column("Ticker",     style="bold white", width=7)
    table.add_column("Verdict",    width=12)
    table.add_column("Conviction", width=10)
    table.add_column("Target",     width=14)
    table.add_column("Catalyst",   width=30)
    table.add_column("One-line",   width=55)

    VERDICT_COLORS = {
        "STRONG BUY": "bold green",
        "BUY":        "green",
        "HOLD":       "yellow",
        "REDUCE":     "orange3",
        "AVOID":      "bold red",
        "ERROR":      "dim red",
    }

    for r in results:
        verdict = r.get("verdict", "?")
        lo = r.get("target_low")
        hi = r.get("target_high")
        target_str = f"${lo:.0f}–${hi:.0f}" if lo and hi else "N/A"
        table.add_row(
            r["ticker"],
            f"[{VERDICT_COLORS.get(verdict, 'white')}]{verdict}[/]",
            r.get("conviction", "?"),
            target_str,
            (r.get("catalyst") or "")[:30],
            (r.get("summary") or "")[:55],
        )

    console.print(table)


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Growth Stock Analyzer — Claude + StockTwits")
    parser.add_argument("--tickers", type=str,
                        help="Comma-separated list of tickers (skips universe screening)")
    parser.add_argument("--limit", type=int, default=50,
                        help="Max number of stocks to analyze (default: 50)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Collect data only — skip Claude API calls")
    parser.add_argument("--resume", action="store_true",
                        help="Skip tickers that already have a report in ./reports/")
    parser.add_argument("--model", type=str,
                        help=f"Claude model override (default: {CLAUDE_MODEL})")
    parser.add_argument("--no-ranking", action="store_true",
                        help="Skip the final portfolio ranking step")
    parser.add_argument("--trending", action="store_true",
                        help="Add currently trending StockTwits symbols to the universe")
    args = parser.parse_args()

    # ── Guards ────────────────────────────────────────────────────────────────
    if not args.dry_run and not os.getenv("ANTHROPIC_API_KEY"):
        import shutil as _sh, subprocess as _sp
        _claude_bin = _sh.which("claude") or "/opt/homebrew/bin/claude"
        probe = _sp.run([_claude_bin, "-p", "ping"], capture_output=True, text=True,
                        timeout=15, env=os.environ)
        if probe.returncode != 0:
            console.print("[bold red]ERROR: claude CLI not responding. Is Claude Code running?[/]")
            sys.exit(1)

    # Model override
    if args.model:
        import config
        config.CLAUDE_MODEL = args.model

    log_file = setup_logging(LOGS_DIR)
    Path(REPORTS_DIR).mkdir(exist_ok=True)
    init_db()
    run_id = create_run(model=CLAUDE_MODEL, notes=f"CLI args: {vars(args)}")

    console.print(Panel.fit(
        "[bold cyan]Growth Stock Analyzer[/]\n"
        f"Model: [green]{CLAUDE_MODEL}[/]  |  "
        f"Mode: {'[yellow]DRY RUN[/]' if args.dry_run else '[green]FULL[/]'}  |  "
        f"Log: [dim]{log_file}[/]",
        title="[bold white]StockTwits + Claude AI[/]"
    ))

    # ── Build ticker list ─────────────────────────────────────────────────────
    explicit_tickers = (
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        if args.tickers else None
    )

    if explicit_tickers:
        tickers = explicit_tickers[: args.limit]
        console.print(f"[cyan]Using {len(tickers)} explicit tickers.[/]")
    else:
        console.print("[cyan]Screening growth stock universe...[/]")
        tickers = get_stock_universe(top_n=args.limit)

        if args.trending:
            trending = get_trending_symbols(limit=20)
            new_ones  = [t for t in trending if t not in tickers]
            tickers   = (tickers + new_ones)[: args.limit]
            console.print(f"[cyan]Added {len(new_ones)} trending symbols.[/]")

        console.print(f"[green]Universe: {len(tickers)} stocks selected.[/]")

    if args.resume:
        before = len(tickers)
        tickers = [t for t in tickers if not already_done(t, REPORTS_DIR)]
        console.print(f"[yellow]Resume: skipping {before - len(tickers)} already-analyzed stocks.[/]")

    if not tickers:
        console.print("[green]All stocks already analyzed. Nothing to do.[/]")
        return

    # ── Per-stock loop ────────────────────────────────────────────────────────
    all_results: list[dict] = []
    errors: list[str] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("[dim]{task.fields[status]}"),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task(
            "Analyzing stocks", total=len(tickers), status="starting..."
        )

        for ticker in tickers:
            progress.update(task, description=f"[bold cyan]{ticker}", status="collecting data...")

            # 1. Collect all data
            try:
                data = collect_data(ticker)
                save_json_cache(ticker, data, REPORTS_DIR)
            except Exception as exc:
                logging.error("Data collection failed for %s: %s", ticker, exc)
                errors.append(f"{ticker}: data collection — {exc}")
                progress.advance(task)
                continue

            if args.dry_run:
                console.print(f"  [dim]{ticker}[/] — data collected (dry run, skipping Claude)")
                progress.advance(task)
                continue

            # 2. Claude analysis
            progress.update(task, status="calling Claude...")
            try:
                result = analyze_stock(ticker, data)
                all_results.append(result)
                save_stock_report(result, REPORTS_DIR)
                save_analysis(run_id, result, data)
                progress.update(task, status=f"[green]{result.get('verdict','?')}[/]")
            except Exception as exc:
                logging.error("Analysis failed for %s: %s", ticker, exc)
                errors.append(f"{ticker}: analysis — {exc}")

            progress.advance(task)
            time.sleep(RATE_LIMIT_DELAY)

    # ── Summary ───────────────────────────────────────────────────────────────
    if all_results:
        console.print()
        print_summary_table(all_results)

    # ── Portfolio ranking ─────────────────────────────────────────────────────
    if all_results and not args.dry_run and not args.no_ranking:
        console.print("\n[bold cyan]Generating portfolio ranking report...[/]")
        ranking_report = rank_portfolio(all_results)

        ranking_path = os.path.join(REPORTS_DIR, "PORTFOLIO_RANKING.md")
        with open(ranking_path, "w") as f:
            f.write("# Growth Stock Portfolio Ranking\n")
            f.write(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")
            f.write(f"*Stocks analyzed: {len(all_results)}*\n\n")
            f.write(ranking_report)

        save_portfolio_ranking(run_id, ranking_report, all_results)
        console.print(f"[green]Portfolio ranking saved → {ranking_path}[/]")

    # ── Finalise DB run ───────────────────────────────────────────────────────
    finish_run(run_id, total_stocks=len(all_results))

    # ── Final status ──────────────────────────────────────────────────────────
    console.print()
    if errors:
        console.print(f"[yellow]Completed with {len(errors)} error(s):[/]")
        for e in errors:
            console.print(f"  [red]• {e}[/]")
    else:
        console.print("[bold green]All done — no errors.[/]")

    console.print(f"[dim]Reports saved to ./{REPORTS_DIR}/[/]")
    console.print(f"[dim]DB saved to ./database/stocks.db[/]")


if __name__ == "__main__":
    main()
