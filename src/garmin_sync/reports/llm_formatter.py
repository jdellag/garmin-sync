"""LLM-friendly report formatting."""

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

from garmin_sync.reports.aggregators import (
    ActivitySummary,
    DataAggregator,
    HealthSummary,
    PeriodComparison,
)


def format_duration(seconds: float) -> str:
    """Format duration in human-readable format."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        mins = int(seconds / 60)
        return f"{mins}m"
    else:
        hours = int(seconds / 3600)
        mins = int((seconds % 3600) / 60)
        if mins > 0:
            return f"{hours}h {mins}m"
        return f"{hours}h"


def format_pace(meters: float, seconds: float) -> str:
    """Format pace in min/km."""
    if meters <= 0 or seconds <= 0:
        return "N/A"
    pace_seconds_per_km = seconds / (meters / 1000)
    mins = int(pace_seconds_per_km / 60)
    secs = int(pace_seconds_per_km % 60)
    return f"{mins}:{secs:02d}/km"


def format_change(value: Optional[float], higher_is_better: bool = True) -> str:
    """Format change percentage with arrow."""
    if value is None:
        return "—"

    if value > 0:
        arrow = "↑" if higher_is_better else "↓"
        return f"{arrow}{abs(value):.0f}%"
    elif value < 0:
        arrow = "↓" if higher_is_better else "↑"
        return f"{arrow}{abs(value):.0f}%"
    else:
        return "→0%"


class LLMReportFormatter:
    """Generates LLM-optimized reports for ChatGPT consumption."""

    def __init__(self, aggregator: DataAggregator):
        self.aggregator = aggregator

    def generate_weekly_report(
        self,
        end_date: Optional[date] = None,
        include_comparison: bool = True,
        llm_mode: bool = True,
    ) -> str:
        """Generate weekly summary report.

        Args:
            end_date: End date of the week (defaults to today)
            include_comparison: Include week-over-week comparison
            llm_mode: Optimize for LLM context (comprehensive data for thinking models)

        Returns:
            Formatted markdown report
        """
        if end_date is None:
            end_date = date.today()

        start_date = end_date - timedelta(days=6)

        # Get basic data
        activities = self.aggregator.get_activity_summary(start_date, end_date)
        health = self.aggregator.get_health_summary(start_date, end_date)
        top_activities = self.aggregator.get_top_activities(start_date, end_date, limit=5)

        comparison = None
        if include_comparison:
            comparison = self.aggregator.get_weekly_comparison(end_date)

        # Get enhanced context data for LLM mode
        hrv_context = None
        sleep_consistency = None
        training_load = None
        rhr_trend = None
        body_battery = None
        training_readiness = None

        if llm_mode:
            hrv_context = self.aggregator.get_hrv_context(end_date)
            sleep_consistency = self.aggregator.get_sleep_consistency(start_date, end_date)
            training_load = self.aggregator.get_training_load_trend(end_date)
            rhr_trend = self.aggregator.get_resting_hr_trend(end_date)
            body_battery = self.aggregator.get_body_battery_recovery(start_date, end_date)
            training_readiness = self.aggregator.get_training_readiness_latest(end_date)

        # Build report
        sections = []

        # Header
        sections.append(self._format_header(start_date, end_date))

        # Quick stats table
        if comparison:
            sections.append(self._format_comparison_table(comparison))
        else:
            sections.append(self._format_quick_stats(activities, health))

        # Activity breakdown
        if activities.by_type:
            sections.append(self._format_activity_breakdown(activities))

        # Top sessions
        if top_activities:
            sections.append(self._format_top_activities(top_activities))

        # Enhanced Recovery & Readiness section for LLM mode
        if llm_mode:
            sections.append(self._format_recovery_analysis(
                hrv_context=hrv_context,
                sleep_consistency=sleep_consistency,
                training_load=training_load,
                rhr_trend=rhr_trend,
                body_battery=body_battery,
                training_readiness=training_readiness,
            ))

            # Decision Context section
            sections.append(self._format_decision_context(
                hrv_context=hrv_context,
                sleep_consistency=sleep_consistency,
                training_load=training_load,
                rhr_trend=rhr_trend,
                training_readiness=training_readiness,
            ))
        else:
            # Compact health metrics for non-LLM mode
            sections.append(self._format_health_section(health, llm_mode=False))

        # Footer
        sections.append(self._format_footer(end_date))

        return "\n\n".join(sections)

    def generate_monthly_report(
        self,
        year: int,
        month: int,
        llm_mode: bool = True,
    ) -> str:
        """Generate monthly summary report."""
        from calendar import monthrange

        _, last_day = monthrange(year, month)
        start_date = date(year, month, 1)
        end_date = date(year, month, last_day)

        activities = self.aggregator.get_activity_summary(start_date, end_date)
        health = self.aggregator.get_health_summary(start_date, end_date)
        top_activities = self.aggregator.get_top_activities(start_date, end_date, limit=5)

        sections = []

        # Header
        month_name = start_date.strftime("%B %Y")
        sections.append(f"# Monthly Fitness Summary: {month_name}")

        # Quick stats
        sections.append(self._format_quick_stats(activities, health))

        # Activity breakdown
        if activities.by_type:
            sections.append(self._format_activity_breakdown(activities))

        # Health metrics
        sections.append(self._format_health_section(health, llm_mode))

        # Top sessions
        if top_activities:
            sections.append(self._format_top_activities(top_activities, title="Top 5 Sessions"))

        # Footer
        sections.append(self._format_footer(end_date))

        return "\n\n".join(sections)

    def _format_header(self, start_date: date, end_date: date) -> str:
        """Format report header."""
        start_str = start_date.strftime("%b %d")
        end_str = end_date.strftime("%b %d, %Y")
        return f"# Weekly Fitness Summary: {start_str} - {end_str}"

    def _format_comparison_table(self, comparison: PeriodComparison) -> str:
        """Format week-over-week comparison table."""
        lines = [
            "## Quick Stats",
            "| Metric | This Week | Last Week | Change |",
            "|--------|-----------|-----------|--------|",
        ]

        metrics = [
            ("Activities", "activities", None, True),
            ("Duration", "duration_hours", "h", True),
            ("Distance", "distance_km", "km", True),
            ("Calories", "calories", None, True),
            ("Avg Steps", "avg_steps", None, True),
            ("Avg Sleep", "avg_sleep_hours", "h", True),
            ("Resting HR", "avg_resting_hr", "bpm", False),
        ]

        for label, key, unit, higher_better in metrics:
            curr = comparison.current.get(key)
            prev = comparison.previous.get(key)
            change = comparison.changes.get(key)

            if curr is None and prev is None:
                continue

            curr_str = self._format_value(curr, unit)
            prev_str = self._format_value(prev, unit)
            change_str = format_change(change, higher_better)

            lines.append(f"| {label} | {curr_str} | {prev_str} | {change_str} |")

        return "\n".join(lines)

    def _format_quick_stats(
        self,
        activities: ActivitySummary,
        health: HealthSummary,
    ) -> str:
        """Format quick stats section without comparison."""
        lines = [
            "## Quick Stats",
            f"- **Activities:** {activities.total_count}",
            f"- **Total Time:** {format_duration(activities.total_duration_seconds)}",
            f"- **Distance:** {activities.total_distance_km:.1f} km",
            f"- **Calories:** {activities.total_calories:,}",
        ]

        if health.avg_steps:
            lines.append(f"- **Avg Steps:** {health.avg_steps:,}/day")

        if health.avg_sleep_hours:
            lines.append(f"- **Avg Sleep:** {health.avg_sleep_hours:.1f}h/night")

        return "\n".join(lines)

    def _format_activity_breakdown(self, activities: ActivitySummary) -> str:
        """Format activity breakdown by type."""
        lines = ["## Activity Breakdown"]

        for activity_type, stats in activities.by_type.items():
            count = stats["count"]
            duration = format_duration(stats["duration_seconds"])
            distance_km = stats["distance_meters"] / 1000

            if distance_km > 0.1:
                # Calculate pace for running/cycling
                if stats["duration_seconds"] > 0:
                    speed_kmh = distance_km / (stats["duration_seconds"] / 3600)
                    if activity_type == "running":
                        pace = format_pace(stats["distance_meters"], stats["duration_seconds"])
                        lines.append(f"- **{activity_type.title()}:** {count}x, {distance_km:.1f}km, {duration}, avg {pace}")
                    else:
                        lines.append(f"- **{activity_type.title()}:** {count}x, {distance_km:.1f}km, {duration}, avg {speed_kmh:.1f}km/h")
                else:
                    lines.append(f"- **{activity_type.title()}:** {count}x, {distance_km:.1f}km, {duration}")
            else:
                lines.append(f"- **{activity_type.title()}:** {count}x, {duration}")

        return "\n".join(lines)

    def _format_health_section(self, health: HealthSummary, llm_mode: bool) -> str:
        """Format health metrics section."""
        lines = ["## Health Metrics"]

        parts = []

        if health.avg_resting_hr:
            parts.append(f"Resting HR: {health.avg_resting_hr} bpm")

        if health.avg_hrv:
            parts.append(f"HRV: {health.avg_hrv:.0f}ms")

        if health.avg_sleep_hours and health.avg_sleep_score:
            parts.append(f"Sleep: {health.avg_sleep_hours:.1f}h/night, score {health.avg_sleep_score}/100")
        elif health.avg_sleep_hours:
            parts.append(f"Sleep: {health.avg_sleep_hours:.1f}h/night")

        if health.avg_stress:
            stress_level = "LOW" if health.avg_stress < 30 else "MODERATE" if health.avg_stress < 50 else "HIGH"
            parts.append(f"Stress: {health.avg_stress} ({stress_level})")

        if health.avg_morning_bb and health.avg_evening_bb:
            parts.append(f"Body Battery: {health.avg_morning_bb}→{health.avg_evening_bb}")

        if not parts:
            lines.append("*No health metrics available.*")
        elif llm_mode:
            # Compact format for LLM
            lines.append("- " + " | ".join(parts))
        else:
            # Expanded format
            for part in parts:
                lines.append(f"- {part}")

        return "\n".join(lines)

    def _format_top_activities(
        self,
        activities: list[dict],
        title: str = "Notable Sessions",
    ) -> str:
        """Format top activities section."""
        lines = [f"## {title}"]

        for i, activity in enumerate(activities, 1):
            name = activity.get("activity_name") or activity.get("activity_type", "Activity")
            duration = format_duration(activity.get("duration_seconds") or 0)
            distance_m = activity.get("distance_meters") or 0

            parts = [name]
            if distance_m > 100:
                parts.append(f"{distance_m/1000:.1f}km")
            parts.append(duration)

            if activity.get("average_hr"):
                parts.append(f"avg HR {activity['average_hr']}")

            # Include HR drift if available
            hr_drift = activity.get("hr_drift")
            if hr_drift is not None:
                drift_pct = hr_drift * 100
                parts.append(f"HR drift {drift_pct:+.1f}%")

            lines.append(f"{i}. {', '.join(parts)}")

        return "\n".join(lines)

    def _format_footer(self, end_date: date) -> str:
        """Format report footer."""
        return f"---\n*Data from Garmin Connect. Generated {end_date.isoformat()}.*"

    def _format_value(self, value, unit: Optional[str] = None) -> str:
        """Format a value with optional unit."""
        if value is None:
            return "—"

        if isinstance(value, float):
            formatted = f"{value:.1f}"
        else:
            formatted = f"{value:,}" if isinstance(value, int) and value >= 1000 else str(value)

        if unit:
            return f"{formatted}{unit}"
        return formatted

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count (rough approximation)."""
        # Roughly 4 characters per token for English text
        return len(text) // 4

    def _format_recovery_analysis(
        self,
        hrv_context: Optional[dict],
        sleep_consistency: Optional[dict],
        training_load: Optional[dict],
        rhr_trend: Optional[dict],
        body_battery: Optional[dict],
        training_readiness: Optional[dict],
    ) -> str:
        """Format comprehensive Recovery & Readiness Analysis section."""
        sections = ["## Recovery & Readiness Analysis"]

        # HRV Status
        sections.append(self._format_hrv_section(hrv_context))

        # Sleep Analysis
        sections.append(self._format_sleep_analysis(sleep_consistency))

        # Training Load
        sections.append(self._format_training_load_section(training_load))

        # Resting Heart Rate Trend
        sections.append(self._format_rhr_section(rhr_trend))

        # Body Battery Recovery
        sections.append(self._format_body_battery_section(body_battery))

        # Training Readiness
        sections.append(self._format_training_readiness_section(training_readiness))

        return "\n\n".join(sections)

    def _format_hrv_section(self, hrv: Optional[dict]) -> str:
        """Format HRV status section."""
        lines = ["### HRV Status"]

        if not hrv or hrv.get("baseline_7d") is None:
            lines.append("*No HRV data available. Use `--detailed` sync for full data.*")
            return "\n".join(lines)

        # Summary table
        lines.extend([
            "| Metric | Value |",
            "|--------|-------|",
        ])

        lines.append(f"| Last Night | {self._fmt(hrv.get('last_night'))} ms |")
        lines.append(f"| 7-Day Baseline | {self._fmt(hrv.get('baseline_7d'))} ms |")
        lines.append(f"| 28-Day Baseline | {self._fmt(hrv.get('baseline_28d'))} ms |")

        delta = hrv.get("delta_from_baseline")
        if delta is not None:
            delta_str = f"{delta:+.1f}%" if delta != 0 else "0%"
            lines.append(f"| Delta from Baseline | {delta_str} |")

        lines.append(f"| Days Below Baseline | {hrv.get('days_below_baseline', 0)} consecutive |")
        lines.append(f"| Garmin Status | {hrv.get('status') or '—'} |")

        # Daily values table
        if hrv.get("daily_values"):
            lines.extend([
                "",
                "**Daily HRV (last 7 days):**",
                "| Date | HRV (ms) | vs Baseline |",
                "|------|----------|-------------|",
            ])
            for day in hrv["daily_values"]:
                delta_pct = day.get("delta_pct")
                delta_str = f"{delta_pct:+.1f}%" if delta_pct is not None else "—"
                lines.append(f"| {day['date']} | {self._fmt(day.get('hrv'))} | {delta_str} |")

        return "\n".join(lines)

    def _format_sleep_analysis(self, sleep: Optional[dict]) -> str:
        """Format sleep analysis section."""
        lines = ["### Sleep Analysis"]

        if not sleep or not sleep.get("daily_values"):
            lines.append("*No detailed sleep data available. Use `--detailed` sync for full data.*")
            return "\n".join(lines)

        # Summary metrics
        lines.extend([
            "| Metric | Value |",
            "|--------|-------|",
        ])

        if sleep.get("avg_deep_pct") is not None:
            lines.append(f"| Avg Deep Sleep | {sleep['avg_deep_pct']:.1f}% |")
        if sleep.get("avg_rem_pct") is not None:
            lines.append(f"| Avg REM Sleep | {sleep['avg_rem_pct']:.1f}% |")
        if sleep.get("avg_awake_mins") is not None:
            lines.append(f"| Avg Awake Time | {sleep['avg_awake_mins']:.0f} min |")
        if sleep.get("sleep_time_variance_mins") is not None:
            lines.append(f"| Bedtime Variance | ±{sleep['sleep_time_variance_mins']:.0f} min |")
        if sleep.get("wake_time_variance_mins") is not None:
            lines.append(f"| Wake Time Variance | ±{sleep['wake_time_variance_mins']:.0f} min |")

        # Daily values table
        if sleep.get("daily_values"):
            lines.extend([
                "",
                "**Daily Sleep (last 7 days):**",
                "| Date | Hours | Score | Deep % | REM % | Awake |",
                "|------|-------|-------|--------|-------|-------|",
            ])
            for day in sleep["daily_values"]:
                hours = f"{day.get('sleep_hours'):.1f}" if day.get('sleep_hours') else "—"
                score = self._fmt(day.get('sleep_score'))
                deep = f"{day.get('deep_pct'):.0f}%" if day.get('deep_pct') else "—"
                rem = f"{day.get('rem_pct'):.0f}%" if day.get('rem_pct') else "—"
                awake = f"{day.get('awake_mins'):.0f}m" if day.get('awake_mins') else "—"
                lines.append(f"| {day['date']} | {hours} | {score} | {deep} | {rem} | {awake} |")

        return "\n".join(lines)

    def _format_training_load_section(self, load: Optional[dict]) -> str:
        """Format training load section."""
        lines = ["### Training Load"]

        if not load or load.get("acute_load_7d") is None:
            lines.append("*No training load data available.*")
            return "\n".join(lines)

        # Summary table
        lines.extend([
            "| Metric | Value |",
            "|--------|-------|",
        ])

        lines.append(f"| This Week Total | {self._fmt(load.get('this_week_load'))} |")
        lines.append(f"| Last Week Total | {self._fmt(load.get('prev_week_load'))} |")

        change = load.get("week_change_pct")
        if change is not None:
            change_str = f"{change:+.1f}%"
            lines.append(f"| Week-over-Week Change | {change_str} |")

        lines.append(f"| Acute Load (7-day) | {self._fmt(load.get('acute_load_7d'))} |")
        lines.append(f"| Chronic Load (28-day avg/week) | {self._fmt(load.get('chronic_load_28d'))} |")

        ratio = load.get("acute_chronic_ratio")
        if ratio is not None:
            # Descriptive load-ramp label (acute 7d vs uncoupled prior-3-week
            # weekly avg). NOT an injury-risk zone — the ACWR "sweet spot" is
            # not evidence-supported (Impellizzeri 2020).
            if 0.8 <= ratio <= 1.3:
                ramp = "steady"
            elif ratio < 0.8:
                ramp = "reduced load"
            elif ratio <= 1.5:
                ramp = "building"
            else:
                ramp = "rapid increase — monitor recovery"
            lines.append(f"| Acute:Chronic Ratio | {ratio:.2f} ({ramp}) |")

        # Cardio vs strength breakdown — surfaces the HEVY strength
        # contribution.  Combined load is approximate (Garmin EPOC + sRPE);
        # shown only when there is actual strength load in the window.
        strength_7d = load.get("strength_load_7d")
        if strength_7d:
            cardio_7d = load.get("cardio_load_7d")
            pct = load.get("strength_pct_of_total")
            pct_str = f" — {pct:.0f}% strength" if pct is not None else ""
            lines.append(
                f"| Cardio / Strength (7-day) | "
                f"{self._fmt(cardio_7d)} / {self._fmt(strength_7d)}{pct_str} |"
            )

        # Load by activity type
        if load.get("by_type"):
            lines.extend([
                "",
                "**Load by Activity Type (7 days):**",
                "| Type | Load | % of Total | Count |",
                "|------|------|------------|-------|",
            ])
            for activity_type, data in sorted(load["by_type"].items(), key=lambda x: x[1]["load"], reverse=True):
                lines.append(
                    f"| {activity_type.title()} | {data['load']:.0f} | {data['pct_of_total']:.0f}% | {data['count']} |"
                )

        # Daily loads
        if load.get("daily_loads"):
            lines.extend([
                "",
                "**Daily Training Load:**",
                "| Date | Load | Activities |",
                "|------|------|------------|",
            ])
            for day in load["daily_loads"]:
                acts = [str(a) for a in (day.get("activities") or []) if a]
                activities_str = ", ".join(acts[:3])
                if len(acts) > 3:
                    activities_str += "..."
                lines.append(f"| {day['date']} | {day['load']:.0f} | {activities_str} |")

        return "\n".join(lines)

    def _format_rhr_section(self, rhr: Optional[dict]) -> str:
        """Format resting heart rate trend section."""
        lines = ["### Resting Heart Rate Trend"]

        if not rhr or rhr.get("current") is None:
            lines.append("*No RHR data available.*")
            return "\n".join(lines)

        # Summary
        lines.extend([
            "| Metric | Value |",
            "|--------|-------|",
        ])

        lines.append(f"| Current | {self._fmt(rhr.get('current'))} bpm |")
        lines.append(f"| 28-Day Baseline | {self._fmt(rhr.get('baseline_28d'))} bpm |")

        delta = rhr.get("delta")
        if delta is not None:
            delta_str = f"{delta:+d}" if delta != 0 else "0"
            lines.append(f"| Delta from Baseline | {delta_str} bpm |")

        if rhr.get("trend"):
            lines.append(f"| Trend Direction | {rhr['trend'].title()} |")

        # Daily values
        if rhr.get("daily_values"):
            lines.extend([
                "",
                "**Daily RHR (last 7 days):**",
                "| Date | RHR | Delta |",
                "|------|-----|-------|",
            ])
            for day in rhr["daily_values"]:
                delta = day.get("delta")
                delta_str = f"{delta:+d}" if delta is not None and delta != 0 else ("0" if delta == 0 else "—")
                lines.append(f"| {day['date']} | {self._fmt(day.get('rhr'))} | {delta_str} |")

        return "\n".join(lines)

    def _format_body_battery_section(self, bb: Optional[dict]) -> str:
        """Format body battery recovery section."""
        lines = ["### Body Battery Recovery"]

        if not bb or bb.get("avg_morning_high") is None:
            lines.append("*No Body Battery data available.*")
            return "\n".join(lines)

        lines.extend([
            "| Metric | Avg This Week |",
            "|--------|---------------|",
        ])

        lines.append(f"| Morning High | {self._fmt(bb.get('avg_morning_high'))} |")
        lines.append(f"| Evening Low | {self._fmt(bb.get('avg_evening_low'))} |")
        ovr = bb.get("avg_overnight_recovery")
        ovr_str = f"+{self._fmt(ovr)} points" if ovr is not None else self._fmt(ovr)
        lines.append(f"| Overnight Recovery | {ovr_str} |")

        # Daily values
        if bb.get("daily_values"):
            lines.extend([
                "",
                "**Daily Body Battery:**",
                "| Date | Morning | Evening | Recovery |",
                "|------|---------|---------|----------|",
            ])
            for day in bb["daily_values"]:
                recovery = day.get("overnight_recovery")
                recovery_str = f"+{recovery}" if recovery is not None else "—"
                lines.append(
                    f"| {day['date']} | {self._fmt(day.get('morning_high'))} | "
                    f"{self._fmt(day.get('evening_low'))} | {recovery_str} |"
                )

        return "\n".join(lines)

    def _format_training_readiness_section(self, readiness: Optional[dict]) -> str:
        """Format training readiness section."""
        lines = ["### Training Readiness (Today)"]

        if not readiness or readiness.get("score") is None:
            lines.append("*No Training Readiness data available.*")
            return "\n".join(lines)

        level = readiness.get("level") or "—"
        score = readiness.get("score")
        lines.extend([
            f"**Overall: {score}/100 ({level})**",
            "",
            "| Component | Score |",
            "|-----------|-------|",
        ])

        if readiness.get("sleep_score") is not None:
            lines.append(f"| Sleep | {readiness['sleep_score']} |")
        if readiness.get("recovery_score") is not None:
            lines.append(f"| Recovery | {readiness['recovery_score']} |")
        if readiness.get("hrv_score") is not None:
            lines.append(f"| HRV | {readiness['hrv_score']} |")
        if readiness.get("stress_history_score") is not None:
            lines.append(f"| Stress History | {readiness['stress_history_score']} |")
        if readiness.get("training_load_balance_score") is not None:
            lines.append(f"| Training Load Balance | {readiness['training_load_balance_score']} |")

        if readiness.get("feedback"):
            lines.append(f"\n*\"{readiness['feedback']}\"*")

        return "\n".join(lines)

    def _format_decision_context(
        self,
        hrv_context: Optional[dict],
        sleep_consistency: Optional[dict],
        training_load: Optional[dict],
        rhr_trend: Optional[dict],
        training_readiness: Optional[dict],
    ) -> str:
        """Format Decision Context section with key observations."""
        lines = ["## Decision Context"]
        lines.append("Key observations for training decisions:")
        observations = []

        # HRV observations
        if hrv_context and hrv_context.get("baseline_7d"):
            days_below = hrv_context.get("days_below_baseline", 0)
            delta = hrv_context.get("delta_from_baseline")
            status = hrv_context.get("status")

            if days_below >= 3:
                observations.append(f"- **HRV Alert:** {days_below} consecutive days below baseline - consider recovery focus")
            elif days_below > 0 and delta and delta < -10:
                observations.append(f"- **HRV Below Baseline:** {delta:+.0f}% from baseline ({days_below} days) - monitor")
            elif status == "UNBALANCED" or status == "LOW":
                observations.append(f"- **HRV Status:** {status} - recovery may be compromised")
            elif delta and delta > 5:
                observations.append(f"- **HRV Elevated:** {delta:+.0f}% above baseline - good recovery sign")
            else:
                observations.append("- **HRV:** Within normal range")

        # Sleep observations
        if sleep_consistency:
            variance = sleep_consistency.get("sleep_time_variance_mins")
            awake = sleep_consistency.get("avg_awake_mins")

            if variance and variance > 60:
                observations.append(f"- **Sleep Inconsistency:** ±{variance:.0f}min bedtime variance - affects recovery")
            elif variance and variance < 30:
                observations.append(f"- **Sleep Consistency:** Good (±{variance:.0f}min variance)")

            if awake and awake > 40:
                observations.append(f"- **Sleep Quality:** High wake time ({awake:.0f}min avg) - may indicate stress")

        # Training load observations
        if training_load:
            ratio = training_load.get("acute_chronic_ratio")
            change = training_load.get("week_change_pct")

            if ratio:
                if ratio > 1.5:
                    observations.append(f"- **Load Alert:** A:C ratio {ratio:.2f} - high injury risk, reduce intensity")
                elif ratio > 1.3:
                    observations.append(f"- **Load Elevated:** A:C ratio {ratio:.2f} - approaching threshold, monitor closely")
                elif ratio < 0.8:
                    observations.append(f"- **Load Low:** A:C ratio {ratio:.2f} - detraining risk, can increase load")
                else:
                    observations.append(f"- **Load Optimal:** A:C ratio {ratio:.2f} - within safe range (0.8-1.3)")

            if change and abs(change) > 20:
                direction = "increase" if change > 0 else "decrease"
                observations.append(f"- **Load Change:** {change:+.0f}% week-over-week {direction}")

        # RHR observations
        if rhr_trend:
            delta = rhr_trend.get("delta")
            trend = rhr_trend.get("trend")

            if delta and delta > 5:
                observations.append(f"- **RHR Elevated:** +{delta} bpm from baseline - possible fatigue/illness")
            elif trend == "rising" and delta and delta > 2:
                observations.append(f"- **RHR Rising:** {trend} trend (+{delta} from baseline)")
            elif trend == "falling":
                observations.append(f"- **RHR Improving:** {trend} trend - good adaptation sign")

        # Training readiness
        if training_readiness and training_readiness.get("score"):
            score = training_readiness["score"]
            level = training_readiness.get("level", "")

            if score < 50:
                observations.append(f"- **Readiness Low:** {score}/100 ({level}) - prioritize recovery")
            elif score >= 75:
                observations.append(f"- **Readiness Good:** {score}/100 ({level}) - ready for harder training")
            else:
                observations.append(f"- **Readiness Moderate:** {score}/100 ({level})")

        if observations:
            lines.extend(observations)
        else:
            lines.append("- Insufficient data to generate decision context. Sync more data with `--detailed` flag.")

        return "\n".join(lines)

    def generate_weekly_json(self, end_date: Optional[date] = None) -> dict[str, Any]:
        """Generate weekly report as structured JSON.

        Args:
            end_date: End date of the week (defaults to today)

        Returns:
            Structured dictionary for JSON serialization
        """
        if end_date is None:
            end_date = date.today()

        start_date = end_date - timedelta(days=6)

        # Get all data (same as markdown version)
        activities = self.aggregator.get_activity_summary(start_date, end_date)
        health = self.aggregator.get_health_summary(start_date, end_date)
        top_activities = self.aggregator.get_top_activities(start_date, end_date, limit=5)
        comparison = self.aggregator.get_weekly_comparison(end_date)

        # Get enhanced context data
        hrv_context = self.aggregator.get_hrv_context(end_date)
        sleep_consistency = self.aggregator.get_sleep_consistency(start_date, end_date)
        training_load = self.aggregator.get_training_load_trend(end_date)
        rhr_trend = self.aggregator.get_resting_hr_trend(end_date)
        body_battery = self.aggregator.get_body_battery_recovery(start_date, end_date)
        training_readiness = self.aggregator.get_training_readiness_latest(end_date)

        # Get Tier 1 cardio + respiration data
        respiration = self.aggregator.get_sleep_respiration_trends(start_date, end_date)
        cadence = self.aggregator.get_cadence_analysis(start_date, end_date)
        vo2 = self.aggregator.get_vo2_max_trend(start_date, end_date)
        elevation = self.aggregator.get_elevation_summary(start_date, end_date)

        # Get Tier 2 PR data
        strength_prs = self.aggregator.get_strength_prs(days=7)
        from garmin_sync.db.repository import Repository
        repo = Repository(self.aggregator.db)
        cardio_prs = repo.get_recent_prs(days=7)

        # Build structured JSON
        result: dict[str, Any] = {
            "meta": {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "period": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                },
                "report_type": "weekly",
            },
            "summary": self._build_summary_json(activities, health),
            "comparison": self._build_comparison_json(comparison),
            "activities": self._build_activities_json(activities, top_activities),
            "recovery": self._build_recovery_json(
                hrv_context=hrv_context,
                sleep_consistency=sleep_consistency,
                rhr_trend=rhr_trend,
                body_battery=body_battery,
                training_readiness=training_readiness,
                respiration=respiration,
            ),
            "training_load": self._build_training_load_json(training_load),
            "cardio_performance": self._build_cardio_json(
                cadence=cadence,
                vo2=vo2,
                elevation=elevation,
                training_load=training_load,
            ),
            "personal_records": {
                "cardio": cardio_prs,
                "strength": strength_prs,
            },
            "alerts": self._generate_alerts(
                hrv_context=hrv_context,
                sleep_consistency=sleep_consistency,
                training_load=training_load,
                rhr_trend=rhr_trend,
                training_readiness=training_readiness,
                respiration=respiration,
                prs=cardio_prs + strength_prs,
            ),
        }

        # Add structured anomaly detection
        try:
            from garmin_sync.reports.anomaly_detector import AnomalyDetector

            detector = AnomalyDetector(self.aggregator.db)
            anomalies = detector.detect_anomalies(end_date)
            if anomalies:
                result["anomalies"] = anomalies
        except Exception:
            logger.debug("Anomaly detection failed in generate_weekly_json", exc_info=True)
            result["anomaly_error"] = "Anomaly detection unavailable"

        return result

    def generate_monthly_json(
        self,
        year: int,
        month: int,
    ) -> dict[str, Any]:
        """Generate monthly report as structured JSON.

        Args:
            year: Year
            month: Month

        Returns:
            Structured dictionary for JSON serialization
        """
        from calendar import monthrange

        _, last_day = monthrange(year, month)
        start_date = date(year, month, 1)
        end_date = date(year, month, last_day)

        # Get data
        activities = self.aggregator.get_activity_summary(start_date, end_date)
        health = self.aggregator.get_health_summary(start_date, end_date)
        top_activities = self.aggregator.get_top_activities(start_date, end_date, limit=5)

        # Get enhanced context data
        hrv_context = self.aggregator.get_hrv_context(end_date)
        sleep_consistency = self.aggregator.get_sleep_consistency(start_date, end_date)
        training_load = self.aggregator.get_training_load_trend(end_date)
        rhr_trend = self.aggregator.get_resting_hr_trend(end_date)
        body_battery = self.aggregator.get_body_battery_recovery(start_date, end_date)
        training_readiness = self.aggregator.get_training_readiness_latest(end_date)

        # Get Tier 1 cardio + respiration data
        respiration = self.aggregator.get_sleep_respiration_trends(start_date, end_date)
        cadence = self.aggregator.get_cadence_analysis(start_date, end_date)
        vo2 = self.aggregator.get_vo2_max_trend(start_date, end_date)
        elevation = self.aggregator.get_elevation_summary(start_date, end_date)

        # Get Tier 2 monthly enrichments
        monthly_comparison = self.aggregator.get_monthly_comparison(year, month)
        best_activities = self.aggregator.get_monthly_best_activities(start_date, end_date)

        # Get Tier 2 PR data for the month
        days_in_range = (end_date - start_date).days + 1
        strength_prs = self.aggregator.get_strength_prs(days=days_in_range)
        from garmin_sync.db.repository import Repository
        repo = Repository(self.aggregator.db)
        cardio_prs = repo.get_recent_prs(days=days_in_range)

        result: dict[str, Any] = {
            "meta": {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "period": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                },
                "report_type": "monthly",
            },
            "summary": self._build_summary_json(activities, health),
            "activities": self._build_activities_json(activities, top_activities),
            "recovery": self._build_recovery_json(
                hrv_context=hrv_context,
                sleep_consistency=sleep_consistency,
                rhr_trend=rhr_trend,
                body_battery=body_battery,
                training_readiness=training_readiness,
                respiration=respiration,
            ),
            "training_load": self._build_training_load_json(training_load),
            "cardio_performance": self._build_cardio_json(
                cadence=cadence,
                vo2=vo2,
                elevation=elevation,
                training_load=training_load,
            ),
            "comparison": self._build_comparison_json(monthly_comparison),
            "best_activities": best_activities,
            "personal_records": {
                "cardio": cardio_prs,
                "strength": strength_prs,
            },
            "alerts": self._generate_alerts(
                hrv_context=hrv_context,
                sleep_consistency=sleep_consistency,
                training_load=training_load,
                rhr_trend=rhr_trend,
                training_readiness=training_readiness,
                respiration=respiration,
                prs=cardio_prs + strength_prs,
            ),
        }

        return result

    def _build_summary_json(
        self,
        activities: ActivitySummary,
        health: HealthSummary,
    ) -> dict[str, Any]:
        """Build summary section of JSON output."""
        return {
            "activities": activities.total_count,
            "duration_hours": round(activities.total_duration_hours, 1),
            "distance_km": round(activities.total_distance_km, 1),
            "calories": activities.total_calories,
            "avg_steps": health.avg_steps,
            "avg_sleep_hours": round(health.avg_sleep_hours, 1) if health.avg_sleep_hours else None,
        }

    def _build_comparison_json(self, comparison: PeriodComparison) -> dict[str, Any]:
        """Build comparison section of JSON output."""
        vs_last_week: dict[str, Any] = {}

        for key in comparison.current:
            curr = comparison.current.get(key)
            prev = comparison.previous.get(key)
            change = comparison.changes.get(key)

            vs_last_week[key] = {
                "current": round(curr, 1) if isinstance(curr, float) else curr,
                "previous": round(prev, 1) if isinstance(prev, float) else prev,
                "change_pct": change,
            }

        return {"vs_last_week": vs_last_week}

    def _build_activities_json(
        self,
        activities: ActivitySummary,
        top_activities: list[dict],
    ) -> dict[str, Any]:
        """Build activities section of JSON output."""
        by_type: dict[str, Any] = {}
        for activity_type, stats in activities.by_type.items():
            by_type[activity_type] = {
                "count": stats["count"],
                "duration_sec": int(stats["duration_seconds"]),
                "distance_m": int(stats["distance_meters"]),
                "avg_hr": stats.get("avg_hr"),
            }

        top_sessions = []
        for activity in top_activities:
            top_sessions.append({
                "name": activity.get("activity_name") or activity.get("activity_type", "Activity"),
                "type": activity.get("activity_type"),
                "duration_sec": activity.get("duration_seconds"),
                "distance_m": activity.get("distance_meters"),
                "avg_hr": activity.get("average_hr"),
                "training_load": activity.get("training_load"),
                "hr_drift": activity.get("hr_drift"),
            })

        return {
            "by_type": by_type,
            "top_sessions": top_sessions,
        }

    def _build_recovery_json(
        self,
        hrv_context: Optional[dict],
        sleep_consistency: Optional[dict],
        rhr_trend: Optional[dict],
        body_battery: Optional[dict],
        training_readiness: Optional[dict],
        respiration: Optional[dict] = None,
    ) -> dict[str, Any]:
        """Build recovery section of JSON output."""
        # HRV
        hrv_json: dict[str, Any] = {
            "last_night": None,
            "baseline_7d": None,
            "baseline_28d": None,
            "delta_pct": None,
            "days_below_baseline": 0,
            "status": None,
            "daily": [],
        }
        if hrv_context:
            hrv_json = {
                "last_night": hrv_context.get("last_night"),
                "baseline_7d": hrv_context.get("baseline_7d"),
                "baseline_28d": hrv_context.get("baseline_28d"),
                "delta_pct": hrv_context.get("delta_from_baseline"),
                "days_below_baseline": hrv_context.get("days_below_baseline", 0),
                "status": hrv_context.get("status"),
                "daily": [
                    {
                        "date": d["date"],
                        "value": d.get("hrv"),
                        "delta_pct": d.get("delta_pct"),
                    }
                    for d in hrv_context.get("daily_values", [])
                ],
            }

        # Resting HR
        rhr_json: dict[str, Any] = {
            "current": None,
            "baseline_28d": None,
            "delta": None,
            "trend": None,
            "daily": [],
        }
        if rhr_trend:
            rhr_json = {
                "current": rhr_trend.get("current"),
                "baseline_28d": rhr_trend.get("baseline_28d"),
                "delta": rhr_trend.get("delta"),
                "trend": rhr_trend.get("trend"),
                "daily": [
                    {
                        "date": d["date"],
                        "value": d.get("rhr"),
                        "delta": d.get("delta"),
                    }
                    for d in rhr_trend.get("daily_values", [])
                ],
            }

        # Sleep
        sleep_json: dict[str, Any] = {
            "avg_hours": None,
            "avg_score": None,
            "avg_deep_pct": None,
            "avg_rem_pct": None,
            "avg_awake_mins": None,
            "bedtime_variance_mins": None,
            "avg_respiration": None,
            "avg_spo2": None,
            "daily": [],
        }
        if sleep_consistency:
            sleep_json = {
                "avg_hours": None,  # Will be calculated if daily values exist
                "avg_score": None,
                "avg_deep_pct": sleep_consistency.get("avg_deep_pct"),
                "avg_rem_pct": sleep_consistency.get("avg_rem_pct"),
                "avg_awake_mins": sleep_consistency.get("avg_awake_mins"),
                "bedtime_variance_mins": sleep_consistency.get("sleep_time_variance_mins"),
                "avg_respiration": None,
                "avg_spo2": None,
                "daily": [],
            }
            # Calculate avg_hours and avg_score from daily values
            daily_values = sleep_consistency.get("daily_values", [])
            if daily_values:
                hours_list = [d.get("sleep_hours") for d in daily_values if d.get("sleep_hours")]
                scores_list = [d.get("sleep_score") for d in daily_values if d.get("sleep_score")]
                if hours_list:
                    sleep_json["avg_hours"] = round(sum(hours_list) / len(hours_list), 1)
                if scores_list:
                    sleep_json["avg_score"] = round(sum(scores_list) / len(scores_list))

                sleep_json["daily"] = [
                    {
                        "date": d["date"],
                        "hours": d.get("sleep_hours"),
                        "score": d.get("sleep_score"),
                        "deep_pct": d.get("deep_pct"),
                        "rem_pct": d.get("rem_pct"),
                        "awake_mins": d.get("awake_mins"),
                    }
                    for d in daily_values
                ]

        # Apply respiration/SpO2 data after sleep_consistency to avoid
        # overwrite when sleep_consistency rebuilds sleep_json.
        if respiration:
            sleep_json["avg_respiration"] = respiration.get("avg_respiration")
            sleep_json["avg_spo2"] = respiration.get("avg_spo2")

        # Body Battery
        bb_json: dict[str, Any] = {
            "avg_morning_high": None,
            "avg_evening_low": None,
            "avg_overnight_recovery": None,
            "weekday_avg_recovery": None,
            "weekend_avg_recovery": None,
            "daily": [],
        }
        if body_battery:
            bb_json = {
                "avg_morning_high": body_battery.get("avg_morning_high"),
                "avg_evening_low": body_battery.get("avg_evening_low"),
                "avg_overnight_recovery": body_battery.get("avg_overnight_recovery"),
                "weekday_avg_recovery": body_battery.get("weekday_avg_recovery"),
                "weekend_avg_recovery": body_battery.get("weekend_avg_recovery"),
                "daily": [
                    {
                        "date": d["date"],
                        "morning": d.get("morning_high"),
                        "evening": d.get("evening_low"),
                        "recovery": d.get("overnight_recovery"),
                    }
                    for d in body_battery.get("daily_values", [])
                ],
            }

        # Training Readiness
        readiness_json: dict[str, Any] = {
            "score": None,
            "level": None,
            "components": {},
            "weakest_component": None,
            "feedback": None,
        }
        if training_readiness:
            components = {
                "sleep": training_readiness.get("sleep_score"),
                "recovery": training_readiness.get("recovery_score"),
                "hrv": training_readiness.get("hrv_score"),
                "stress": training_readiness.get("stress_history_score"),
                "load_balance": training_readiness.get("training_load_balance_score"),
            }
            # Identify weakest component
            weakest = None
            lowest = None
            for key, val in components.items():
                if val is not None and (lowest is None or val < lowest):
                    lowest = val
                    weakest = key

            readiness_json = {
                "score": training_readiness.get("score"),
                "level": training_readiness.get("level"),
                "components": components,
                "weakest_component": weakest,
                "feedback": training_readiness.get("feedback"),
            }

        return {
            "hrv": hrv_json,
            "resting_hr": rhr_json,
            "sleep": sleep_json,
            "body_battery": bb_json,
            "training_readiness": readiness_json,
        }

    def _build_training_load_json(self, training_load: Optional[dict]) -> dict[str, Any]:
        """Build training load section of JSON output."""
        result: dict[str, Any] = {
            "acute_7d": None,
            "chronic_28d": None,
            "ac_ratio": None,
            "cardio_7d": None,
            "strength_7d": None,
            "strength_pct": None,
            "this_week": None,
            "prev_week": None,
            "change_pct": None,
            "avg_training_effect_aerobic": None,
            "avg_training_effect_anaerobic": None,
            "training_effect_balance": None,
            "by_type": {},
            "daily": [],
        }

        if not training_load:
            return result

        result["acute_7d"] = training_load.get("acute_load_7d")
        result["chronic_28d"] = training_load.get("chronic_load_28d")
        result["ac_ratio"] = training_load.get("acute_chronic_ratio")
        result["cardio_7d"] = training_load.get("cardio_load_7d")
        result["strength_7d"] = training_load.get("strength_load_7d")
        result["strength_pct"] = training_load.get("strength_pct_of_total")
        result["this_week"] = training_load.get("this_week_load")
        result["prev_week"] = training_load.get("prev_week_load")
        result["change_pct"] = training_load.get("week_change_pct")
        result["avg_training_effect_aerobic"] = training_load.get("avg_training_effect_aerobic")
        result["avg_training_effect_anaerobic"] = training_load.get("avg_training_effect_anaerobic")
        result["training_effect_balance"] = training_load.get("training_effect_balance")

        # By type
        by_type = training_load.get("by_type", {})
        for activity_type, data in by_type.items():
            result["by_type"][activity_type] = {
                "load": data.get("load"),
                "pct": data.get("pct_of_total"),
                "count": data.get("count"),
            }

        # Daily loads
        daily_loads = training_load.get("daily_loads", [])
        result["daily"] = [
            {
                "date": d["date"],
                "load": d.get("load"),
                "activities": d.get("activities", []),
            }
            for d in daily_loads
        ]

        return result

    def _build_cardio_json(
        self,
        cadence: Optional[dict],
        vo2: Optional[dict],
        elevation: Optional[dict],
        training_load: Optional[dict],
    ) -> dict[str, Any]:
        """Build cardio performance section of JSON output."""
        result: dict[str, Any] = {
            "cadence": {
                "avg": None,
                "max": None,
                "total_activities": 0,
                "weekly_trend": [],
                "by_type": {},
            },
            "vo2_max": {
                "current": None,
                "delta": None,
                "trend": None,
                "data_points": 0,
            },
            "elevation": {
                "total_gain_meters": None,
                "total_loss_meters": None,
                "total_activities": 0,
                "vert_per_hour": None,
                "by_type": {},
            },
            "training_effect": {
                "avg_aerobic": None,
                "avg_anaerobic": None,
                "balance": None,
            },
        }

        if cadence:
            result["cadence"] = {
                "avg": cadence.get("avg_cadence"),
                "max": cadence.get("max_cadence"),
                "total_activities": cadence.get("total_activities_with_cadence", 0),
                "weekly_trend": cadence.get("weekly_trend", []),
                "by_type": cadence.get("by_activity_type", {}),
            }

        if vo2:
            result["vo2_max"] = {
                "current": vo2.get("current"),
                "delta": vo2.get("delta"),
                "trend": vo2.get("trend"),
                "data_points": vo2.get("data_points", 0),
            }

        if elevation:
            result["elevation"] = {
                "total_gain_meters": elevation.get("total_gain_meters"),
                "total_loss_meters": elevation.get("total_loss_meters"),
                "total_activities": elevation.get("total_activities", 0),
                "vert_per_hour": elevation.get("vert_per_hour"),
                "by_type": elevation.get("by_activity_type", {}),
            }

        if training_load:
            result["training_effect"] = {
                "avg_aerobic": training_load.get("avg_training_effect_aerobic"),
                "avg_anaerobic": training_load.get("avg_training_effect_anaerobic"),
                "balance": training_load.get("training_effect_balance"),
            }

        return result

    def _generate_alerts(
        self,
        hrv_context: Optional[dict],
        sleep_consistency: Optional[dict],
        training_load: Optional[dict],
        rhr_trend: Optional[dict],
        training_readiness: Optional[dict],
        respiration: Optional[dict] = None,
        prs: Optional[list] = None,
    ) -> list[dict[str, str]]:
        """Generate alerts list from metrics.

        Returns:
            List of alert dicts with type, severity, and message
        """
        alerts: list[dict[str, str]] = []

        # HRV alerts
        if hrv_context and hrv_context.get("baseline_7d"):
            days_below = hrv_context.get("days_below_baseline", 0)
            delta = hrv_context.get("delta_from_baseline")
            status = hrv_context.get("status")

            if days_below >= 3:
                alerts.append({
                    "type": "hrv",
                    "severity": "warning",
                    "message": f"HRV {days_below} consecutive days below baseline - consider recovery focus",
                })
            elif days_below > 0 and delta is not None and delta < -10:
                alerts.append({
                    "type": "hrv",
                    "severity": "warning",
                    "message": f"HRV below baseline ({delta:+.0f}%) for {days_below} days - monitor",
                })
            elif status == "UNBALANCED" or status == "LOW":
                alerts.append({
                    "type": "hrv",
                    "severity": "warning",
                    "message": f"HRV status {status} - recovery may be compromised",
                })
            elif delta is not None and delta > 5:
                alerts.append({
                    "type": "hrv",
                    "severity": "info",
                    "message": f"HRV elevated {delta:+.0f}% above baseline - good recovery sign",
                })
            else:
                alerts.append({
                    "type": "hrv",
                    "severity": "info",
                    "message": "HRV within normal range",
                })

        # Training load alerts
        if training_load:
            ratio = training_load.get("acute_chronic_ratio")
            change = training_load.get("week_change_pct")

            if ratio:
                if ratio > 1.5:
                    alerts.append({
                        "type": "load",
                        "severity": "warning",
                        "message": f"A:C ratio {ratio:.2f} - high injury risk, reduce intensity",
                    })
                elif ratio > 1.3:
                    alerts.append({
                        "type": "load",
                        "severity": "warning",
                        "message": f"A:C ratio {ratio:.2f} - elevated, approaching threshold",
                    })
                elif ratio < 0.8:
                    alerts.append({
                        "type": "load",
                        "severity": "info",
                        "message": f"A:C ratio {ratio:.2f} - detraining risk, can increase load",
                    })
                else:
                    alerts.append({
                        "type": "load",
                        "severity": "info",
                        "message": f"A:C ratio {ratio:.2f} - optimal range (0.8-1.3)",
                    })

            if change is not None and abs(change) > 20:
                direction = "increase" if change > 0 else "decrease"
                alerts.append({
                    "type": "load",
                    "severity": "info",
                    "message": f"Training load {change:+.0f}% week-over-week {direction}",
                })

        # RHR alerts
        if rhr_trend:
            delta = rhr_trend.get("delta")
            trend = rhr_trend.get("trend")

            if delta is not None and delta > 5:
                alerts.append({
                    "type": "rhr",
                    "severity": "warning",
                    "message": f"RHR elevated +{delta} bpm from baseline - possible fatigue/illness",
                })
            elif trend == "rising" and delta is not None and delta > 2:
                alerts.append({
                    "type": "rhr",
                    "severity": "info",
                    "message": f"RHR rising trend (+{delta} from baseline)",
                })
            elif trend == "falling":
                alerts.append({
                    "type": "rhr",
                    "severity": "info",
                    "message": "RHR falling trend - good adaptation sign",
                })

        # Sleep alerts
        if sleep_consistency:
            variance = sleep_consistency.get("sleep_time_variance_mins")
            awake = sleep_consistency.get("avg_awake_mins")

            if variance is not None and variance > 60:
                alerts.append({
                    "type": "sleep",
                    "severity": "warning",
                    "message": f"Sleep timing inconsistent (±{variance:.0f}min variance) - affects recovery",
                })

            if awake is not None and awake > 40:
                alerts.append({
                    "type": "sleep",
                    "severity": "warning",
                    "message": f"High wake time during sleep ({awake:.0f}min avg) - may indicate stress",
                })

        # Training readiness alerts
        if training_readiness and training_readiness.get("score"):
            score = training_readiness["score"]
            level = training_readiness.get("level", "")

            if score < 50:
                # Identify weakest component for actionable advice
                component_map = {
                    "sleep_score": "sleep",
                    "recovery_score": "recovery",
                    "hrv_score": "HRV",
                    "stress_history_score": "stress",
                    "training_load_balance_score": "load balance",
                }
                weakest = None
                lowest = None
                for key in component_map:
                    val = training_readiness.get(key)
                    if val is not None and (lowest is None or val < lowest):
                        lowest = val
                        weakest = component_map[key]

                weak_msg = f" (weakest: {weakest})" if weakest else ""
                alerts.append({
                    "type": "readiness",
                    "severity": "warning",
                    "message": f"Training readiness low ({score}/100 - {level}){weak_msg} - prioritize recovery",
                })
            elif score >= 75:
                alerts.append({
                    "type": "readiness",
                    "severity": "info",
                    "message": f"Training readiness good ({score}/100 - {level}) - ready for harder training",
                })
            else:
                alerts.append({
                    "type": "readiness",
                    "severity": "info",
                    "message": f"Training readiness moderate ({score}/100 - {level})",
                })

        # Respiration / SpO2 alerts
        if respiration:
            avg_spo2 = respiration.get("avg_spo2")
            min_spo2 = respiration.get("min_spo2")
            resp_trend = respiration.get("respiration_trend")

            if min_spo2 is not None and min_spo2 < 90:
                alerts.append({
                    "type": "respiration",
                    "severity": "warning",
                    "message": f"SpO2 dropped to {min_spo2:.0f}% during sleep - worth monitoring",
                })
            elif avg_spo2 is not None and avg_spo2 < 94:
                alerts.append({
                    "type": "respiration",
                    "severity": "warning",
                    "message": f"Average sleep SpO2 low ({avg_spo2:.1f}%) - monitor for altitude or breathing issues",
                })

            if resp_trend == "rising":
                alerts.append({
                    "type": "respiration",
                    "severity": "info",
                    "message": "Sleep respiration rate rising trend - may indicate developing illness",
                })

        # Personal record celebration alerts
        if prs:
            pr_count = len(prs)
            if pr_count == 1:
                pr = prs[0]
                name = pr.get("exercise_name") or pr.get("metric_name", "")
                alerts.append({
                    "type": "pr",
                    "severity": "info",
                    "message": f"New personal record: {name}",
                })
            elif pr_count > 1:
                alerts.append({
                    "type": "pr",
                    "severity": "info",
                    "message": f"{pr_count} new personal records this period",
                })

        return alerts

    def _fmt(self, value) -> str:
        """Format a value, returning '—' for None."""
        if value is None:
            return "—"
        if isinstance(value, float):
            return f"{value:.1f}"
        return str(value)
