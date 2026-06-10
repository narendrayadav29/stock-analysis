#!/usr/bin/env python3
"""
Pull ownership (institutional, insider, congress) + macro (FRED, indices) data.
Run daily/weekly: python pull_ownership_macro.py

Usage:
  python pull_ownership_macro.py                     # all
  python pull_ownership_macro.py --tickers NVDA,AMD  # specific tickers
  python pull_ownership_macro.py --macro-only        # skip per-stock ownership
  python pull_ownership_macro.py --ownership-only    # skip macro
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

sys.path.insert(0, str(Path(__file__).parent))

from data_sources.ownership_collector import (
    get_institutional_holders, get_insider_transactions, get_congress_trades
)
from data_sources.edgar_collector import get_company_facts
from data_sources.macro_collector import get_macro_snapshot, get_market_indices
from data_sources.stock_universe import _UNIVERSE
from database.db import (
    init_db,
    save_institutional_holdings,
    save_congress_trades,
    save_edgar_fundamentals,
    save_macro_data,
)

console = Console()
TODAY   = datetime.now().strftime("%Y-%m-%d")


def pull_macro():
    console.print("[cyan]Fetching macro data (FRED + market indices)...[/]")
    macro   = get_macro_snapshot()
    indices = get_market_indices(period="1y")

    save_macro_data(TODAY, macro)

    # Print quick summary
    t = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    t.add_column("Indicator", width=25)
    t.add_column("Latest", width=12)
    t.add_column("Prev",   width=12)
    t.add_column("Change", width=10)

    for key, series in macro.get("series", {}).items():
        latest = series.get("latest")
        prev   = series.get("prev")
        if not latest:
            continue
        val     = latest["value"]
        prev_v  = prev["value"] if prev else None
        chg     = round(val - prev_v, 3) if prev_v is not None else None
        chg_str = f"{chg:+.3f}" if chg is not None else "—"
        color   = "green" if (chg or 0) > 0 else "red" if (chg or 0) < 0 else "white"
        t.add_row(series["label"][:24], str(val), str(prev_v or "—"),
                  f"[{color}]{chg_str}[/]")

    console.print(t)

    ys = macro.get("yield_curve_spread")
    if ys is not None:
        inv = macro.get("yield_curve_inverted", False)
        color = "bold red" if inv else "green"
        console.print(f"[{color}]Yield Curve (10y-2y): {ys:+.3f}%"
                      + (" ⚠ INVERTED" if inv else "") + "[/]")

    # Index table
    t2 = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    t2.add_column("Index",    width=20)
    t2.add_column("Current",  width=10)
    t2.add_column("1D Chg%",  width=9)
    t2.add_column("YTD%",     width=9)
    for name, idx in indices.items():
        c1d = idx.get("change_1d")
        cy  = idx.get("change_ytd")
        color1d = "green" if (c1d or 0) > 0 else "red"
        colory  = "green" if (cy  or 0) > 0 else "red"
        t2.add_row(
            name, str(idx.get("current", "—")),
            f"[{color1d}]{c1d:+.2f}%[/]" if c1d is not None else "—",
            f"[{colory}]{cy:+.1f}%[/]"   if cy  is not None else "—",
        )
    console.print(t2)
    console.print(f"[dim]Macro saved → macro_data table ({len(macro['series'])} series)[/]")


def pull_ownership(tickers: list[str]):
    # 1. Congress trades (one call for all tickers)
    console.print("[cyan]Fetching Congress trading disclosures...[/]")
    all_congress = get_congress_trades(ticker=None, days=180)
    save_congress_trades(all_congress)
    # Filter to our universe for display
    universe_set   = set(t.upper() for t in tickers)
    matching       = [c for c in all_congress if c.get("ticker", "").upper() in universe_set]
    console.print(f"[dim]Congress trades: {len(all_congress)} total, "
                  f"{len(matching)} in our universe[/]")
    if matching:
        ct = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
        ct.add_column("Date",   width=11)
        ct.add_column("Ticker", width=7)
        ct.add_column("Rep",    width=22)
        ct.add_column("Party",  width=4)
        ct.add_column("Type",   width=10)
        ct.add_column("Amount", width=22)
        for c in matching[:15]:
            txn = c.get("transaction", "")
            color = "green" if "purchase" in txn.lower() else "red"
            ct.add_row(c["transaction_date"][:10], c["ticker"],
                       c["representative"][:22],
                       c.get("party","")[:1],
                       f"[{color}]{txn}[/]", c.get("amount",""))
        console.print(ct)

    # 2. Per-ticker: institutional holders + insider txns + EDGAR fundamentals
    console.print(f"\n[cyan]Fetching ownership & EDGAR for {len(tickers)} tickers...[/]")
    with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"),
                  BarColumn(), console=console, transient=False) as prog:
        task = prog.add_task("", total=len(tickers))

        for ticker in tickers:
            prog.update(task, description=f"[cyan]{ticker}")

            # Institutional holders
            try:
                inst = get_institutional_holders(ticker)
                save_institutional_holdings(TODAY, ticker, inst)
            except Exception as exc:
                console.print(f"[red]{ticker} inst error: {exc}[/]")

            # Insider transactions (via yfinance Form 4)
            try:
                get_insider_transactions(ticker)  # stored separately, used in dashboard
            except Exception:
                pass

            # EDGAR quarterly fundamentals
            try:
                facts = get_company_facts(ticker)
                if facts.get("available"):
                    save_edgar_fundamentals(TODAY, ticker, facts)
            except Exception as exc:
                console.print(f"[red]{ticker} EDGAR error: {exc}[/]")

            prog.advance(task)
            time.sleep(0.3)   # gentle on SEC servers

    console.print(f"[dim]Ownership saved for {len(tickers)} tickers[/]")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers",        type=str)
    parser.add_argument("--limit",          type=int, default=30)
    parser.add_argument("--macro-only",     action="store_true")
    parser.add_argument("--ownership-only", action="store_true")
    args = parser.parse_args()

    tickers = (
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        if args.tickers else list(_UNIVERSE)[: args.limit]
    )

    console.print(Panel.fit(
        f"[bold cyan]Ownership & Macro Pull[/]  |  "
        f"[green]{len(tickers)} tickers[/]  |  [dim]{TODAY}[/]",
        title="[bold white]EDGAR + FRED + Quiver Congress + yfinance[/]",
    ))

    init_db()

    if not args.ownership_only:
        pull_macro()

    if not args.macro_only:
        console.print()
        pull_ownership(tickers)

    console.print("\n[bold green]Done.[/]")


if __name__ == "__main__":
    main()
