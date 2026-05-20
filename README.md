# garmin-sync

A command-line tool that syncs your Garmin Connect and HEVY fitness data locally, with AI-powered analysis via OpenAI and MCP (Model Context Protocol) integration for Claude Desktop. Works on **macOS** and **Windows 11**.

## Features

- **Secure Authentication** - OAuth login using the same method as the official Garmin Connect app
- **Comprehensive Data Sync** - Activities, sleep, heart rate, stress, HRV, body battery, training readiness
- **HEVY Integration** - Sync strength training data (exercises, sets, volume by muscle group)
- **AI Fitness Coach** - Interactive chat with tool calling for on-demand data queries
- **Longitudinal Review** - Multi-year fitness analysis surfacing plateaus and regime shifts
- **MCP Server** - Use your fitness data directly in Claude Desktop
- **Cross-Platform Scheduling** - Automatic daily sync via launchd (macOS) or Task Scheduler (Windows)
- **Computed Metrics** - HR drift, training load, exercise progression, RPE analysis, stress-recovery and sleep-performance correlations, personal records tracking
- **Smart Sync** - Skips unchanged daily metrics older than 7 days to save API calls (override with `--force`)
- **Local Storage** - All data in a SQLite database you control (see [SECURITY.md](SECURITY.md))

## Installation

```bash
# Clone and install
git clone https://github.com/jdellag/garmin-sync.git
cd garmin-sync
pip install -e .

# Verify
garmin-sync --version
```

**Requirements:** Python 3.10+

**Platform support:** macOS (primary), Windows 11 (fully supported). Linux works for all features except automatic scheduling (use crontab manually).

## Quick Start

```bash
# 1. Login to Garmin
garmin-sync auth login

# 2. Sync your data
garmin-sync sync all

# 3. Configure AI (optional)
garmin-sync analyze configure

# 4. Chat with your AI coach
garmin-sync analyze chat
```

## MCP Server for Claude Desktop

Use your fitness data directly in Claude Desktop conversations.

### Setup

```bash
# View setup instructions
garmin-sync mcp info

# Add to Claude Desktop
claude mcp add garmin-sync -- uv run --directory /path/to/garmin-sync python -m garmin_sync.mcp.server
```

### Available Tools

| Tool | Description |
|------|-------------|
| `get_recent_activities` | Activities with duration, HR, training load, HR drift, cadence, VO2 max |
| `get_recovery_status` | HRV, sleep (+ respiration/SpO2), body battery, RHR, training readiness, stress-recovery patterns, sleep-performance correlation |
| `get_training_load_analysis` | Acute:chronic ratio with risk assessment + training effect balance |
| `get_cardio_performance` | Running cadence trends, VO2 max progression, elevation summary, training effect balance |
| `get_strength_training_summary` | HEVY volume by muscle group, RPE analysis with overreaching detection, personal records |
| `get_exercise_progression` | Track estimated 1RM over time with RPE trend |
| `get_workout_details` | Detailed workouts with sets |
| `get_weekly_comparison` | This week vs last week, month-to-date context, personal records |
| `get_longitudinal_summary` | Multi-year aerobic efficiency, health baselines, volume, drift |
| `sync_garmin_data` | Trigger a fresh sync (auto-detects cardio PRs) |

## AI Analysis & Chat

### Interactive Chat

```bash
garmin-sync analyze chat
```

The AI coach uses **tool calling** to query your data on-demand. Ask questions like:
- "How has my bench press progressed over the last 3 months?"
- "What's my recovery status today?"
- "Compare my training this week vs last week"

**Chat Commands:**
| Command | Action |
|---------|--------|
| `/quit` | Exit chat |
| `/clear` | Clear conversation history |
| `/context` | Show loaded context and token usage |
| `/tools` | Toggle tool calling on/off |

### Configuration

```toml
# ~/.config/garmin-sync/config.toml
[openai]
api_key = "sk-..."
model = "o3-mini"        # For non-tool chat
use_tools = true         # Enable tool calling (uses gpt-5.4)
enabled = true

[analysis]
timezone = "America/New_York"
schedule = """
Monday: Rest day
Tuesday: Speed/interval workout
Wednesday: Easy run
..."""
user_context = """
Training for a spring marathon.
"""
```

### Other Analysis Commands

| Command | Description |
|---------|-------------|
| `garmin-sync analyze` | Run one-shot analysis (last 7 days) |
| `garmin-sync analyze longitudinal` | Multi-year fitness review (saves a separate markdown report) |
| `garmin-sync analyze configure` | Interactive setup |
| `garmin-sync analyze view` | View most recent analysis (accepts optional `--date YYYY-MM-DD`) |
| `garmin-sync analyze list` | List all analysis reports |

### Longitudinal Review

Surfaces multi-year trends — pace-at-HR, RHR/HRV/sleep baselines, weekly-volume consistency, HR drift — and asks the model to call out plateaus or regime shifts. Runs against the full sync history.

```bash
garmin-sync analyze longitudinal                    # earliest year in DB → today
garmin-sync analyze longitudinal --start-year 2023  # narrow the window
garmin-sync analyze longitudinal -g quarter         # quarter buckets instead of yearly
```

Output is saved to `~/.local/share/garmin-sync/reports/longitudinal-YYYY-MM-DD.md` at `0o600`.

## Complete Command Reference

### Authentication

| Command | Description |
|---------|-------------|
| `garmin-sync auth login` | Login to Garmin Connect (OAuth) |
| `garmin-sync auth status` | Show authentication status and token info |
| `garmin-sync auth logout` | Remove stored OAuth tokens |

### Data Sync

```bash
# Sync all data (last 30 days)
garmin-sync sync all

# Sync specific days
garmin-sync sync all --days 7

# Sync with detailed per-day data (sleep/stress/HRV)
garmin-sync sync all --detailed

# Force re-download (overrides smart-skip optimization)
garmin-sync sync all --force
```

| Command | Description |
|---------|-------------|
| `garmin-sync sync all` | Sync all Garmin + HEVY data |
| `garmin-sync sync activities` | Sync activities only (with FIT files and HR drift) |
| `garmin-sync sync health` | Sync health metrics only (sleep, HR, stress, HRV, body battery, readiness) |

> **Smart sync:** Daily metrics older than 7 days are skipped if already present in the database. This significantly reduces API calls during large backfills. Use `--force` to re-sync all data.

### Data Types

**Garmin Connect:**
- Activities (running, cycling, strength, etc.) with HR drift computation
- Sleep (duration, stages, score, respiration, SpO2)
- Heart rate, stress, HRV, body battery
- Training readiness (composite score with component breakdown)

**HEVY (optional):**
- Workouts, exercises, sets
- Volume by muscle group
- Exercise progression (estimated 1RM via Epley formula)

### Reports & Stats

| Command | Description |
|---------|-------------|
| `garmin-sync report weekly` | Generate weekly report (add `--llm` for ChatGPT-optimized output) |
| `garmin-sync report monthly` | Generate monthly report |
| `garmin-sync stats today` | Quick summary of today's activity |
| `garmin-sync stats week` | Quick summary of this week's activity |
| `garmin-sync export activities` | Export activities to JSON/CSV (`-f json -o file.json`) |
| `garmin-sync export health` | Export health data to JSON/CSV |

### MCP Server

| Command | Description |
|---------|-------------|
| `garmin-sync mcp info` | Show Claude Desktop setup instructions |
| `garmin-sync mcp serve` | Start the MCP server directly |

## HEVY Strength Training

```bash
garmin-sync hevy login    # Configure API key
garmin-sync hevy sync     # Sync workouts
garmin-sync hevy status   # Show recent workouts
garmin-sync hevy volume   # Volume by muscle group
```

**Requirements:** HEVY Pro + API key from https://hevy.com/settings?developer

## Automatic Scheduling

Automatically sync and analyze your data daily. Works on both macOS (launchd) and Windows (Task Scheduler).

```bash
garmin-sync schedule install   # Install daily sync + analysis
garmin-sync schedule status    # Check status
garmin-sync schedule logs      # View logs
garmin-sync schedule uninstall # Remove
```

**Schedule:** Weekdays 7:00 AM, Weekends 10:00 AM

| Platform | Backend | Notes |
|----------|---------|-------|
| macOS | launchd | Includes catch-up logic if Mac was asleep; shows macOS notification when done |
| Windows | Task Scheduler | Creates `GarminSync-Weekday` and `GarminSync-Weekend` tasks via `schtasks.exe` |
| Linux | Manual | Add to crontab: `0 7 * * 1-5 garmin-sync sync all --days 1 --detailed && garmin-sync analyze` |

## Data Storage

All data is stored locally on your machine:

| Purpose | macOS / Linux | Windows |
|---------|---------------|---------|
| SQLite database | `~/.local/share/garmin-sync/garmin.db` | `%LOCALAPPDATA%\garmin-sync\garmin.db` |
| AI analysis reports | `~/.local/share/garmin-sync/reports/` | `%LOCALAPPDATA%\garmin-sync\reports\` |
| Scheduled sync logs | `~/.local/share/garmin-sync/logs/` | `%LOCALAPPDATA%\garmin-sync\logs\` |
| FIT files | `~/.local/share/garmin-sync/fit_files/` | `%LOCALAPPDATA%\garmin-sync\fit_files\` |
| AI + HEVY config | `~/.config/garmin-sync/config.toml` | `%LOCALAPPDATA%\garmin-sync\config.toml` |
| OAuth tokens | `~/.garminconnect/` | `~/.garminconnect/` |

Path defaults are managed by `platformdirs`. Override with `GARMIN_SYNC_DATA_DIR` environment variable.

## Configuration

All settings can be configured via environment variables (prefix `GARMIN_SYNC_`) or `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATA_DIR` | Platform default (see above) | Data storage directory |
| `GARTH_TOKEN_DIR` | `~/.garminconnect` | OAuth token directory |
| `DATABASE_NAME` | `garmin.db` | SQLite database filename |
| `DEFAULT_SYNC_DAYS` | `30` | Days to sync (1-365) |
| `DOWNLOAD_FIT_FILES` | `true` | Download FIT files during activity sync |
| `API_TIMEOUT_SECONDS` | `30` | API request timeout (5-120) |
| `RATE_LIMIT_CALLS_PER_MINUTE` | `15` | Garmin API rate limit (1-60) |
| `DEFAULT_REPORT_FORMAT` | `markdown` | Report format: `markdown`, `text`, or `json` |
| `LLM_MODE_DEFAULT` | `false` | Enable LLM-optimized report output by default |

## Privacy & Security

- All data stored locally - no third-party transmission except to APIs you configure (Garmin, HEVY, OpenAI)
- On macOS/Linux: config, tokens, database, and reports are `0o600` (owner-only); directories are `0o700`
- On Windows: standard NTFS permissions apply (POSIX chmod silently skips)
- HEVY-derived strings are sanitized before reaching the LLM (see [SECURITY.md](SECURITY.md))
- API error responses are logged to stderr only; sanitized messages in exceptions
- `.gitignore` blocks `config.toml`, `*.fit`, `*.db`, `reports/`, `.env` from accidental commits

For a complete security overview, see [SECURITY.md](SECURITY.md).

**Delete all data:**
- macOS/Linux: `rm -rf ~/.local/share/garmin-sync ~/.garminconnect ~/.config/garmin-sync`
- Windows: `rmdir /s /q "%LOCALAPPDATA%\garmin-sync"` and `rmdir /s /q "%USERPROFILE%\.garminconnect"`

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests (520+ tests)
pytest

# Run with coverage
pytest --cov=garmin_sync

# Lint
ruff check src/
```

### Project Structure

```
src/garmin_sync/
├── cli.py              # CLI commands (24 commands across 8 groups)
├── config/
│   ├── paths.py        # Platform-aware path defaults (platformdirs)
│   └── settings.py     # Pydantic Settings (env var config)
├── api/                # Garmin API client with rate limiting
├── db/                 # Database, models & repository (upsert pattern)
├── sync/               # Data synchronization with smart-skip optimization
├── hevy/               # HEVY strength training integration
├── tools/              # Shared tool executor (MCP + OpenAI)
├── mcp/                # MCP server for Claude Desktop
├── ai/                 # OpenAI integration & chat with tool calling
├── scheduler/          # Automatic sync (launchd on macOS, Task Scheduler on Windows)
└── reports/            # Report generation & SQL aggregators
```

## Troubleshooting

**"Not authenticated"** - Run `garmin-sync auth login`. Check with `garmin-sync auth status`.

**Rate limiting** - Garmin limits to ~15 calls/min. Large syncs take time. Adjust with `GARMIN_SYNC_RATE_LIMIT_CALLS_PER_MINUTE`.

**Missing data** - Some metrics (HRV, body battery, training readiness) require compatible Garmin devices.

**Tool calling not working** - Ensure `use_tools = true` in config. Uses gpt-5.4.

**Longitudinal analysis empty** - Needs historical data. Run `garmin-sync sync all --days 1825` first.

**Smart sync skipping too much** - Use `--force` to re-sync all data regardless of what's in the database.

## License

MIT License

## Acknowledgments

- [python-garminconnect](https://github.com/cyberjunky/python-garminconnect)
- [Garth](https://github.com/matin/garth)
- [Typer](https://typer.tiangolo.com/)
- [Rich](https://rich.readthedocs.io/)
- [FastMCP](https://github.com/jlowin/fastmcp)
