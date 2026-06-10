#!/bin/bash
# Daily stock analysis runner.
# Creates a date-stamped results folder and runs the full analysis.

set -euo pipefail

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="/usr/bin/python3"
DATE_TAG=$(date +%Y-%m-%d)
RUN_DIR="$PROJECT_DIR/results/$DATE_TAG"

# Add homebrew to PATH so the claude CLI is found
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# ── Setup ──────────────────────────────────────────────────────────────────────
mkdir -p "$RUN_DIR"
mkdir -p "$PROJECT_DIR/logs"

LOG="$PROJECT_DIR/logs/daily_$DATE_TAG.log"

echo "[$DATE_TAG] Starting analysis..." | tee -a "$LOG"
echo "Output folder: $RUN_DIR" | tee -a "$LOG"

# ── Run analysis ───────────────────────────────────────────────────────────────
cd "$PROJECT_DIR"

REPORTS_DIR="$RUN_DIR" $PYTHON main.py \
  --limit 20 \
  2>&1 | tee -a "$LOG"

EXIT_CODE=${PIPESTATUS[0]}

# ── macOS notification when done ───────────────────────────────────────────────
if command -v osascript &>/dev/null; then
  if [ $EXIT_CODE -eq 0 ]; then
    osascript -e 'display notification "Stock analysis complete. Check results folder." with title "Stock Analyzer" sound name "Glass"'
  else
    osascript -e 'display notification "Stock analysis failed. Check logs." with title "Stock Analyzer" sound name "Basso"'
  fi
fi

# ── Fill in actual prices for past predictions ────────────────────────────────
echo "[$DATE_TAG] Updating historical actuals..." | tee -a "$LOG"
$PYTHON -m database.track_actuals 2>&1 | tee -a "$LOG"

echo "[$DATE_TAG] Done (exit $EXIT_CODE)" | tee -a "$LOG"
exit $EXIT_CODE
