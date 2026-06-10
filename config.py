import os
from dotenv import load_dotenv

load_dotenv()

# StockTwits (public endpoints — no key required)
STOCKTWITS_TOKEN     = os.getenv("STOCKTWITS_ACCESS_TOKEN", "")

# Free data sources
ALPHA_VANTAGE_KEY    = os.getenv("ALPHA_VANTAGE_KEY", "")
FINNHUB_KEY          = os.getenv("FINNHUB_KEY", "")

# Paid data sources
POLYGON_KEY          = os.getenv("POLYGON_KEY", "")
FMP_KEY              = os.getenv("FMP_KEY", "")
FMP_BASE             = os.getenv("FMP_BASE", "https://financialmodelingprep.com/stable")

# Claude CLI (no API key — uses Claude Code Pro auth)
CLAUDE_MODEL         = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# Runtime tuning
RATE_LIMIT_DELAY            = float(os.getenv("RATE_LIMIT_DELAY", "2"))
STOCKTWITS_SENTIMENT_LIMIT  = 30    # public endpoint max
NEWS_ARTICLES_LIMIT         = 25

REPORTS_DIR = os.getenv("REPORTS_DIR", "reports")
LOGS_DIR    = os.getenv("LOGS_DIR", "logs")
