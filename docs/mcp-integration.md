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

All 9 tools are available in both MCP (Claude Desktop) and OpenAI chat. They share the same backend, so behavior is identical.

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_recent_activities` | Activities with duration, HR, training load, HR drift, cadence, VO2 max, max speed (best pace for runs) | `days` (default 7), `activity_type`, `limit` (default 20) |
| `get_recovery_status` | HRV, sleep, body battery, RHR, training readiness, anomalies | None |
| `get_training_load_analysis` | Acute vs chronic load with a descriptive load-ramp label (not injury risk), cardio/strength breakdown, training-effect balance | None |
| `get_cardio_performance` | Running cadence, VO2 max progression, elevation, pacing consistency | `days` (default 28) |
| `get_strength_training_summary` | HEVY sessions, volume, sets by muscle group (actual/target), RPE, PRs; set-by-set detail with `include_sets` | `days` (default 7), `include_sets` (default false) |
| `get_exercise_progression` | Estimated 1RM over time with RPE trend for a specific lift | `exercise_name` (required), `days` (default 90) |
| `get_weekly_comparison` | This week vs last week, month-to-date, personal records | None |
| `get_longitudinal_summary` | Multi-year aerobic efficiency, health baselines, volume, HR drift | `start_year`, `end_year`, `granularity` ("year" or "quarter") |
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
