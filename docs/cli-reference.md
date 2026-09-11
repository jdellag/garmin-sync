# CLI Reference

## Global Flags

These flags apply to the top-level `garmin-sync` command and affect all subcommands:

| Flag | Description |
|------|-------------|
| `--verbose` / `-V` | Enable debug logging (sets root logger to DEBUG) |
| `--version` | Show version and exit |
| `--help` | Show help and exit |

Subcommand-specific flags:

| Flag | Applies to | Description |
|------|------------|-------------|
| `--dry-run` | `sync all`, `sync activities`, `sync health` | Preview sync plan without API calls |
| `--quiet` / `-q` | `sync` commands | Suppress post-sync status check |

## setup

```bash
garmin-sync setup
```

Interactive wizard that configures Garmin auth, OpenAI API key, training profile, and HEVY integration in one step.

## auth

| Command | Description |
|---------|-------------|
| `garmin-sync auth login` | Login to Garmin Connect via OAuth |
| `garmin-sync auth status` | Show authentication status and token info |
| `garmin-sync auth logout` | Remove stored OAuth tokens |

## sync

```bash
garmin-sync sync all                    # Sync all Garmin + HEVY data (last 30 days)
garmin-sync sync all --days 7           # Sync last 7 days
garmin-sync sync all --detailed         # Include per-day sleep/stress/HRV data
garmin-sync sync all --force            # Re-download even if data exists
garmin-sync sync all --dry-run          # Preview what would be synced
garmin-sync -V sync all                 # Verbose mode (debug logging)
```

| Command | Description |
|---------|-------------|
| `garmin-sync sync all` | Sync all Garmin + HEVY data |
| `garmin-sync sync activities` | Sync activities only (with FIT files and HR drift) |
| `garmin-sync sync health` | Sync health metrics only (sleep, HR, stress, HRV, body battery, readiness) |
| `garmin-sync sync fit-reparse` | Re-parse existing FIT files (laps, splits, HR drift) |
| `garmin-sync sync backfill-prs` | Re-scan all activities to set correct personal records |

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--days` | 30 | Number of days to sync |
| `--force` | off | Re-download data even if it already exists in the database |
| `--detailed` | off | Fetch per-day endpoints for sleep/stress/HRV (more API calls) |
| `--dry-run` | off | Preview sync plan without making API calls |
| `--quiet` / `-q` | off | Suppress post-sync status check |

**Smart sync:** Daily metrics older than 7 days are skipped if already present. This saves API calls during large backfills. Use `--force` to override.

**Data types synced:**

From Garmin Connect:
- Activities (with FIT files and HR drift computation)
- Sleep (duration, stages, score, respiration, SpO2)
- Heart rate, stress, HRV, body battery
- Training readiness (composite score with component breakdown)

From HEVY (if configured):
- Workouts, exercises, sets
- Volume by muscle group
- Exercise progression (estimated 1RM)

## analyze

| Command | Description |
|---------|-------------|
| `garmin-sync analyze` | Run one-shot daily analysis (last 7 days) |
| `garmin-sync analyze chat` | Interactive AI coach with tool calling |
| `garmin-sync analyze longitudinal` | Multi-year fitness review |
| `garmin-sync analyze configure` | Configure API key, model, training profile |
| `garmin-sync analyze view` | View most recent analysis (`--date YYYY-MM-DD` for specific date) |
| `garmin-sync analyze list` | List all analysis reports |
| `garmin-sync analyze anomalies` | Health/training anomaly scan |

**Longitudinal review:**

```bash
garmin-sync analyze longitudinal                    # Earliest year in DB to today
garmin-sync analyze longitudinal --start-year 2023  # Narrow the window
garmin-sync analyze longitudinal -g quarter         # Quarter buckets instead of yearly
```

Surfaces multi-year trends (pace-at-HR, RHR/HRV/sleep baselines, weekly-volume consistency, HR drift) and highlights plateaus or regime shifts. Output saved to `reports/longitudinal-YYYY-MM-DD.md`.

## report

| Command | Description |
|---------|-------------|
| `garmin-sync report weekly` | Generate weekly report (`--llm` for ChatGPT-optimized output) |
| `garmin-sync report monthly` | Generate monthly report |

## export

| Command | Description |
|---------|-------------|
| `garmin-sync export activities` | Export activities to JSON or CSV |
| `garmin-sync export health` | Export health data to JSON or CSV |

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `-f` / `--format` | `json` | Output format: `json` or `csv` |
| `-o` / `--output` | auto-generated | Output file path (defaults to exports directory) |
| `-d` / `--days` | 30 | Days of data to export |

## stats

| Command | Description |
|---------|-------------|
| `garmin-sync stats today` | Quick summary of today's activity |
| `garmin-sync stats week` | Quick summary of this week |

## hevy

| Command | Description |
|---------|-------------|
| `garmin-sync hevy login` | Configure HEVY API key |
| `garmin-sync hevy sync` | Sync workouts from HEVY |
| `garmin-sync hevy status` | Show config and recent workouts |
| `garmin-sync hevy volume` | Volume breakdown by muscle group |
| `garmin-sync hevy recalc-stl` | Recompute Strength Training Load for existing workouts |

See [HEVY Integration](hevy-integration.md) for setup details.

## mcp

| Command | Description |
|---------|-------------|
| `garmin-sync mcp info` | Show Claude Desktop setup instructions |
| `garmin-sync mcp serve` | Start the MCP server directly |

See [MCP Integration](mcp-integration.md) for full tool reference.

## schedule

| Command | Description |
|---------|-------------|
| `garmin-sync schedule install` | Install daily auto-sync + analysis |
| `garmin-sync schedule uninstall` | Remove scheduled tasks |
| `garmin-sync schedule status` | Show next run, last exit code, sync age |
| `garmin-sync schedule logs` | View scheduled sync logs |

See [Scheduling](scheduling.md) for platform details.
