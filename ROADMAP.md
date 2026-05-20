# Roadmap

Future improvements for garmin-sync, organized by implementation effort. The database already stores significant data that isn't yet surfaced through aggregators or tools.

## Tier 1: Quick Wins ✅ Complete

All 7 Tier 1 features have been implemented. The data was already stored in the SQLite database; these features added 4 new aggregator methods, enriched 2 existing aggregators, added 1 new tool (`get_cardio_performance`), enriched 2 existing tools, and integrated everything into daily AI reports.

| Feature | Status | Implementation |
|---------|--------|----------------|
| **Cadence analysis** | ✅ | `get_cadence_analysis()` aggregator → `get_cardio_performance` tool |
| **VO2 max tracking** | ✅ | `get_vo2_max_trend()` aggregator → `get_cardio_performance` tool |
| **Sleep respiration trends** | ✅ | `get_sleep_respiration_trends()` aggregator → `get_recovery_status` tool + daily report alerts |
| **Elevation analysis** | ✅ | `get_elevation_summary()` aggregator → `get_cardio_performance` tool |
| **Training effect analysis** | ✅ | Enriched `get_training_load_trend()` → `get_training_load_analysis` tool + `get_cardio_performance` tool |
| **Training readiness breakdown** | ✅ | Enriched `get_recovery_status` tool with weakest component identification |
| **Body battery patterns** | ✅ | Enriched `get_body_battery_recovery()` with weekday/weekend split → `get_recovery_status` tool |

**Test coverage:** 34 new tests in `test_aggregators_tier1.py` + updated tool/MCP tests (487 total).

## Tier 2: New Aggregators & Tools ✅ Complete

Requires new code (aggregators, parsers, or cross-table queries) but no new external data sources.

5 of 7 features implemented. Pace splits and power zones deferred.

| Feature | Status | Description |
|---------|--------|-------------|
| **Pace splits from FIT files** | Deferred | Parse FIT lap/record messages for per-km splits, negative split detection, even pacing scores. |
| **Power zone analysis** | Deferred | Power zone distribution, FTP estimation, intensity factor tracking. |
| ✅ **RPE-adjusted strength analytics** | Done | `get_rpe_analysis()`, `get_exercise_rpe_trend()`. RPE-adjusted volume, overreaching detection (RPE rising while volume flat), per-exercise RPE trend. Enriches `get_strength_training_summary` and `get_exercise_progression` tools. |
| ✅ **Stress-recovery correlation** | Done | `get_stress_recovery_correlation()`. Cross-references stress_daily with next-day body battery and training load. High-stress-poor-recovery pattern detection. Enriches `get_recovery_status` tool. |
| ✅ **Sleep-performance correlation** | Done | `get_sleep_performance_correlation()`. Personal A-F grading (mean ± σ), next-day training load/HR drift/training effect by grade, HRV-performance link, auto-generated insight. Enriches `get_recovery_status` tool. |
| ✅ **Monthly/quarterly progress reports** | Done | `get_monthly_comparison()`, `get_monthly_best_activities()`. Month-over-month comparison, best activities by category. Enriches `generate_monthly_json()` and `get_weekly_comparison` (adds month-to-date context). |
| ✅ **Personal records tracking** | Done | Schema v5 migration (`personal_records` table). `detect_activity_prs()` for cardio (fastest 5K/10K/half, longest run, highest load). `get_strength_prs()` surfaces HEVY `is_pr` flags. PR detection wired into sync pipeline. PRs in weekly/monthly reports with celebration alerts. |

## Tier 3: New Data Sources & Advanced Features

Requires new external integrations, significant new parsing logic, or architectural changes.

| Feature | Effort | Description |
|---------|--------|-------------|
| **Personalized training zones** | High | Calculate HR, pace, and power zones from historical data (lactate threshold estimation, HR zone distribution). Would enhance all existing activity analysis. |
| **Recovery time forecasting** | High | Predict recovery timeline based on training load, sleep patterns, HRV trends, and body battery. Could integrate with training readiness for forward-looking recommendations. |
| **FIT file deep parsing** | High | Extract running dynamics (ground contact time, vertical oscillation), detailed HR variability during exercise, power curve analysis. Requires expanding `fit_parser.py` significantly. |
| **Weather correlation** | Medium | Cross-reference outdoor activity performance with historical weather data (temperature, humidity, altitude). Would explain pace/HR anomalies on hot or high-altitude days. |
| **Nutrition integration** | High | MyFitnessPal or Cronometer API for calorie/macro tracking. Correlate nutrition with performance, recovery, and body composition. |
| **Social/sharing features** | Medium | Export formatted weekly summaries or achievement cards for sharing. Generate training partner comparisons. |
| **Windows toast notifications** | Low | Native Windows notifications when scheduled sync completes (macOS already has `osascript` notifications). |
| **Linux systemd timer** | Low | Scheduler backend for Linux. Currently users set up crontab manually; a systemd timer would match the macOS/Windows experience. |

## Contributing

If you'd like to work on any of these features:

1. Check the [CLAUDE.md](CLAUDE.md) developer guide for architecture details and common patterns
2. Tier 1 items are the best starting point — they follow established patterns and need no new dependencies
3. Each new tool should include unit tests (see `tests/unit/test_ai_tools.py` and `tests/unit/test_mcp.py` for examples)
