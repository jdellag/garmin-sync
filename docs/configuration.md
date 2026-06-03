# Configuration

Configuration is split across two TOML files. Secrets (API keys) are kept separate from training preferences so you can share your profile without exposing credentials.

## config.toml (secrets + technical settings)

Permissions: `0o600` (owner-only read/write).

```toml
[openai]
api_key = "sk-..."
model = "o3-mini"        # Model for non-tool chat
use_tools = true         # Enable tool calling (uses gpt-5.4 when active)
enabled = true

[hevy]
api_key = "..."          # HEVY API key (requires HEVY Pro)
enabled = true
sync_days = 30           # Days of HEVY data to sync
```

## profile.toml (training profile)

Permissions: `0o644` (readable). Safe to share or version control.

```toml
[training]
timezone = "America/New_York"
schedule = """
Monday: Rest day or easy recovery
Tuesday: Speed/interval workout
Wednesday: Easy run
Thursday: Tempo or threshold run
Friday: Rest or cross-training
Saturday: Long run
Sunday: Easy run or rest"""
user_context = """
Training for a spring marathon.
- Today: {today_date}
- Day of week: {day_of_week}
"""

[strength]
# Weekly set targets per muscle group.
# Defaults are science-backed (Renaissance Periodization / Schoenfeld).
# Override any group here:
# quadriceps = 16
# upper_back = 14
```

### Weekly set target defaults

The defaults are tuned for **hypertrophy** — they sit in the MEV→low-MAV band
(Schoenfeld et al. 2017 found >10 sets/week beats <10 for growth; Renaissance
Periodization puts MEV ~10–16 and MAV ~16–20 sets/muscle/week). If your goal is
general fitness/maintenance rather than growth, set lower values in `[strength]`.

| Muscle Group | Sets/Week | Muscle Group | Sets/Week |
|-------------|-----------|-------------|-----------|
| Quadriceps | 12 | Biceps | 12 |
| Hamstrings | 10 | Triceps | 12 |
| Glutes | 12 | Traps | 10 |
| Chest | 14 | Calves | 12 |
| Lats | 14 | Abdominals | 10 |
| Shoulders | 14 | Forearms | 8 |
| Upper Back | 12 | Adductors | 8 |
| Lower Back | 6 | Abductors | 8 |

Any muscle group not listed defaults to 6 sets/week. Targets flow into AI analysis and tool output as actual/target ratios.

## Environment variables

All settings can also be configured via environment variables (prefix `GARMIN_SYNC_`) or a `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATA_DIR` | Platform default | Data storage directory (DB, reports, FIT files, logs) |
| `CONFIG_DIR` | Platform default | Directory for `config.toml` + `profile.toml` |
| `GARTH_TOKEN_DIR` | `~/.garminconnect` | OAuth token directory |
| `DATABASE_NAME` | `garmin.db` | SQLite database filename |
| `DEFAULT_SYNC_DAYS` | `30` | Days to sync (1-365) |
| `DOWNLOAD_FIT_FILES` | `true` | Download FIT files during activity sync |
| `API_TIMEOUT_SECONDS` | `30` | API request timeout (5-120) |
| `RATE_LIMIT_CALLS_PER_MINUTE` | `15` | Garmin API rate limit (1-60) |
| `DEFAULT_REPORT_FORMAT` | `markdown` | Report format: `markdown`, `text`, or `json` |
| `LLM_MODE_DEFAULT` | `false` | LLM-optimized report output by default |

## Data storage paths

All data is stored locally. Paths are managed by `platformdirs`. Override the data location with `GARMIN_SYNC_DATA_DIR` and the config/profile location with `GARMIN_SYNC_CONFIG_DIR` (they are separate roots — relocating data does not move your API keys/profile, so set both if you want everything together). `~` in these values is expanded to your home directory.

| Purpose | macOS / Linux | Windows |
|---------|---------------|---------|
| SQLite database | `~/.local/share/garmin-sync/garmin.db` | `%LOCALAPPDATA%\garmin-sync\garmin.db` |
| AI analysis reports | `~/.local/share/garmin-sync/reports/` | `%LOCALAPPDATA%\garmin-sync\reports\` |
| Scheduled sync logs | `~/.local/share/garmin-sync/logs/` | `%LOCALAPPDATA%\garmin-sync\logs\` |
| FIT files | `~/.local/share/garmin-sync/fit_files/` | `%LOCALAPPDATA%\garmin-sync\fit_files\` |
| API keys + settings | `~/.config/garmin-sync/config.toml` | `%LOCALAPPDATA%\garmin-sync\config.toml` |
| Training profile | `~/.config/garmin-sync/profile.toml` | `%LOCALAPPDATA%\garmin-sync\profile.toml` |
| OAuth tokens | `~/.garminconnect/` | `~/.garminconnect/` |

## Config migration

If you have an older single-file `config.toml` with an `[analysis]` section, it will be automatically migrated to the split layout on first run. The `[analysis]` data moves to `profile.toml` and is removed from `config.toml`.
