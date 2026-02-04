# TokenBoard

A simple dashboard for tracking your Claude token consumption across 5-hour rolling windows and weekly limits.

## Features

- **Real-time tracking**: Monitors your `~/.claude` directory for usage data
- **5-hour window view**: Track burst usage within Claude's rolling limit window
- **Weekly view**: Track cumulative usage against weekly allocation
- **Forecasting**: Projects usage based on burn rate
- **Auto-refresh**: Updates every 30 seconds
- **Model breakdown**: See usage split by Opus vs Sonnet

## Quick Start

### Option 1: Run Locally (No Docker)

```bash
cd F:/GitHub/TokenBoard

# Install dependencies
pip install -r requirements.txt

# Run the dashboard
python run.py
```

Open http://localhost:8080 in your browser.

### Option 2: Docker

```bash
cd F:/GitHub/TokenBoard

# Build and run
docker-compose up -d

# View logs
docker-compose logs -f
```

Open http://localhost:8080 in your browser.

## Configuration

All settings can be configured via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_DATA_PATH` | `~/.claude` | Path to Claude data directory |
| `DB_PATH` | `./data/usage.db` | SQLite database path |
| `FIVE_HOUR_LIMIT_TOKENS` | `None` | Optional: 5-hour token limit |
| `WEEKLY_OPUS_HOURS` | `35` | Weekly Opus allocation (Max 5x plan) |
| `WEEKLY_SONNET_HOURS` | `280` | Weekly Sonnet allocation (Max 5x plan) |
| `OPUS_TOKENS_PER_HOUR` | `50000` | Estimated tokens per Opus hour |
| `SONNET_TOKENS_PER_HOUR` | `100000` | Estimated tokens per Sonnet hour |

### Plan Limits Reference

Based on [Anthropic's documentation](https://support.anthropic.com/en/articles/11145838-using-claude-code-with-your-pro-or-max-plan):

| Plan | Sonnet Hours/Week | Opus Hours/Week |
|------|-------------------|-----------------|
| Pro ($20/mo) | 40-80 | - |
| Max 5x ($100/mo) | 140-280 | 15-35 |
| Max 20x ($200/mo) | 240-480 | 24-40 |

## How It Works

1. **Data Source**: Parses JSONL session files from `~/.claude/projects/`
2. **Storage**: Stores usage records in SQLite for historical analysis
3. **Watcher**: Monitors for new/modified files to update in real-time
4. **Dashboard**: Displays current usage, forecasts, and charts

## API Endpoints

- `GET /` - Dashboard UI
- `GET /api/usage` - Current 5-hour and weekly usage stats
- `GET /api/history` - Hourly and daily aggregates for charts
- `GET /api/forecast` - Projected usage based on burn rate
- `GET /api/refresh` - Manually trigger data refresh
- `GET /api/status` - System status

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run in debug mode
python run.py
```

## Troubleshooting

**No data showing up?**
- Ensure `~/.claude` exists and contains session data
- Check the console/logs for import messages
- Try accessing `/api/refresh` to force a data reload

**Docker volume mount issues on Windows?**
- Make sure Docker Desktop has access to your drives
- Use `${USERPROFILE}/.claude` syntax in docker-compose.yml

## License

MIT
