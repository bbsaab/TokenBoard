"""OAuth API client for fetching official Claude usage data."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from . import config

# Cache for OAuth usage to avoid hammering the API
_oauth_cache = {
    "data": None,
    "timestamp": None,
    "cache_duration_seconds": 60  # Cache for 1 minute
}


def get_oauth_token() -> Optional[str]:
    """
    Extract OAuth access token from Claude credentials file.

    Returns None if credentials not found or invalid.
    """
    creds_path = Path(config.CLAUDE_DATA_PATH) / ".credentials.json"

    if not creds_path.exists():
        return None

    try:
        with open(creds_path, "r") as f:
            creds = json.load(f)

        # Token is nested under claudeAiOauth
        oauth_data = creds.get("claudeAiOauth", {})
        return oauth_data.get("accessToken")
    except (json.JSONDecodeError, IOError):
        return None


def fetch_oauth_usage() -> Optional[dict]:
    """
    Fetch real-time usage data from Anthropic OAuth API.

    Returns:
        {
            "five_hour": {"utilization": 36.0, "resets_at": "2026-02-03T..."},
            "seven_day": {"utilization": 30.0, "resets_at": "2026-02-10T..."}
        }

    Returns None if API call fails or token not available.
    """
    token = get_oauth_token()
    if not token:
        return None

    try:
        resp = requests.get(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20"
            },
            timeout=10
        )

        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"OAuth API error: {resp.status_code}", flush=True)
            return None

    except requests.RequestException as e:
        print(f"OAuth API request failed: {e}", flush=True)
        return None


def get_oauth_usage_cached() -> Optional[dict]:
    """
    Get OAuth usage with caching to avoid excessive API calls.

    Returns cached data if less than cache_duration_seconds old.
    """
    now = datetime.now()

    # Check if cache is valid
    if _oauth_cache["data"] is not None and _oauth_cache["timestamp"] is not None:
        age = (now - _oauth_cache["timestamp"]).total_seconds()
        if age < _oauth_cache["cache_duration_seconds"]:
            return _oauth_cache["data"]

    # Fetch fresh data
    data = fetch_oauth_usage()
    if data:
        _oauth_cache["data"] = data
        _oauth_cache["timestamp"] = now

    return data


def get_calibration_data(calculated_5h_tokens: int, calculated_7d_tokens: int) -> dict:
    """
    Get calibration data comparing OAuth percentages with calculated tokens.

    Returns derived limits based on the ratio.
    """
    oauth_data = get_oauth_usage_cached()

    result = {
        "oauth_available": oauth_data is not None,
        "five_hour": {
            "official_percent": None,
            "resets_at": None,
            "calculated_tokens": calculated_5h_tokens,
            "derived_limit": None,
        },
        "seven_day": {
            "official_percent": None,
            "resets_at": None,
            "calculated_tokens": calculated_7d_tokens,
            "derived_limit": None,
        },
        "last_updated": datetime.now().isoformat(),
    }

    if oauth_data:
        # 5-hour window
        five_hour = oauth_data.get("five_hour", {})
        five_hour_pct = five_hour.get("utilization")
        if five_hour_pct is not None and five_hour_pct > 0:
            result["five_hour"]["official_percent"] = five_hour_pct
            result["five_hour"]["resets_at"] = five_hour.get("resets_at")
            # Derive the limit: tokens / (percent/100)
            result["five_hour"]["derived_limit"] = int(calculated_5h_tokens / (five_hour_pct / 100))

        # 7-day window
        seven_day = oauth_data.get("seven_day", {})
        seven_day_pct = seven_day.get("utilization")
        if seven_day_pct is not None and seven_day_pct > 0:
            result["seven_day"]["official_percent"] = seven_day_pct
            result["seven_day"]["resets_at"] = seven_day.get("resets_at")
            # Derive the limit: tokens / (percent/100)
            result["seven_day"]["derived_limit"] = int(calculated_7d_tokens / (seven_day_pct / 100))

    return result
