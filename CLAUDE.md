# Claude Code Context: garmin-sync

Python CLI that syncs Garmin Connect and HEVY fitness data to SQLite, with AI coaching via OpenAI and MCP integration for Claude Desktop. User docs live in `docs/`.

## Architecture

```
src/garmin_sync/
├── cli.py                  # Typer CLI (33 commands across 9 groups + setup wizard; --verbose, --dry-run)
├── units.py                # Unit conversions (SI storage → imperial presentation; single home of constants)
├── config/
│   ├── paths.py            # Platform-aware path defaults (platformdirs)
│   └── settings.py         # Pydantic Settings (env var config; data_dir + config_dir, expanduser'd)
├── auth/garmin_auth.py     # OAuth via Garth library (MFA-capable login)
├── api/
│   ├── client.py           # Garmin API wrapper with rate limiting (token acquired per retry)
│   └── rate_limiter.py     # Sliding-window limiter (monotonic clock)
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
│   └── executor.py         # ToolExecutor class - 9 fitness data tools (sanitizes HEVY text in output)
├── mcp/                    # Model Context Protocol server
│   └── server.py           # FastMCP server with tool definitions
├── ai/                     # OpenAI integration
│   ├── config.py           # TOML config (API key, model, use_tools, StrengthConfig); atomic 0o600 write
│   ├── chat.py             # ChatSession - interactive coach with tool calling (reference data folded into system msg; ANALYSES_CONTEXT_DAYS / CHAT_HISTORY_LIMIT caps)
│   ├── tools.py            # OpenAI function schemas for 9 tools
│   ├── openai_client.py    # API wrapper (chat_with_tools, chat_with_history); sanitizes tool errors; per-call tool limit guard
│   └── prompt_builder.py   # Daily + longitudinal prompts; verdict-list continuity (no echo chamber); safe_user_string for HEVY data
├── scheduler/
│   ├── __init__.py         # get_scheduler() factory — dispatches per platform
│   ├── launchd.py          # macOS launchd plist management
│   └── windows_task.py     # Windows Task Scheduler via schtasks.exe
└── reports/
    ├── aggregators.py      # SQL aggregation queries (UNION ALL cardio+strength load)
    ├── anomaly_detector.py # AnomalyDetector: 9 health/training anomaly checks (the ONLY alert layer)
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
HEVY-sourced strings pass through `safe_user_string()` (strips control chars and `<>`) and are wrapped in `<hevy_title>`/`<hevy_exercise>` XML tags. System message instructs the model to treat tagged content as inert data. **Two paths:** the static prompt (`prompt_builder.py`) tags+sanitizes; the tool-call path has no tags, so `tools/executor.py` sanitizes HEVY free-text (`_sanitize_hevy_text`) before returning tool output. Sanitize at the executor boundary so MCP and OpenAI both benefit.

### Config permissions
`config.toml` (secrets) is written via `_write_secret_toml()` in `ai/config.py`, which `fchmod`s the fd to `0o600` *before* the key is written (no world-readable window, even re-saving over a loose-mode file). `profile.toml` gets `0o644`. Both wrapped in `try/except OSError` for Windows compatibility.

## Testing

```bash
pytest                               # Run all tests
pytest tests/unit/test_ai_tools.py   # Tool calling tests
pytest tests/unit/test_mcp.py        # MCP tests
pytest --cov=garmin_sync             # With coverage
```

**690 tests** covering all modules.

## Gotchas

1. **`--detailed` scope**: Affects only sleep/stress/HRV (per-day endpoints). Does *not* affect activities, FIT-file downloads, or body battery. `sync activities` doesn't accept the flag.
2. **`--force` for hr_drift backfill**: Existing activities are skipped on re-sync, so populating `hr_drift` retroactively requires `garmin-sync sync activities --days N --force`.
3. **HEVY prompt safety (two paths)**: Static prompts wrap HEVY titles/exercise names in `<hevy_title>`/`<hevy_exercise>` tags + `safe_user_string`. Tool-call results have NO tags (raw JSON to the model), so `tools/executor.py` sanitizes HEVY free-text via `_sanitize_hevy_text` before returning. If you add a tool that surfaces HEVY-controlled strings, route them through it.
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
20. **Muscle group targets**: Weekly set targets live in `DEFAULT_WEEKLY_SET_TARGETS` in `ai/config.py`, tuned for **hypertrophy** (MEV→low-MAV band; major muscles ~12–14 sets/wk per Schoenfeld 2017 + RP landmarks). Users override via `[strength]` in `profile.toml`. Targets flow through `tools/executor.py` (as `target_sets` per group) into MCP/OpenAI tool output and AI prompts as `(actual/target sets)` format.
21. **MCP structured errors**: MCP tools return structured error responses with `error_type` classification (DATA_MISSING, SYNC_NEEDED, AUTH_FAILED, INTERNAL) and `suggestion` fields. The `_mcp_error_handler` decorator in `mcp/server.py` wraps all tool functions.
22. **Schedule status enrichment**: `schedule status` on macOS shows next scheduled run time, last exit code, and sync age via `launchctl print` parsing. The `_try_parse_date()` helper handles timezone abbreviation differences across platforms.
23. **Module-level logging**: All modules use `logging.getLogger(__name__)`. The `--verbose`/`-V` CLI flag sets the root logger to DEBUG.
24. **Strength Training Load (STL)**: `reports/strength_load.py` computes per-workout load via sRPE method (session RPE × duration). Falls back to estimation heuristics when RPE not logged. Stored as `training_load` + `stl_method` on `hevy_workouts`. UNION ALL'd with Garmin's EPOC-based load in `get_training_load_trend()` for the combined A:C ratio. Science note: mixing EPOC with sRPE is approximate — always surface the cardio/strength breakdown alongside headline totals.
25. **STL backfill**: Existing HEVY workouts need `garmin-sync hevy recalc-stl` to populate `training_load`. New syncs compute STL automatically. Same pattern as `fit-reparse` for FIT files.
26. **One alert layer, one readiness number (2026-09 de-bloat)**: `AnomalyDetector` is the ONLY alert system — the legacy `_generate_alerts` (llm_formatter), the `PeriodizationAnalyzer` (phase detection + custom readiness score + deload), and the stress-recovery/sleep-performance correlation aggregators were deliberately DELETED (they triple-counted signals, contradicted the A:C reframing, and drowned the coach prompt). "Readiness" now always means Garmin's own Training Readiness score. `get_recovery_status` embeds anomalies; there is no separate anomaly/periodization tool. Don't reintroduce a second interpretation layer — add new checks to `anomaly_detector.py` instead.
27. **Rate limiter uses `time.monotonic()`**: `api/rate_limiter.py` is a sliding-window limiter that loops (`while`, not `if`) with inclusive (`<=`) eviction so it keeps limiting after the first throttle. It uses `time.monotonic()`, so **tests must mock `time.monotonic`, not `time.time`** (mocking the wrong one makes a test busy-loop in real time). `_api_call` in `api/client.py` acquires a token per retry attempt.
28. **A:C ratio is UNCOUPLED and reframed (not injury prediction)**: `get_training_load_trend()` computes `acute_chronic_ratio` = acute(7d) ÷ `chronic_baseline_weekly` (= load in days 8–28 ÷ 3), deliberately EXCLUDING the acute window so the ratio isn't mathematically coupled (Lolli 2019). It's surfaced as a descriptive **load-ramp** label (`load_ramp`: reduced/steady/building/rapid_increase), NOT injury risk (the ACWR "sweet spot" is unsupported — Impellizzeri 2020). The overload anomaly is **warning** (cardio) / **info** (strength), not critical, and only fires when `chronic_baseline_load > 0`. Mock dicts feeding these checks need `chronic_baseline_load` (+ `chronic_baseline_weekly` for messages).
29. **HEVY pagination + parsing**: `hevy/client.py` `get_all_workouts` does NOT stop on a missing `start_time` (would truncate the sync) and treats an absent `page_count` as "a full page implies more". Requests have a `(5, 30)` timeout. `models.py` tolerates `"sets"/"exercises": null` and coerces string-typed `weight_kg`/`reps`.
30. **`has_tokens()` requires non-empty files**: `auth/garmin_auth.py` checks token files exist AND are non-empty (garth writes 0-byte files on a partial login). `login()` passes an MFA prompt to garth so 2FA accounts can authenticate, and clears the password after the token dump.
31. **`GARMIN_SYNC_CONFIG_DIR`**: `config_dir` is a separate Settings field (default `default_config_dir()`) — `ai_config_path`/`profile_path` derive from it, so config can be relocated independently of `GARMIN_SYNC_DATA_DIR`. Path env vars are `expanduser()`'d. `paths.py` passes `appauthor=False` to platformdirs (avoids doubled `…\garmin-sync\garmin-sync` on Windows).
32. **HRV is smoothed + personalized**: `get_hrv_context()` sets `delta_from_baseline` from the **7-day rolling mean vs the 28d baseline** (not a single night), and computes `cv_pct` (coefficient of variation of daily HRV) + `swc_pct` (≈0.5×CV, smallest worthwhile change) when ≥7 days exist. `_score_hrv` ramps from −SWC (full) to −2×CV (zero); `_check_hrv_crash` fires when the smoothed delta drops below −1×CV — both fall back to a fixed −20%/−15% when CV is unavailable (Plews & Buchheit). Mocks feeding these need `cv_pct`/`swc_pct` to exercise the personalized path.
33. **Units policy (imperial presentation, SI storage)**: the DB stores Garmin's native SI (meters, m/s; HEVY kg) — never convert at the storage layer. Everything user/model-facing is imperial: miles, mph, min/mile pace, feet, lbs. All conversion constants and helpers live in `units.py` (no scattered `* 2.20462` / `* 3.6` literals). Raw `export activities|health` output intentionally stays SI. FIT splits are *bucketed* per-km in `activity_splits` (schema unchanged), but their displayed paces are min/mi via `sec_per_km_to_sec_per_mile`. When adding a field, name the key with its unit (`distance_miles`, `max_speed_mph`, `total_gain_ft`, `vert_ft_per_hour`).
34. **Daily-prompt continuity contract**: `_run_analysis` (cli.py) feeds the model a one-line verdict list from the last 7 reports plus yesterday's analysis only. `_extract_verdict` matches the `Today: <call>` line (the instructions mandate it as the report's first line) — keep that output contract or verdict extraction goes blind. Never reintroduce multiple full previous analyses into the prompt: that was the echo-chamber regression that degraded coaching quality (the model anchored on a week of its own cautious headlines).
35. **launchd report must not run before morning**: the daily job (`scheduler/launchd.py` `generate_plist`) keys the report to *today* and syncs `--days 1`, but `StartInterval` polls every 2h for catch-up. Without a floor, the **first poll after midnight (~00:36) generates today's report from a few minutes of post-midnight data** — a partial-day `body_battery_daily` row (e.g. `max_level=45` instead of the real overnight peak ~90), wrong sleep/HRV — and the idempotency guard (`if [ -f "$REPORT" ]`) then **blocks the real 08:30 run**. Fix: the command floors generation at the per-day scheduled hour (`DOW=$(date +%u)`; weekday→`weekday_hour`, weekend→`weekend_hour`; `HOUR=$((10#$(date +%H)))` forces base-10 so `08`/`09` don't trip octal parsing). Catch-up still works (a poll ≥ floor with no report yet generates it). The fix only reaches the live agent after `schedule install` rewrites the plist. Windows (`windows_task.py`) fires at exact times via `schtasks`, no poll, so it's unaffected.
