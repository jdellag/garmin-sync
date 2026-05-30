# HEVY Integration

garmin-sync integrates with the [HEVY](https://www.hevyapp.com/) app to track strength training data alongside your Garmin cardio metrics.

## Prerequisites

- **HEVY Pro subscription** (required for API access)
- **API key** from [hevy.com/settings?developer](https://hevy.com/settings?developer)

## Setup

```bash
garmin-sync hevy login
```

This stores your API key in `config.toml` (permissions `0o600`).

## Syncing workouts

```bash
garmin-sync hevy sync              # Sync recent workouts (default 30 days)
garmin-sync hevy status            # Show config and recent workouts
```

HEVY data is also synced automatically when you run `garmin-sync sync all`.

Synced data includes:
- Workouts with timestamps and duration
- Exercises with muscle group mapping
- Individual sets with weight, reps, and RPE
- Personal record flags

## Volume analysis

```bash
garmin-sync hevy volume            # Volume breakdown by muscle group
```

Shows total volume (lbs), set count, and session count per muscle group.

## Weekly set targets

The AI coach compares your actual training volume against science-backed weekly set targets per muscle group. Defaults are based on Renaissance Periodization and Schoenfeld (2017) guidelines for moderate general fitness.

In tool output and AI prompts, muscle groups show as actual/target:

```
- Chest: 4,200 lbs (9/10 sets)
- Upper Back: 1,800 lbs (4/8 sets)
- Glutes: 0/10 sets
```

Groups with 0 actual sets but a non-zero target are flagged, helping identify gaps in your training.

### Customizing targets

Override any muscle group in `profile.toml`:

```toml
[strength]
quadriceps = 16
upper_back = 14
calves = 8
```

See [Configuration](configuration.md) for the full default table.

## Exercise progression

The AI coach can track estimated 1RM progression for any exercise using the Epley formula. Ask in chat:

```
"How has my bench press progressed over the last 3 months?"
```

Or via MCP/tools: `get_exercise_progression(exercise_name="Bench Press", days=90)`

Returns session-by-session max weight, estimated 1RM, and overall progression percentage.

## RPE tracking

If you log RPE (Rate of Perceived Exertion) in HEVY:

- **Session RPE averages** are computed per workout
- **Overreaching detection** flags when RPE is consistently high alongside increasing volume
- **Per-exercise RPE trends** show effort progression alongside 1RM changes

## Personal records

HEVY flags personal records automatically. garmin-sync surfaces these in:

- `get_strength_training_summary` tool output
- `get_weekly_comparison` (PRs this week)
- AI analysis reports
