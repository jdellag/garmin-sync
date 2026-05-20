"""Sync manager for orchestrating data synchronization."""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from garmin_sync.api.client import GarminClient, get_garmin_client
from garmin_sync.config import get_settings
from garmin_sync.sync.fit_parser import compute_hr_drift_from_fit

# Activity types where HR drift is meaningful
HR_DRIFT_ACTIVITY_TYPES = {"running", "treadmill_running", "elliptical"}

# Minimum duration in seconds for HR drift calculation (20 minutes)
HR_DRIFT_MIN_DURATION = 1200

# Re-fetch this many recent days even when a DB row already exists (Garmin
# can retroactively correct sleep scores, training readiness, etc.)
FRESHNESS_DAYS = 7

# Maps data_type argument → SQLite table name (used by _sync_daily_metric skip logic)
_DAILY_METRIC_TABLE = {
    "heart_rate": "heart_rate_daily",
    "sleep": "sleep_daily",
    "stress": "stress_daily",
    "hrv": "hrv_daily",
    "training_readiness": "training_readiness",
}
from garmin_sync.db.database import Database
from garmin_sync.db.models import (
    Activity,
    BodyBatteryDaily,
    DailySummary,
    HeartRateDaily,
    HRVDaily,
    SleepDaily,
    StressDaily,
    SyncMetadata,
    TrainingReadiness,
)
from garmin_sync.db.repository import Repository


class SyncResult:
    """Result of a sync operation."""

    def __init__(self, data_type: str):
        self.data_type = data_type
        self.records_synced = 0
        self.records_skipped = 0
        self.errors: list[str] = []
        self.success = True

    def add_error(self, error: str):
        self.errors.append(error)
        self.success = False

    def __repr__(self):
        return (
            f"SyncResult({self.data_type}: "
            f"synced={self.records_synced}, skipped={self.records_skipped}, "
            f"success={self.success})"
        )


class SyncManager:
    """Orchestrates data synchronization from Garmin Connect."""

    def __init__(
        self,
        db: Database,
        client: Optional[GarminClient] = None,
        console: Optional[Console] = None,
    ):
        """Initialize sync manager.

        Args:
            db: Database instance
            client: Garmin API client (creates default if None)
            console: Rich console for output (creates default if None)
        """
        self.db = db
        self.repo = Repository(db)
        self._client = client
        self.console = console or Console()
        self._pr_aggregator = None  # Lazy-init for PR detection

    @property
    def client(self) -> GarminClient:
        """Get or create Garmin client."""
        if self._client is None:
            self._client = get_garmin_client()
        return self._client

    def sync_all(
        self,
        days: int = 30,
        force: bool = False,
        detailed: bool = False,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> dict[str, SyncResult]:
        """Sync all data types.

        Args:
            days: Number of days to sync
            force: Force re-download of existing data
            detailed: Use per-day endpoints for full data (slower but more complete)
            progress_callback: Optional callback for progress updates

        Returns:
            Dict of data_type -> SyncResult
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        results = {}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
        ) as progress:
            # Sync activities
            task = progress.add_task("Syncing activities...", total=None)
            results["activities"] = self.sync_activities(start_date, end_date, force)
            progress.update(task, completed=True)

            # Sync health metrics - use detailed or batch methods
            if detailed:
                health_types = [
                    ("daily_summary", self.sync_daily_summaries),
                    ("sleep", self.sync_sleep_detailed),
                    ("heart_rate", self.sync_heart_rate),
                    ("stress", self.sync_stress_detailed),
                    ("hrv", self.sync_hrv_detailed),
                    ("body_battery", self.sync_body_battery),
                    ("training_readiness", self.sync_training_readiness),
                ]
            else:
                health_types = [
                    ("daily_summary", self.sync_daily_summaries),
                    ("sleep", self.sync_sleep),
                    ("heart_rate", self.sync_heart_rate),
                    ("stress", self.sync_stress),
                    ("hrv", self.sync_hrv),
                    ("body_battery", self.sync_body_battery),
                    ("training_readiness", self.sync_training_readiness),
                ]

            for data_type, sync_func in health_types:
                task = progress.add_task(f"Syncing {data_type}...", total=None)
                results[data_type] = sync_func(start_date, end_date, force)
                progress.update(task, completed=True)

        return results

    def sync_activities(
        self,
        start_date: date,
        end_date: date,
        force: bool = False,
    ) -> SyncResult:
        """Sync activities within date range.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            force: Force re-download of existing data

        Returns:
            SyncResult with sync statistics
        """
        result = SyncResult("activities")

        try:
            # Get existing activity IDs for deduplication
            existing_ids = set() if force else self.repo.get_activity_ids(
                since_date=start_date.isoformat()
            )

            # Fetch activities from API
            activities = self.client.get_activities_by_date(start_date, end_date)

            for activity_data in activities:
                activity_id = str(activity_data.get("activityId", ""))

                if not activity_id:
                    continue

                if activity_id in existing_ids and not force:
                    result.records_skipped += 1
                    continue

                try:
                    activity = Activity.from_api_response(activity_data)
                    activity.raw_json = json.dumps(activity_data)

                    # Compute HR drift for qualifying activities
                    should_compute_hr_drift = (
                        activity.average_hr
                        and activity.duration_seconds
                        and activity.duration_seconds >= HR_DRIFT_MIN_DURATION
                        and activity.activity_type in HR_DRIFT_ACTIVITY_TYPES
                    )

                    if should_compute_hr_drift:
                        hr_drift, fit_path = self._compute_hr_drift(activity.activity_id)
                        activity.hr_drift = hr_drift
                        if fit_path:
                            activity.has_fit_file = True
                            activity.fit_file_path = str(fit_path)

                    self.repo.upsert_activity(activity)
                    result.records_synced += 1

                    # Detect personal records for this activity
                    try:
                        if self._pr_aggregator is None:
                            from garmin_sync.reports.aggregators import DataAggregator
                            self._pr_aggregator = DataAggregator(self.db)
                        self._pr_aggregator.detect_activity_prs(activity.activity_id)
                    except Exception:
                        pass  # PR detection is non-critical
                except Exception as e:
                    result.add_error(f"Activity {activity_id}: {e}")

            # Update sync metadata
            self._update_sync_metadata("activities", result)

        except Exception as e:
            result.add_error(f"Failed to sync activities: {e}")

        return result

    def sync_daily_summaries(
        self,
        start_date: date,
        end_date: date,
        force: bool = False,
    ) -> SyncResult:
        """Sync daily summaries (steps, calories, etc.) using batch endpoint."""
        result = SyncResult("daily_summary")

        try:
            # Use batch endpoint for steps data - single API call
            step_data = self.client.get_daily_steps_batch(start_date, end_date)

            for item in step_data:
                try:
                    # Convert step data format to expected DailySummary format
                    summary_data = {
                        "calendarDate": item.get("calendarDate"),
                        "totalSteps": item.get("totalSteps"),
                        "stepGoal": item.get("stepGoal"),
                        "totalDistanceMeters": item.get("totalDistance"),
                        "totalKilocalories": item.get("totalCalories"),
                    }
                    model = DailySummary.from_api_response(summary_data)
                    model.raw_json = json.dumps(item)
                    self.repo.upsert_daily_summary(model)
                    result.records_synced += 1
                except Exception as e:
                    result.add_error(f"Daily summary {item.get('calendarDate', 'unknown')}: {e}")

            self._update_sync_metadata("daily_summary", result)

        except Exception as e:
            result.add_error(f"Failed to sync daily summaries: {e}")

        return result

    def sync_sleep(
        self,
        start_date: date,
        end_date: date,
        force: bool = False,
    ) -> SyncResult:
        """Sync sleep data using batch endpoint."""
        result = SyncResult("sleep")

        try:
            days = (end_date - start_date).days + 1
            sleep_data = self.client.get_daily_sleep_batch(end_date, days)

            for item in sleep_data:
                try:
                    model = SleepDaily.from_batch_response(item)
                    model.raw_json = json.dumps(item)
                    self.repo.upsert_sleep(model)
                    result.records_synced += 1
                except Exception as e:
                    result.add_error(f"Sleep {item.get('calendarDate', 'unknown')}: {e}")

            self._update_sync_metadata("sleep", result)

        except Exception as e:
            result.add_error(f"Failed to sync sleep: {e}")

        return result

    def sync_heart_rate(
        self,
        start_date: date,
        end_date: date,
        force: bool = False,
    ) -> SyncResult:
        """Sync heart rate data."""
        return self._sync_daily_metric(
            data_type="heart_rate",
            start_date=start_date,
            end_date=end_date,
            force=force,
            fetch_func=self.client.get_heart_rates,
            model_class=HeartRateDaily,
            upsert_func=self.repo.upsert_heart_rate,
        )

    def sync_stress(
        self,
        start_date: date,
        end_date: date,
        force: bool = False,
    ) -> SyncResult:
        """Sync stress data using batch endpoint."""
        result = SyncResult("stress")

        try:
            days = (end_date - start_date).days + 1
            stress_data = self.client.get_daily_stress_batch(end_date, days)

            for item in stress_data:
                try:
                    model = StressDaily.from_batch_response(item)
                    model.raw_json = json.dumps(item)
                    self.repo.upsert_stress(model)
                    result.records_synced += 1
                except Exception as e:
                    result.add_error(f"Stress {item.get('calendarDate', 'unknown')}: {e}")

            self._update_sync_metadata("stress", result)

        except Exception as e:
            result.add_error(f"Failed to sync stress: {e}")

        return result

    def sync_hrv(
        self,
        start_date: date,
        end_date: date,
        force: bool = False,
    ) -> SyncResult:
        """Sync HRV data using batch endpoint."""
        result = SyncResult("hrv")

        try:
            days = (end_date - start_date).days + 1
            hrv_data = self.client.get_daily_hrv_batch(end_date, days)

            for item in hrv_data:
                try:
                    model = HRVDaily.from_batch_response(item)
                    model.raw_json = json.dumps(item)
                    self.repo.upsert_hrv(model)
                    result.records_synced += 1
                except Exception as e:
                    if isinstance(item, dict):
                        date_str = item.get('calendarDate', 'unknown')
                        keys = list(item.keys())
                        val_types = {k: type(v).__name__ for k, v in item.items()}
                        print(f"[HRV debug] date={date_str} keys={keys} types={val_types} raw={item!r}", file=sys.stderr)
                        result.add_error(f"HRV {date_str} (keys={keys}): {e}")
                    else:
                        print(f"[HRV debug] non-dict item: type={type(item).__name__} value={item!r}", file=sys.stderr)
                        result.add_error(f"HRV <non-dict type={type(item).__name__}>: {e}")

            self._update_sync_metadata("hrv", result)

        except Exception as e:
            result.add_error(f"Failed to sync hrv: {e}")

        return result

    # ==================== Detailed (per-day) sync methods ====================

    def sync_sleep_detailed(
        self,
        start_date: date,
        end_date: date,
        force: bool = False,
    ) -> SyncResult:
        """Sync sleep data using per-day endpoints (full data)."""
        return self._sync_daily_metric(
            data_type="sleep",
            start_date=start_date,
            end_date=end_date,
            force=force,
            fetch_func=self.client.get_sleep_data,
            model_class=SleepDaily,
            upsert_func=self.repo.upsert_sleep,
        )

    def sync_stress_detailed(
        self,
        start_date: date,
        end_date: date,
        force: bool = False,
    ) -> SyncResult:
        """Sync stress data using per-day endpoints (full data)."""
        return self._sync_daily_metric(
            data_type="stress",
            start_date=start_date,
            end_date=end_date,
            force=force,
            fetch_func=self.client.get_stress_data,
            model_class=StressDaily,
            upsert_func=self.repo.upsert_stress,
        )

    def sync_hrv_detailed(
        self,
        start_date: date,
        end_date: date,
        force: bool = False,
    ) -> SyncResult:
        """Sync HRV data using per-day endpoints (full data)."""
        return self._sync_daily_metric(
            data_type="hrv",
            start_date=start_date,
            end_date=end_date,
            force=force,
            fetch_func=self.client.get_hrv_data,
            model_class=HRVDaily,
            upsert_func=self.repo.upsert_hrv,
        )

    # ==================== Body Battery and Training Readiness ====================

    def sync_body_battery(
        self,
        start_date: date,
        end_date: date,
        force: bool = False,
    ) -> SyncResult:
        """Sync Body Battery data using batch endpoint.

        Garmin's body-battery endpoint caps the request range, so we walk it
        in 30-day windows rather than one big call.
        """
        result = SyncResult("body_battery")
        chunk_days = 30

        try:
            window_start = start_date
            saw_any_data = False
            while window_start <= end_date:
                window_end = min(
                    window_start + timedelta(days=chunk_days - 1),
                    end_date,
                )
                try:
                    data_list = self.client.get_body_battery_batch(window_start, window_end)
                except Exception as e:
                    result.add_error(
                        f"Body Battery {window_start}..{window_end}: {e}"
                    )
                    window_start = window_end + timedelta(days=1)
                    continue

                if data_list:
                    saw_any_data = True
                    for item in data_list:
                        if isinstance(item, dict) and item.get("date"):
                            try:
                                bb = BodyBatteryDaily.from_daily_response(item)
                                bb.raw_json = json.dumps(item)
                                self.repo.upsert_body_battery(bb)
                                result.records_synced += 1
                            except Exception as e:
                                result.add_error(f"Body Battery {item.get('date', 'unknown')}: {e}")

                window_start = window_end + timedelta(days=1)

            if not saw_any_data:
                result.records_skipped += 1

            self._update_sync_metadata("body_battery", result)

        except Exception as e:
            result.add_error(f"Failed to sync body battery: {e}")

        return result

    def sync_training_readiness(
        self,
        start_date: date,
        end_date: date,
        force: bool = False,
    ) -> SyncResult:
        """Sync training readiness data."""
        return self._sync_daily_metric(
            data_type="training_readiness",
            start_date=start_date,
            end_date=end_date,
            force=force,
            fetch_func=self.client.get_training_readiness,
            model_class=TrainingReadiness,
            upsert_func=self.repo.upsert_training_readiness,
        )

    def _sync_daily_metric(
        self,
        data_type: str,
        start_date: date,
        end_date: date,
        force: bool,
        fetch_func: Callable,
        model_class: type,
        upsert_func: Callable,
    ) -> SyncResult:
        """Generic method for syncing daily metrics.

        Args:
            data_type: Name of the data type
            start_date: Start date
            end_date: End date
            force: Force re-download
            fetch_func: Function to fetch data from API
            model_class: Model class with from_api_response method
            upsert_func: Repository function to upsert data
        """
        result = SyncResult(data_type)
        table = _DAILY_METRIC_TABLE.get(data_type)
        freshness_cutoff = date.today() - timedelta(days=FRESHNESS_DAYS)

        try:
            current_date = start_date
            while current_date <= end_date:
                try:
                    # Skip dates that already have data and are outside the freshness
                    # window. Garmin can retroactively correct recent metrics (sleep
                    # scores, training readiness), so we always re-fetch the last
                    # FRESHNESS_DAYS days. --force bypasses this entirely.
                    if (
                        not force
                        and table
                        and current_date < freshness_cutoff
                        and self.repo.has_daily_record(table, current_date.isoformat())
                    ):
                        result.records_skipped += 1
                        current_date += timedelta(days=1)
                        continue

                    data = fetch_func(current_date)
                    if data:
                        # Handle the date field - some APIs return calendarDate, others don't
                        if "calendarDate" not in data:
                            data["calendarDate"] = current_date.isoformat()

                        model = model_class.from_api_response(data)
                        model.raw_json = json.dumps(data)
                        upsert_func(model)
                        result.records_synced += 1
                    else:
                        result.records_skipped += 1
                except Exception as e:
                    result.add_error(f"{data_type} {current_date}: {e}")

                current_date += timedelta(days=1)

            self._update_sync_metadata(data_type, result)

        except Exception as e:
            result.add_error(f"Failed to sync {data_type}: {e}")

        return result

    def _download_and_store_fit(self, activity_id: str) -> Optional[Path]:
        """Download and store FIT file for an activity.

        Args:
            activity_id: Garmin activity ID

        Returns:
            Path to stored FIT file, or None if download failed
        """
        try:
            settings = get_settings()
            fit_dir = settings.fit_files_dir
            fit_dir.mkdir(parents=True, exist_ok=True)

            fit_path = fit_dir / f"{activity_id}.fit"

            # Skip if already downloaded
            if fit_path.exists():
                return fit_path

            fit_data = self.client.download_activity_fit(activity_id)
            fit_path.write_bytes(fit_data)
            return fit_path

        except Exception as e:
            # Log so failures are visible — silent swallow previously hid that
            # FIT downloads had been broken for every activity.
            print(
                f"FIT download failed for activity {activity_id}: "
                f"{type(e).__name__}: {e}",
                file=sys.stderr,
            )
            return None

    def _compute_hr_drift(self, activity_id: str) -> tuple[Optional[float], Optional[Path]]:
        """Compute HR drift for an activity by downloading and parsing FIT file.

        Args:
            activity_id: Garmin activity ID

        Returns:
            Tuple of (hr_drift, fit_file_path)
        """
        fit_path = self._download_and_store_fit(activity_id)

        if fit_path is None:
            return None, None

        try:
            fit_data = fit_path.read_bytes()
            hr_drift = compute_hr_drift_from_fit(fit_data)
            return hr_drift, fit_path
        except Exception as e:
            print(
                f"FIT parse failed for activity {activity_id}: "
                f"{type(e).__name__}: {e}",
                file=sys.stderr,
            )
            return None, fit_path  # Still return path even if parsing failed

    def _update_sync_metadata(self, data_type: str, result: SyncResult):
        """Update sync metadata after a sync operation."""
        metadata = SyncMetadata(
            data_type=data_type,
            last_sync_timestamp=datetime.now().isoformat(),
            last_sync_date=date.today().isoformat(),
            sync_status="success" if result.success else "partial",
            records_synced=result.records_synced,
            error_message="; ".join(result.errors) if result.errors else None,
        )
        self.repo.update_sync_metadata(metadata)
