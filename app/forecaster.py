"""
Usage forecasting module for Claude token usage prediction.

Provides functions for forecasting token usage based on historical data
using simple linear regression and trend analysis.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import numpy as np


@dataclass
class UsagePoint:
    """Represents a single usage data point."""
    timestamp: datetime
    tokens: int


@dataclass
class Forecast:
    """Represents a forecast result with confidence information."""
    predicted_tokens: int
    confidence: float  # 0.0 to 1.0, based on R-squared
    trend: str  # 'increasing', 'decreasing', 'stable'


def _linear_regression(
    x: np.ndarray,
    y: np.ndarray
) -> Tuple[float, float, float]:
    """
    Perform simple linear regression.

    Args:
        x: Independent variable array (e.g., time)
        y: Dependent variable array (e.g., tokens)

    Returns:
        Tuple of (slope, intercept, r_squared)
    """
    n = len(x)
    if n < 2:
        return 0.0, float(y[0]) if n > 0 else 0.0, 0.0

    # Calculate means
    x_mean = np.mean(x)
    y_mean = np.mean(y)

    # Calculate slope and intercept
    numerator = np.sum((x - x_mean) * (y - y_mean))
    denominator = np.sum((x - x_mean) ** 2)

    if denominator == 0:
        return 0.0, y_mean, 0.0

    slope = numerator / denominator
    intercept = y_mean - slope * x_mean

    # Calculate R-squared
    y_pred = slope * x + intercept
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - y_mean) ** 2)

    r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0.0
    r_squared = max(0.0, min(1.0, r_squared))  # Clamp to [0, 1]

    return slope, intercept, r_squared


def forecast_5hour_usage(
    current_usage: int,
    window_start: datetime,
    current_time: Optional[datetime] = None
) -> Forecast:
    """
    Forecast total usage at the end of a 5-hour window using linear extrapolation.

    Args:
        current_usage: Current token usage in the window
        window_start: Start time of the 5-hour window
        current_time: Current time (defaults to now)

    Returns:
        Forecast with predicted tokens at window end
    """
    if current_time is None:
        current_time = datetime.now()

    # Calculate elapsed time in hours
    elapsed = (current_time - window_start).total_seconds() / 3600.0

    if elapsed <= 0:
        return Forecast(
            predicted_tokens=current_usage,
            confidence=0.0,
            trend='stable'
        )

    # Simple linear extrapolation to 5 hours
    rate_per_hour = current_usage / elapsed
    remaining_hours = max(0, 5.0 - elapsed)
    predicted_tokens = current_usage + int(rate_per_hour * remaining_hours)

    # Confidence based on how much of the window has elapsed
    # More elapsed time = more confident prediction
    confidence = min(elapsed / 5.0, 1.0)

    # Determine trend based on rate
    if rate_per_hour > 100:  # Arbitrary threshold for "increasing"
        trend = 'increasing'
    elif rate_per_hour < 10:
        trend = 'stable'
    else:
        trend = 'increasing'

    return Forecast(
        predicted_tokens=predicted_tokens,
        confidence=confidence,
        trend=trend
    )


def forecast_weekly_usage(
    daily_usage_history: List[UsagePoint]
) -> Forecast:
    """
    Forecast weekly usage based on daily usage history using trend analysis.

    Args:
        daily_usage_history: List of daily usage points (should be 7+ days for best results)

    Returns:
        Forecast with predicted weekly tokens
    """
    if not daily_usage_history:
        return Forecast(
            predicted_tokens=0,
            confidence=0.0,
            trend='stable'
        )

    if len(daily_usage_history) == 1:
        # With one data point, assume constant daily usage
        return Forecast(
            predicted_tokens=daily_usage_history[0].tokens * 7,
            confidence=0.1,
            trend='stable'
        )

    # Sort by timestamp
    sorted_history = sorted(daily_usage_history, key=lambda p: p.timestamp)

    # Convert to arrays for regression
    base_time = sorted_history[0].timestamp
    x = np.array([
        (p.timestamp - base_time).total_seconds() / 86400.0  # Days
        for p in sorted_history
    ])
    y = np.array([p.tokens for p in sorted_history])

    slope, intercept, r_squared = _linear_regression(x, y)

    # Predict daily values for next 7 days from last point
    last_day = x[-1]
    future_days = np.arange(last_day + 1, last_day + 8)
    predicted_daily = slope * future_days + intercept

    # Ensure no negative predictions
    predicted_daily = np.maximum(predicted_daily, 0)
    predicted_weekly = int(np.sum(predicted_daily))

    # Determine trend
    if slope > 50:  # Tokens per day increase threshold
        trend = 'increasing'
    elif slope < -50:
        trend = 'decreasing'
    else:
        trend = 'stable'

    # Confidence based on R-squared and data quantity
    data_confidence = min(len(daily_usage_history) / 14.0, 1.0)  # 14 days = full confidence
    confidence = (r_squared * 0.7 + data_confidence * 0.3)

    return Forecast(
        predicted_tokens=predicted_weekly,
        confidence=confidence,
        trend=trend
    )


def will_hit_limit(
    current_usage: int,
    limit: int,
    time_remaining: timedelta,
    recent_usage_points: Optional[List[UsagePoint]] = None
) -> bool:
    """
    Predict whether usage will exceed the limit within the remaining time.

    Args:
        current_usage: Current token usage
        limit: Token limit to check against
        time_remaining: Time remaining in the current window
        recent_usage_points: Optional recent usage data for better prediction

    Returns:
        True if predicted to hit limit, False otherwise
    """
    if current_usage >= limit:
        return True

    if time_remaining.total_seconds() <= 0:
        return False

    # If we have recent usage points, use burn rate
    if recent_usage_points and len(recent_usage_points) >= 2:
        burn_rate = get_burn_rate(recent_usage_points)
        if burn_rate > 0:
            hours_remaining = time_remaining.total_seconds() / 3600.0
            predicted_additional = burn_rate * hours_remaining
            return (current_usage + predicted_additional) >= limit

    # Fallback: assume current rate continues
    # This is a conservative estimate
    return False


def get_burn_rate(
    recent_usage_points: List[UsagePoint]
) -> float:
    """
    Calculate the current token burn rate (tokens per hour).

    Args:
        recent_usage_points: List of recent usage data points

    Returns:
        Burn rate in tokens per hour (0.0 if insufficient data)
    """
    if len(recent_usage_points) < 2:
        return 0.0

    # Sort by timestamp
    sorted_points = sorted(recent_usage_points, key=lambda p: p.timestamp)

    # Convert to arrays
    base_time = sorted_points[0].timestamp
    x = np.array([
        (p.timestamp - base_time).total_seconds() / 3600.0  # Hours
        for p in sorted_points
    ])
    y = np.array([float(p.tokens) for p in sorted_points])

    # Use linear regression to get rate
    slope, _, _ = _linear_regression(x, y)

    # Return positive rate (tokens per hour)
    return max(0.0, slope)


def get_usage_trend(
    usage_points: List[UsagePoint],
    window_hours: float = 1.0
) -> str:
    """
    Analyze recent usage trend.

    Args:
        usage_points: List of usage data points
        window_hours: Time window to analyze (default 1 hour)

    Returns:
        Trend string: 'increasing', 'decreasing', or 'stable'
    """
    if len(usage_points) < 2:
        return 'stable'

    # Filter to window
    now = datetime.now()
    window_start = now - timedelta(hours=window_hours)

    filtered = [p for p in usage_points if p.timestamp >= window_start]

    if len(filtered) < 2:
        return 'stable'

    # Calculate trend using first and last points
    sorted_points = sorted(filtered, key=lambda p: p.timestamp)
    first = sorted_points[0]
    last = sorted_points[-1]

    time_diff = (last.timestamp - first.timestamp).total_seconds() / 3600.0
    if time_diff <= 0:
        return 'stable'

    rate = (last.tokens - first.tokens) / time_diff

    # Thresholds for trend classification
    if rate > 100:  # More than 100 tokens/hour increase
        return 'increasing'
    elif rate < -100:
        return 'decreasing'
    else:
        return 'stable'


def estimate_time_to_limit(
    current_usage: int,
    limit: int,
    burn_rate: float
) -> Optional[timedelta]:
    """
    Estimate time until limit is reached at current burn rate.

    Args:
        current_usage: Current token usage
        limit: Token limit
        burn_rate: Current burn rate (tokens per hour)

    Returns:
        Estimated time to limit, or None if limit won't be reached
    """
    if current_usage >= limit:
        return timedelta(seconds=0)

    if burn_rate <= 0:
        return None

    remaining_tokens = limit - current_usage
    hours_to_limit = remaining_tokens / burn_rate

    return timedelta(hours=hours_to_limit)


# Example usage and testing
if __name__ == '__main__':
    from datetime import datetime, timedelta

    # Test forecast_5hour_usage
    print("=== 5-Hour Forecast Test ===")
    window_start = datetime.now() - timedelta(hours=2)
    forecast = forecast_5hour_usage(
        current_usage=10000,
        window_start=window_start
    )
    print(f"Predicted tokens: {forecast.predicted_tokens}")
    print(f"Confidence: {forecast.confidence:.2f}")
    print(f"Trend: {forecast.trend}")

    # Test forecast_weekly_usage
    print("\n=== Weekly Forecast Test ===")
    daily_history = [
        UsagePoint(datetime.now() - timedelta(days=6), 5000),
        UsagePoint(datetime.now() - timedelta(days=5), 5500),
        UsagePoint(datetime.now() - timedelta(days=4), 6000),
        UsagePoint(datetime.now() - timedelta(days=3), 5800),
        UsagePoint(datetime.now() - timedelta(days=2), 6200),
        UsagePoint(datetime.now() - timedelta(days=1), 6500),
        UsagePoint(datetime.now(), 7000),
    ]
    weekly_forecast = forecast_weekly_usage(daily_history)
    print(f"Predicted weekly tokens: {weekly_forecast.predicted_tokens}")
    print(f"Confidence: {weekly_forecast.confidence:.2f}")
    print(f"Trend: {weekly_forecast.trend}")

    # Test burn rate
    print("\n=== Burn Rate Test ===")
    recent_points = [
        UsagePoint(datetime.now() - timedelta(minutes=30), 1000),
        UsagePoint(datetime.now() - timedelta(minutes=20), 1500),
        UsagePoint(datetime.now() - timedelta(minutes=10), 2200),
        UsagePoint(datetime.now(), 3000),
    ]
    rate = get_burn_rate(recent_points)
    print(f"Burn rate: {rate:.2f} tokens/hour")

    # Test will_hit_limit
    print("\n=== Limit Prediction Test ===")
    will_hit = will_hit_limit(
        current_usage=80000,
        limit=100000,
        time_remaining=timedelta(hours=3),
        recent_usage_points=recent_points
    )
    print(f"Will hit limit: {will_hit}")

    # Test time to limit
    print("\n=== Time to Limit Test ===")
    time_to_limit = estimate_time_to_limit(
        current_usage=80000,
        limit=100000,
        burn_rate=rate
    )
    if time_to_limit:
        print(f"Time to limit: {time_to_limit}")
    else:
        print("Limit will not be reached at current rate")
