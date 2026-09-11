# MCP Integration

The MCP (Model Context Protocol) server lets you use your fitness data directly in Claude Desktop conversations.

## Setup

```bash
# View setup instructions
garmin-sync mcp info

# Add to Claude Desktop
claude mcp add garmin-sync -- uv run --directory /path/to/garmin-sync python -m garmin_sync.mcp.server

# Or start the server directly
garmin-sync mcp serve
```

## Available tools

All 12 tools are available in both MCP (Claude Desktop) and OpenAI chat. They share the same backend, so behavior is identical.

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_recent_activities` | Activities with duration, HR, training load, HR drift, cadence, VO2 max, max speed (best pace for runs) | `days` (default 7), `activity_type`, `limit` (default 20) |
| `get_recovery_status` | HRV, sleep, body battery, RHR, training readiness, anomalies, stress-recovery, sleep-performance | None |
| `get_training_load_analysis` | Combined cardio+strength A:C ratio, cardio/strength load breakdown, risk assessment | None |
| `get_cardio_performance` | Running cadence, VO2 max progression, elevation, training effect, pacing | `days` (default 28) |
| `get_strength_training_summary` | HEVY volume by muscle group with weekly set targets (actual/target), RPE, PRs, per-workout STL | `days` (default 7) |
| `get_exercise_progression` | Estimated 1RM over time with RPE trend for a specific lift | `exercise_name` (required), `days` (default 90) |
| `get_workout_details` | Detailed workouts with sets (e.g., "135x10, 155x8") | `days` (default 7) |
| `get_weekly_comparison` | This week vs last week, month-to-date, personal records | None |
| `get_longitudinal_summary` | Multi-year aerobic efficiency, health baselines, volume, HR drift | `start_year`, `end_year`, `granularity` ("year" or "quarter") |
| `get_anomaly_report` | Health/training anomaly scan sorted by severity | None |
| `get_periodization_status` | Training phase, readiness score (0-100), deload recommendation | None |
| `sync_garmin_data` | Trigger a fresh sync from Garmin/HEVY | `days` (default 1) |

## Error handling

MCP tools return structured error responses when something goes wrong, with classification to help Claude provide useful guidance:

| Error Type | Meaning | Typical Cause |
|-----------|---------|---------------|
| `DATA_MISSING` | Requested data not found | No data synced yet, or no match for query |
| `SYNC_NEEDED` | Database issue | Database not initialized, run `sync all` |
| `AUTH_FAILED` | Authentication problem | Garmin tokens expired, API key invalid |
| `NETWORK_ERROR` | Connection failure | No internet, API timeout |
| `INTERNAL` | Unexpected error | Bug or unhandled edge case |

Each error includes a `suggestion` field with recommended user action.

## Example conversation

After setup, you can ask Claude Desktop questions like:

- "What's my recovery status?" -- calls `get_recovery_status`
- "How has my squat progressed?" -- calls `get_exercise_progression` with "squat"
- "Compare my training this week to last" -- calls `get_weekly_comparison`
- "Show me a multi-year fitness overview" -- calls `get_longitudinal_summary`
- "My data seems stale, can you refresh it?" -- calls `sync_garmin_data`
