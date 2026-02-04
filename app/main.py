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
    five_hour = db.get_usage_in_window(hours=5)
    weekly = db.get_usage_in_days(days=7)

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

    # Convert to UsagePoint format for forecaster
    usage_points = []
    for entry in hourly_data:
        try:
            ts = datetime.fromisoformat(entry["hour"].replace("Z", "+00:00"))
            usage_points.append(UsagePoint(timestamp=ts, tokens=entry["total_tokens"]))
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

    # Forecast for 5-hour window
    five_hour_forecast = None
    will_exceed_5h = False
    time_to_limit = None

    if config.FIVE_HOUR_LIMIT_TOKENS and burn_rate > 0:
        # Use simple linear extrapolation based on burn rate
        five_hour_forecast = int(current_total + (burn_rate * 5))
        will_exceed_5h = five_hour_forecast > config.FIVE_HOUR_LIMIT_TOKENS

        if will_exceed_5h:
            remaining = config.FIVE_HOUR_LIMIT_TOKENS - current_total
            hours_to_limit = remaining / burn_rate
            time_to_limit = f"{hours_to_limit:.1f}h"

    return jsonify({
        "hourly_rate": hourly_rate,
        "daily_projection": daily_projection,
        "weekly_projection": weekly_projection,
        "five_hour_projection": five_hour_forecast,
        "will_exceed_5h": will_exceed_5h,
        "time_to_limit": time_to_limit,
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
    # Get calculated token totals
    five_hour = db.get_usage_in_window(hours=5)
    weekly = db.get_usage_in_days(days=7)

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
