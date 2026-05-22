"""Detect 'expired idle' Claude session windows and expose state for the UI.

Runs as a background daemon thread (see app/main.py:init_app()). Re-evaluates
every REFRESH_CHECK_INTERVAL_SECONDS using the cached OAuth metering response
plus a MAX(timestamp) query against usage_records. No outbound HTTP of its
own — relies on usage_api.get_oauth_usage_cached() (5-min TTL).
"""

import threading
import time
from datetime import datetime, timezone

from . import config, db, usage_api

_window_status: dict = {
    "state": "unknown",
    "expired_at": None,
    "next_resets_at": None,
    "minutes_since_expiry": None,
    "minutes_since_last_activity": None,
    "refresh_recommended": False,
    "last_evaluated_at": None,
}
_lock = threading.Lock()


def evaluate_once() -> dict:
    """Compute and store the current window state. Returns a snapshot copy."""
    now = datetime.now(timezone.utc)
    oauth = usage_api.get_oauth_usage_cached()
    last_activity_iso = db.get_latest_activity()

    snapshot = {
        "state": "unknown",
        "expired_at": None,
        "next_resets_at": None,
        "minutes_since_expiry": None,
        "minutes_since_last_activity": None,
        "refresh_recommended": False,
        "last_evaluated_at": now.isoformat(),
    }

    if last_activity_iso:
        last_activity = datetime.fromisoformat(last_activity_iso.replace("Z", "+00:00"))
        snapshot["minutes_since_last_activity"] = int((now - last_activity).total_seconds() / 60)

    if oauth and oauth.get("five_hour", {}).get("resets_at"):
        resets_at = datetime.fromisoformat(oauth["five_hour"]["resets_at"].replace("Z", "+00:00"))
        snapshot["next_resets_at"] = resets_at.isoformat()
        utilization = oauth["five_hour"].get("utilization", 0)

        if resets_at > now and utilization > 0:
            snapshot["state"] = "active"
        elif resets_at <= now:
            snapshot["state"] = "expired_idle"
            snapshot["expired_at"] = resets_at.isoformat()
            snapshot["minutes_since_expiry"] = int((now - resets_at).total_seconds() / 60)

            idle_min = snapshot["minutes_since_last_activity"] or 0
            if idle_min >= config.REFRESH_IDLE_THRESHOLD_MINUTES:
                snapshot["refresh_recommended"] = True
        else:
            snapshot["state"] = "no_data"

    with _lock:
        _window_status.update(snapshot)
    return dict(snapshot)


def get_status() -> dict:
    """Thread-safe read of the current snapshot."""
    with _lock:
        return dict(_window_status)


def run_loop() -> None:
    """Daemon-thread entry point. Re-evaluates every REFRESH_CHECK_INTERVAL_SECONDS."""
    while True:
        try:
            evaluate_once()
        except Exception as e:
            print(f"window_state evaluation error: {e}", flush=True)
        time.sleep(config.REFRESH_CHECK_INTERVAL_SECONDS)
