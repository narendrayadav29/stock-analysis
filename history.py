#!/usr/bin/env python3
"""
CLI for browsing historical predictions stored in the SQLite database.

Usage:
  python history.py                        # today's picks
  python history.py --ticker NVDA          # all NVDA predictions
  python history.py --date 2026-06-04      # all picks from a specific date
  python history.py --runs                 # list all past runs
  python history.py --accuracy             # prediction accuracy report
  python history.py --export picks.csv     # export everything to CSV
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich import box

from database.db import (
    get_history, get_todays_picks, get_accuracy_summary, get_all_runs, _connect
)

console = Console()

VERDICT_STYLE = {
    "STRONG BUY": "bold green",
    "BUY":        "green",
    "HOLD":       "yellow",
    "REDUCE":     "orange3",
    "AVOID":      "bold red",
    "ERROR":      "dim red",
}


def show_todays_picks(run_date: str | None = None):
    date  = run_date or datetime.now().strftime("%Y-%m-%d")
    picks = get_todays_picks(date)

    if not picks:
        console.print(f"[yellow]No analyses found for {date}.[/]")
        return

    t = Table(title=f"Picks — {date}", box=box.ROUNDED, header_style="bold cyan")
    t.add_column("Ticker",    width=7,  style="bold white")
    t.add_column("Company",   width=22)
    t.add_column("Verdict",   width=12)
    t.add_column("Conv",      width=6)
    t.add_column("Price",     width=8)
    t.add_column("Target",    width=14)
    t.add_column("RSI",       width=5)
    t.add_column("F&G",       width=5)
    t.add_column("Summary",   width=55)

    for p in picks:
        lo = p.get("target_low")
        hi = p.get("target_high")
        verdict = p.get("verdict") or "?"
        t.add_row(
            p["ticker"],
            (p.get("company_name") or "")[:22],
            f"[{VERDICT_STYLE.get(verdict,'white')}]{verdict}[/]",
            p.get("conviction") or "?",
            f"${p['price_at_analysis']:.2f}" if p.get("price_at_analysis") else "N/A",
            f"${lo:.0f}–${hi:.0f}" if lo and hi else "N/A",
            str(round(p["rsi_14"], 0)) if p.get("rsi_14") else "N/A",
            str(int(p["fear_greed_score"])) if p.get("fear_greed_score") else "N/A",
            (p.get("summary") or "")[:55],
        )
    console.print(t)


def show_ticker_history(ticker: str):
    rows = get_history(ticker.upper(), limit=60)
    if not rows:
        console.print(f"[yellow]No history found for {ticker.upper()}.[/]")
        return

    t = Table(title=f"{ticker.upper()} — Prediction History", box=box.ROUNDED,
              header_style="bold cyan")
    t.add_column("Date",      width=11)
    t.add_column("Verdict",   width=12)
    t.add_column("Conv",      width=6)
    t.add_column("Price",     width=8)
    t.add_column("Target",    width=12)
    t.add_column("Ret 7d",    width=7)
    t.add_column("Ret 30d",   width=7)
    t.add_column("Hit 30d",   width=8)
    t.add_column("Catalyst",  width=30)

    for r in rows:
        verdict = r.get("verdict") or "?"
        lo, hi  = r.get("target_low"), r.get("target_high")
        ret7    = r.get("return_7d")
        ret30   = r.get("return_30d")
        hit     = r.get("hit_target_30d")
        t.add_row(
            r["run_date"],
            f"[{VERDICT_STYLE.get(verdict,'white')}]{verdict}[/]",
            r.get("conviction") or "?",
            f"${r['price_at_analysis']:.2f}" if r.get("price_at_analysis") else "N/A",
            f"${lo:.0f}–${hi:.0f}" if lo and hi else "N/A",
            (f"[green]+{ret7:.1f}%[/]" if ret7 and ret7 > 0 else
             f"[red]{ret7:.1f}%[/]"   if ret7 else "—"),
            (f"[green]+{ret30:.1f}%[/]" if ret30 and ret30 > 0 else
             f"[red]{ret30:.1f}%[/]"   if ret30 else "—"),
            ("✅" if hit else "❌") if hit is not None else "—",
            (r.get("catalyst") or "")[:30],
        )
    console.print(t)


def show_accuracy():
    rows = get_accuracy_summary()
    if not rows:
        console.print("[yellow]No accuracy data yet. Run track_actuals.py after 7+ days.[/]")
        return

    t = Table(title="Prediction Accuracy by Verdict", box=box.ROUNDED,
              header_style="bold cyan")
    t.add_column("Verdict",   width=12)
    t.add_column("N",         width=5,  justify="right")
    t.add_column("Avg 7d %",  width=9,  justify="right")
    t.add_column("Avg 30d %", width=9,  justify="right")
    t.add_column("Avg 90d %", width=9,  justify="right")
    t.add_column("Hit Rate 30d", width=12, justify="right")

    for r in rows:
        verdict = r.get("verdict") or "?"
        def fmt_ret(v):
            if v is None: return "—"
            v = round(v, 1)
            return f"[green]+{v}%[/]" if v > 0 else f"[red]{v}%[/]"

        hit = r.get("hit_rate_30d")
        t.add_row(
            f"[{VERDICT_STYLE.get(verdict,'white')}]{verdict}[/]",
            str(r["total"]),
            fmt_ret(r.get("avg_return_7d")),
            fmt_ret(r.get("avg_return_30d")),
            fmt_ret(r.get("avg_return_90d")),
            f"{hit:.0f}%" if hit else "—",
        )
    console.print(t)


def show_runs():
    runs = get_all_runs()
    if not runs:
        console.print("[yellow]No runs recorded yet.[/]")
        return

    t = Table(title="All Runs", box=box.ROUNDED, header_style="bold cyan")
    t.add_column("ID",        width=4)
    t.add_column("Date",      width=11)
    t.add_column("Timestamp", width=20)
    t.add_column("Stocks",    width=7, justify="right")
    t.add_column("Model",     width=20)

    for r in runs:
        t.add_row(str(r["id"]), r["run_date"], r["run_timestamp"],
                  str(r["total_stocks"]), r.get("model") or "")
    console.print(t)


def export_csv(path: str):
    with _connect() as con:
        rows = con.execute("""
            SELECT a.*, r.run_timestamp, r.model
            FROM analyses a JOIN runs r ON a.run_id = r.id
            ORDER BY a.run_date DESC, a.ticker
        """).fetchall()

    if not rows:
        console.print("[yellow]Nothing to export.[/]")
        return

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows([dict(r) for r in rows])

    console.print(f"[green]Exported {len(rows)} rows → {path}[/]")


def main():
    parser = argparse.ArgumentParser(description="Stock prediction history viewer")
    parser.add_argument("--ticker",   help="Show history for a specific ticker")
    parser.add_argument("--date",     help="Show picks for a specific date (YYYY-MM-DD)")
    parser.add_argument("--runs",     action="store_true", help="List all past runs")
    parser.add_argument("--accuracy", action="store_true", help="Show accuracy report")
    parser.add_argument("--export",   metavar="FILE", help="Export all data to CSV")
    args = parser.parse_args()

    if args.ticker:
        show_ticker_history(args.ticker)
    elif args.runs:
        show_runs()
    elif args.accuracy:
        show_accuracy()
    elif args.export:
        export_csv(args.export)
    else:
        show_todays_picks(args.date)


if __name__ == "__main__":
    main()
