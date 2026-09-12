# AI Chat & Analysis

garmin-sync includes an AI fitness coach powered by OpenAI that can query your data on-demand using tool calling.

## Interactive chat

```bash
garmin-sync analyze chat
```

The coach's system message carries reference data: your last 7 days of activities and HEVY workouts, plus the 2 most recent daily analyses. The 30 most recent chat messages carry over between sessions (`/clear` wipes them). When you ask about anything beyond that, it calls tools dynamically to fetch what it needs.

**Example questions:**
- "How has my bench press progressed over the last 3 months?"
- "What's my recovery status today?"
- "Compare my training this week vs last week"
- "Am I ready for a hard workout?"
- "How's my muscle group balance?"

### Chat commands

| Command | Action |
|---------|--------|
| `/quit` or `/exit` | Exit chat |
| `/clear` | Clear conversation history |
| `/context` | Show loaded context (analyses, tokens, tool status) |
| `/tools` | Toggle tool calling on/off |

### Model selection

When tool calling is enabled (`use_tools = true` in config), the chat uses `gpt-5.4` for its strong function calling support, regardless of the configured model. When tools are disabled, it uses whatever model you've configured (default: `o3-mini`).

## One-shot analysis

```bash
garmin-sync analyze
```

Runs a single daily analysis covering the last 7 days of data and saves the output to `reports/analysis-YYYY-MM-DD.md`. This is what the scheduled sync runs automatically.

The report has three sections — **Today's call** (opening with a one-line `Today: <recommendation>`), **Why**, and **Week ahead** — and stays under ~450 words. For continuity the prompt includes a one-line verdict list from the last 7 reports plus yesterday's full analysis (not a week of full reports, which made the coach anchor on its own prior caution). After 3+ consecutive easy/rest verdicts, the coach must prescribe a structured deload or name concrete criteria for resuming normal training instead of defaulting to another easy day.

## Longitudinal review

```bash
garmin-sync analyze longitudinal                    # Earliest year in DB to today
garmin-sync analyze longitudinal --start-year 2023  # Narrow the window
garmin-sync analyze longitudinal -g quarter         # Quarter buckets instead of yearly
```

Surfaces multi-year trends and asks the model to identify plateaus or regime shifts:
- Pace-at-HR (aerobic efficiency) by year or quarter
- RHR, HRV, and sleep baselines over time
- Weekly-volume consistency (coefficient of variation)
- HR drift trends for long runs

Output saved to `reports/longitudinal-YYYY-MM-DD.md`.

**Note:** Needs historical data in the database. Run `garmin-sync sync all --days 1825` (5 years) before expecting multi-year output.

## Anomaly detection

```bash
garmin-sync analyze anomalies
```

Scans for 9 health and training anomalies:
- HRV crash (7-day mean meaningfully below baseline, personalized to your own variability)
- RHR spike (>5 bpm above your 28-day baseline)
- Training overload (rapid load ramp, A:C > 1.5)
- Reduced load / detraining (A:C < 0.8 — informational, intentional if tapering)
- Strength overload (strength-specific A:C spike)
- Sleep degradation (3+ consecutive nights more than 1σ below your personal mean)
- Body battery depletion (morning start below 25 for 2+ days)
- Overreaching (RPE rising while volume is flat or falling)
- SpO2 concern (weekly sleep average below 92%)

Results are sorted by severity (critical, warning, info). This is the single
alert layer: the same anomalies are embedded in `get_recovery_status` tool
output and in the daily analysis prompt.

## Computed analytics

The following metrics are computed from your data and available through tools and reports:

| Category | Metrics |
|----------|---------|
| **Recovery** | HRV context (7d/28d baselines, delta), sleep consistency (bedtime variance, REM/deep %), body battery (overnight recovery, weekday/weekend), RHR trend, training readiness |
| **Training Load** | Combined cardio + strength load (EPOC + sRPE), acute (7d) vs chronic baseline, A:C ratio as a descriptive load-ramp label, cardio/strength breakdown, load by sport, training effect balance |
| **Cardio** | Running cadence trends, VO2 max progression, elevation summary, HR drift, max speed / best pace, pacing analysis (CoV, negative splits) |
| **Strength** | Volume by muscle group (actual/target sets), exercise progression (est. 1RM via Epley), RPE analysis, overreaching detection, PR surfacing |
| **Comparisons** | Weekly and monthly comparison, month-to-date, personal records |
| **Longitudinal** | Aerobic efficiency by period, yearly health baselines, volume trends, HR drift by year |
| **Respiratory** | Sleep respiration rate, SpO2 averages, all-day respiration/SpO2 |

### A:C ratio (load-ramp signal)

The acute:chronic ratio compares your last 7 days of load to the **prior 3-week
weekly average** (uncoupled — the recent week is excluded from the baseline to
avoid the well-known mathematical-coupling artifact). It is a **descriptive
load-ramp signal, not an injury predictor** — the ACWR injury "sweet spot" is
not supported by evidence ([Impellizzeri et al. 2020](https://pubmed.ncbi.nlm.nih.gov/32502973/)).

| Ratio | Load ramp |
|-------|-----------|
| < 0.8 | Reduced (tapering / rest) |
| 0.8 - 1.3 | Steady |
| 1.3 - 1.5 | Building |
| > 1.5 | Rapid increase — worth checking recovery |
