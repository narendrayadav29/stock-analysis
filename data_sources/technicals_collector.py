"""
Technical indicators computed locally from yfinance price history.
No external API calls beyond yfinance price download.
"""

import logging
import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def get_technicals(ticker: str, period: str = "1y") -> dict:
    try:
        df = yf.Ticker(ticker).history(period=period)
        if df.empty or len(df) < 20:
            return {"ticker": ticker, "available": False}

        close  = df["Close"]
        volume = df["Volume"]
        high   = df["High"]
        low    = df["Low"]
        current = float(close.iloc[-1])

        # ── Moving averages ───────────────────────────────────────────────
        ma20  = float(close.rolling(20).mean().iloc[-1])
        ma50  = float(close.rolling(50).mean().iloc[-1])
        ma200 = float(close.rolling(200, min_periods=100).mean().iloc[-1]) \
                if len(close) >= 100 else None

        # ── RSI (14) ──────────────────────────────────────────────────────
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, np.nan)
        rsi   = float((100 - 100 / (1 + rs)).iloc[-1])

        # ── MACD (12/26/9) ────────────────────────────────────────────────
        ema12     = close.ewm(span=12, adjust=False).mean()
        ema26     = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal    = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = float((macd_line - signal).iloc[-1])
        macd_cross = (
            "bullish_cross" if macd_line.iloc[-1] > signal.iloc[-1] and
                               macd_line.iloc[-2] <= signal.iloc[-2]
            else "bearish_cross" if macd_line.iloc[-1] < signal.iloc[-1] and
                                    macd_line.iloc[-2] >= signal.iloc[-2]
            else "no_cross"
        )

        # ── Bollinger Bands (20, 2σ) ──────────────────────────────────────
        std20    = close.rolling(20).std()
        bb_upper = float((close.rolling(20).mean() + 2 * std20).iloc[-1])
        bb_lower = float((close.rolling(20).mean() - 2 * std20).iloc[-1])
        bb_pct   = round((current - bb_lower) / max(bb_upper - bb_lower, 0.01), 3)

        # ── Volume analysis ───────────────────────────────────────────────
        avg_vol_20  = float(volume.rolling(20).mean().iloc[-1])
        vol_today   = float(volume.iloc[-1])
        vol_ratio   = round(vol_today / max(avg_vol_20, 1), 2)

        # ── OBV (On-Balance Volume) trend ─────────────────────────────────
        direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        obv       = (volume * direction).cumsum()
        obv_trend = "rising" if float(obv.iloc[-1]) > float(obv.iloc[-20]) else "falling"

        # ── Average True Range (14) — volatility ──────────────────────────
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr14 = float(tr.rolling(14).mean().iloc[-1])
        atr_pct = round(atr14 / current * 100, 2)

        # ── 52-week stats ─────────────────────────────────────────────────
        high_52w = float(high.max())
        low_52w  = float(low.min())
        pct_from_52w_high = round((current - high_52w) / high_52w * 100, 1)
        pct_from_52w_low  = round((current - low_52w)  / low_52w  * 100, 1)

        # ── Price trend context ───────────────────────────────────────────
        trend = (
            "strong_uptrend"  if current > ma50 > ma200 else
            "uptrend"         if current > ma50 else
            "downtrend"       if current < ma50 < (ma200 or ma50) else
            "weak"
        ) if ma200 else (
            "above_ma50" if current > ma50 else "below_ma50"
        )

        return {
            "ticker":              ticker,
            "current_price":       round(current, 2),
            "ma20":                round(ma20, 2),
            "ma50":                round(ma50, 2),
            "ma200":               round(ma200, 2) if ma200 else None,
            "price_vs_ma50_pct":   round((current - ma50) / ma50 * 100, 1),
            "price_vs_ma200_pct":  round((current - ma200) / ma200 * 100, 1) if ma200 else None,
            "rsi_14":              round(rsi, 1),
            "macd_histogram":      round(macd_hist, 4),
            "macd_signal":         macd_cross,
            "bb_pct_b":            bb_pct,        # 0=lower band, 1=upper band
            "volume_ratio_20d":    vol_ratio,
            "obv_trend":           obv_trend,
            "atr_pct":             atr_pct,        # daily volatility as % of price
            "high_52w":            round(high_52w, 2),
            "low_52w":             round(low_52w, 2),
            "pct_from_52w_high":   pct_from_52w_high,
            "pct_from_52w_low":    pct_from_52w_low,
            "trend":               trend,
            "available":           True,
        }
    except Exception as exc:
        logger.warning("Technicals error for %s: %s", ticker, exc)
        return {"ticker": ticker, "available": False}
