# AI Chat & Analysis

garmin-sync includes an AI fitness coach powered by OpenAI that can query your data on-demand using tool calling.

## Interactive chat

```bash
garmin-sync analyze chat
```

The coach pre-loads your recent activities, HEVY workouts, and past analyses as context. When you ask about specific data, it calls tools dynamically to fetch what it needs.

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
- HRV crash (significant drop from baseline)
- RHR spike (elevated resting heart rate)
- Training overload (high acute:chronic ratio)
- Sleep degradation (declining quality or duration)
- Body battery depletion (poor overnight recovery)
- SpO2 drop (blood oxygen below threshold)
- Stress elevation (sustained high stress scores)
- Training monotony (low variation in training stimulus)
- Detraining risk (declining load without recovery purpose)

Results are sorted by severity (critical, warning, info).

## Periodization analysis

```bash
garmin-sync analyze periodization
```

Analyzes your current training phase:
- **Phase detection:** Recovery, maintenance, building, peaking, or overreaching
- **Readiness score:** 0-100 composite with traffic-light signal
- **Deload recommendation:** Whether a deload week is advised

## Computed analytics

The following metrics are computed from your data and available through tools and reports:

| Category | Metrics |
|----------|---------|
| **Recovery** | HRV context (7d/28d baselines, delta), sleep consistency (bedtime variance, REM/deep %), body battery (overnight recovery, weekday/weekend), RHR trend, training readiness |
| **Training Load** | Acute (7d) / chronic (28d) load, A:C ratio with risk assessment, load by sport, training effect balance |
| **Cardio** | Running cadence trends, VO2 max progression, elevation summary, HR drift, pacing analysis (CoV, negative splits) |
| **Strength** | Volume by muscle group (actual/target sets), exercise progression (est. 1RM via Epley), RPE analysis, overreaching detection, PR surfacing |
| **Correlations** | Stress-recovery patterns, sleep-performance grading (A-F scale with next-day impact) |
| **Comparisons** | Weekly and monthly comparison, month-to-date, personal records |
| **Longitudinal** | Aerobic efficiency by period, yearly health baselines, volume trends, HR drift by year |
| **Respiratory** | Sleep respiration rate, SpO2 averages, all-day respiration/SpO2 |

### A:C ratio risk assessment

| Ratio | Assessment |
|-------|------------|
| < 0.8 | Detraining |
| 0.8 - 1.3 | Optimal |
| 1.3 - 1.5 | Building |
| > 1.5 | High risk |
