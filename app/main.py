"""Flask application for TokenBoard dashboard."""

import threading
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, render_template, send_from_directory

from . import config, db, parser, usage_api
from .watcher import create_watcher
from .forecaster import get_burn_rate, forecast_5hour_usage, UsagePoint

# Track background import status
_import_status = {
    "running": False,
    "completed": False,
    "new_records": 0,
    "total_processed": 0,
}

# Set up Flask with correct template and static paths
app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent.parent / "templates"),
    static_folder=str(Path(__file__).parent.parent / "static"),
)

# Global watcher instance
_watcher = None
_watcher_thread = None


def on_new_usage(raw_record: dict) -> None:
    """Callback for when new usage data is detected from watcher."""
    try:
        # Only process assistant messages with usage data
        if raw_record.get("type") != "assistant":
            return

        usage = raw_record.get("message", {}).get("usage")
        if not usage:
            return

        timestamp = raw_record.get("timestamp")
        if not timestamp:
            return

        session_id = raw_record.get("sessionId", "unknown")
        model = raw_record.get("message", {}).get("model", "unknown")

        db.insert_usage(
            timestamp=timestamp,
            session_id=session_id,
            model=model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
        )
    except Exception as e:
        # Silently ignore malformed records
        pass


@app.route("/")
def dashboard():
    """Serve the dashboard HTML."""
    return render_template("index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    """Serve static files."""
    return send_from_directory(app.static_folder, filename)


@app.route("/api/usage")
def api_usage():
    """Return current usage stats for 5-hour window and weekly."""
    # Try to get accurate window start times from OAuth resets_at
    oauth_data = usage_api.get_oauth_usage_cached()

    five_hour_since = None
    weekly_since = None

    if oauth_data:
        # Calculate 5-hour window start from resets_at
        five_hour_resets = oauth_data.get("five_hour", {}).get("resets_at")
        if five_hour_resets:
            try:
                reset_time = datetime.fromisoformat(five_hour_resets.replace("Z", "+00:00"))
                # Window started 5 hours before it resets
                window_start = reset_time - timedelta(hours=5)
                five_hour_since = window_start.isoformat()
            except (ValueError, TypeError):
                pass

        # Calculate 7-day window start from resets_at
        weekly_resets = oauth_data.get("seven_day", {}).get("resets_at")
        if weekly_resets:
            try:
                reset_time = datetime.fromisoformat(weekly_resets.replace("Z", "+00:00"))
                # Window started 7 days before it resets
                window_start = reset_time - timedelta(days=7)
                weekly_since = window_start.isoformat()
            except (ValueError, TypeError):
                pass

    # Get usage with OAuth-aligned windows (fall back to rolling windows)
    five_hour = db.get_usage_in_window(since=five_hour_since, hours=5)
    weekly = db.get_usage_in_window(since=weekly_since, hours=7*24)

    return jsonify({
        "five_hour": five_hour,
        "five_hour_limit": config.FIVE_HOUR_LIMIT_TOKENS,
        "weekly": weekly,
        "weekly_opus_hours": config.WEEKLY_OPUS_HOURS,
        "weekly_sonnet_hours": config.WEEKLY_SONNET_HOURS,
        "opus_tokens_per_hour": config.OPUS_TOKENS_PER_HOUR,
        "sonnet_tokens_per_hour": config.SONNET_TOKENS_PER_HOUR,
    })


@app.route("/api/history")
def api_history():
    """Return historical data for charts."""
    hourly = db.get_hourly_aggregates(hours=48)
    daily = db.get_daily_aggregates(days=14)

    return jsonify({
        "hourly": hourly,
        "daily": daily,
    })


@app.route("/api/forecast")
def api_forecast():
    """Return projected usage based on recent activity."""
    # Get recent hourly aggregates for burn rate calculation
    hourly_data = db.get_hourly_aggregates(hours=6)

    # Convert to UsagePoint format with CUMULATIVE tokens for forecaster
    # The burn rate function expects cumulative data for linear regression
    usage_points = []
    cumulative_tokens = 0
    for entry in sorted(hourly_data, key=lambda x: x["hour"]):
        try:
            ts = datetime.fromisoformat(entry["hour"].replace("Z", "+00:00"))
            cumulative_tokens += entry["total_tokens"]
            usage_points.append(UsagePoint(timestamp=ts, tokens=cumulative_tokens))
        except (KeyError, ValueError):
            continue

    # Calculate burn rate
    burn_rate = get_burn_rate(usage_points) if len(usage_points) >= 2 else 0

    # Get current usage for projection
    current_5h = db.get_usage_in_window(hours=5)
    current_total = current_5h.get("total_tokens", 0)

    # Calculate projections
    hourly_rate = int(burn_rate)
    daily_projection = int(burn_rate * 24)
    weekly_projection = int(burn_rate * 24 * 7)

    # Get calibration data for OAuth-derived limits
    current_weekly = db.get_usage_in_days(days=7)
    weekly_total = current_weekly.get("total_tokens", 0)
    calibration = usage_api.get_calibration_data(current_total, weekly_total)

    # Forecast for 5-hour window using OAuth-derived limit
    five_hour_forecast = None
    will_exceed_5h = False
    time_to_limit = None
    hours_to_5h_limit = None
    critical_5h = False  # True if will hit limit before reset

    # Prefer OAuth-derived limit, fall back to config
    five_hour_limit = calibration.get("five_hour", {}).get("derived_limit") or config.FIVE_HOUR_LIMIT_TOKENS

    if five_hour_limit and burn_rate > 0:
        # Use simple linear extrapolation based on burn rate
        five_hour_forecast = int(current_total + (burn_rate * 5))
        will_exceed_5h = five_hour_forecast > five_hour_limit

        if current_total < five_hour_limit:
            remaining = five_hour_limit - current_total
            hours_to_5h_limit = remaining / burn_rate
            will_exceed_5h = True
            if hours_to_5h_limit < 1:
                time_to_limit = f"{int(hours_to_5h_limit * 60)}m"
            else:
                time_to_limit = f"{hours_to_5h_limit:.1f}h"

            # Check if we'll hit limit before reset (critical warning)
            five_hour_resets_at = calibration.get("five_hour", {}).get("resets_at")
            if five_hour_resets_at:
                try:
                    reset_time = datetime.fromisoformat(five_hour_resets_at.replace("Z", "+00:00"))
                    hours_until_reset = (reset_time - datetime.now(reset_time.tzinfo)).total_seconds() / 3600
                    if hours_to_5h_limit < hours_until_reset:
                        critical_5h = True
                except (ValueError, TypeError):
                    pass

    # Calculate historical daily burn rate from recent days
    historical_daily_burn_rate = 0
    daily_data = db.get_daily_aggregates(days=7)
    if daily_data:
        active_days = [d for d in daily_data if d.get("total_tokens", 0) > 0]
        if active_days:
            total_tokens = sum(d.get("total_tokens", 0) for d in active_days)
            historical_daily_burn_rate = total_tokens / len(active_days)

    # Historical hourly burn rate = daily average / 24
    historical_hourly_burn_rate = historical_daily_burn_rate / 24 if historical_daily_burn_rate > 0 else 0

    # Session daily burn rate = current hourly rate * 24
    session_daily_burn_rate = burn_rate * 24 if burn_rate > 0 else 0

    # Get limits and reset times
    five_hour_limit = calibration.get("five_hour", {}).get("derived_limit") or config.FIVE_HOUR_LIMIT_TOKENS
    weekly_limit = calibration.get("seven_day", {}).get("derived_limit")
    five_hour_resets_at = calibration.get("five_hour", {}).get("resets_at")
    weekly_resets_at = calibration.get("seven_day", {}).get("resets_at")

    # Calculate hours until 5-hour reset
    hours_until_5h_reset = 5  # Default fallback
    if five_hour_resets_at:
        try:
            reset_time = datetime.fromisoformat(five_hour_resets_at.replace("Z", "+00:00"))
            hours_until_5h_reset = (reset_time - datetime.now(reset_time.tzinfo)).total_seconds() / 3600
        except (ValueError, TypeError):
            pass

    # Calculate days until weekly reset
    days_until_reset = 7  # Default fallback
    if weekly_resets_at:
        try:
            reset_time = datetime.fromisoformat(weekly_resets_at.replace("Z", "+00:00"))
            days_until_reset = (reset_time - datetime.now(reset_time.tzinfo)).total_seconds() / (3600 * 24)
        except (ValueError, TypeError):
            pass

    # Helper function to format time to limit
    def format_time_to_limit(hours):
        if hours is None:
            return None
        if hours < 1:
            return f"{int(hours * 60)}m"
        elif hours < 24:
            return f"{hours:.1f}h"
        else:
            days = hours / 24
            return f"{days:.1f}d"

    # === 5-HOUR SESSION FORECASTS ===
    five_hour_remaining = five_hour_limit - current_total if five_hour_limit else 0

    # Session forecast (current burn rate)
    five_hour_session_forecast = None
    five_hour_session_critical = False
    if burn_rate > 0 and five_hour_remaining > 0:
        hours_to_limit = five_hour_remaining / burn_rate
        five_hour_session_forecast = format_time_to_limit(hours_to_limit)
        if hours_to_limit < hours_until_5h_reset:
            five_hour_session_critical = True

    # Historical forecast (historical burn rate)
    five_hour_historical_forecast = None
    five_hour_historical_critical = False
    if historical_hourly_burn_rate > 0 and five_hour_remaining > 0:
        hours_to_limit = five_hour_remaining / historical_hourly_burn_rate
        five_hour_historical_forecast = format_time_to_limit(hours_to_limit)
        if hours_to_limit < hours_until_5h_reset:
            five_hour_historical_critical = True

    # === WEEKLY SESSION FORECASTS ===
    weekly_remaining = weekly_limit - weekly_total if weekly_limit else 0

    # Session forecast (current burn rate extrapolated to daily)
    weekly_session_forecast = None
    weekly_session_critical = False
    if session_daily_burn_rate > 0 and weekly_remaining > 0:
        days_to_limit = weekly_remaining / session_daily_burn_rate
        weekly_session_forecast = format_time_to_limit(days_to_limit * 24)
        if days_to_limit < days_until_reset:
            weekly_session_critical = True

    # Historical forecast (historical daily burn rate)
    weekly_historical_forecast = None
    weekly_historical_critical = False
    if historical_daily_burn_rate > 0 and weekly_remaining > 0:
        days_to_limit = weekly_remaining / historical_daily_burn_rate
        weekly_historical_forecast = format_time_to_limit(days_to_limit * 24)
        if days_to_limit < days_until_reset:
            weekly_historical_critical = True

    return jsonify({
        # New structured data for 2x2 grid
        "five_hour": {
            "session": {
                "burn_rate": int(burn_rate / 60) if burn_rate > 0 else 0,  # tokens/min
                "burn_rate_unit": "tok/min",
                "forecast": five_hour_session_forecast,
                "critical": five_hour_session_critical
            },
            "historical": {
                "burn_rate": int(historical_hourly_burn_rate / 60) if historical_hourly_burn_rate > 0 else 0,
                "burn_rate_unit": "tok/min",
                "forecast": five_hour_historical_forecast,
                "critical": five_hour_historical_critical
            },
            "hours_until_reset": round(hours_until_5h_reset, 1)
        },
        "weekly": {
            "session": {
                "burn_rate": int(session_daily_burn_rate / 1000000) if session_daily_burn_rate > 0 else 0,  # M tokens/day
                "burn_rate_unit": "M/day",
                "forecast": weekly_session_forecast,
                "critical": weekly_session_critical
            },
            "historical": {
                "burn_rate": int(historical_daily_burn_rate / 1000000) if historical_daily_burn_rate > 0 else 0,
                "burn_rate_unit": "M/day",
                "forecast": weekly_historical_forecast,
                "critical": weekly_historical_critical
            },
            "days_until_reset": round(days_until_reset, 1)
        },
        # Legacy fields for backward compatibility
        "hourly_rate": hourly_rate,
        "daily_projection": daily_projection,
        "weekly_projection": weekly_projection,
        "burn_rate_per_min": int(burn_rate / 60) if burn_rate > 0 else 0,
    })


@app.route("/api/refresh")
def api_refresh():
    """Trigger a refresh of data from JSONL files."""
    claude_path = Path(config.CLAUDE_DATA_PATH)
    new_records, total_processed = parser.import_from_directory(claude_path)

    return jsonify({
        "new_records": new_records,
        "total_processed": total_processed,
        "total_in_db": db.get_record_count(),
    })


@app.route("/api/status")
def api_status():
    """Return system status information."""
    return jsonify({
        "watcher_active": _watcher is not None,
        "db_path": config.DB_PATH,
        "claude_data_path": config.CLAUDE_DATA_PATH,
        "total_records": db.get_record_count(),
        "import_status": _import_status,
    })


@app.route("/api/calibration")
def api_calibration():
    """
    Return calibration data comparing OAuth usage percentages with calculated tokens.

    This allows cross-referencing our JSONL-based calculations with
    Anthropic's official usage percentages from /usage.
    """
    # Try to get accurate window start times from OAuth resets_at
    oauth_data = usage_api.get_oauth_usage_cached()

    five_hour_since = None
    weekly_since = None

    if oauth_data:
        # Calculate 5-hour window start from resets_at
        five_hour_resets = oauth_data.get("five_hour", {}).get("resets_at")
        if five_hour_resets:
            try:
                reset_time = datetime.fromisoformat(five_hour_resets.replace("Z", "+00:00"))
                window_start = reset_time - timedelta(hours=5)
                five_hour_since = window_start.isoformat()
            except (ValueError, TypeError):
                pass

        # Calculate 7-day window start from resets_at
        weekly_resets = oauth_data.get("seven_day", {}).get("resets_at")
        if weekly_resets:
            try:
                reset_time = datetime.fromisoformat(weekly_resets.replace("Z", "+00:00"))
                window_start = reset_time - timedelta(days=7)
                weekly_since = window_start.isoformat()
            except (ValueError, TypeError):
                pass

    # Get calculated token totals with OAuth-aligned windows
    five_hour = db.get_usage_in_window(since=five_hour_since, hours=5)
    weekly = db.get_usage_in_window(since=weekly_since, hours=7*24)

    calculated_5h = five_hour.get("total_tokens", 0)
    calculated_7d = weekly.get("total_tokens", 0)

    # Get calibration data from OAuth API
    calibration = usage_api.get_calibration_data(calculated_5h, calculated_7d)

    return jsonify(calibration)


def start_watcher():
    """Start the file watcher in a background thread."""
    global _watcher, _watcher_thread

    try:
        _watcher = create_watcher(
            watch_path=Path(config.CLAUDE_DATA_PATH) / "projects",
            callback=on_new_usage,
        )
        _watcher_thread = threading.Thread(target=_watcher.start, daemon=True)
        _watcher_thread.start()
        print("File watcher started")
    except Exception as e:
        print(f"Warning: Could not start file watcher: {e}")
        _watcher = None


def background_import():
    """Run JSONL import in background thread."""
    global _import_status

    _import_status["running"] = True
    claude_path = Path(config.CLAUDE_DATA_PATH)

    try:
        if claude_path.exists():
            print(f"Background import started: {claude_path}", flush=True)
            new_records, total_processed = parser.import_from_directory(claude_path)
            _import_status["new_records"] = new_records
            _import_status["total_processed"] = total_processed
            print(f"Background import complete: {new_records} new records from {total_processed} entries", flush=True)
        else:
            print(f"Warning: Claude data path not found: {claude_path}", flush=True)
    except Exception as e:
        print(f"Background import error: {e}", flush=True)
    finally:
        _import_status["running"] = False
        _import_status["completed"] = True
        print(f"Total records in database: {db.get_record_count()}", flush=True)


def init_app():
    """Initialize the application on startup."""
    import sys

    print("=" * 50, flush=True)
    print("Initializing TokenBoard...", flush=True)
    print("=" * 50, flush=True)

    # Ensure data directory exists
    data_dir = Path(config.DB_PATH).parent
    data_dir.mkdir(parents=True, exist_ok=True)

    # Initialize database
    db.init_db()
    print(f"Database: {config.DB_PATH}", flush=True)

    # Start background import thread (non-blocking)
    import_thread = threading.Thread(target=background_import, daemon=True)
    import_thread.start()
    print("Background import started...", flush=True)

    # Start file watcher for real-time updates
    start_watcher()

    print("=" * 50, flush=True)
    print("TokenBoard ready at http://localhost:8080", flush=True)
    print("=" * 50, flush=True)
    sys.stdout.flush()


# Initialize on module load
with app.app_context():
    init_app()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080, use_reloader=False)
