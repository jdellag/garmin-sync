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

The AI coach compares your actual training volume against science-backed weekly set targets per muscle group. Defaults are tuned for **hypertrophy** (MEV→low-MAV band per Renaissance Periodization and Schoenfeld et al. 2017 — most major muscles ~12–14 sets/week). Lower them in `profile.toml` if your goal is general fitness/maintenance.

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

## Strength Training Load (STL)

garmin-sync computes a Strength Training Load per HEVY workout using the sRPE method (session RPE x duration), the standard approach in exercise science for quantifying training stress across modalities (Foster et al., 2001).

**How it works:**
- When you log RPE in HEVY (50%+ of sets), the system uses your actual RPE data, volume-weighted by each set's weight x reps
- When RPE isn't logged, it estimates session intensity from workout characteristics (PR flags, set types, volume, exercise count)
- The computed STL is combined with Garmin's cardio training load (EPOC-based) for a unified A:C ratio, readiness score, and periodization analysis

**Checking your STL:**

Ask the AI coach: "What's my training load breakdown?" — it shows cardio vs. strength contributions. The weekly and monthly reports (`garmin-sync report weekly` / `monthly`) also include a "Cardio / Strength (7-day)" line and the split in their JSON output when strength load is present.

**Backfilling existing workouts:**

```bash
garmin-sync hevy recalc-stl           # Compute STL for workouts missing it
garmin-sync hevy recalc-stl --force   # Recompute all workouts
```

New workouts get STL computed automatically during sync.

**Important:** Combining Garmin's EPOC-based cardio load with sRPE-based strength load is scientifically approximate — the two metrics measure different physiological stresses but produce similar numerical ranges. The system always shows the cardio/strength breakdown alongside the combined total so you can see what's contributing.

**Improving accuracy:** Logging RPE in HEVY gives the system your actual perceived effort rather than heuristic estimates. Even logging RPE on a few key exercises per session helps.

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
