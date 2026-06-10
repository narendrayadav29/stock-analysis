#!/usr/bin/env python3
"""
Growth Stock Intelligence Dashboard
Run: streamlit run dashboard.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH = "database/stocks.db"

st.set_page_config(
    page_title="Stock Intelligence Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── DB helpers ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_table(table: str) -> pd.DataFrame:
    try:
        with sqlite3.connect(DB_PATH) as con:
            tables = pd.read_sql_query(
                "SELECT name FROM sqlite_master WHERE type='table'", con
            )["name"].tolist()
            if table not in tables:
                return pd.DataFrame()
            return pd.read_sql_query(f"SELECT * FROM {table}", con)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_analyses() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        df = pd.read_sql_query("SELECT * FROM analyses ORDER BY run_date DESC", con)
    if df.empty:
        return df
    df["run_date"] = pd.to_datetime(df["run_date"])
    return df


@st.cache_data(ttl=300)
def load_sentiment_pulls() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        tables = pd.read_sql_query(
            "SELECT name FROM sqlite_master WHERE type='table'", con
        )["name"].tolist()
        if "sentiment_pulls" not in tables:
            return pd.DataFrame()
        df = pd.read_sql_query(
            "SELECT * FROM sentiment_pulls ORDER BY pull_date DESC", con
        )
    if df.empty:
        return df
    df["pull_date"] = pd.to_datetime(df["pull_date"])
    return df


@st.cache_data(ttl=300)
def load_portfolio_rankings() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        df = pd.read_sql_query(
            "SELECT run_date, top_picks FROM portfolio_rankings ORDER BY run_date DESC", con
        )
    if not df.empty:
        df["run_date"] = pd.to_datetime(df["run_date"])
        df["top_picks"] = df["top_picks"].apply(lambda x: json.loads(x) if x else [])
    return df


def available_dates(df: pd.DataFrame, date_col: str = "run_date") -> list[str]:
    if df.empty:
        return []
    return sorted(df[date_col].dt.strftime("%Y-%m-%d").unique(), reverse=True)


# ── Colour maps ───────────────────────────────────────────────────────────────
VERDICT_COLORS = {
    "STRONG BUY": "#00c853",
    "BUY":        "#69f0ae",
    "HOLD":       "#ffd740",
    "REDUCE":     "#ff6d00",
    "AVOID":      "#d50000",
}

SENTIMENT_COLORS = {
    "Bullish":          "#00c853",
    "Somewhat-Bullish": "#69f0ae",
    "Neutral":          "#ffd740",
    "Somewhat-Bearish": "#ff6d00",
    "Bearish":          "#d50000",
}


# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.title("📈 Stock Intelligence")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigation",
    ["Overview", "Sentiment Timeline", "Fundamentals", "Ownership & Flows",
     "Macro & Markets", "Claude Verdicts", "Prediction Accuracy"],
    index=0,
)

analyses_df      = load_analyses()
sentiment_df     = load_sentiment_pulls()
rankings_df      = load_portfolio_rankings()

all_tickers = sorted(analyses_df["ticker"].unique().tolist()) if not analyses_df.empty else []

# Date range filter — applies to all pages
st.sidebar.markdown("---")
st.sidebar.subheader("Date Range")
if not analyses_df.empty:
    min_date = analyses_df["run_date"].min().date()
    max_date = analyses_df["run_date"].max().date()
    date_from = st.sidebar.date_input("From", value=min_date, min_value=min_date, max_value=max_date)
    date_to   = st.sidebar.date_input("To",   value=max_date, min_value=min_date, max_value=max_date)
else:
    date_from = date_to = datetime.today().date()

# Ticker filter
st.sidebar.markdown("---")
st.sidebar.subheader("Tickers")
selected_tickers = st.sidebar.multiselect(
    "Select tickers (blank = all)",
    options=all_tickers,
    default=[],
)

def filter_analyses(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    mask = (df["run_date"].dt.date >= date_from) & (df["run_date"].dt.date <= date_to)
    if selected_tickers:
        mask &= df["ticker"].isin(selected_tickers)
    return df[mask]

def filter_sentiment(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    mask = (df["pull_date"].dt.date >= date_from) & (df["pull_date"].dt.date <= date_to)
    if selected_tickers:
        mask &= df["ticker"].isin(selected_tickers)
    return df[mask]

filtered_analyses  = filter_analyses(analyses_df)
filtered_sentiment = filter_sentiment(sentiment_df)


# ── Page: Overview ────────────────────────────────────────────────────────────
if page == "Overview":
    st.title("📊 Market Overview")

    if filtered_analyses.empty and filtered_sentiment.empty:
        st.info("No data for the selected date range. Run `python main.py` or `python pull_sentiment.py` first.")
        st.stop()

    # ── Fear & Greed timeline ─────────────────────────────────────────────────
    st.subheader("Fear & Greed Index Over Time")

    fg_source = None
    if not filtered_sentiment.empty and "fear_greed_score" in filtered_sentiment.columns:
        fg_source = (
            filtered_sentiment
            .drop_duplicates("pull_date")
            .sort_values("pull_date")[["pull_date", "fear_greed_score", "fear_greed_rating"]]
            .rename(columns={"pull_date": "date", "fear_greed_score": "score"})
        )
    elif not filtered_analyses.empty and "fear_greed_score" in filtered_analyses.columns:
        fg_source = (
            filtered_analyses
            .drop_duplicates("run_date")
            .sort_values("run_date")[["run_date", "fear_greed_score"]]
            .rename(columns={"run_date": "date", "fear_greed_score": "score"})
        )

    if fg_source is not None and not fg_source.empty and fg_source["score"].notna().any():
        fig_fg = go.Figure()
        fig_fg.add_trace(go.Scatter(
            x=fg_source["date"], y=fg_source["score"],
            mode="lines+markers+text",
            text=fg_source["score"].astype(str),
            textposition="top center",
            line=dict(color="#4fc3f7", width=2),
            marker=dict(size=8),
            fill="tozeroy",
            fillcolor="rgba(79,195,247,0.15)",
            name="F&G Score",
        ))
        # Zone bands
        for y0, y1, color, label in [
            (0, 25, "rgba(213,0,0,0.08)", "Extreme Fear"),
            (25, 45, "rgba(255,109,0,0.08)", "Fear"),
            (45, 55, "rgba(255,215,64,0.08)", "Neutral"),
            (55, 75, "rgba(105,240,174,0.08)", "Greed"),
            (75, 100, "rgba(0,200,83,0.08)", "Extreme Greed"),
        ]:
            fig_fg.add_hrect(y0=y0, y1=y1, fillcolor=color, line_width=0,
                             annotation_text=label, annotation_position="right")
        fig_fg.update_layout(
            yaxis=dict(range=[0, 100], title="Score"),
            xaxis_title="Date",
            height=280,
            margin=dict(t=10, b=40),
            plot_bgcolor="#0e1117",
            paper_bgcolor="#0e1117",
            font_color="#fafafa",
        )
        st.plotly_chart(fig_fg, use_container_width=True)
    else:
        st.info("Fear & Greed data not yet collected. Run `python pull_sentiment.py` to populate.")

    st.markdown("---")

    # ── Verdict heatmap ───────────────────────────────────────────────────────
    st.subheader("Verdict Heatmap (Ticker × Date)")
    if not filtered_analyses.empty:
        pivot = (
            filtered_analyses
            .assign(date_str=filtered_analyses["run_date"].dt.strftime("%Y-%m-%d"))
            .pivot_table(index="ticker", columns="date_str", values="verdict", aggfunc="first")
        )
        verdict_order = ["STRONG BUY", "BUY", "HOLD", "REDUCE", "AVOID", None]
        score_map = {"STRONG BUY": 2, "BUY": 1, "HOLD": 0, "REDUCE": -1, "AVOID": -2}
        pivot_scores = pivot.applymap(lambda v: score_map.get(v, 0))

        fig_heat = px.imshow(
            pivot_scores,
            color_continuous_scale=["#d50000", "#ff6d00", "#ffd740", "#69f0ae", "#00c853"],
            zmin=-2, zmax=2,
            text_auto=False,
            aspect="auto",
        )
        # Overlay verdict text
        for i, ticker in enumerate(pivot.index):
            for j, col in enumerate(pivot.columns):
                val = pivot.iloc[i, j]
                if pd.notna(val):
                    fig_heat.add_annotation(
                        x=j, y=i, text=str(val),
                        showarrow=False, font=dict(size=9, color="white"),
                        xref="x", yref="y",
                    )
        fig_heat.update_layout(
            height=max(300, len(pivot) * 28),
            coloraxis_showscale=False,
            margin=dict(t=10, b=40),
            plot_bgcolor="#0e1117",
            paper_bgcolor="#0e1117",
            font_color="#fafafa",
        )
        st.plotly_chart(fig_heat, use_container_width=True)

    st.markdown("---")

    # ── Latest day KPIs ───────────────────────────────────────────────────────
    if not filtered_analyses.empty:
        latest_date = filtered_analyses["run_date"].max()
        latest = filtered_analyses[filtered_analyses["run_date"] == latest_date]
        st.subheader(f"Latest Run: {latest_date.strftime('%Y-%m-%d')}")
        cols = st.columns(5)
        for v, col in zip(["STRONG BUY", "BUY", "HOLD", "REDUCE", "AVOID"], cols):
            count = (latest["verdict"] == v).sum()
            col.metric(v, count)


# ── Page: Sentiment Timeline ──────────────────────────────────────────────────
elif page == "Sentiment Timeline":
    st.title("📰 Sentiment Timeline")

    if filtered_analyses.empty and filtered_sentiment.empty:
        st.info("No data. Run `python pull_sentiment.py` first.")
        st.stop()

    # Use sentiment_pulls if available, else fall back to analyses
    if not filtered_sentiment.empty and "news_score" in filtered_sentiment.columns:
        sent_data = (
            filtered_sentiment
            .rename(columns={"pull_date": "date", "news_score": "score", "news_label": "label"})
        )
        score_col = "score"
    elif not filtered_analyses.empty:
        sent_data = (
            filtered_analyses
            .rename(columns={"run_date": "date", "news_sentiment": "score"})
        )
        score_col = "score"
    else:
        sent_data = pd.DataFrame()

    if not sent_data.empty and sent_data[score_col].notna().any():
        # Line chart: sentiment score over time per ticker
        st.subheader("News Sentiment Score Over Time")
        tickers_with_data = sent_data.groupby("ticker")[score_col].count()
        tickers_with_data = tickers_with_data[tickers_with_data > 0].index.tolist()

        if selected_tickers:
            plot_tickers = [t for t in selected_tickers if t in tickers_with_data]
        else:
            plot_tickers = tickers_with_data[:15]   # cap at 15 for readability

        if plot_tickers:
            plot_df = sent_data[sent_data["ticker"].isin(plot_tickers)].copy()
            fig_line = px.line(
                plot_df.sort_values("date"),
                x="date", y=score_col, color="ticker",
                markers=True,
                title="News Sentiment Score (−1 bearish → +1 bullish)",
                labels={score_col: "Sentiment Score", "date": "Date"},
            )
            fig_line.add_hline(y=0, line_dash="dot", line_color="gray", opacity=0.5)
            fig_line.add_hrect(y0=0.10, y1=1.0,  fillcolor="rgba(0,200,83,0.05)",  line_width=0)
            fig_line.add_hrect(y0=-1.0, y1=-0.10, fillcolor="rgba(213,0,0,0.05)", line_width=0)
            fig_line.update_layout(
                height=420,
                plot_bgcolor="#0e1117",
                paper_bgcolor="#0e1117",
                font_color="#fafafa",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig_line, use_container_width=True)

        # Latest sentiment bar chart
        st.subheader("Latest Sentiment Snapshot")
        latest_sent = (
            sent_data
            .sort_values("date")
            .groupby("ticker")
            .last()
            .reset_index()
            .dropna(subset=[score_col])
            .sort_values(score_col, ascending=True)
        )
        if not latest_sent.empty:
            colors = [SENTIMENT_COLORS.get(row.get("label"), "#4fc3f7")
                      for _, row in latest_sent.iterrows()]
            fig_bar = go.Figure(go.Bar(
                x=latest_sent[score_col],
                y=latest_sent["ticker"],
                orientation="h",
                marker_color=colors,
                text=latest_sent[score_col].round(3).astype(str),
                textposition="outside",
            ))
            fig_bar.update_layout(
                xaxis=dict(range=[-1, 1], title="Score"),
                height=max(300, len(latest_sent) * 26),
                margin=dict(t=10, b=40),
                plot_bgcolor="#0e1117",
                paper_bgcolor="#0e1117",
                font_color="#fafafa",
            )
            st.plotly_chart(fig_bar, use_container_width=True)

    else:
        st.info("No sentiment scores yet. Run `python pull_sentiment.py` to populate.")

    # Price change table
    if not filtered_sentiment.empty and "price_change_pct" in filtered_sentiment.columns:
        st.subheader("Price Change & Volume (Latest Pull)")
        latest_pull = (
            filtered_sentiment
            .sort_values("pull_date")
            .groupby("ticker")
            .last()
            .reset_index()[["ticker", "pull_date", "price", "price_change_pct", "volume", "volume_ratio"]]
            .sort_values("price_change_pct", ascending=False)
        )

        def color_chg(val):
            if pd.isna(val): return ""
            return f"color: {'#00c853' if val > 0 else '#d50000'}"

        if not latest_pull.empty:
            st.dataframe(
                latest_pull.style.applymap(color_chg, subset=["price_change_pct"]),
                use_container_width=True,
            )


# ── Page: Fundamentals ────────────────────────────────────────────────────────
elif page == "Fundamentals":
    st.title("📐 Fundamentals")

    if filtered_analyses.empty:
        st.info("No analysis data. Run `python main.py` first.")
        st.stop()

    # Date selector for snapshot
    run_dates = available_dates(filtered_analyses)
    if not run_dates:
        st.info("No dates available.")
        st.stop()

    selected_date = st.selectbox("Run date", run_dates)
    snapshot = filtered_analyses[
        filtered_analyses["run_date"].dt.strftime("%Y-%m-%d") == selected_date
    ].copy()

    if snapshot.empty:
        st.info("No data for this date.")
        st.stop()

    col1, col2 = st.columns(2)

    # Revenue growth
    with col1:
        st.subheader("Revenue Growth YoY")
        rg = snapshot.dropna(subset=["revenue_growth"]).sort_values("revenue_growth", ascending=False)
        if not rg.empty:
            fig_rg = px.bar(rg, x="ticker", y="revenue_growth",
                            color="revenue_growth",
                            color_continuous_scale=["#d50000", "#ffd740", "#00c853"],
                            labels={"revenue_growth": "Rev Growth"})
            fig_rg.update_layout(
                coloraxis_showscale=False, height=320,
                plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#fafafa",
            )
            st.plotly_chart(fig_rg, use_container_width=True)

    # Forward P/E
    with col2:
        st.subheader("Forward P/E")
        pe = snapshot.dropna(subset=["fwd_pe"]).sort_values("fwd_pe")
        if not pe.empty:
            fig_pe = px.bar(pe, x="ticker", y="fwd_pe",
                            color="fwd_pe",
                            color_continuous_scale=["#00c853", "#ffd740", "#d50000"],
                            labels={"fwd_pe": "Fwd P/E"})
            fig_pe.update_layout(
                coloraxis_showscale=False, height=320,
                plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#fafafa",
            )
            st.plotly_chart(fig_pe, use_container_width=True)

    col3, col4 = st.columns(2)

    # RSI
    with col3:
        st.subheader("RSI (14)")
        rsi = snapshot.dropna(subset=["rsi_14"]).sort_values("rsi_14", ascending=False)
        if not rsi.empty:
            fig_rsi = px.bar(rsi, x="ticker", y="rsi_14",
                             color="rsi_14",
                             color_continuous_scale=["#00c853","#ffd740","#d50000"],
                             range_color=[30, 80],
                             labels={"rsi_14": "RSI 14"})
            fig_rsi.add_hline(y=70, line_dash="dot", line_color="#d50000", annotation_text="Overbought")
            fig_rsi.add_hline(y=30, line_dash="dot", line_color="#00c853", annotation_text="Oversold")
            fig_rsi.update_layout(
                coloraxis_showscale=False, height=320,
                plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#fafafa",
            )
            st.plotly_chart(fig_rsi, use_container_width=True)

    # PEG ratio
    with col4:
        st.subheader("PEG Ratio")
        peg = snapshot.dropna(subset=["peg_ratio"]).sort_values("peg_ratio")
        peg = peg[peg["peg_ratio"] < 20]   # filter outliers
        if not peg.empty:
            fig_peg = px.bar(peg, x="ticker", y="peg_ratio",
                             color="peg_ratio",
                             color_continuous_scale=["#00c853","#ffd740","#d50000"],
                             labels={"peg_ratio": "PEG"})
            fig_peg.add_hline(y=1, line_dash="dot", line_color="#69f0ae", annotation_text="Fair Value (1x)")
            fig_peg.update_layout(
                coloraxis_showscale=False, height=320,
                plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#fafafa",
            )
            st.plotly_chart(fig_peg, use_container_width=True)

    # Scatter: Rev Growth vs Fwd PE
    st.subheader("Revenue Growth vs Forward P/E")
    scatter = snapshot.dropna(subset=["revenue_growth", "fwd_pe"])
    scatter = scatter[scatter["fwd_pe"] < 200]
    if not scatter.empty:
        fig_scat = px.scatter(
            scatter, x="fwd_pe", y="revenue_growth",
            text="ticker", color="verdict",
            color_discrete_map=VERDICT_COLORS,
            size="market_cap",
            labels={"fwd_pe": "Forward P/E", "revenue_growth": "Revenue Growth"},
            title="Size = Market Cap",
        )
        fig_scat.update_traces(textposition="top center")
        fig_scat.update_layout(
            height=440,
            plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#fafafa",
        )
        st.plotly_chart(fig_scat, use_container_width=True)

    # Raw table
    st.subheader("Metrics Table")
    cols_show = ["ticker", "company_name", "sector", "verdict", "conviction",
                 "revenue_growth", "fwd_pe", "peg_ratio", "rsi_14", "market_cap",
                 "price_at_analysis", "news_sentiment", "fear_greed_score"]
    display = snapshot[[c for c in cols_show if c in snapshot.columns]].copy()
    display = display.sort_values("verdict", key=lambda s: s.map(
        {"STRONG BUY": 0, "BUY": 1, "HOLD": 2, "REDUCE": 3, "AVOID": 4}).fillna(9)
    )
    st.dataframe(display, use_container_width=True)


# ── Page: Claude Verdicts ─────────────────────────────────────────────────────
elif page == "Claude Verdicts":
    st.title("🤖 Claude Verdicts")

    if filtered_analyses.empty:
        st.info("No analysis data. Run `python main.py` first.")
        st.stop()

    # Verdict distribution over time
    st.subheader("Verdict Distribution Over Time")
    verdict_ts = (
        filtered_analyses
        .assign(date_str=filtered_analyses["run_date"].dt.strftime("%Y-%m-%d"))
        .groupby(["date_str", "verdict"])
        .size()
        .reset_index(name="count")
    )
    if not verdict_ts.empty:
        fig_vt = px.bar(
            verdict_ts, x="date_str", y="count", color="verdict",
            color_discrete_map=VERDICT_COLORS,
            barmode="stack",
            labels={"date_str": "Date", "count": "# Stocks"},
        )
        fig_vt.update_layout(
            height=320,
            plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#fafafa",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_vt, use_container_width=True)

    # Individual ticker verdicts over time
    st.subheader("Ticker Verdict History")
    date_cols = sorted(filtered_analyses["run_date"].dt.strftime("%Y-%m-%d").unique())
    ticker_pivot = (
        filtered_analyses
        .assign(date_str=filtered_analyses["run_date"].dt.strftime("%Y-%m-%d"))
        .pivot_table(index="ticker", columns="date_str", values="verdict", aggfunc="first")
    )
    if not ticker_pivot.empty:
        st.dataframe(
            ticker_pivot.style.applymap(
                lambda v: f"background-color: {VERDICT_COLORS.get(str(v), '#333')}"
                          if pd.notna(v) else ""
            ),
            use_container_width=True,
        )

    # Full detail table with targets + returns
    st.subheader("Full Verdict Detail")
    detail_cols = ["run_date", "ticker", "company_name", "verdict", "conviction",
                   "target_low", "target_high", "price_at_analysis",
                   "return_7d", "return_30d", "return_90d",
                   "hit_target_7d", "hit_target_30d", "catalyst", "summary"]
    detail = filtered_analyses[[c for c in detail_cols if c in filtered_analyses.columns]].copy()
    detail["run_date"] = detail["run_date"].dt.strftime("%Y-%m-%d")
    detail = detail.sort_values(["run_date", "verdict"], ascending=[False, True])

    search = st.text_input("Search ticker / summary")
    if search:
        mask = (
            detail["ticker"].str.contains(search, case=False, na=False) |
            detail.get("summary", pd.Series(dtype=str)).str.contains(search, case=False, na=False)
        )
        detail = detail[mask]

    st.dataframe(detail, use_container_width=True, height=500)

    # Expandable full analysis text
    st.subheader("Full Analysis Text")
    run_dates_d = available_dates(filtered_analyses)
    sel_date_d  = st.selectbox("Run date", run_dates_d, key="verdict_date")
    sel_tickers_d = filtered_analyses[
        filtered_analyses["run_date"].dt.strftime("%Y-%m-%d") == sel_date_d
    ]["ticker"].tolist()
    sel_ticker_d = st.selectbox("Ticker", sorted(sel_tickers_d), key="verdict_ticker")

    if sel_ticker_d:
        row = filtered_analyses[
            (filtered_analyses["run_date"].dt.strftime("%Y-%m-%d") == sel_date_d) &
            (filtered_analyses["ticker"] == sel_ticker_d)
        ]
        if not row.empty and "full_analysis" in row.columns:
            text = row.iloc[0]["full_analysis"] or "No analysis text stored."
            st.markdown(text)


# ── Page: Prediction Accuracy ─────────────────────────────────────────────────
elif page == "Prediction Accuracy":
    st.title("🎯 Prediction Accuracy")

    if analyses_df.empty:
        st.info("No data. Run `python main.py` first.")
        st.stop()

    # Only rows with actual return data
    has_returns = analyses_df.dropna(subset=["return_7d", "return_30d"], how="all")

    if has_returns.empty:
        st.info("No actual return data yet. Run `python database/track_actuals.py` to populate.")
    else:
        # Avg return by verdict
        st.subheader("Average Return by Verdict")
        avg_ret = (
            has_returns
            .groupby("verdict")[["return_7d", "return_30d", "return_90d"]]
            .mean()
            .reset_index()
        )
        fig_ret = px.bar(
            avg_ret.melt(id_vars="verdict", var_name="period", value_name="avg_return"),
            x="verdict", y="avg_return", color="period", barmode="group",
            color_discrete_map={"return_7d": "#4fc3f7", "return_30d": "#69f0ae", "return_90d": "#ce93d8"},
            labels={"avg_return": "Avg Return (%)", "verdict": "Verdict"},
        )
        fig_ret.add_hline(y=0, line_dash="dot", line_color="gray")
        fig_ret.update_layout(
            height=340,
            plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#fafafa",
        )
        st.plotly_chart(fig_ret, use_container_width=True)

        # Hit rate
        st.subheader("Target Hit Rate")
        hit_rate = (
            analyses_df
            .groupby("verdict")
            .agg(
                hit_7d  =("hit_target_7d",  "mean"),
                hit_30d =("hit_target_30d", "mean"),
                hit_90d =("hit_target_90d", "mean"),
                count   =("ticker",         "count"),
            )
            .reset_index()
        )
        for col in ["hit_7d", "hit_30d", "hit_90d"]:
            hit_rate[col] = (hit_rate[col] * 100).round(1)
        st.dataframe(hit_rate, use_container_width=True)

        # Return distribution scatter
        st.subheader("Return Distribution (30d)")
        fig_dist = px.strip(
            has_returns.dropna(subset=["return_30d"]),
            x="verdict", y="return_30d",
            color="conviction",
            hover_data=["ticker", "run_date", "target_low", "target_high"],
            labels={"return_30d": "30d Return (%)"},
        )
        fig_dist.add_hline(y=0, line_dash="dot", line_color="gray")
        fig_dist.update_layout(
            height=380,
            plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#fafafa",
        )
        st.plotly_chart(fig_dist, use_container_width=True)

    # Portfolio rankings history
    if not rankings_df.empty:
        st.subheader("Portfolio Top Picks Over Time")
        for _, row in rankings_df.iterrows():
            with st.expander(f"📅 {row['run_date'].strftime('%Y-%m-%d')} — {', '.join(row['top_picks'][:6])}"):
                st.write("**Top Picks:**", ", ".join(row["top_picks"]))


# ── Page: Ownership & Flows ───────────────────────────────────────────────────
elif page == "Ownership & Flows":
    st.title("🏛 Ownership & Flows")
    st.caption("Institutional holders · Congress trades · Insider transactions · Source: yfinance, Quiver Quant, SEC EDGAR")

    holdings_df  = load_table("institutional_holdings")
    congress_df  = load_table("congress_trades")
    edgar_df     = load_table("edgar_fundamentals")

    if holdings_df.empty and congress_df.empty:
        st.info("No ownership data yet. Run `python pull_ownership_macro.py` first.")
        st.stop()

    # ── Congress trades feed ──────────────────────────────────────────────────
    st.subheader("Congress Trading Disclosures (STOCK Act)")
    if not congress_df.empty:
        congress_df["transaction_date"] = pd.to_datetime(congress_df["transaction_date"])

        # Filters
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            congress_ticker = st.text_input("Filter by ticker", "")
        with col_f2:
            congress_party  = st.multiselect("Party", ["D", "R", "I"], default=[])
        with col_f3:
            congress_txn    = st.multiselect("Type", ["Purchase", "Sale"], default=[])

        cdf = congress_df.copy()
        if congress_ticker:
            cdf = cdf[cdf["ticker"].str.upper() == congress_ticker.upper()]
        if congress_party:
            cdf = cdf[cdf["party"].isin(congress_party)]
        if congress_txn:
            cdf = cdf[cdf["txn_type"].isin(congress_txn)]

        cdf = cdf.sort_values("transaction_date", ascending=False)

        # Purchase vs Sale bar over time
        if not cdf.empty:
            cdf_month = (
                cdf.assign(month=cdf["transaction_date"].dt.to_period("M").astype(str))
                .groupby(["month", "txn_type"])
                .size().reset_index(name="count")
            )
            fig_cong = px.bar(
                cdf_month, x="month", y="count", color="txn_type",
                color_discrete_map={"Purchase": "#00c853", "Sale": "#d50000"},
                barmode="group",
                labels={"month": "Month", "count": "# Trades", "txn_type": "Type"},
                title="Congress Trades Per Month",
            )
            fig_cong.update_layout(
                height=280, plot_bgcolor="#0e1117",
                paper_bgcolor="#0e1117", font_color="#fafafa",
            )
            st.plotly_chart(fig_cong, use_container_width=True)

        # Most active tickers among congress
        if not congress_df.empty:
            top_tickers = (
                congress_df.groupby("ticker").size()
                .sort_values(ascending=False).head(20)
                .reset_index(name="trade_count")
            )
            fig_top = px.bar(
                top_tickers, x="ticker", y="trade_count",
                color="trade_count", color_continuous_scale="Blues",
                labels={"trade_count": "# Trades"},
                title="Most-Traded Tickers by Congress Members",
            )
            fig_top.update_layout(
                height=260, coloraxis_showscale=False,
                plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#fafafa",
            )
            st.plotly_chart(fig_top, use_container_width=True)

        show_cols = ["transaction_date", "ticker", "representative", "party",
                     "house", "txn_type", "amount"]
        st.dataframe(
            cdf[[c for c in show_cols if c in cdf.columns]]
            .rename(columns={"txn_type": "type", "transaction_date": "date"})
            .head(200),
            use_container_width=True,
        )
    else:
        st.info("No congress trade data. Run `python pull_ownership_macro.py`.")

    st.markdown("---")

    # ── Institutional ownership ───────────────────────────────────────────────
    st.subheader("Institutional & Mutual Fund Holdings")
    if not holdings_df.empty:
        # Ticker selector
        tickers_with_data = sorted(holdings_df["ticker"].unique().tolist())
        sel_ticker_h = st.selectbox(
            "Ticker", tickers_with_data,
            index=tickers_with_data.index("NVDA") if "NVDA" in tickers_with_data else 0,
            key="holding_ticker",
        )
        ticker_h = holdings_df[holdings_df["ticker"] == sel_ticker_h].copy()

        col_h1, col_h2 = st.columns(2)

        with col_h1:
            st.markdown("**Top Institutions**")
            inst = ticker_h[ticker_h["holder_type"] == "institution"].sort_values("pct_held", ascending=False).head(15)
            if not inst.empty:
                fig_inst = px.bar(
                    inst, x="pct_held", y="holder", orientation="h",
                    color="pct_change",
                    color_continuous_scale=["#d50000", "#ffd740", "#00c853"],
                    color_continuous_midpoint=0,
                    labels={"pct_held": "% Held", "holder": "", "pct_change": "QoQ Chg"},
                    title=f"{sel_ticker_h} — Institutional Holders",
                )
                fig_inst.update_layout(
                    height=max(300, len(inst) * 28),
                    plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#fafafa",
                )
                st.plotly_chart(fig_inst, use_container_width=True)

        with col_h2:
            st.markdown("**Top Mutual Funds**")
            mf = ticker_h[ticker_h["holder_type"] == "mutual_fund"].sort_values("pct_held", ascending=False).head(10)
            if not mf.empty:
                fig_mf = px.bar(
                    mf, x="pct_held", y="holder", orientation="h",
                    color="pct_change",
                    color_continuous_scale=["#d50000", "#ffd740", "#00c853"],
                    color_continuous_midpoint=0,
                    labels={"pct_held": "% Held", "holder": "", "pct_change": "QoQ Chg"},
                    title=f"{sel_ticker_h} — Mutual Fund Holders",
                )
                fig_mf.update_layout(
                    height=max(300, len(mf) * 28),
                    plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#fafafa",
                )
                st.plotly_chart(fig_mf, use_container_width=True)

        # QoQ change winners/losers
        st.subheader("Biggest Position Changes This Quarter")
        movers = holdings_df.dropna(subset=["pct_change"]).copy()
        movers = movers[movers["pct_change"].abs() > 0.001]
        movers = movers.sort_values("pct_change", ascending=False)
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            st.markdown("**Largest Increases**")
            st.dataframe(
                movers.head(10)[["ticker", "holder", "pct_held", "pct_change", "shares"]],
                use_container_width=True,
            )
        with col_m2:
            st.markdown("**Largest Reductions**")
            st.dataframe(
                movers.tail(10)[["ticker", "holder", "pct_held", "pct_change", "shares"]],
                use_container_width=True,
            )
    else:
        st.info("No institutional data. Run `python pull_ownership_macro.py`.")

    st.markdown("---")

    # ── EDGAR quarterly fundamentals ──────────────────────────────────────────
    st.subheader("EDGAR Quarterly Fundamentals (Direct from SEC Filings)")
    if not edgar_df.empty:
        tickers_e = sorted(edgar_df["ticker"].unique().tolist())
        sel_ticker_e = st.selectbox("Ticker", tickers_e, key="edgar_ticker")
        metrics_e    = sorted(edgar_df[edgar_df["ticker"] == sel_ticker_e]["metric"].unique())
        sel_metrics  = st.multiselect(
            "Metrics", metrics_e,
            default=[m for m in ["revenue", "net_income", "gross_profit", "rd_expense", "eps_diluted"] if m in metrics_e],
        )

        if sel_metrics:
            plot_e = edgar_df[
                (edgar_df["ticker"] == sel_ticker_e) &
                (edgar_df["metric"].isin(sel_metrics))
            ].copy()
            plot_e["quarter_end"] = pd.to_datetime(plot_e["quarter_end"])
            plot_e = plot_e.sort_values("quarter_end")

            # Scale revenue/income to billions for readability
            def _scale(row):
                if row["metric"] in ("revenue", "net_income", "gross_profit", "rd_expense",
                                     "total_assets", "total_liabilities", "cash", "long_term_debt"):
                    return row["value"] / 1e9
                return row["value"]

            plot_e["display_val"] = plot_e.apply(_scale, axis=1)

            fig_edgar = px.line(
                plot_e, x="quarter_end", y="display_val", color="metric",
                markers=True,
                labels={"display_val": "Value (B$ or per share)", "quarter_end": "Quarter"},
                title=f"{sel_ticker_e} — Quarterly Fundamentals (SEC EDGAR XBRL)",
            )
            fig_edgar.update_layout(
                height=420, plot_bgcolor="#0e1117",
                paper_bgcolor="#0e1117", font_color="#fafafa",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig_edgar, use_container_width=True)

        # YoY growth table
        rev_data = edgar_df[
            (edgar_df["ticker"] == sel_ticker_e) & (edgar_df["metric"] == "revenue")
        ].sort_values("quarter_end")
        if len(rev_data) >= 5:
            rev_data = rev_data.copy()
            rev_data["yoy_growth"] = rev_data["value"].pct_change(4).round(4)
            st.dataframe(
                rev_data[["quarter_end", "value", "yoy_growth"]].tail(8),
                use_container_width=True,
            )
    else:
        st.info("No EDGAR data. Run `python pull_ownership_macro.py`.")


# ── Page: Macro & Markets ─────────────────────────────────────────────────────
elif page == "Macro & Markets":
    st.title("🌍 Macro & Markets")
    st.caption("FRED economic data · Market indices · Sector ETFs · Yield curve")

    macro_df = load_table("macro_data")

    if macro_df.empty:
        st.info("No macro data yet. Run `python pull_ownership_macro.py` first.")
        st.stop()

    macro_df["data_date"] = pd.to_datetime(macro_df["data_date"])

    def _macro_series(key: str) -> pd.DataFrame:
        s = macro_df[macro_df["series_key"] == key].copy()
        return s.sort_values("data_date")

    # ── Key macro metrics (latest values) ────────────────────────────────────
    st.subheader("Key Indicators — Latest Values")
    indicators = {
        "GDP ($B)":        ("gdp",          None),
        "GDP Growth %":    ("gdp_growth",   None),
        "CPI":             ("cpi",          None),
        "Core CPI":        ("core_cpi",     None),
        "Fed Funds %":     ("fed_funds",    None),
        "10Y Treasury %":  ("treasury_10y", None),
        "Unemployment %":  ("unemployment", None),
        "Consumer Sent.":  ("consumer_sentiment", None),
        "HY Credit Spread":("credit_spread", None),
    }

    cols_kpi = st.columns(len(indicators))
    for (label, (key, _)), col in zip(indicators.items(), cols_kpi):
        s = _macro_series(key)
        if not s.empty:
            latest = s.iloc[-1]["value"]
            prev   = s.iloc[-2]["value"] if len(s) >= 2 else None
            delta  = round(latest - prev, 3) if prev is not None else None
            col.metric(label, f"{latest:.2f}", f"{delta:+.3f}" if delta is not None else None)

    st.markdown("---")

    # ── Interest rates & yield curve ─────────────────────────────────────────
    st.subheader("Interest Rates & Yield Curve")
    col_r1, col_r2 = st.columns(2)

    with col_r1:
        rate_keys = ["fed_funds", "treasury_2y", "treasury_10y", "treasury_30y"]
        rate_labels = {"fed_funds": "Fed Funds", "treasury_2y": "2Y", "treasury_10y": "10Y", "treasury_30y": "30Y"}
        rate_frames = []
        for k in rate_keys:
            s = _macro_series(k)
            if not s.empty:
                s = s[["data_date", "value"]].copy()
                s["series"] = rate_labels.get(k, k)
                rate_frames.append(s)
        if rate_frames:
            rates_df = pd.concat(rate_frames)
            fig_rates = px.line(
                rates_df, x="data_date", y="value", color="series",
                labels={"value": "Rate (%)", "data_date": "Date"},
                title="Interest Rates Over Time",
            )
            fig_rates.update_layout(
                height=320, plot_bgcolor="#0e1117",
                paper_bgcolor="#0e1117", font_color="#fafafa",
            )
            st.plotly_chart(fig_rates, use_container_width=True)

    with col_r2:
        # Yield curve spread (10y - 2y)
        t10 = _macro_series("treasury_10y").set_index("data_date")["value"]
        t2  = _macro_series("treasury_2y").set_index("data_date")["value"]
        if not t10.empty and not t2.empty:
            spread = (t10 - t2).dropna().reset_index()
            spread.columns = ["date", "spread"]
            fig_yc = go.Figure()
            fig_yc.add_trace(go.Scatter(
                x=spread["date"], y=spread["spread"],
                fill="tozeroy",
                fillcolor="rgba(213,0,0,0.15)",
                line=dict(color="#4fc3f7"),
                name="10Y − 2Y Spread",
            ))
            fig_yc.add_hline(y=0, line_dash="dot", line_color="red", opacity=0.6,
                             annotation_text="Inversion = Recession Signal")
            fig_yc.update_layout(
                title="Yield Curve Spread (10Y − 2Y)",
                height=320, plot_bgcolor="#0e1117",
                paper_bgcolor="#0e1117", font_color="#fafafa",
            )
            st.plotly_chart(fig_yc, use_container_width=True)

    st.markdown("---")

    # ── Inflation ─────────────────────────────────────────────────────────────
    st.subheader("Inflation")
    col_i1, col_i2 = st.columns(2)
    with col_i1:
        cpi = _macro_series("cpi")
        core = _macro_series("core_cpi")
        if not cpi.empty:
            cpi_yoy  = cpi.copy(); cpi_yoy["yoy"] = cpi["value"].pct_change(12) * 100
            core_yoy = core.copy(); core_yoy["yoy"] = core["value"].pct_change(12) * 100
            fig_cpi = go.Figure()
            fig_cpi.add_trace(go.Scatter(x=cpi_yoy["data_date"], y=cpi_yoy["yoy"].round(2),
                                         name="CPI YoY %", line=dict(color="#f06292")))
            fig_cpi.add_trace(go.Scatter(x=core_yoy["data_date"], y=core_yoy["yoy"].round(2),
                                         name="Core CPI YoY %", line=dict(color="#4fc3f7")))
            fig_cpi.add_hline(y=2.0, line_dash="dot", line_color="gray",
                              annotation_text="Fed 2% Target")
            fig_cpi.update_layout(
                title="CPI Inflation YoY %", height=300,
                plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#fafafa",
            )
            st.plotly_chart(fig_cpi, use_container_width=True)

    with col_i2:
        unemp = _macro_series("unemployment")
        gdpg  = _macro_series("gdp_growth")
        if not unemp.empty:
            fig_labor = px.line(
                unemp, x="data_date", y="value",
                labels={"value": "Rate (%)", "data_date": "Date"},
                title="Unemployment Rate (%)", color_discrete_sequence=["#69f0ae"],
            )
            fig_labor.update_layout(
                height=300, plot_bgcolor="#0e1117",
                paper_bgcolor="#0e1117", font_color="#fafafa",
            )
            st.plotly_chart(fig_labor, use_container_width=True)

    st.markdown("---")

    # ── GDP ───────────────────────────────────────────────────────────────────
    st.subheader("GDP & Growth")
    gdpg = _macro_series("gdp_growth")
    if not gdpg.empty:
        colors = ["#00c853" if v >= 0 else "#d50000" for v in gdpg["value"]]
        fig_gdp = go.Figure(go.Bar(
            x=gdpg["data_date"], y=gdpg["value"],
            marker_color=colors,
            name="Real GDP Growth %",
        ))
        fig_gdp.add_hline(y=0, line_dash="dot", line_color="gray")
        fig_gdp.update_layout(
            title="Real GDP Growth Rate (QoQ Annualized %)",
            height=300, plot_bgcolor="#0e1117",
            paper_bgcolor="#0e1117", font_color="#fafafa",
        )
        st.plotly_chart(fig_gdp, use_container_width=True)

    st.markdown("---")

    # ── Market indices & sectors ──────────────────────────────────────────────
    st.subheader("Market Indices & Sector Performance")

    # Pull fresh from yfinance for normalized chart
    @st.cache_data(ttl=1800)
    def _load_indices():
        import sys
        sys.path.insert(0, ".")
        from data_sources.macro_collector import get_market_indices
        return get_market_indices(period="1y")

    with st.spinner("Loading index data..."):
        indices = _load_indices()

    if indices:
        col_idx, col_sec = st.columns(2)

        with col_idx:
            frames = []
            for name in ["S&P 500", "NASDAQ 100", "Russell 2000", "Dow Jones"]:
                if name in indices:
                    df_i = pd.DataFrame(indices[name]["normalized"])
                    df_i["index"] = name
                    df_i["date"]  = pd.to_datetime(df_i["date"])
                    frames.append(df_i)
            if frames:
                idx_df = pd.concat(frames)
                fig_idx = px.line(
                    idx_df, x="date", y="value", color="index",
                    labels={"value": "Normalized (base=100)", "date": "Date"},
                    title="Major Indices (1Y, base=100)",
                )
                fig_idx.update_layout(
                    height=340, plot_bgcolor="#0e1117",
                    paper_bgcolor="#0e1117", font_color="#fafafa",
                )
                st.plotly_chart(fig_idx, use_container_width=True)

        with col_sec:
            sec_names = ["Tech (XLK)", "Semis (SOXX)", "Financials (XLF)",
                         "Energy (XLE)", "Healthcare (XLV)", "Consumer (XLY)"]
            sec_ytd   = [(n, indices[n]["change_ytd"]) for n in sec_names if n in indices]
            if sec_ytd:
                sec_df  = pd.DataFrame(sec_ytd, columns=["sector", "ytd_pct"])
                colors  = ["#00c853" if v >= 0 else "#d50000" for v in sec_df["ytd_pct"]]
                fig_sec = go.Figure(go.Bar(
                    x=sec_df["ytd_pct"], y=sec_df["sector"],
                    orientation="h", marker_color=colors,
                    text=sec_df["ytd_pct"].apply(lambda v: f"{v:+.1f}%"),
                    textposition="outside",
                ))
                fig_sec.update_layout(
                    title="Sector YTD Performance (%)", height=340,
                    plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="#fafafa",
                )
                st.plotly_chart(fig_sec, use_container_width=True)

        # VIX
        if "VIX" in indices:
            vix_df  = pd.DataFrame(indices["VIX"]["normalized"])
            vix_df["date"] = pd.to_datetime(vix_df["date"])
            # Renormalize back to actual value (base was first day's actual price)
            # Instead fetch actual close
            vix_raw = pd.DataFrame(indices["VIX"]["normalized"])
            vix_current = indices["VIX"]["current"]
            st.metric("VIX (Fear Index)", f"{vix_current:.2f}",
                      delta=f"{indices['VIX']['change_1d']:+.2f}% today" if indices["VIX"].get("change_1d") else None)

    # Macro context for stocks
    st.markdown("---")
    st.subheader("Macro Context for Growth Stocks")
    ff = _macro_series("fed_funds")
    cpi_s = _macro_series("cpi")
    if not ff.empty and not cpi_s.empty:
        ff_latest  = ff.iloc[-1]["value"]
        cpi_latest = cpi_s.iloc[-1]["value"]
        cpi_yoy_val= round((cpi_latest / cpi_s.iloc[-13]["value"] - 1) * 100, 1) if len(cpi_s) >= 13 else None
        unemp_s    = _macro_series("unemployment")
        unemp_v    = unemp_s.iloc[-1]["value"] if not unemp_s.empty else None
        cs_s       = _macro_series("consumer_sentiment")
        cs_v       = cs_s.iloc[-1]["value"] if not cs_s.empty else None

        regime = "unknown"
        if ff_latest >= 4.0 and (cpi_yoy_val or 0) > 3:
            regime = "RESTRICTIVE — High rates + high inflation. Headwind for growth stocks."
        elif ff_latest >= 4.0 and (cpi_yoy_val or 0) <= 3:
            regime = "TIGHT but cooling — Rates high, inflation easing. Mixed for growth."
        elif ff_latest < 4.0 and (cpi_yoy_val or 0) <= 3:
            regime = "ACCOMMODATIVE — Low rates + low inflation. Tailwind for growth stocks."
        else:
            regime = "STAGFLATION RISK — Low rates but rising inflation."

        color = "#00c853" if "ACCOMMODATIVE" in regime else "#ffd740" if "TIGHT" in regime else "#d50000"
        st.markdown(f"**Macro Regime:** [{color}]{regime}[/]".replace("[", "<span style='color:").replace("]",  "'>").replace("[/]", "</span>"), unsafe_allow_html=True)

        col_mc1, col_mc2, col_mc3, col_mc4 = st.columns(4)
        col_mc1.metric("Fed Funds", f"{ff_latest:.2f}%")
        col_mc2.metric("CPI YoY", f"{cpi_yoy_val:.1f}%" if cpi_yoy_val else "—")
        col_mc3.metric("Unemployment", f"{unemp_v:.1f}%" if unemp_v else "—")
        col_mc4.metric("Consumer Sentiment", f"{cs_v:.1f}" if cs_v else "—")
