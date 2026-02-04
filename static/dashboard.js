// TokenBoard Dashboard JavaScript

// Chart instances
let hourlyChart = null;
let weeklyChart = null;

// Cached derived limits from OAuth calibration
let cachedDerivedLimits = {
    fiveHour: null,
    sevenDay: null
};

// Chart.js default configuration for dark theme
Chart.defaults.color = '#a0a0a0';
Chart.defaults.borderColor = 'rgba(255, 255, 255, 0.1)';

// Utility Functions
function formatNumber(num) {
    if (num === null || num === undefined) return '--';
    return num.toLocaleString('en-US');
}

function formatTokens(num) {
    if (num === null || num === undefined) return '--';
    if (num >= 1000000) {
        return (num / 1000000).toFixed(2) + 'M';
    } else if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    }
    return formatNumber(num);
}

function formatTime(timestamp) {
    if (!timestamp) return '--';
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit'
    });
}

function formatDate(dateStr) {
    if (!dateStr) return '--';
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
        weekday: 'short',
        month: 'short',
        day: 'numeric'
    });
}

function getStatusColor(percent) {
    if (percent < 50) return 'green';
    if (percent < 80) return 'yellow';
    return 'red';
}

function getStatusText(percent) {
    if (percent < 50) return 'On Track';
    if (percent < 80) return 'Moderate Usage';
    return 'High Usage';
}

// Update status indicator
function updateStatusIndicator(percent) {
    const indicator = document.getElementById('statusIndicator');
    if (!indicator) return;

    const status = getStatusColor(percent);
    const text = getStatusText(percent);

    indicator.className = 'status-indicator status-' + status;
    const textEl = indicator.querySelector('.status-text');
    if (textEl) textEl.textContent = text;
}

// Update progress bar
function updateProgressBar(id, percent, value, limit) {
    const progressEl = document.getElementById(id);
    const percentEl = document.getElementById(id.replace('Progress', 'Percent'));

    if (progressEl) {
        const color = getStatusColor(percent);
        progressEl.style.width = Math.min(percent, 100) + '%';
        progressEl.className = 'progress-fill progress-' + color;
    }

    if (percentEl) {
        percentEl.textContent = percent.toFixed(1) + '%';
    }
}

// Fetch and update usage data
async function fetchUsage() {
    try {
        const response = await fetch('/api/usage');
        if (!response.ok) throw new Error('Failed to fetch usage');
        const data = await response.json();

        // 5-hour window stats
        const fiveHour = data.five_hour || {};
        const fiveHourTotal = fiveHour.total_tokens || 0;
        // Use cached derived limit from OAuth calibration, fall back to config
        const fiveHourLimit = cachedDerivedLimits.fiveHour || data.five_hour_limit;

        // Update 5-hour display
        const hourlyUsageEl = document.getElementById('hourlyUsage');
        if (hourlyUsageEl) hourlyUsageEl.textContent = formatTokens(fiveHourTotal);

        const hourlyLimitEl = document.getElementById('hourlyLimit');
        if (hourlyLimitEl) hourlyLimitEl.textContent = fiveHourLimit ? formatTokens(fiveHourLimit) : 'No limit set';

        // Calculate and show percentage if we have a limit
        let hourlyPercent = 0;
        if (fiveHourLimit && fiveHourLimit > 0) {
            hourlyPercent = (fiveHourTotal / fiveHourLimit) * 100;
            updateProgressBar('hourlyProgress', hourlyPercent);
        }

        // Weekly stats
        const weekly = data.weekly || {};
        const weeklyTotal = weekly.total_tokens || 0;

        // Use cached derived limit from OAuth calibration, fall back to estimate
        let weeklyLimit;
        if (cachedDerivedLimits.sevenDay) {
            weeklyLimit = cachedDerivedLimits.sevenDay;
        } else {
            // Fallback: combined Opus + Sonnet estimate
            const opusLimit = (data.weekly_opus_hours || 35) * (data.opus_tokens_per_hour || 50000);
            const sonnetLimit = (data.weekly_sonnet_hours || 280) * (data.sonnet_tokens_per_hour || 100000);
            weeklyLimit = opusLimit + sonnetLimit;
        }

        const weeklyUsageEl = document.getElementById('weeklyUsage');
        if (weeklyUsageEl) weeklyUsageEl.textContent = formatTokens(weeklyTotal);

        const weeklyLimitEl = document.getElementById('weeklyLimit');
        if (weeklyLimitEl) weeklyLimitEl.textContent = formatTokens(weeklyLimit);

        let weeklyPercent = 0;
        if (weeklyLimit > 0) {
            weeklyPercent = (weeklyTotal / weeklyLimit) * 100;
            updateProgressBar('weeklyProgress', weeklyPercent);
        }

        // Note: Reset times are set by fetchCalibration() using actual OAuth data

        // Update status indicator with the higher percentage
        updateStatusIndicator(Math.max(hourlyPercent, weeklyPercent));

        // Update last updated time
        const lastUpdatedEl = document.getElementById('lastUpdated');
        if (lastUpdatedEl) lastUpdatedEl.textContent = new Date().toLocaleTimeString();

        // Update model breakdown if elements exist
        updateModelBreakdown('hourlyModels', fiveHour.by_model);
        updateModelBreakdown('weeklyModels', weekly.by_model);

    } catch (error) {
        console.error('Error fetching usage:', error);
    }
}

function updateModelBreakdown(elementId, byModel) {
    const container = document.getElementById(elementId);
    if (!container || !byModel) return;

    container.innerHTML = '';
    for (const [model, stats] of Object.entries(byModel)) {
        // Shorten model name for display
        const shortName = model.includes('opus') ? 'Opus' :
                         model.includes('sonnet') ? 'Sonnet' :
                         model.split('-')[0];
        const div = document.createElement('div');
        div.className = 'model-row';
        div.innerHTML = `
            <span class="model-name">${shortName}</span>
            <span class="model-value">${formatTokens(stats.total_tokens)}</span>
        `;
        container.appendChild(div);
    }
}

// Helper to format forecast cell with proper styling
function formatForecastCell(element, forecast, critical) {
    if (!element) return;

    if (forecast) {
        if (critical) {
            element.innerHTML = '<span class="critical-warning">' + forecast + '</span>';
            element.className = 'stat-value text-red critical';
        } else {
            element.textContent = forecast;
            element.className = 'stat-value text-green';
        }
    } else {
        element.textContent = 'Safe';
        element.className = 'stat-value text-green';
    }
}

// Helper to format burn rate cell
function formatBurnRateCell(element, rate, unit) {
    if (!element) return;
    element.textContent = rate > 0 ? formatNumber(rate) + ' ' + unit : 'Idle';
}

// Fetch and update forecast data
async function fetchForecast() {
    try {
        const response = await fetch('/api/forecast');
        if (!response.ok) throw new Error('Failed to fetch forecast');
        const data = await response.json();

        // === 5-HOUR SESSION ===
        const fiveHour = data.five_hour || {};

        // Session burn rate
        formatBurnRateCell(
            document.getElementById('hourlyBurnRateSession'),
            fiveHour.session?.burn_rate || 0,
            fiveHour.session?.burn_rate_unit || 'tok/min'
        );

        // Historical burn rate
        formatBurnRateCell(
            document.getElementById('hourlyBurnRateHistorical'),
            fiveHour.historical?.burn_rate || 0,
            fiveHour.historical?.burn_rate_unit || 'tok/min'
        );

        // Session forecast
        formatForecastCell(
            document.getElementById('hourlyForecastSession'),
            fiveHour.session?.forecast,
            fiveHour.session?.critical
        );

        // Historical forecast
        formatForecastCell(
            document.getElementById('hourlyForecastHistorical'),
            fiveHour.historical?.forecast,
            fiveHour.historical?.critical
        );

        // === WEEKLY SESSION ===
        const weekly = data.weekly || {};

        // Session burn rate
        formatBurnRateCell(
            document.getElementById('weeklyBurnRateSession'),
            weekly.session?.burn_rate || 0,
            weekly.session?.burn_rate_unit || 'M/day'
        );

        // Historical burn rate
        formatBurnRateCell(
            document.getElementById('weeklyBurnRateHistorical'),
            weekly.historical?.burn_rate || 0,
            weekly.historical?.burn_rate_unit || 'M/day'
        );

        // Session forecast
        formatForecastCell(
            document.getElementById('weeklyForecastSession'),
            weekly.session?.forecast,
            weekly.session?.critical
        );

        // Historical forecast
        formatForecastCell(
            document.getElementById('weeklyForecastHistorical'),
            weekly.historical?.forecast,
            weekly.historical?.critical
        );

    } catch (error) {
        console.error('Error fetching forecast:', error);
    }
}

// Create or update hourly chart
function updateHourlyChart(data) {
    const canvas = document.getElementById('hourlyChart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');

    // API returns {hour: "2026-02-03T10:00:00", total_tokens: 123}
    const labels = data.map(d => formatTime(d.hour));
    const values = data.map(d => d.total_tokens);

    if (hourlyChart) {
        hourlyChart.data.labels = labels;
        hourlyChart.data.datasets[0].data = values;
        hourlyChart.update('none');
    } else {
        hourlyChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Tokens',
                    data: values,
                    borderColor: '#e94560',
                    backgroundColor: 'rgba(233, 69, 96, 0.1)',
                    fill: true,
                    tension: 0.4,
                    pointRadius: 3,
                    pointBackgroundColor: '#e94560'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: ctx => formatNumber(ctx.raw) + ' tokens'
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' }
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: {
                            callback: value => formatTokens(value)
                        }
                    }
                }
            }
        });
    }
}

// Create or update weekly chart
function updateWeeklyChart(data) {
    const canvas = document.getElementById('weeklyChart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');

    // API returns {day: "2026-02-03", total_tokens: 123}
    const labels = data.map(d => formatDate(d.day));
    const values = data.map(d => d.total_tokens);

    // Color bars based on relative usage
    const maxVal = Math.max(...values, 1);
    const colors = values.map(v => {
        const percent = (v / maxVal) * 100;
        if (percent < 50) return 'rgba(0, 200, 83, 0.8)';
        if (percent < 80) return 'rgba(255, 193, 7, 0.8)';
        return 'rgba(233, 69, 96, 0.8)';
    });

    if (weeklyChart) {
        weeklyChart.data.labels = labels;
        weeklyChart.data.datasets[0].data = values;
        weeklyChart.data.datasets[0].backgroundColor = colors;
        weeklyChart.update('none');
    } else {
        weeklyChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Tokens',
                    data: values,
                    backgroundColor: colors,
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: ctx => formatNumber(ctx.raw) + ' tokens'
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false }
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: {
                            callback: value => formatTokens(value)
                        }
                    }
                }
            }
        });
    }
}

// Fetch and update history data
async function fetchHistory() {
    try {
        const response = await fetch('/api/history');
        if (!response.ok) throw new Error('Failed to fetch history');
        const data = await response.json();

        if (data.hourly && data.hourly.length > 0) {
            updateHourlyChart(data.hourly);
        }

        if (data.daily && data.daily.length > 0) {
            updateWeeklyChart(data.daily);
        }

    } catch (error) {
        console.error('Error fetching history:', error);
    }
}

// Fetch and update calibration data (official % from OAuth API)
async function fetchCalibration() {
    try {
        const response = await fetch('/api/calibration');
        if (!response.ok) throw new Error('Failed to fetch calibration');
        const data = await response.json();

        // Update 5-hour official percentage
        const hourlyOfficialEl = document.getElementById('hourlyOfficial');
        if (hourlyOfficialEl) {
            if (data.five_hour && data.five_hour.official_percent !== null) {
                const pct = data.five_hour.official_percent;
                hourlyOfficialEl.textContent = pct.toFixed(1) + '%';
                hourlyOfficialEl.className = 'official-percent text-' + getStatusColor(pct);

                // Update progress bar with official percentage
                updateProgressBar('hourlyProgress', pct);

                // Cache and update derived limit display
                if (data.five_hour.derived_limit) {
                    cachedDerivedLimits.fiveHour = data.five_hour.derived_limit;
                    const hourlyLimitEl = document.getElementById('hourlyLimit');
                    if (hourlyLimitEl) {
                        hourlyLimitEl.textContent = formatTokens(data.five_hour.derived_limit);
                    }
                }

                // If OAuth shows low % (< 10%), window likely just reset
                // Update usage display based on OAuth percentage to avoid showing stale data
                if (pct < 10) {
                    // Use cached limit or estimate ~92M (typical 5-hour limit)
                    const estimatedLimit = cachedDerivedLimits.fiveHour || 92000000;
                    const estimatedUsage = Math.round(estimatedLimit * (pct / 100));
                    const hourlyUsageEl = document.getElementById('hourlyUsage');
                    if (hourlyUsageEl) {
                        hourlyUsageEl.textContent = formatTokens(estimatedUsage);
                    }
                    // Also update the limit display if we don't have a derived one
                    if (!cachedDerivedLimits.fiveHour) {
                        const hourlyLimitEl = document.getElementById('hourlyLimit');
                        if (hourlyLimitEl) {
                            hourlyLimitEl.textContent = formatTokens(estimatedLimit);
                        }
                    }
                }
            } else {
                hourlyOfficialEl.textContent = 'N/A';
            }
        }

        // Update 7-day official percentage
        const weeklyOfficialEl = document.getElementById('weeklyOfficial');
        if (weeklyOfficialEl) {
            if (data.seven_day && data.seven_day.official_percent !== null) {
                const pct = data.seven_day.official_percent;
                weeklyOfficialEl.textContent = pct.toFixed(1) + '%';
                weeklyOfficialEl.className = 'official-percent text-' + getStatusColor(pct);

                // Update progress bar with official percentage
                updateProgressBar('weeklyProgress', pct);

                // Cache and update derived limit display
                if (data.seven_day.derived_limit) {
                    cachedDerivedLimits.sevenDay = data.seven_day.derived_limit;
                    const weeklyLimitEl = document.getElementById('weeklyLimit');
                    if (weeklyLimitEl) {
                        weeklyLimitEl.textContent = formatTokens(data.seven_day.derived_limit);
                    }
                }
            } else {
                weeklyOfficialEl.textContent = 'N/A';
            }
        }

        // Update reset times
        const hourlyResetEl = document.getElementById('hourlyTimeRemaining');
        if (hourlyResetEl && data.five_hour && data.five_hour.resets_at) {
            const resetTime = new Date(data.five_hour.resets_at);
            const now = new Date();
            const diffMs = resetTime - now;
            if (diffMs > 0) {
                const hours = Math.floor(diffMs / (1000 * 60 * 60));
                const mins = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));
                hourlyResetEl.textContent = `${hours}h ${mins}m`;
            }
        }

        const weeklyResetEl = document.getElementById('weeklyDaysRemaining');
        if (weeklyResetEl && data.seven_day && data.seven_day.resets_at) {
            const resetTime = new Date(data.seven_day.resets_at);
            const now = new Date();
            const diffDays = Math.ceil((resetTime - now) / (1000 * 60 * 60 * 24));
            if (diffDays > 0) {
                weeklyResetEl.textContent = diffDays + ' days';
            }
        }

        // Update status indicator with official percentages
        const maxPct = Math.max(
            data.five_hour?.official_percent || 0,
            data.seven_day?.official_percent || 0
        );
        if (maxPct > 0) {
            updateStatusIndicator(maxPct);
        }

        // Show calibration status
        const calibStatusEl = document.getElementById('calibrationStatus');
        if (calibStatusEl) {
            if (data.oauth_available) {
                calibStatusEl.textContent = 'Synced with Anthropic';
                calibStatusEl.className = 'calibration-status synced';
            } else {
                calibStatusEl.textContent = 'OAuth unavailable';
                calibStatusEl.className = 'calibration-status unavailable';
            }
        }

    } catch (error) {
        console.error('Error fetching calibration:', error);
        const calibStatusEl = document.getElementById('calibrationStatus');
        if (calibStatusEl) {
            calibStatusEl.textContent = 'Calibration error';
            calibStatusEl.className = 'calibration-status error';
        }
    }
}

// Refresh all data
async function refreshData() {
    await Promise.all([
        fetchUsage(),
        fetchForecast(),
        fetchHistory(),
        fetchCalibration()
    ]);
}

// Initialize dashboard
document.addEventListener('DOMContentLoaded', function() {
    console.log('TokenBoard initializing...');

    // Initial data load
    refreshData();

    // Auto-refresh every 30 seconds
    setInterval(refreshData, 30000);

    console.log('TokenBoard ready - auto-refresh every 30s');
});
