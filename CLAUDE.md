# Claude Code Context: garmin-sync

Python CLI that syncs Garmin Connect and HEVY fitness data to SQLite, with AI coaching via OpenAI and MCP integration for Claude Desktop. User docs live in `docs/`.

## Architecture

```
src/garmin_sync/
├── cli.py                  # Typer CLI (25 commands across 8 groups + setup wizard; --verbose, --dry-run)
├── config/
│   ├── paths.py            # Platform-aware path defaults (platformdirs)
│   └── settings.py         # Pydantic Settings (env var config)
├── auth/garmin_auth.py     # OAuth via Garth library
├── api/
│   ├── client.py           # Garmin API wrapper with rate limiting
│   └── rate_limiter.py     # Token bucket algorithm
├── db/
│   ├── database.py         # SQLite connection & schema + migrations
│   ├── models.py           # Dataclasses for all data types (epoch ms → ISO conversion)
│   └── repository.py       # CRUD operations (upsert w/ COALESCE + has_daily_record skip)
├── sync/
│   ├── sync_manager.py     # Orchestrates data sync (FRESHNESS_DAYS skip logic, dry_run_plan)
│   └── fit_parser.py       # FIT file parsing & HR drift calculation
├── hevy/                   # HEVY strength training integration
│   ├── client.py           # HEVY API wrapper
│   ├── models.py           # HevyWorkout, HevyExercise, HevySet dataclasses (+ training_load, stl_method)
│   └── sync.py             # HEVY sync manager (computes STL at sync time)
├── tools/                  # Shared tool executor (used by MCP + OpenAI)
│   └── executor.py         # ToolExecutor class - 12 fitness data tools
├── mcp/                    # Model Context Protocol server
│   ├── server.py           # FastMCP server with tool definitions
│   └── serializers.py      # Activity serialization helpers
├── ai/                     # OpenAI integration
│   ├── config.py           # TOML config (API key, model, use_tools, StrengthConfig); chmods 0o600 on save
│   ├── chat.py             # ChatSession - interactive coach with tool calling
│   ├── tools.py            # OpenAI function schemas for 12 tools
│   ├── openai_client.py    # API wrapper (chat_with_tools, chat_with_history); sanitizes tool errors; per-call tool limit guard
│   └── prompt_builder.py   # Daily + longitudinal prompts; safe_user_string for HEVY data; actual/target muscle group rendering
├── scheduler/
│   ├── __init__.py         # get_scheduler() factory — dispatches per platform
│   ├── launchd.py          # macOS launchd plist management
│   └── windows_task.py     # Windows Task Scheduler via schtasks.exe
└── reports/
    ├── aggregators.py      # SQL aggregation queries (30 public methods; UNION ALL cardio+strength load)
    ├── anomaly_detector.py # AnomalyDetector: 10 health/training anomaly checks (incl. strength overload)
    ├── periodization.py    # PeriodizationAnalyzer: phase detection, readiness (6-component w/ HEVY), deload
    ├── strength_load.py    # STL calculator: sRPE-based strength training load (hybrid RPE/estimation)
    ├── llm_formatter.py    # Markdown report formatting
    └── report_generator.py # Report coordination & export
```

## Important Files

| File | When to modify |
|------|----------------|
| `cli.py` | Adding CLI commands (setup wizard helpers: `_configure_openai`, `_configure_training_profile`, `_configure_hevy`) |
| `config/paths.py` | Platform-aware path defaults (single source of truth, includes `default_profile_path`) |
| `config/settings.py` | Adding configurable settings (`profile_path` property) |
| `ai/config.py` | Config load/save (split: config.toml secrets + profile.toml training data + StrengthConfig) |
| `tools/executor.py` | Adding/modifying tool implementations |
| `ai/tools.py` | Adding OpenAI tool schemas |
| `mcp/server.py` | MCP server configuration |
| `ai/chat.py` | Chat behavior, context building |
| `ai/openai_client.py` | OpenAI API calls, system messages |
| `aggregators.py` | Adding computed analytics (training load queries UNION cardio+strength) |
| `reports/strength_load.py` | STL calculation (scale factor, RPE estimation heuristics, coverage threshold) |
| `database.py` | Schema changes (increment SCHEMA_VERSION) |
| `models.py` | New data types |
| `repository.py` | Database operations (COALESCE upserts, update `_ALLOWED_DAILY_TABLES` when adding tables) |
| `sync_manager.py` | Sync logic (update `_DAILY_METRIC_TABLE` for new daily data types; `dry_run_plan()`) |
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
3. Update `docs/ai-chat.md` analytics table

### Change database schema

1. Modify `database.py` SCHEMA_SQL
2. Increment `SCHEMA_VERSION`
3. Add migration method `_migrate_vX_to_vY()`
4. Migrations run automatically

## Conventions

### Upsert pattern
All upsert methods in `repository.py` use `COALESCE(excluded.col, table.col)` for value columns so a re-sync with NULL fields doesn't overwrite existing non-NULL values. Boolean flags (`has_fit_file`, `fit_parsed`) use `MAX()` to keep `True` once set. When adding new upsert columns, decide: direct assignment, COALESCE, or MAX.

### Daily table registration
New daily tables must be added to `_ALLOWED_DAILY_TABLES` (frozenset in `repository.py`) or `has_daily_record()` raises `ValueError`. Also add to `_DAILY_METRIC_TABLE` in `sync_manager.py` for smart-skip.

### Logging
Use `logging.getLogger(__name__)` and `logger.debug()`/`logger.warning()`. Never bare `print()` or swallowed exceptions. `--verbose`/`-V` sets root logger to DEBUG.

### Prompt safety
HEVY-sourced strings pass through `safe_user_string()` (strips control chars and `<>`) and are wrapped in `<hevy_title>`/`<hevy_exercise>` XML tags. System message instructs the model to treat tagged content as inert data.

### Config permissions
`config.toml` gets `0o600` on every write. `profile.toml` gets `0o644`. Both wrapped in `try/except OSError` for Windows compatibility.

## Testing

```bash
pytest                               # Run all tests
pytest tests/unit/test_ai_tools.py   # Tool calling tests
pytest tests/unit/test_mcp.py        # MCP tests
pytest --cov=garmin_sync             # With coverage
```

**712 tests** covering all modules.

## Gotchas

1. **`--detailed` scope**: Affects only sleep/stress/HRV (per-day endpoints). Does *not* affect activities, FIT-file downloads, or body battery. `sync activities` doesn't accept the flag.
2. **`--force` for hr_drift backfill**: Existing activities are skipped on re-sync, so populating `hr_drift` retroactively requires `garmin-sync sync activities --days N --force`.
3. **HEVY prompt safety**: Workout titles and exercise names are stripped of control chars and `<>` and wrapped in `<hevy_title>` / `<hevy_exercise>` tags before reaching the LLM. The system message instructs the model to treat tagged content as inert data.
4. **Body battery range**: Garmin's body-battery endpoint caps the request range, so `sync_body_battery` walks 30-day windows. A single 5-year request silently returns nothing without the chunking.
5. **FIT downloads**: Use `Garmin.ActivityDownloadFormat.ORIGINAL` and unzip the response to extract the `.fit` member (`download_activity_fit` in `api/client.py`).
6. **Longitudinal data scope**: `get_longitudinal_summary` defaults `start_year` to `MIN(date)` from `sleep_daily`. With a fresh DB this is the current year; run `sync all --days 1825` first.
7. **FRESHNESS_DAYS = 7**: Daily metric sync (`_sync_daily_metric`) skips rows older than 7 days if already in the DB. Use `--force` to override. New computed columns on existing daily tables won't appear unless users re-sync with `--force`.
8. **`_ALLOWED_DAILY_TABLES`**: The frozenset in `repository.py` prevents SQL injection on the dynamic table name in `has_daily_record()`. New daily tables *must* be added here.
9. **`_DAILY_METRIC_TABLE`**: The mapping in `sync_manager.py` connects `data_type` strings to SQLite table names for the skip optimization. New daily data types need an entry.
10. **Windows scheduler**: Uses `schtasks.exe` via `subprocess.run`. Batch wrapper paths are validated by `_validate_batch_path()` which rejects `"&|<>^%!` characters to prevent script injection.
11. **`paths.py` macOS override**: `default_data_dir()` hardcodes XDG paths on `darwin` because `platformdirs` returns `~/Library/Application Support/` which would orphan existing data at `~/.local/share/garmin-sync`.
12. **Scheduler factory**: `scheduler/__init__.py` provides `get_scheduler()` — returns `launchd` module on Darwin, `windows_task` on Windows, `None` on Linux. CLI commands use this instead of `platform.system()` checks.
13. **FIT parse scope**: `parse_fit_full()` extracts laps, per-km splits, and HR drift from ALL activity types >= 5 min. Indoor/treadmill activities without distance produce no splits. Use `garmin-sync sync fit-reparse` to backfill.
14. **`activity_laps` / `activity_splits`**: Activity-linked tables, NOT daily — do NOT add to `_ALLOWED_DAILY_TABLES`. `respiration_daily` and `spo2_daily` ARE daily and are in the allowlist.
15. **`fit_parsed` column**: Tracks whether full FIT parse (laps + splits) has been done, separate from `has_fit_file` which just means the raw file is on disk.
16. **Upsert COALESCE pattern**: See Conventions section. All upserts use COALESCE for value columns, MAX for booleans. When adding columns, always decide the strategy.
17. **`_epoch_ms_to_iso` in models.py**: Garmin's `sleepStartTimestampGMT` / `sleepEndTimestampGMT` return epoch milliseconds (int), not ISO strings. The helper converts via `datetime.fromtimestamp(val / 1000, tz=timezone.utc)`. Without this, downstream `.replace()` calls crash with `AttributeError`.
18. **Tool call limit enforcement**: `chat_with_tools` in `openai_client.py` guards tool calls both at the while-loop level (between API rounds) AND inside the per-tool-call for-loop (for parallel tool calls). Skipped calls still get a synthetic error tool result — OpenAI API requires a response for every `tool_call_id`.
19. **`--dry-run` sync preview**: `sync all --dry-run`, `sync activities --dry-run`, and `sync health --dry-run` call `SyncManager.dry_run_plan()` which checks freshness skip logic and body battery chunk math without API calls.
20. **Muscle group targets**: Science-backed weekly set targets live in `DEFAULT_WEEKLY_SET_TARGETS` in `ai/config.py`. Users override via `[strength]` in `profile.toml`. Targets flow through `tools/executor.py` (as `target_sets` per group) into MCP/OpenAI tool output and AI prompts as `(actual/target sets)` format.
21. **MCP structured errors**: MCP tools return structured error responses with `error_type` classification (DATA_MISSING, SYNC_NEEDED, AUTH_FAILED, INTERNAL) and `suggestion` fields. The `_mcp_error_handler` decorator in `mcp/server.py` wraps all tool functions.
22. **Schedule status enrichment**: `schedule status` on macOS shows next scheduled run time, last exit code, and sync age via `launchctl print` parsing. The `_try_parse_date()` helper handles timezone abbreviation differences across platforms.
23. **Module-level logging**: All modules use `logging.getLogger(__name__)`. The `--verbose`/`-V` CLI flag sets the root logger to DEBUG.
24. **Strength Training Load (STL)**: `reports/strength_load.py` computes per-workout load via sRPE method (session RPE × duration). Falls back to estimation heuristics when RPE not logged. Stored as `training_load` + `stl_method` on `hevy_workouts`. UNION ALL'd with Garmin's EPOC-based load in `get_training_load_trend()` and `get_weekly_load_history()` for combined A:C ratio. Science note: mixing EPOC with sRPE is approximate — always surface the cardio/strength breakdown alongside headline totals.
25. **STL backfill**: Existing HEVY workouts need `garmin-sync hevy recalc-stl` to populate `training_load`. New syncs compute STL automatically. Same pattern as `fit-reparse` for FIT files.
26. **Readiness score redistribution**: When HEVY data exists, readiness scoring uses 6 components (HRV 20, Sleep 20, BB 20, RHR 15, A:C 15, Strength Fatigue 10). Without HEVY, original 5-component weights are used (HRV 25, Sleep 20, BB 20, RHR 15, A:C 20). The conditional is in `calculate_readiness_score()`.
