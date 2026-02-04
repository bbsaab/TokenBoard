"""Configuration settings for TokenBoard."""

import os
from pathlib import Path


# Path to Claude data directory containing JSONL files
CLAUDE_DATA_PATH = os.environ.get(
    "CLAUDE_DATA_PATH",
    str(Path.home() / ".claude")
)

# Path to SQLite database
DB_PATH = os.environ.get(
    "DB_PATH",
    str(Path(__file__).parent.parent / "data" / "usage.db")
)

# Token limits for 5-hour rolling window
# Set to None for auto-detection based on usage patterns
FIVE_HOUR_LIMIT_TOKENS = os.environ.get("FIVE_HOUR_LIMIT_TOKENS", None)
if FIVE_HOUR_LIMIT_TOKENS is not None:
    FIVE_HOUR_LIMIT_TOKENS = int(FIVE_HOUR_LIMIT_TOKENS)

# Weekly usage limits in "equivalent hours" (Max plan 5x defaults)
# These represent the weekly allocation for each model tier
WEEKLY_OPUS_HOURS = int(os.environ.get("WEEKLY_OPUS_HOURS", 35))
WEEKLY_SONNET_HOURS = int(os.environ.get("WEEKLY_SONNET_HOURS", 280))

# Estimated tokens per hour for each model (for hour-based calculations)
OPUS_TOKENS_PER_HOUR = int(os.environ.get("OPUS_TOKENS_PER_HOUR", 50000))
SONNET_TOKENS_PER_HOUR = int(os.environ.get("SONNET_TOKENS_PER_HOUR", 100000))
