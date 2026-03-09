"""Configuration settings for TokenBoard."""

import os
import platform
from pathlib import Path


def discover_claude_data_path() -> str:
    """
    Discover the Claude data directory across Windows, Linux, and macOS.

    Search order:
      1. CLAUDE_DATA_PATH environment variable (explicit override)
      2. ~/.claude (Linux/macOS native, or Windows if present)
      3. %APPDATA%/claude (Windows alternative)
      4. %USERPROFILE%/.claude (Windows home fallback)

    Returns the first path that exists, or ~/.claude as the default.
    """
    # 1. Explicit override always wins
    env_path = os.environ.get("CLAUDE_DATA_PATH")
    if env_path:
        resolved = Path(env_path)
        if resolved.exists():
            print(f"Claude data: {resolved} (from CLAUDE_DATA_PATH env)", flush=True)
            return str(resolved)
        print(f"Warning: CLAUDE_DATA_PATH={env_path} does not exist, searching...", flush=True)

    # 2. Build candidate paths based on platform
    candidates = []
    home = Path.home()
    system = platform.system()  # 'Windows', 'Linux', 'Darwin'

    # Universal: ~/.claude (works on all platforms)
    candidates.append(home / ".claude")

    if system == "Windows":
        # %APPDATA%/claude
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "claude")
        # %LOCALAPPDATA%/claude
        localappdata = os.environ.get("LOCALAPPDATA")
        if localappdata:
            candidates.append(Path(localappdata) / "claude")
        # %USERPROFILE%/.claude (explicit, in case home != USERPROFILE)
        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            candidates.append(Path(userprofile) / ".claude")

    # 3. Return first path that exists
    for path in candidates:
        if path.exists():
            print(f"Claude data: {path} (auto-detected on {system})", flush=True)
            return str(path)

    # 4. Default fallback
    default = str(home / ".claude")
    print(f"Claude data: {default} (default — directory not yet found)", flush=True)
    return default


# Path to Claude data directory containing JSONL files
CLAUDE_DATA_PATH = discover_claude_data_path()

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
