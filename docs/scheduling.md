# Automatic Scheduling

garmin-sync can automatically sync your data and run AI analysis daily. Scheduling is supported on macOS and Windows, with manual crontab instructions for Linux.

## Overview

The scheduled task runs two commands:

1. `garmin-sync sync all --days 1 --detailed` -- sync the latest day of data
2. `garmin-sync analyze` -- run daily AI analysis

**Default schedule:** Weekdays at 8:30 AM, Weekends at 10:00 AM.

## Commands

```bash
garmin-sync schedule install     # Install daily sync + analysis
garmin-sync schedule uninstall   # Remove scheduled tasks
garmin-sync schedule status      # Show next run, last exit code, sync age
garmin-sync schedule logs        # View scheduled sync logs
```

### Status output

`schedule status` shows:
- **Next scheduled run** time
- **Last exit code** (0 = success)
- **Sync age** -- time since the last successful sync

## macOS (launchd)

Uses a launchd plist (`com.garmin-sync.daily`) installed in `~/Library/LaunchAgents/`.

Features:
- **Catch-up logic:** If your Mac was asleep during the scheduled time, the sync runs when it wakes up
- **macOS notification:** Shows a notification when the sync completes
- Logs to `~/.local/share/garmin-sync/logs/`

## Windows (Task Scheduler)

Creates two tasks via `schtasks.exe`:
- **GarminSync-Weekday** -- runs at 8:30 AM Monday-Friday
- **GarminSync-Weekend** -- runs at 10:00 AM Saturday-Sunday

Uses a batch wrapper script. The wrapper path is validated to prevent script injection.

## Linux (manual)

Add to your crontab (`crontab -e`):

```crontab
# Weekdays at 8:30 AM
30 8 * * 1-5 garmin-sync sync all --days 1 --detailed && garmin-sync analyze

# Weekends at 10:00 AM
0 10 * * 0,6 garmin-sync sync all --days 1 --detailed && garmin-sync analyze
```

## Troubleshooting

**Sync not running:**
- macOS: Check `launchctl list | grep garmin` and review logs with `schedule logs`
- Windows: Open Task Scheduler and check the GarminSync tasks

**Authentication errors in scheduled runs:**
- Garmin OAuth tokens expire periodically. Run `garmin-sync auth login` to refresh.

**Logs location:**
- macOS/Linux: `~/.local/share/garmin-sync/logs/`
- Windows: `%LOCALAPPDATA%\garmin-sync\logs\`
