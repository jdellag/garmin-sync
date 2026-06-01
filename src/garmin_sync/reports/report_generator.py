"""Report generation coordinator."""

import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional, Union

from garmin_sync.db.database import Database
from garmin_sync.reports.aggregators import DataAggregator
from garmin_sync.reports.llm_formatter import LLMReportFormatter


def _harden_perms(path: Path) -> None:
    """Best-effort: chmod the file to 0o600 and its parent dir to 0o700."""
    try:
        path.chmod(0o600)
        path.parent.chmod(0o700)
    except OSError as e:
        print(f"Warning: could not tighten permissions on {path}: {e}", file=sys.stderr)


class ReportGenerator:
    """Generates fitness reports from synced data."""

    def __init__(self, db: Database):
        self.db = db
        self.aggregator = DataAggregator(db)
        self.formatter = LLMReportFormatter(self.aggregator)

    def generate_weekly_report(
        self,
        end_date: Optional[date] = None,
        llm_mode: bool = False,
        include_comparison: bool = True,
        format: str = "markdown",
    ) -> Union[str, dict[str, Any]]:
        """Generate weekly summary report.

        Args:
            end_date: End date of week (defaults to today)
            llm_mode: Optimize for LLM context
            include_comparison: Include week-over-week comparison
            format: Output format ("markdown" or "json")

        Returns:
            Formatted markdown report or structured dictionary for JSON
        """
        if format == "json":
            return self.formatter.generate_weekly_json(end_date)

        return self.formatter.generate_weekly_report(
            end_date=end_date,
            include_comparison=include_comparison,
            llm_mode=llm_mode,
        )

    def generate_monthly_report(
        self,
        year: Optional[int] = None,
        month: Optional[int] = None,
        llm_mode: bool = False,
        format: str = "markdown",
    ) -> Union[str, dict[str, Any]]:
        """Generate monthly summary report.

        Args:
            year: Year (defaults to current year)
            month: Month (defaults to current month)
            llm_mode: Optimize for LLM context
            format: Output format ("markdown" or "json")

        Returns:
            Formatted markdown report or structured dictionary for JSON
        """
        today = date.today()
        # Use `is None` (not falsy) so an explicit 0 isn't silently treated as
        # "current" — then range-validate rather than producing a wrong month.
        year = today.year if year is None else year
        month = today.month if month is None else month
        if not 1 <= month <= 12:
            raise ValueError(f"Invalid month {month}; must be 1-12")
        if year < 1900:
            raise ValueError(f"Invalid year {year}")

        if format == "json":
            return self.formatter.generate_monthly_json(year, month)

        return self.formatter.generate_monthly_report(
            year=year,
            month=month,
            llm_mode=llm_mode,
        )

    def generate_today_stats(self) -> str:
        """Generate quick stats for today."""
        today = date.today()
        activities = self.aggregator.get_activity_summary(today, today)
        health = self.aggregator.get_health_summary(today, today)

        lines = [f"# Today: {today.strftime('%A, %B %d, %Y')}"]

        if activities.total_count > 0:
            lines.append(f"\n## Activities: {activities.total_count}")
            for act_type, stats in activities.by_type.items():
                duration_min = stats["duration_seconds"] / 60
                distance_km = stats["distance_meters"] / 1000
                lines.append(f"- {act_type.title()}: {duration_min:.0f}min, {distance_km:.1f}km")

        lines.append("\n## Health")
        if health.total_steps:
            goal_pct = health.step_goal_pct or 0
            lines.append(f"- Steps: {health.total_steps:,} ({goal_pct:.0f}% of goal)")

        if health.avg_resting_hr:
            lines.append(f"- Resting HR: {health.avg_resting_hr} bpm")

        if health.avg_sleep_hours:
            score = f", score {health.avg_sleep_score}/100" if health.avg_sleep_score else ""
            lines.append(f"- Last night sleep: {health.avg_sleep_hours:.1f}h{score}")

        if health.avg_stress:
            lines.append(f"- Stress level: {health.avg_stress}")

        return "\n".join(lines)

    def generate_week_stats(self) -> str:
        """Generate quick stats for current week."""
        today = date.today()
        # Start of week (Monday)
        start_of_week = today - timedelta(days=today.weekday())

        return self.formatter.generate_weekly_report(
            end_date=today,
            include_comparison=True,
            llm_mode=True,
        )

    def save_report(self, content: str, output_path: Path) -> None:
        """Save report to file.

        Args:
            content: Report content
            output_path: Path to save file
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content)
        _harden_perms(output_path)

    def export_activities_json(
        self,
        start_date: date,
        end_date: date,
        output_path: Path,
    ) -> int:
        """Export activities to JSON file.

        Returns:
            Number of activities exported
        """
        import json

        cursor = self.db.connection.cursor()
        cursor.execute(
            """
            SELECT * FROM activities
            WHERE date(start_time) >= ? AND date(start_time) <= ?
            ORDER BY start_time DESC
            """,
            (start_date.isoformat(), end_date.isoformat())
        )

        activities = [dict(row) for row in cursor.fetchall()]

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(activities, f, indent=2, default=str)
        _harden_perms(output_path)

        return len(activities)

    def export_activities_csv(
        self,
        start_date: date,
        end_date: date,
        output_path: Path,
    ) -> int:
        """Export activities to CSV file.

        Returns:
            Number of activities exported
        """
        import csv

        cursor = self.db.connection.cursor()
        cursor.execute(
            """
            SELECT
                activity_id, activity_name, activity_type,
                start_time, duration_seconds, distance_meters,
                average_hr, max_hr, calories,
                elevation_gain_meters, training_load
            FROM activities
            WHERE date(start_time) >= ? AND date(start_time) <= ?
            ORDER BY start_time DESC
            """,
            (start_date.isoformat(), end_date.isoformat())
        )

        rows = cursor.fetchall()
        if not rows:
            return 0

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            # Header
            writer.writerow([
                "activity_id", "name", "type", "start_time",
                "duration_sec", "distance_m", "avg_hr", "max_hr",
                "calories", "elevation_gain_m", "training_load"
            ])
            # Data
            for row in rows:
                writer.writerow(list(row))
        _harden_perms(output_path)

        return len(rows)

    def export_health_csv(
        self,
        start_date: date,
        end_date: date,
        output_path: Path,
    ) -> int:
        """Export health metrics to CSV file.

        Returns:
            Number of days exported
        """
        import csv

        cursor = self.db.connection.cursor()

        # Join all health tables
        cursor.execute(
            """
            SELECT
                ds.date,
                ds.total_steps,
                ds.total_calories,
                hr.resting_hr,
                sl.total_sleep_seconds,
                sl.sleep_score,
                st.avg_stress_level,
                hv.hrv_value,
                bb.max_level as bb_max,
                bb.min_level as bb_min
            FROM daily_summaries ds
            LEFT JOIN heart_rate_daily hr ON ds.date = hr.date
            LEFT JOIN sleep_daily sl ON ds.date = sl.date
            LEFT JOIN stress_daily st ON ds.date = st.date
            LEFT JOIN hrv_daily hv ON ds.date = hv.date
            LEFT JOIN body_battery_daily bb ON ds.date = bb.date
            WHERE ds.date >= ? AND ds.date <= ?
            ORDER BY ds.date DESC
            """,
            (start_date.isoformat(), end_date.isoformat())
        )

        rows = cursor.fetchall()
        if not rows:
            return 0

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "date", "steps", "calories", "resting_hr",
                "sleep_seconds", "sleep_score", "stress",
                "hrv", "body_battery_max", "body_battery_min"
            ])
            for row in rows:
                writer.writerow(list(row))
        _harden_perms(output_path)

        return len(rows)
