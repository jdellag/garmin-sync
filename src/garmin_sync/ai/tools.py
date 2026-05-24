"""OpenAI tool definitions for fitness data access."""

# OpenAI function calling tool definitions
# These match the tools available in ToolExecutor
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_recent_activities",
            "description": "Get recent Garmin activities with metrics including duration, distance, heart rate, training load, HR drift, and per-km pace splits (with pacing consistency CoV and negative-split detection). Use this to see what workouts have been done recently.",
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
            "description": "Get current recovery metrics for training decisions. Returns HRV (baseline, delta, status), sleep quality (with all-day respiration rate and SpO2), body battery recovery, resting HR trend, training readiness score, stress-recovery correlation patterns, and sleep-performance correlation.",
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
            "description": "Analyze training load for injury prevention and periodization. Returns acute (7-day) and chronic (28-day) load, acute:chronic ratio with risk assessment (<0.8 detraining, 0.8-1.3 optimal, >1.5 high risk), and breakdown by activity type.",
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
            "description": "Get HEVY strength training summary including total sessions, volume in pounds, sets by muscle group, recent workouts with exercise details, RPE averages with overreaching detection, RPE-adjusted volume metrics, and HEVY-flagged personal records.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Days to analyze (default: 7)",
                        "default": 7,
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
            "description": "Track strength progression for a specific exercise over time. Returns estimated 1RM history, max weights, progression percentage, and RPE trend alongside strength gains. Use this when asked about progress on specific lifts like bench press, squat, or deadlift.",
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
            "name": "get_workout_details",
            "description": "Get detailed HEVY workout data with exercise names, muscle groups, and sets in compact format (e.g., '135x10, 155x8'). Use this to see exactly what exercises and weights were used.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Days to look back (default: 7)",
                        "default": 7,
                    },
                },
                "required": [],
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
            "description": "Multi-year fitness review covering aerobic efficiency (pace + HR + meters/heartbeat), yearly health baselines (RHR, HRV, sleep, stress), training volume by sport with weekly-volume consistency, and HR drift trend. Use this when the user asks about long-term trends, plateaus, year-over-year change, or how their fitness has evolved.",
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
            "description": "Get cardio performance metrics: running cadence trends, VO2 max progression, elevation summary, pacing consistency (CoV, negative-split percentage), and aerobic/anaerobic training effect balance. Use when the user asks about running form, pacing, cadence, VO2 max, elevation, or training effect.",
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
            "name": "get_anomaly_report",
            "description": "Scan recent health and training data for anomalies. Checks HRV crashes, RHR spikes, training overload/detraining, sleep degradation, body battery depletion, stress-recovery imbalance, overreaching, and SpO2 concerns. Returns anomalies sorted by severity (critical first).",
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
            "name": "get_periodization_status",
            "description": "Get current training phase (recovery/base/build/peak/overload), composite readiness score (0-100 with green/yellow/red signal from HRV, sleep, body battery, RHR, and A:C ratio), and deload recommendation. Use when the user asks about training phase, readiness to train, or whether they need a deload week.",
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
            "name": "sync_garmin_data",
            "description": "Sync latest data from Garmin Connect (and HEVY if configured). Use this when the user mentions data seems stale or wants to see the most recent activities.",
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
