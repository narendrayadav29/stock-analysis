"""
Fundamental and earnings data via yfinance (Yahoo Finance).
No API key required. Rate-limit gracefully with caller-side sleep.
"""

import logging
import yfinance as yf

logger = logging.getLogger(__name__)


def get_fundamentals(ticker: str) -> dict:
    try:
        t = yf.Ticker(ticker)
        info = t.info

        # Quarterly revenue trend — last 4 quarters, most-recent first
        q_rev = []
        try:
            qf = t.quarterly_financials
            if qf is not None and "Total Revenue" in qf.index:
                q_rev = [
                    int(v) for v in qf.loc["Total Revenue"].head(4).tolist()
                    if v == v  # drop NaN
                ]
        except Exception:
            pass

        # Free cash flow from cash-flow statement
        fcf = None
        try:
            cf = t.cashflow
            if cf is not None and "Free Cash Flow" in cf.index:
                fcf = cf.loc["Free Cash Flow"].iloc[0]
                fcf = int(fcf) if fcf == fcf else None
        except Exception:
            pass

        return {
            "ticker": ticker,
            "company_name":      info.get("longName", ticker),
            "sector":            info.get("sector", ""),
            "industry":          info.get("industry", ""),
            "country":           info.get("country", ""),
            "market_cap":        info.get("marketCap"),
            "employees":         info.get("fullTimeEmployees"),
            # Growth
            "revenue_growth_yoy":   info.get("revenueGrowth"),
            "earnings_growth_yoy":  info.get("earningsGrowth"),
            "revenue_ttm":          info.get("totalRevenue"),
            "quarterly_revenue":    q_rev,
            # Margins
            "gross_margin":       info.get("grossMargins"),
            "operating_margin":   info.get("operatingMargins"),
            "net_margin":         info.get("profitMargins"),
            # Valuation
            "pe_trailing":        info.get("trailingPE"),
            "pe_forward":         info.get("forwardPE"),
            "peg_ratio":          info.get("pegRatio"),
            "ps_ratio":           info.get("priceToSalesTrailing12Months"),
            "pb_ratio":           info.get("priceToBook"),
            "ev_to_ebitda":       info.get("enterpriseToEbitda"),
            # Balance sheet / quality
            "ebitda":             info.get("ebitda"),
            "free_cash_flow":     fcf,
            "debt_to_equity":     info.get("debtToEquity"),
            "current_ratio":      info.get("currentRatio"),
            "cash":               info.get("totalCash"),
            "roe":                info.get("returnOnEquity"),
            "roa":                info.get("returnOnAssets"),
            # Analyst views
            "analyst_target":     info.get("targetMeanPrice"),
            "analyst_low":        info.get("targetLowPrice"),
            "analyst_high":       info.get("targetHighPrice"),
            "analyst_consensus":  info.get("recommendationKey"),
            "analyst_count":      info.get("numberOfAnalystOpinions"),
            "eps_forward":        info.get("forwardEps"),
            "eps_trailing":       info.get("trailingEps"),
            # Description (truncated for prompt)
            "description":        (info.get("longBusinessSummary") or "")[:600],
        }
    except Exception as exc:
        logger.warning("Fundamentals error for %s: %s", ticker, exc)
        return {"ticker": ticker, "company_name": ticker, "available": False}


def get_earnings(ticker: str) -> dict:
    try:
        t = yf.Ticker(ticker)
        cal = t.calendar or {}

        # Earnings date(s)
        dates = cal.get("Earnings Date", [])
        # calendar returns datetime.date objects in newer yfinance versions
        next_date = str(dates[0].date() if hasattr(dates[0], "date") else dates[0]) if dates else None
        eps_est   = cal.get("EPS Estimate")
        rev_est   = cal.get("Revenue Estimate")

        # Last 4 quarters of earnings history
        history = t.earnings_history
        surprise_last = None
        eps_actual_last = None
        if history is not None and not history.empty:
            row = history.iloc[-1]  # most recent is last row
            eps_actual_last = row.get("epsActual")
            # column is surprisePercent in newer yfinance, epsSurprisePct in older
            surprise_last = row.get("surprisePercent") or row.get("epsSurprisePct")

        # Beat rate over last 4 quarters
        beat_rate = None
        try:
            if history is not None and len(history) >= 2:
                col = "surprisePercent" if "surprisePercent" in history.columns else "epsSurprisePct"
                beats = (history[col] > 0).sum()
                beat_rate = round(beats / len(history), 2)
        except Exception:
            pass

        return {
            "ticker":            ticker,
            "next_earnings_date": next_date,
            "eps_estimate":       float(eps_est)  if eps_est  else None,
            "revenue_estimate":   float(rev_est)  if rev_est  else None,
            "eps_actual_last":    float(eps_actual_last) if eps_actual_last else None,
            "surprise_pct_last":  float(surprise_last)   if surprise_last   else None,
            "beat_rate_4q":       beat_rate,
        }
    except Exception as exc:
        logger.warning("Earnings error for %s: %s", ticker, exc)
        return {"ticker": ticker}
