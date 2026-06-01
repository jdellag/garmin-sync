"""MCP server for garmin-sync fitness data."""

import functools
import logging
import sqlite3

from mcp.server.fastmcp import FastMCP

from garmin_sync.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)

mcp = FastMCP("garmin-sync")


# ---------------------------------------------------------------------------
# Structured error handling for MCP tools
# ---------------------------------------------------------------------------


def _classify_mcp_error(e: Exception) -> tuple[str, str]:
    """Map an exception to a (error_type, user_message) tuple.

    The error_type lets the LLM suggest corrective actions (e.g. "run
    sync_garmin_data" for SYNC_NEEDED).
    """
    msg = str(e).lower()
    if isinstance(e, ValueError):
        if "not configured" in msg or "not enabled" in msg:
            return "AUTH_FAILED", str(e)
        return "DATA_MISSING", str(e)
    if isinstance(e, sqlite3.OperationalError):
        return "SYNC_NEEDED", f"Database error: {e}. Try running sync_garmin_data first."
    # File/permission problems are OSErrors too, but they indicate a setup or
    # filesystem issue — not a network one — so classify them before the
    # network branch (otherwise the model is told to retry the connection).
    if isinstance(e, (FileNotFoundError, PermissionError, IsADirectoryError)):
        return "INTERNAL", f"File access error: {type(e).__name__}"
    if isinstance(e, (ConnectionError, TimeoutError, OSError)):
        return "NETWORK_ERROR", f"Connection failed: {type(e).__name__}"
    return "INTERNAL", f"Internal error: {type(e).__name__}"


def mcp_error_handler(func):
    """Wrap MCP tool functions with structured error responses."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_type, message = _classify_mcp_error(e)
            logger.warning("MCP tool %s failed: %s", func.__name__, e)
            return {
                "error": True,
                "error_type": error_type,
                "message": message,
                "tool": func.__name__,
            }

    return wrapper

# Lazy initialization
_db = None
_repo = None
_aggregator = None
_executor = None


def _get_repo():
    """Lazy-initialize repository."""
    global _db, _repo
    if _repo is None:
        from garmin_sync.config import get_settings
        from garmin_sync.db.database import Database
        from garmin_sync.db.repository import Repository

        settings = get_settings()
        settings.ensure_directories()
        _db = Database(settings.database_path)
        _db.initialize()
        _db.migrate()
        _repo = Repository(_db)
    return _repo


def _get_aggregator():
    """Lazy-initialize aggregator."""
    global _aggregator
    if _aggregator is None:
        from garmin_sync.reports.aggregators import DataAggregator

        _aggregator = DataAggregator(_get_repo().db)
    return _aggregator


def _get_executor() -> ToolExecutor:
    """Lazy-initialize tool executor."""
    global _executor
    if _executor is None:
        _executor = ToolExecutor(_get_repo(), _get_aggregator())
    return _executor


@mcp.tool()
@mcp_error_handler
def get_recent_activities(
    days: int = 7,
    activity_type: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Get recent Garmin activities with metrics.

    Args:
        days: Days to look back (default: 7)
        activity_type: Filter by type (running, cycling, swimming, etc.)
        limit: Max results (default: 20)

    Returns activities with: name, type, duration, distance, HR, training load, HR drift,
    and per-km pace splits (with pacing consistency and negative-split detection).
    """
    return _get_executor().get_recent_activities(
        days=days,
        activity_type=activity_type,
        limit=limit,
    )


@mcp.tool()
@mcp_error_handler
def get_recovery_status() -> dict:
    """Get current recovery metrics for training decisions.

    Returns HRV (baseline, delta, status), sleep (hours, score, all-day
    respiration rate and SpO2), body battery (recovery), resting HR
    (trend), training readiness, stress-recovery patterns, and
    sleep-performance correlation.
    """
    return _get_executor().get_recovery_status()


@mcp.tool()
@mcp_error_handler
def get_training_load_analysis() -> dict:
    """Analyze training load for injury prevention.

    Returns acute (7d) and chronic (28d) load, acute:chronic ratio,
    week-over-week change, breakdown by activity type, and risk assessment.

    A:C ratio thresholds: <0.8 detraining, 0.8-1.3 optimal, >1.5 high risk.
    """
    return _get_executor().get_training_load_analysis()


@mcp.tool()
@mcp_error_handler
def get_strength_training_summary(days: int = 7) -> dict:
    """Get HEVY strength training summary. Requires HEVY integration.

    Args:
        days: Days to analyze (default: 7)

    Returns sessions, total volume (lbs), sets by muscle group,
    recent workouts with exercise details, RPE averages with
    overreaching detection, RPE-adjusted volume, and personal records.
    """
    return _get_executor().get_strength_training_summary(days=days)


@mcp.tool()
@mcp_error_handler
def get_exercise_progression(exercise_name: str, days: int = 90) -> dict:
    """Track strength progression for a specific exercise. Requires HEVY integration; returns empty if not configured.

    Args:
        exercise_name: Exercise to track (e.g., "Bench Press", "Squat")
        days: Days to analyze (default: 90)

    Returns estimated 1RM, max weights, progression percentage,
    and RPE trend alongside strength gains.
    """
    return _get_executor().get_exercise_progression(
        exercise_name=exercise_name,
        days=days,
    )


@mcp.tool()
@mcp_error_handler
def get_workout_details(days: int = 7) -> list[dict]:
    """Get detailed HEVY workouts with exercise and set breakdown. Requires HEVY integration.

    Args:
        days: Days to look back (default: 7)

    Returns list of workouts with exercises and sets (e.g., "135x10, 155x8").
    """
    return _get_executor().get_workout_details(days=days)


@mcp.tool()
@mcp_error_handler
def get_weekly_comparison() -> dict:
    """Compare this week vs last week across all metrics.

    Returns current week, previous week, and percentage changes for:
    activities, duration, distance, calories, steps, sleep, resting HR.
    Also includes month-to-date totals, previous month's totals,
    and personal records set this week.
    """
    return _get_executor().get_weekly_comparison()


@mcp.tool()
@mcp_error_handler
def get_longitudinal_summary(
    start_year: int | None = None,
    end_year: int | None = None,
    granularity: str = "year",
) -> dict:
    """Multi-year fitness review: aerobic efficiency, health baselines, volume, HR drift.

    Requires multi-year synced data; returns sparse results if DB only has recent data.

    Args:
        start_year: First year to include (default: earliest year in DB).
        end_year: Last year (default: current year).
        granularity: 'year' or 'quarter'.

    Use this for long-term trend / plateau / year-over-year questions.
    """
    return _get_executor().get_longitudinal_summary(
        start_year=start_year,
        end_year=end_year,
        granularity=granularity,
    )


@mcp.tool()
@mcp_error_handler
def get_cardio_performance(days: int = 28) -> dict:
    """Get cardio performance metrics: running cadence trends, VO2 max
    progression, elevation summary, pacing consistency (CoV,
    negative-split percentage), and training effect balance.

    Args:
        days: Number of days to analyze (default: 28)

    Returns:
        Dict with cadence, vo2_max, elevation, pacing, and training_effect sections.
    """
    return _get_executor().get_cardio_performance(days=days)


@mcp.tool()
@mcp_error_handler
def get_anomaly_report() -> dict:
    """Scan recent health and training data for anomalies.

    Checks HRV crashes, RHR spikes, training overload/detraining, sleep
    degradation, body battery depletion, stress-recovery imbalance,
    overreaching, and SpO2 concerns.  Returns anomalies sorted by
    severity (critical first) with summary counts.
    """
    return _get_executor().get_anomaly_report()


@mcp.tool()
@mcp_error_handler
def get_periodization_status() -> dict:
    """Get current training phase, readiness score, and deload recommendation.

    Returns training phase (recovery / base / build / peak / overload),
    composite readiness score (0-100 with green/yellow/red signal from
    HRV, sleep, body battery, RHR, and A:C ratio), and whether a deload
    week is recommended.
    """
    return _get_executor().get_periodization_status()


@mcp.tool()
@mcp_error_handler
def sync_garmin_data(days: int = 1) -> dict:
    """Sync latest data from Garmin Connect (and HEVY if configured).

    Triggers activity, sleep, HR, HRV, stress, body battery, SpO2, and
    respiration sync. For detailed per-day data use the CLI with --detailed.

    Args:
        days: Days to sync (default: 1 for today only)

    Returns sync results for each data type.
    """
    return _get_executor().sync_garmin_data(days=days)


def main():
    """Entry point for MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
