"""OpenAI tool definitions for fitness data access."""

# OpenAI function calling tool definitions
# These match the tools available in ToolExecutor
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_recent_activities",
            "description": "Get recent Garmin activities with metrics including duration, distance, heart rate, training load, HR drift, max speed (with best instantaneous pace for runs), and per-km pace splits (with pacing consistency CoV and negative-split detection). Use this to see what workouts have been done recently.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Days to look back (default: 7)",
                        "default": 7,
                    },
                    "activity_type": {
                        "type": "string",
                        "description": "Filter by activity type (e.g., 'running', 'cycling', 'swimming')",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of activities to return (default: 20)",
                        "default": 20,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recovery_status",
            "description": "Get current recovery metrics for training decisions. Returns HRV (baseline, delta, status), sleep quality (with all-day respiration rate and SpO2), body battery recovery, resting HR trend, training readiness score, and any detected health/training anomalies.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_training_load_analysis",
            "description": "Analyze the training-load trend. Returns acute (7-day) load, chronic baseline (prior 3 weeks, uncoupled), their ratio as a descriptive load-ramp signal (<0.8 reduced, 0.8-1.3 steady, 1.3-1.5 building, >1.5 rapid increase — not an injury predictor), week-over-week change, cardio/strength breakdown, and training-effect balance.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_strength_training_summary",
            "description": "Get HEVY strength training summary including total sessions, volume in pounds, sets by muscle group (actual/target), recent workouts with exercise details, RPE averages with overreaching detection, and HEVY-flagged personal records. Set include_sets=true for set-by-set detail (e.g. '135x10, 155x8') when asked exactly what was lifted. Requires HEVY integration to be configured.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Days to analyze (default: 7)",
                        "default": 7,
                    },
                    "include_sets": {
                        "type": "boolean",
                        "description": "Include per-workout set-by-set breakdown (default: false)",
                        "default": False,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_exercise_progression",
            "description": "Track strength progression for a specific exercise over time. Returns estimated 1RM history, max weights, progression percentage, and RPE trend alongside strength gains. Requires HEVY integration; returns empty if HEVY is not configured. Use this when asked about progress on specific lifts like bench press, squat, or deadlift.",
            "parameters": {
                "type": "object",
                "properties": {
                    "exercise_name": {
                        "type": "string",
                        "description": "Name of the exercise to track (e.g., 'Bench Press', 'Squat', 'Deadlift')",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Days to analyze (default: 90)",
                        "default": 90,
                    },
                },
                "required": ["exercise_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weekly_comparison",
            "description": "Compare this week vs last week across all fitness metrics including activities, duration, distance, calories, steps, sleep hours, and resting heart rate. Also includes month-to-date accumulated totals, previous month's completed totals, and personal records set this week.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_longitudinal_summary",
            "description": "Multi-year fitness review covering aerobic efficiency (pace + HR + meters/heartbeat), yearly health baselines (RHR, HRV, sleep, stress), training volume by sport with weekly-volume consistency, and HR drift trend. Requires multi-year synced data; returns sparse results if the database only has recent data. Use this when the user asks about long-term trends, plateaus, year-over-year change, or how their fitness has evolved.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_year": {
                        "type": "integer",
                        "description": "First year to include (default: earliest year present in the database).",
                    },
                    "end_year": {
                        "type": "integer",
                        "description": "Last year to include (default: current year).",
                    },
                    "granularity": {
                        "type": "string",
                        "enum": ["year", "quarter"],
                        "description": "Bucket size for aerobic efficiency and volume (default: year).",
                        "default": "year",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cardio_performance",
            "description": "Get cardio performance metrics: running cadence trends, VO2 max progression, elevation summary, and pacing consistency (CoV, negative-split percentage). Use when the user asks about running form, pacing, cadence, VO2 max, or elevation. Training-effect balance comes from get_training_load_analysis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Number of days to analyze (default: 28)",
                        "default": 28,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sync_garmin_data",
            "description": "Sync latest data from Garmin Connect (and HEVY if configured). Triggers activity, sleep, HR, HRV, stress, body battery, SpO2, and respiration sync. For detailed per-day data use the CLI with --detailed. Use this when the user mentions data seems stale or wants to see the most recent activities.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Days to sync (default: 1 for today only)",
                        "default": 1,
                    },
                },
                "required": [],
            },
        },
    },
]


def get_tool_names() -> list[str]:
    """Get list of available tool names."""
    return [t["function"]["name"] for t in TOOLS]
