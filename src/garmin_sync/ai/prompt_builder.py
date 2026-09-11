"""Build prompts for OpenAI analysis."""

import json
import logging
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore


def safe_user_string(s: Any) -> str:
    """Strip control chars and tag-breaking characters from third-party-supplied
    strings (HEVY workout titles, exercise names, etc.) before they are embedded
    in an LLM prompt. Defends against prompt injection from a compromised HEVY
    account, shared workout templates, or MITM on the HEVY API.
    """
    if not s:
        return ""
    return "".join(
        c for c in str(s)
        if c.isprintable() and c not in "\n\r<>"
    )


def process_template(
    template: str,
    timezone: str = "America/New_York",
    completed_today: str | None = None,
) -> str:
    """Process template string with runtime variable substitution.

    Supported variables:
    - {today_date} - Current date (YYYY-MM-DD)
    - {day_of_week} - Current day name (Monday, Tuesday, etc.)
    - {time_of_day} - morning/afternoon/evening based on current hour
    - {completed_today} - Activities completed today (passed in or "none")

    Args:
        template: String with optional {variable} placeholders
        timezone: Timezone for date/time calculations
        completed_today: Summary of today's completed activities

    Returns:
        Template with variables substituted
    """
    if not template or "{" not in template:
        return template

    try:
        now = datetime.now(ZoneInfo(timezone))
    except Exception:
        logger.debug("Invalid timezone %r, falling back to UTC", timezone)
        now = datetime.now(ZoneInfo("UTC"))

    # Determine time of day
    hour = now.hour
    if hour < 12:
        time_of_day = "morning"
    elif hour < 18:
        time_of_day = "afternoon"
    else:
        time_of_day = "evening"

    # Build substitution dict
    variables = {
        "today_date": now.strftime("%Y-%m-%d"),
        "day_of_week": now.strftime("%A"),
        "time_of_day": time_of_day,
        "completed_today": completed_today or "none",
    }

    # Substitute variables (use safe format to ignore unknown placeholders)
    result = template
    for key, value in variables.items():
        result = result.replace("{" + key + "}", value)

    return result


def build_analysis_prompt(
    baseline_30d: dict[str, Any],
    detailed_7d: dict[str, Any],
    current_date: date,
    user_schedule: str,
    user_context: str,
    yesterday_analysis: str | None = None,
    recent_verdicts: list[str] | None = None,
    timezone: str = "America/New_York",
    completed_today: str | None = None,
    strength_data: dict[str, Any] | None = None,
) -> str:
    """Build the analysis prompt for OpenAI.

    Args:
        baseline_30d: 30-day baseline summary metrics
        detailed_7d: Detailed 7-day data with daily breakdowns
        current_date: Current date for context
        user_schedule: User's typical weekly training schedule (supports template variables)
        user_context: Additional user context (supports template variables)
        yesterday_analysis: Yesterday's analysis text (truncated; for continuity)
        recent_verdicts: One-line "date: verdict" strings from prior reports,
            oldest first — lets the model spot its own repeated-caution loops
            without re-reading a week of its own prose
        timezone: Timezone for template variable processing
        completed_today: Summary of activities completed today for template
        strength_data: Optional HEVY strength training data

    Returns:
        Formatted prompt string for OpenAI
    """
    day_of_week = current_date.strftime("%A")
    formatted_date = current_date.strftime("%A, %B %d, %Y")

    # Process templates in user_schedule and user_context
    processed_schedule = process_template(user_schedule, timezone, completed_today)
    processed_context = process_template(user_context, timezone, completed_today)

    prompt_parts = [
        "## Current Date",
        formatted_date,
        "",
    ]

    if processed_schedule.strip():
        prompt_parts.extend([
            "## My Typical Weekly Schedule",
            processed_schedule.strip(),
            "",
        ])

    if processed_context.strip():
        prompt_parts.extend([
            "## Additional Context",
            processed_context.strip(),
            "",
        ])

    if recent_verdicts:
        prompt_parts.extend([
            "## Recent Daily Verdicts",
            "One line per prior day, oldest first:",
        ])
        prompt_parts.extend(f"- {v}" for v in recent_verdicts)
        prompt_parts.append("")

    if yesterday_analysis:
        if len(yesterday_analysis) > 3000:
            yesterday_analysis = yesterday_analysis[:3000] + "\n...[truncated]"
        prompt_parts.extend([
            "## Yesterday's Analysis",
            "For continuity of reasoning — do not simply repeat it:",
            "",
            yesterday_analysis,
            "",
        ])

    # Deliberately short: one line per metric family. Interpretation nuance
    # (citations, methodology caveats) lives in code and docs, not in every
    # API call — a hedging-heavy dictionary makes the coach output mushy.
    prompt_parts.extend([
        "## Data Dictionary",
        "- **HRV**: ms. `delta_pct` = 7-day rolling mean vs 28-day baseline; treat a drop as real only beyond `meaningful_change` (the athlete's own normal variability). Garmin's status (BALANCED/LOW/HIGH/UNBALANCED) is an independent label.",
        "- **Resting HR**: vs 28-day baseline; +3-5 bpm sustained suggests fatigue or illness.",
        "- **Training Load**: cardio = Garmin EPOC-based; strength = sRPE-based estimate. The combined total is approximate — read the cardio/strength breakdown.",
        "- **AC Ratio**: 7-day load vs prior-3-week weekly average. Descriptive ramp rate only (not an injury predictor): <0.8 reduced, 0.8-1.3 steady, 1.3-1.5 building, >1.5 rapid increase.",
        "- **Body Battery**: 0-100, completed days only (today excluded). Overnight recovery and morning high are the key reads.",
        "- **Sleep Score**: 0-100 composite; deep 15-20% and REM 20-25% are the ideal bands.",
        "- **Training Readiness**: Garmin's own 0-100 composite; its weakest component is what to prioritize.",
        "- **HR Drift**: >5% on a steady run suggests aerobic fatigue.",
        "- **Strength**: volume in lbs; weekly sets shown as actual/target per muscle group; RPE 1-10 self-reported (rising RPE at flat volume = overreaching sign); est. 1RM via Epley.",
        "- **Cardio performance**: cadence (spm), VO2 max trend (±1.0 is meaningful), elevation vert/hour — background context, not daily decision drivers.",
        "- **Watch items**: sleep SpO2 <94% avg or a rising sleep respiration trend can signal illness — mention only if present.",
        "",
        "## 30-Day Baseline Metrics",
        "```json",
        json.dumps(baseline_30d, indent=2),
        "```",
        "",
        "## Detailed Last 7 Days",
        "```json",
        json.dumps(detailed_7d, indent=2),
        "```",
        "",
    ])

    # Add strength training data if available
    kg_to_lbs = 2.20462
    if strength_data and strength_data.get("total_sessions", 0) > 0:
        total_volume_lbs = strength_data.get("total_volume_kg", 0) * kg_to_lbs
        prompt_parts.extend([
            "## Strength Training (HEVY Data - Last 7 Days)",
            f"Sessions: {strength_data.get('total_sessions', 0)}",
            f"Total Volume: {total_volume_lbs:,.0f} lbs",
            f"Total Sets: {strength_data.get('total_sets', 0)}",
            "",
        ])

        # Volume by muscle group with weekly set targets
        by_muscle = strength_data.get("by_muscle_group", {})
        if by_muscle:
            # Load targets for groups that may not be in the strength_data
            try:
                from garmin_sync.ai.config import load_config
                from garmin_sync.config import get_settings
                _settings = get_settings()
                _ai_cfg = load_config(_settings.ai_config_path, _settings.profile_path)
                _strength_cfg = _ai_cfg.strength
            except Exception:
                from garmin_sync.ai.config import StrengthConfig
                _strength_cfg = StrengthConfig()

            prompt_parts.append("Volume by muscle group (actual/target sets per week):")
            # Sort by descending volume, then include zero-actual groups at the end
            trained = {g: d for g, d in by_muscle.items() if d.get("volume_kg", 0) or d.get("sets", 0)}
            untrained = {g: d for g, d in by_muscle.items() if g not in trained}

            for group, data in sorted(trained.items(), key=lambda x: x[1].get("volume_kg", 0), reverse=True):
                volume_lbs = data.get("volume_kg", 0) * kg_to_lbs
                sets = data.get("sets", 0)
                target = _strength_cfg.get_target(group)
                prompt_parts.append(f"  - {group.title()}: {volume_lbs:,.0f} lbs ({sets}/{target} sets)")

            # Show untrained groups that have a target
            for group in sorted(untrained):
                target = _strength_cfg.get_target(group)
                if target > 0:
                    prompt_parts.append(f"  - {group.title()}: 0/{target} sets")

            prompt_parts.append("")

        # Recent workouts with exercise details
        recent = strength_data.get("recent_workouts", [])
        if recent:
            prompt_parts.append("Recent strength workouts:")
            for w in recent[:5]:
                date_str = w.get("date", "N/A")
                title = safe_user_string(w.get("title", "Workout"))
                volume_lbs = (w.get("volume_kg", 0) or 0) * kg_to_lbs
                duration = w.get("duration_minutes")
                duration_str = f", {duration} min" if duration else ""
                prompt_parts.append(
                    f"  - {date_str}: <hevy_title>{title}</hevy_title> "
                    f"({volume_lbs:,.0f} lbs{duration_str})"
                )

                # Add exercise details if available
                exercises = w.get("exercises", [])
                for ex in exercises:
                    name = safe_user_string(ex.get("name", "Unknown"))
                    muscle = safe_user_string(ex.get("muscle_group", ""))
                    sets = ex.get("sets", "")
                    muscle_str = f" ({muscle})" if muscle else ""
                    prompt_parts.append(
                        f"    * <hevy_exercise>{name}</hevy_exercise>{muscle_str}: {sets}"
                    )

            prompt_parts.append("")

    # Add anomaly alerts if present in the detailed data
    anomalies = detailed_7d.get("anomalies", [])
    if anomalies:
        prompt_parts.extend([
            "## Health & Training Alerts",
            "The following anomalies were detected from recent data:",
            "",
        ])
        for a in anomalies:
            severity = a.get("severity", "info").upper()
            message = a.get("message", "")
            prompt_parts.append(f"- **[{severity}]** {message}")
        prompt_parts.extend(["", "Factor these into your call.", ""])

    prompt_parts.extend([
        "## Instructions",
        f"Today is {day_of_week}. Write a concise coaching analysis with exactly three sections:",
        "",
        "1. **Today's call** — First line must be `Today: <specific recommendation>` (session type, duration, intensity). Then the 2-4 numbers that drove the call. If yesterday's recommendation was followed or ignored, note it in one sentence.",
        "2. **Why** — Brief recovery + load reasoning. Cite only decision-relevant numbers; do not tour every metric. Mention strength balance vs targets, PRs, or health alerts ONLY when the data shows something noteworthy.",
        "3. **Week ahead** — The next 2-3 days as concrete sessions (type, duration, intensity), plus the specific morning signal that would change the plan.",
        "",
        "Rules:",
        "- Be decisive. When signals conflict, make one call and say what would change your mind.",
        "- Check the recent verdicts: if you have advised easy/rest days 3+ days in a row, do NOT default to another vague easy day. Either prescribe a structured deload (concrete volumes and duration) or state the exact criteria for resuming normal training — and say plainly if illness should be considered.",
        "- Skip anything the data doesn't support; no filler sections. Keep the whole analysis under ~450 words.",
    ])

    return "\n".join(prompt_parts)


LONGITUDINAL_SYSTEM_MESSAGE = (
    "You are an expert endurance coach analyzing multi-year fitness data to "
    "answer one specific question: is the athlete improving, plateauing, or "
    "declining? Cite specific numbers from the data. Prefer year-over-year "
    "deltas over absolute values. Only call something a plateau when at least "
    "two independent signals agree (e.g. meters_per_beat AND resting HR). "
    "Treat strength 1RM data as decoration when it spans only one year. "
    "Be direct — if the data contradicts the user's intuition, say so."
)


def _format_aerobic(data: dict) -> list[str]:
    parts = ["## Aerobic Efficiency (running)"]
    periods = data.get("periods", [])
    if not periods:
        parts.append("- No running activities with HR data in range.")
        return parts
    parts.append("| Period | Runs | Total km | Avg pace (min/km) | Avg HR | m/heartbeat |")
    parts.append("|---|---|---|---|---|---|")
    for p in periods:
        parts.append(
            f"| {p['label']} | {p['run_count']} | {p['total_km']} | "
            f"{p.get('avg_pace_min_per_km')} | {p.get('avg_hr')} | "
            f"{p.get('meters_per_beat')} |"
        )
    return parts


def _format_health(data: dict) -> list[str]:
    parts = ["## Health Baselines (yearly)"]
    years = data.get("years", [])
    if not years:
        parts.append("- No health data in range.")
        return parts
    parts.append("| Year | Avg RHR | Avg HRV | Sleep (hrs) | Sleep CoV | Avg Stress | Days |")
    parts.append("|---|---|---|---|---|---|---|")
    for y in years:
        n = max(y.get("rhr_n_days", 0), y.get("hrv_n_days", 0), y.get("sleep_n_days", 0))
        parts.append(
            f"| {y['year']} | {y.get('avg_resting_hr')} | {y.get('avg_hrv')} | "
            f"{y.get('avg_sleep_hours')} | {y.get('sleep_cov')} | "
            f"{y.get('avg_stress')} | {n} |"
        )
    return parts


def _format_volume(data: dict) -> list[str]:
    parts = ["## Training Volume & Consistency"]
    periods = data.get("periods", [])
    if not periods:
        parts.append("- No activities in range.")
        return parts
    parts.append("| Period | Total hrs | Total km | Weekly-hours CoV | Active weeks | Top sports |")
    parts.append("|---|---|---|---|---|---|")
    for p in periods:
        by_type = p.get("by_type", {})
        top = sorted(
            ((t, info.get("hours", 0)) for t, info in by_type.items()),
            key=lambda x: -x[1],
        )[:3]
        top_str = ", ".join(f"{t} {h:.0f}h" for t, h in top)
        parts.append(
            f"| {p['label']} | {p['total_hours']} | {p['total_km']} | "
            f"{p.get('weekly_hours_cov')} | {p.get('weeks_with_activity')} | {top_str} |"
        )
    return parts


def _format_drift(data: dict) -> list[str]:
    parts = ["## HR Drift on Long Runs (45+ min)"]
    periods = data.get("periods", [])
    if not periods:
        parts.append("- No HR-drift data available (FIT files not parsed for historical activities).")
        return parts
    parts.append("| Year | Long runs | Avg drift % | Median drift % |")
    parts.append("|---|---|---|---|")
    for p in periods:
        parts.append(
            f"| {p['year']} | {p['n']} | {p['avg_drift_pct']} | {p['median_drift_pct']} |"
        )
    return parts


def _format_strength(strength_progressions: dict) -> list[str]:
    parts = ["## Strength (decoration — HEVY data only spans one year)"]
    if not strength_progressions:
        parts.append("- No HEVY data.")
        return parts
    for lift_name, prog in strength_progressions.items():
        current = prog.get("current_1rm")
        delta = prog.get("progression_pct")
        if current is None:
            continue
        delta_str = f", {delta:+.1f}% vs older sessions" if delta is not None else ""
        parts.append(
            f"- **{safe_user_string(lift_name)}**: est. 1RM {current} lbs"
            f"{delta_str} ({len(prog.get('sessions', []))} sessions)"
        )
    return parts


def build_longitudinal_prompt(
    longitudinal_data: dict[str, Any],
    current_date: date,
    user_context: str = "",
    granularity: str = "year",
) -> str:
    """Build the prompt for `garmin-sync analyze longitudinal`.

    longitudinal_data is the dict composed in `_run_longitudinal_analysis`,
    with keys: aerobic_efficiency, health_baselines, volume, hr_drift, strength.
    """
    parts: list[str] = [
        f"# Longitudinal Fitness Review — generated {current_date.isoformat()}",
        f"Granularity: {granularity}",
        "",
        "Below is multi-year data drawn from the user's local Garmin and HEVY syncs.",
        "Use only the numbers shown. Do not invent metrics not present.",
        "",
    ]

    if user_context:
        parts.append("## User Context")
        parts.append(user_context)
        parts.append("")

    parts.extend(_format_aerobic(longitudinal_data.get("aerobic_efficiency", {})))
    parts.append("")
    parts.extend(_format_health(longitudinal_data.get("health_baselines", {})))
    parts.append("")
    parts.extend(_format_volume(longitudinal_data.get("volume", {})))
    parts.append("")
    parts.extend(_format_drift(longitudinal_data.get("hr_drift", {})))
    parts.append("")
    parts.extend(_format_strength(longitudinal_data.get("strength", {})))
    parts.append("")

    parts.extend([
        "## Required Output Sections",
        "Produce a markdown report with these sections, in this order:",
        "",
        "1. **Headline Verdict** — one paragraph: improving / plateau / decline,",
        "   with the primary supporting evidence.",
        "2. **Aerobic Efficiency** — read pace + HR + meters/heartbeat by period.",
        "   This is the strongest plateau indicator: same HR + faster pace = improving.",
        "3. **Health Baselines** — RHR, HRV, sleep duration + consistency, by year.",
        "4. **Training Volume & Consistency** — volume table interpretation; note that",
        "   weekly-hours CoV closer to 0 means more consistent week-to-week.",
        "5. **HR Drift Trend** — long-run drift by year (skip if no data shown above).",
        "6. **Strength** — a single paragraph; HEVY only covers ~1 year so this is",
        "   decoration, not a primary signal.",
        "7. **Regime Shifts** — name 1-3 inflection points with approximate dates",
        "   (where a metric clearly changed direction).",
        "8. **What to Drill Into Next** — 3 targeted follow-up questions the user",
        "   could ask via `garmin-sync analyze chat`.",
        "",
        "Cite specific numbers in every section. If two signals disagree, say so.",
    ])

    return "\n".join(parts)


def generate_baseline_summary(
    weekly_json: dict[str, Any],
) -> dict[str, Any]:
    """Generate 30-day baseline summary from weekly JSON data.

    This extracts the key baseline metrics that provide context for the
    more detailed 7-day data.

    Args:
        weekly_json: The full weekly report JSON

    Returns:
        Condensed 30-day baseline summary
    """
    summary = weekly_json.get("summary", {})
    recovery = weekly_json.get("recovery", {})
    training_load = weekly_json.get("training_load", {})

    baseline = {
        "period": "30 days (where available)",
        "activities": {
            "total_count": summary.get("activities"),
            "duration_hours": summary.get("duration_hours"),
            "distance_km": summary.get("distance_km"),
        },
        "hrv": {
            "baseline_28d": recovery.get("hrv", {}).get("baseline_28d"),
            "baseline_7d": recovery.get("hrv", {}).get("baseline_7d"),
        },
        "resting_hr": {
            "baseline_28d": recovery.get("resting_hr", {}).get("baseline_28d"),
            "trend": recovery.get("resting_hr", {}).get("trend"),
        },
        "sleep": {
            "avg_hours": recovery.get("sleep", {}).get("avg_hours"),
            "avg_score": recovery.get("sleep", {}).get("avg_score"),
            "avg_deep_pct": recovery.get("sleep", {}).get("avg_deep_pct"),
            "avg_rem_pct": recovery.get("sleep", {}).get("avg_rem_pct"),
            "avg_respiration": recovery.get("sleep", {}).get("avg_respiration"),
            "avg_spo2": recovery.get("sleep", {}).get("avg_spo2"),
        },
        "body_battery": {
            "avg_overnight_recovery": recovery.get("body_battery", {}).get("avg_overnight_recovery"),
            "weekday_avg_recovery": recovery.get("body_battery", {}).get("weekday_avg_recovery"),
            "weekend_avg_recovery": recovery.get("body_battery", {}).get("weekend_avg_recovery"),
        },
        "training_load": {
            "chronic_28d_weekly_avg": training_load.get("chronic_28d"),
            "ac_ratio": training_load.get("ac_ratio"),
            "training_effect_balance": training_load.get("training_effect_balance"),
        },
    }

    # Add comparison data if present (weekly or monthly)
    comparison = weekly_json.get("comparison", {})
    if comparison:
        baseline["comparison"] = comparison

    return baseline


def generate_detailed_7d(
    weekly_json: dict[str, Any],
) -> dict[str, Any]:
    """Generate detailed 7-day data from weekly JSON.

    This includes daily breakdowns for HRV, sleep, training load, etc.

    Args:
        weekly_json: The full weekly report JSON

    Returns:
        Detailed 7-day data with daily values
    """
    recovery = weekly_json.get("recovery", {})
    training_load = weekly_json.get("training_load", {})
    activities = weekly_json.get("activities", {})

    cardio = weekly_json.get("cardio_performance", {})

    detailed = {
        "period": "last 7 days",
        "current_status": {
            "training_readiness": recovery.get("training_readiness", {}),
            "hrv_last_night": recovery.get("hrv", {}).get("last_night"),
            "hrv_delta_pct": recovery.get("hrv", {}).get("delta_pct"),
            "hrv_days_below_baseline": recovery.get("hrv", {}).get("days_below_baseline"),
            "hrv_status": recovery.get("hrv", {}).get("status"),
            "resting_hr_current": recovery.get("resting_hr", {}).get("current"),
            "resting_hr_delta": recovery.get("resting_hr", {}).get("delta"),
            "sleep_respiration": recovery.get("sleep", {}).get("avg_respiration"),
            "sleep_spo2": recovery.get("sleep", {}).get("avg_spo2"),
        },
        "training_load": {
            "acute_7d": training_load.get("acute_7d"),
            "this_week": training_load.get("this_week"),
            "prev_week": training_load.get("prev_week"),
            "change_pct": training_load.get("change_pct"),
            "avg_training_effect_aerobic": training_load.get("avg_training_effect_aerobic"),
            "avg_training_effect_anaerobic": training_load.get("avg_training_effect_anaerobic"),
            "training_effect_balance": training_load.get("training_effect_balance"),
            "by_activity_type": training_load.get("by_type", {}),
        },
        "body_battery": {
            "avg_morning_high": recovery.get("body_battery", {}).get("avg_morning_high"),
            "avg_evening_low": recovery.get("body_battery", {}).get("avg_evening_low"),
            "avg_overnight_recovery": recovery.get("body_battery", {}).get("avg_overnight_recovery"),
            "weekday_avg_recovery": recovery.get("body_battery", {}).get("weekday_avg_recovery"),
            "weekend_avg_recovery": recovery.get("body_battery", {}).get("weekend_avg_recovery"),
        },
        "cardio_performance": {
            "cadence_avg": cardio.get("cadence", {}).get("avg"),
            "vo2_max_current": cardio.get("vo2_max", {}).get("current"),
            "vo2_max_trend": cardio.get("vo2_max", {}).get("trend"),
            "elevation_gain_meters": cardio.get("elevation", {}).get("total_gain_meters"),
            "vert_per_hour": cardio.get("elevation", {}).get("vert_per_hour"),
        },
        "daily_hrv": recovery.get("hrv", {}).get("daily", []),
        "daily_sleep": recovery.get("sleep", {}).get("daily", []),
        "daily_rhr": recovery.get("resting_hr", {}).get("daily", []),
        "daily_body_battery": recovery.get("body_battery", {}).get("daily", []),
        "daily_training_load": training_load.get("daily", []),
        "top_activities": activities.get("top_sessions", []),
        "anomalies": weekly_json.get("anomalies", []),
    }

    # Add personal records if any were set this week
    prs = weekly_json.get("personal_records", {})
    cardio_prs = prs.get("cardio", [])
    strength_prs = prs.get("strength", [])
    if cardio_prs or strength_prs:
        detailed["personal_records"] = {
            "cardio": cardio_prs,
            "strength": strength_prs,
        }

    return detailed
