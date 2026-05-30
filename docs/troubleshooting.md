# Troubleshooting

## Authentication

**"Not authenticated" errors:**
Re-run `garmin-sync auth login`. Garmin OAuth tokens expire periodically. Check current status with `garmin-sync auth status`.

## Rate limiting

**Sync is slow or hitting errors:**
Garmin enforces ~15 API calls per minute. Large syncs (many days of data) will take time. Adjust the limit with the `GARMIN_SYNC_RATE_LIMIT_CALLS_PER_MINUTE` environment variable if needed.

## Missing data

**HRV, body battery, or training readiness is empty:**
These metrics require compatible Garmin devices. Not all watches support every data type.

**Sleep respiration or SpO2 missing:**
Requires a Garmin device with Pulse Ox sensor and overnight tracking enabled.

## AI and tool calling

**Tool calling not working:**
Ensure `use_tools = true` in `config.toml`. When enabled, chat uses `gpt-5.4` regardless of the configured model.

**"AI not configured" error:**
Run `garmin-sync analyze configure` and enter your OpenAI API key.

**Chat seems to ignore my timezone:**
Check `timezone` in `profile.toml`. Default is `America/New_York`.

## Data sync

**Smart sync is skipping data I need:**
Daily metrics older than 7 days are skipped if they already exist. Use `--force` to re-sync:
```bash
garmin-sync sync all --days 90 --force
```

**`--detailed` not fetching what I expected:**
The `--detailed` flag only affects sleep, stress, and HRV (per-day endpoints). It does not affect activities, FIT file downloads, or body battery.

**Want to see what would sync before running:**
```bash
garmin-sync sync all --dry-run
```

**HR drift missing for older activities:**
Existing activities are skipped on re-sync. To backfill HR drift retroactively:
```bash
garmin-sync sync activities --days 365 --force
```

## Longitudinal analysis

**Analysis output is empty or only shows current year:**
Longitudinal analysis needs historical data. Sync a large date range first:
```bash
garmin-sync sync all --days 1825    # ~5 years
```

## FIT files

**Laps/splits missing for activities:**
Run `garmin-sync sync fit-reparse` to re-process existing FIT files for laps, per-km splits, and HR drift.

## HEVY

**HEVY sync fails:**
Verify your API key with `garmin-sync hevy status`. HEVY API access requires a Pro subscription.

## Scheduling

**Scheduled sync not running:**
- macOS: `launchctl list | grep garmin` to check if the job is loaded
- Windows: Open Task Scheduler and verify the GarminSync tasks exist
- Check logs: `garmin-sync schedule logs`

**Missed runs:**
- macOS launchd includes catch-up logic -- if your Mac was asleep, it runs on wake
- Windows Task Scheduler may need "Run task as soon as possible after a scheduled start is missed" enabled

## Deleting all data

To remove all garmin-sync data from your machine:

- **macOS/Linux:** `rm -rf ~/.local/share/garmin-sync ~/.garminconnect ~/.config/garmin-sync`
- **Windows:** `rmdir /s /q "%LOCALAPPDATA%\garmin-sync"` and `rmdir /s /q "%USERPROFILE%\.garminconnect"`
