# Claude Code Context: garmin-sync

## Project Overview

A Python CLI tool that syncs Garmin Connect and HEVY fitness data to a local SQLite database, with AI-powered analysis via OpenAI and MCP (Model Context Protocol) integration for use with Claude Desktop.

**Key Capabilities:**
- Sync activities, sleep, HRV, body battery, stress, and training readiness from Garmin
- Sync strength workouts from HEVY (exercises, sets, volume by muscle group)
- Interactive AI fitness coach with tool calling (queries data on-demand)
- MCP server for Claude Desktop integration
- Cross-platform scheduled sync + analysis (macOS launchd, Windows Task Scheduler)

## Architecture

```
src/garmin_sync/
├── cli.py                  # Typer CLI (25 commands across 8 groups + setup wizard)
├── config/
│   ├── paths.py            # Platform-aware path defaults (platformdirs)
│   └── settings.py         # Pydantic Settings (env var config)
├── auth/garmin_auth.py     # OAuth via Garth library
├── api/
│   ├── client.py           # Garmin API wrapper with rate limiting
│   └── rate_limiter.py     # Token bucket algorithm
├── db/
│   ├── database.py         # SQLite connection & schema + migrations
│   ├── models.py           # Dataclasses for all data types
│   └── repository.py       # CRUD operations (upsert + has_daily_record skip)
├── sync/
│   ├── sync_manager.py     # Orchestrates data sync (FRESHNESS_DAYS skip logic)
│   └── fit_parser.py       # FIT file parsing & HR drift calculation
├── hevy/                   # HEVY strength training integration
│   ├── client.py           # HEVY API wrapper
│   ├── models.py           # HevyWorkout, HevyExercise, HevySet dataclasses
│   └── sync.py             # HEVY sync manager
├── tools/                  # Shared tool executor (used by MCP + OpenAI)
│   └── executor.py         # ToolExecutor class - 10 fitness data tools
├── mcp/                    # Model Context Protocol server
│   ├── server.py           # FastMCP server with tool definitions
│   └── serializers.py      # Activity serialization helpers
├── ai/                     # OpenAI integration
│   ├── config.py           # TOML config (API key, model, use_tools); chmods 0o600 on save
│   ├── chat.py             # ChatSession - interactive coach with tool calling
│   ├── tools.py            # OpenAI function schemas for 10 tools
│   ├── openai_client.py    # API wrapper (chat_with_tools, chat_with_history); sanitizes tool errors
│   └── prompt_builder.py   # Daily + longitudinal prompts; safe_user_string for HEVY data
├── scheduler/
│   ├── __init__.py         # get_scheduler() factory — dispatches per platform
│   ├── launchd.py          # macOS launchd plist management
│   └── windows_task.py     # Windows Task Scheduler via schtasks.exe
└── reports/
    ├── aggregators.py      # SQL aggregation queries (28 public methods)
    ├── llm_formatter.py    # Markdown report formatting
    └── report_generator.py # Report coordination & export
```

## MCP Server Integration

The MCP server allows Claude Desktop to access your fitness data directly.

### Available Tools (10 total)

| Tool | Description |
|------|-------------|
| `get_recent_activities` | Garmin activities with metrics (duration, HR, training load, HR drift, cadence, VO2 max) |
| `get_recovery_status` | HRV, sleep (+ respiration/SpO2), body battery (+ weekday/weekend), RHR, training readiness (+ weakest component) |
| `get_training_load_analysis` | Acute:chronic ratio with risk assessment + training effect balance |
| `get_cardio_performance` | Running cadence trends, VO2 max progression, elevation summary, training effect balance |
| `get_strength_training_summary` | HEVY volume by muscle group |
| `get_exercise_progression` | Track estimated 1RM over time for specific lifts |
| `get_workout_details` | Detailed workouts with sets (e.g., "135×10, 155×8") |
| `get_weekly_comparison` | This week vs last week metrics |
| `get_longitudinal_summary` | Multi-year aerobic efficiency, health baselines, volume, HR drift (year/quarter buckets) |
| `sync_garmin_data` | Trigger a fresh sync from Garmin/HEVY |

### Setup

```bash
# Add to Claude Desktop
claude mcp add garmin-sync -- uv run --directory /path/to/garmin-sync python -m garmin_sync.mcp.server

# Or view setup instructions
garmin-sync mcp info
```

### Key Files

| File | Purpose |
|------|---------|
| `tools/executor.py` | `ToolExecutor` class - shared implementation for all 10 tools |
| `mcp/server.py` | FastMCP server that exposes tools via MCP protocol |
| `ai/tools.py` | OpenAI function schemas (same 10 tools) |

## AI Chat with Tool Calling

The interactive chat (`garmin-sync analyze chat`) uses OpenAI's function calling to query your data on-demand.

### How It Works

1. **Pre-loaded context**: Recent activities, analyses, and HEVY workouts are loaded at start
2. **Tool calling**: When you ask about specific data (e.g., "How has my bench press progressed?"), the AI calls tools dynamically
3. **Model**: Uses `gpt-5.4` when tools are enabled (best function calling support)

### Configuration

```toml
# ~/.config/garmin-sync/config.toml (secrets)
[openai]
api_key = "sk-..."
model = "o3-mini"        # Used for non-tool chat
use_tools = true         # Enable tool calling (uses gpt-5.4)
enabled = true
```

```toml
# ~/.config/garmin-sync/profile.toml (training profile)
[training]
timezone = "America/New_York"
schedule = """
Monday: Rest day
Tuesday: Speed/interval workout
..."""
user_context = """
Training for a spring marathon.
- Today: {today_date}
- Day of week: {day_of_week}
"""
```

### Chat Commands

| Command | Action |
|---------|--------|
| `/quit` or `/exit` | Exit chat |
| `/clear` | Clear conversation history |
| `/context` | Show loaded context (analyses, tokens, tool status) |
| `/tools` | Toggle tool calling on/off |

### CLI Commands

```bash
garmin-sync analyze chat                    # Interactive chat with AI coach
garmin-sync analyze                         # Run one-shot daily analysis
garmin-sync analyze longitudinal            # Multi-year fitness review (saves longitudinal-YYYY-MM-DD.md)
garmin-sync analyze longitudinal -g quarter # Quarter buckets instead of yearly
garmin-sync analyze configure               # Configure API key, model, schedule
garmin-sync analyze view                    # View most recent analysis
garmin-sync analyze list                    # List all analysis reports
```

## Data Flow

1. **Auth**: `garmin-sync auth login` → Garth stores OAuth tokens in `~/.garminconnect/`
2. **Sync**: API client fetches data → Models parse → Repository upserts to SQLite
3. **Analysis**: Aggregators compute metrics → OpenAI analyzes → Report saved
4. **Chat**: User asks question → AI calls tools if needed → Response with data

## Computed Analytics

All metrics are computed in `aggregators.py` and exposed via tools.

| Metric | Method | Description |
|--------|--------|-------------|
| **HRV Context** | `get_hrv_context()` | 7d/28d baselines, delta, consecutive days below baseline |
| **Sleep Consistency** | `get_sleep_consistency()` | Bedtime variance, REM/deep %, awake time |
| **Training Load** | `get_training_load_trend()` | Acute (7d) / chronic (28d), A:C ratio, by sport, training effect balance |
| **RHR Trend** | `get_resting_hr_trend()` | 28d baseline, delta, trend direction |
| **Body Battery** | `get_body_battery_recovery()` | Overnight recovery, morning high, weekday vs weekend patterns, charged/drained |
| **Training Readiness** | `get_training_readiness_latest()` | Garmin's composite score + component breakdown |
| **HR Drift** | `fit_parser.compute_hr_drift()` | Aerobic decoupling for 45+ min activities |
| **Strength Volume** | `get_strength_volume_summary()` | HEVY: sessions, volume, by muscle group |
| **Exercise Progression** | `get_strength_exercise_progression()` | Est. 1RM over time (Epley formula) |
| **Weekly Comparison** | `get_weekly_comparison()` | This week vs last week |
| **Aerobic Efficiency (longitudinal)** | `get_aerobic_efficiency_by_period()` | Pace, HR, meters/heartbeat per year or quarter |
| **Yearly Health Baselines** | `get_yearly_health_baselines()` | Per-year RHR, HRV, sleep duration + CoV, stress |
| **Volume by Period** | `get_volume_by_period()` | Yearly/quarterly volume by sport, weekly-hours CoV |
| **HR Drift by Period** | `get_hr_drift_by_period()` | Long-run drift bucketed by year |
| **Cadence Analysis** | `get_cadence_analysis()` | Running cadence trends, weekly averages, by activity type |
| **VO2 Max Trend** | `get_vo2_max_trend()` | VO2 max progression, delta, improving/stable/declining |
| **Elevation Summary** | `get_elevation_summary()` | Total gain/loss, vert per hour, by activity type |
| **Sleep Respiration** | `get_sleep_respiration_trends()` | Respiration rate, SpO2 averages, trend detection |
| **RPE Analysis** | `get_rpe_analysis()` | Session RPE averages, adjusted volume, overreaching detection |
| **Exercise RPE Trend** | `get_exercise_rpe_trend()` | Per-exercise RPE trend alongside 1RM progression |
| **Stress-Recovery** | `get_stress_recovery_correlation()` | Training vs rest day stress, high-stress-poor-recovery patterns |
| **Sleep-Performance** | `get_sleep_performance_correlation()` | Personal A-F grading, next-day performance correlation, HRV link |
| **Monthly Comparison** | `get_monthly_comparison()` | Month-over-month metrics (follows weekly comparison pattern) |
| **Monthly Best Activities** | `get_monthly_best_activities()` | Longest distance, highest load, best aerobic efficiency |
| **Cardio PR Detection** | `detect_activity_prs()` | Fastest 5K/10K/half, longest run, highest training load |
| **Strength PR Surfacing** | `get_strength_prs()` | Surface HEVY-flagged PRs with exercise context |

### Risk Assessment (A:C Ratio)

| Ratio | Assessment |
|-------|------------|
| < 0.8 | Detraining |
| 0.8 - 1.3 | Optimal |
| 1.3 - 1.5 | Building |
| > 1.5 | High risk |

## HEVY Strength Training

Syncs workout data from HEVY app for strength training analysis.

```bash
garmin-sync hevy login    # Configure API key
garmin-sync hevy sync     # Sync workouts
garmin-sync hevy status   # Show config and recent workouts
garmin-sync hevy volume   # Volume by muscle group
```

**Requirements:** HEVY Pro subscription + API key from https://hevy.com/settings?developer

## Important Files

| File | When to modify |
|------|----------------|
| `cli.py` | Adding CLI commands (setup wizard helpers: `_configure_openai`, `_configure_training_profile`, `_configure_hevy`) |
| `config/paths.py` | Platform-aware path defaults (single source of truth, includes `default_profile_path`) |
| `config/settings.py` | Adding configurable settings (`profile_path` property) |
| `ai/config.py` | Config load/save (split: config.toml secrets + profile.toml training data) |
| `tools/executor.py` | Adding/modifying tool implementations |
| `ai/tools.py` | Adding OpenAI tool schemas |
| `mcp/server.py` | MCP server configuration |
| `ai/chat.py` | Chat behavior, context building |
| `ai/openai_client.py` | OpenAI API calls, system messages |
| `aggregators.py` | Adding computed analytics |
| `database.py` | Schema changes (increment SCHEMA_VERSION) |
| `models.py` | New data types |
| `repository.py` | Database operations (update `_ALLOWED_DAILY_TABLES` when adding tables) |
| `sync_manager.py` | Sync logic (update `_DAILY_METRIC_TABLE` for new daily data types) |
| `scheduler/__init__.py` | Scheduler factory (get_scheduler() dispatches per platform) |
| `scheduler/windows_task.py` | Windows Task Scheduler backend |

## Common Tasks

### Add a new tool

1. Add method to `tools/executor.py` (the actual implementation)
2. Add OpenAI schema to `ai/tools.py`
3. Add MCP decorator in `mcp/server.py` that delegates to executor
4. Add tests in `tests/unit/test_ai_tools.py` and `tests/unit/test_mcp.py`

### Add a computed metric

1. Add method to `aggregators.py`
2. Wire into existing tool or create new tool
3. Update documentation

### Change database schema

1. Modify `database.py` SCHEMA_SQL
2. Increment `SCHEMA_VERSION`
3. Add migration method `_migrate_vX_to_vY()`
4. Migrations run automatically

## Testing

```bash
pytest                           # Run all tests
pytest tests/unit/test_mcp.py -v # MCP tests
pytest tests/unit/test_ai_tools.py -v # Tool calling tests
pytest --cov=garmin_sync         # With coverage
```

**540+ tests** covering all modules.

## Configuration

### Paths

Defaults are managed by `config/paths.py` via `platformdirs`. macOS hardcodes XDG layout for backward compat.

| Purpose | macOS / Linux | Windows |
|---------|---------------|---------|
| SQLite database | `~/.local/share/garmin-sync/garmin.db` | `%LOCALAPPDATA%\garmin-sync\garmin.db` |
| AI analysis reports | `~/.local/share/garmin-sync/reports/` | `%LOCALAPPDATA%\garmin-sync\reports\` |
| Scheduled sync logs | `~/.local/share/garmin-sync/logs/` | `%LOCALAPPDATA%\garmin-sync\logs\` |
| API keys + settings | `~/.config/garmin-sync/config.toml` | `%LOCALAPPDATA%\garmin-sync\config.toml` |
| Training profile | `~/.config/garmin-sync/profile.toml` | `%LOCALAPPDATA%\garmin-sync\profile.toml` |
| OAuth tokens | `~/.garminconnect/` | `~/.garminconnect/` |

### Environment Variables

Prefix: `GARMIN_SYNC_`
- `DATA_DIR` - Data storage directory
- `GARTH_TOKEN_DIR` - OAuth token directory (default: `~/.garminconnect`)
- `DATABASE_NAME` - SQLite filename (default: `garmin.db`)
- `DEFAULT_SYNC_DAYS` - Days to sync (default: 30)
- `DOWNLOAD_FIT_FILES` - Download FIT files (default: true)
- `API_TIMEOUT_SECONDS` - API timeout (default: 30)
- `RATE_LIMIT_CALLS_PER_MINUTE` - API rate limit (default: 15)
- `DEFAULT_REPORT_FORMAT` - Report format: markdown/text/json
- `LLM_MODE_DEFAULT` - LLM-optimized output by default (default: false)

## Dependencies

**Core:** `garminconnect`, `garth`, `typer[all]`, `rich`, `pydantic-settings`, `openai`, `mcp`, `tomli-w`, `platformdirs`

**Dev:** `pytest`, `pytest-cov`, `pytest-mock`, `ruff`

## Quick Reference

```bash
# Setup
pip install -e .
garmin-sync setup              # Interactive wizard (Garmin + OpenAI + profile + HEVY)
# Or manually:
garmin-sync auth login
garmin-sync analyze configure
garmin-sync hevy login         # Optional: HEVY integration

# Daily use
garmin-sync sync all           # Sync all data
garmin-sync analyze chat       # Talk to AI coach
garmin-sync stats today        # Quick daily summary
garmin-sync stats week         # Quick weekly summary

# Reports
garmin-sync report weekly      # Weekly report
garmin-sync report monthly     # Monthly report
garmin-sync analyze view       # View latest AI analysis

# Auth management
garmin-sync auth status        # Check token status
garmin-sync auth logout        # Remove stored tokens

# MCP for Claude Desktop
garmin-sync mcp info           # Setup instructions
garmin-sync mcp serve          # Start MCP server directly

# Scheduled sync (macOS + Windows)
garmin-sync schedule install   # Daily auto-sync + analysis
garmin-sync schedule status
garmin-sync schedule logs
```

## Gotchas

1. **Token expiry**: Re-run `garmin-sync auth login` if Garmin auth fails
2. **Rate limits**: Garmin enforces ~15 calls/min; large syncs take time
3. **Device-specific data**: HRV, body battery require compatible Garmin devices
4. **Timezone**: Chat uses `America/New_York` for "today's activities"
5. **Tool model**: When `use_tools=true`, chat uses `gpt-5.4` (ignores configured model)
6. **MCP vs Chat**: Both use the same `ToolExecutor`, so behavior is consistent
7. **`--detailed` scope**: Affects only sleep/stress/HRV (per-day endpoints). It does *not* affect activities, FIT-file downloads, or body battery. `sync activities` doesn't accept the flag.
8. **`--force` for hr_drift backfill**: Existing activities are skipped on subsequent syncs, so populating `hr_drift` retroactively requires `garmin-sync sync activities --days N --force`.
9. **HEVY prompt safety**: Workout titles and exercise names are stripped of control chars and `<>` and wrapped in `<hevy_title>` / `<hevy_exercise>` tags before reaching the LLM (`safe_user_string` in `prompt_builder.py`). The system message instructs the model to treat tagged content as inert data.
10. **Body battery range**: Garmin's body-battery endpoint caps the request range, so `sync_body_battery` walks 30-day windows. A single 5-year request silently returns nothing without the chunking.
11. **FIT downloads**: Use `Garmin.ActivityDownloadFormat.ORIGINAL` and unzip the response to extract the `.fit` member (`download_activity_fit` in `api/client.py`). Failures print to stderr; they're no longer silently swallowed.
12. **Longitudinal data scope**: `get_longitudinal_summary` defaults `start_year` to `MIN(date)` from `sleep_daily`. With a fresh DB this is the current year; run `sync all --days 1825` (or longer) before expecting multi-year output.
13. **FRESHNESS_DAYS = 7**: Daily metric sync (`_sync_daily_metric`) skips rows older than 7 days if they already exist in the DB. This saves API calls on backfills. Use `--force` to override. If you add a new computed column to an existing daily table, existing rows won't be re-fetched unless the user runs `--force`.
14. **`_ALLOWED_DAILY_TABLES`**: The frozenset in `repository.py` prevents SQL injection on the dynamic table name in `has_daily_record()`. When adding a new daily table, you *must* add it to this allowlist or the skip-check will raise `ValueError`.
15. **`_DAILY_METRIC_TABLE`**: The mapping in `sync_manager.py` connects `data_type` strings to SQLite table names for the skip optimization. New daily data types need an entry here to benefit from smart-skip.
16. **Windows scheduler**: Uses `schtasks.exe` via `subprocess.run`. Batch wrapper paths are validated by `_validate_batch_path()` which rejects `"&|<>^%!` characters to prevent script injection.
17. **`paths.py` macOS override**: `default_data_dir()` hardcodes XDG paths when `sys.platform == "darwin"` because `platformdirs` returns `~/Library/Application Support/` on macOS, which would orphan existing data at `~/.local/share/garmin-sync`.
18. **Scheduler factory**: `scheduler/__init__.py` provides `get_scheduler()` which returns the `launchd` module on Darwin, `windows_task` on Windows, or `None` on Linux. CLI commands use this instead of `platform.system()` checks.
