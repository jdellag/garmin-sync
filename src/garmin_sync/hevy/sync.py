"""HEVY sync manager for orchestrating strength training data synchronization."""

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from garmin_sync.hevy.client import HevyClient
from garmin_sync.hevy.models import HevyExerciseTemplate, HevyWorkout
from garmin_sync.reports.strength_load import compute_stl_from_workout


@dataclass
class HevySyncResult:
    """Result of a HEVY sync operation."""

    data_type: str
    records_synced: int = 0
    records_skipped: int = 0
    errors: list[str] = None
    success: bool = True

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    def add_error(self, error: str):
        """Add an error message."""
        self.errors.append(error)
        self.success = False


class HevySyncManager:
    """Manages syncing HEVY data to local database."""

    def __init__(self, client: HevyClient, repository):
        """Initialize sync manager.

        Args:
            client: HEVY API client
            repository: Database repository with HEVY methods
        """
        self.client = client
        self.repo = repository

    def sync_workouts(self, days: int = 30) -> HevySyncResult:
        """Sync workouts from last N days.

        Args:
            days: Number of days to sync

        Returns:
            HevySyncResult with sync statistics
        """
        result = HevySyncResult(data_type="hevy_workouts")
        since_date = (date.today() - timedelta(days=days)).isoformat()

        try:
            # Get existing workout IDs for deduplication
            existing_ids = self.repo.get_hevy_workout_ids(since_date=since_date)

            # Fetch workouts from API
            workouts_data = self.client.get_all_workouts(since_date=since_date)

            for workout_data in workouts_data:
                workout_id = workout_data.get("id", "")

                if not workout_id:
                    continue

                if workout_id in existing_ids:
                    result.records_skipped += 1
                    continue

                try:
                    workout = HevyWorkout.from_api_response(workout_data)
                    workout.raw_json = json.dumps(workout_data)

                    # Compute Strength Training Load (sRPE-based)
                    stl, method = compute_stl_from_workout(workout)
                    workout.training_load = stl
                    workout.stl_method = method

                    self.repo.upsert_hevy_workout(workout)
                    result.records_synced += 1
                except Exception as e:
                    result.add_error(f"Workout {workout_id}: {e}")

            # Update sync metadata
            self._update_sync_metadata("hevy_workouts", result)

        except Exception as e:
            result.add_error(f"Failed to sync HEVY workouts: {e}")

        return result

    def sync_exercise_templates(self) -> HevySyncResult:
        """Sync exercise template library.

        Returns:
            HevySyncResult with sync statistics
        """
        result = HevySyncResult(data_type="hevy_exercise_templates")

        try:
            templates_data = self.client.get_all_exercise_templates()

            for template_data in templates_data:
                try:
                    template = HevyExerciseTemplate.from_api_response(template_data)
                    self.repo.upsert_hevy_exercise_template(template)
                    result.records_synced += 1
                except Exception as e:
                    result.add_error(f"Template {template_data.get('id', 'unknown')}: {e}")

            self._update_sync_metadata("hevy_exercise_templates", result)

        except Exception as e:
            result.add_error(f"Failed to sync exercise templates: {e}")

        return result

    def sync_all(self, days: int = 30) -> dict[str, HevySyncResult]:
        """Sync all HEVY data types.

        Args:
            days: Number of days of workout history to sync

        Returns:
            Dict of data_type -> HevySyncResult
        """
        results = {}
        results["workouts"] = self.sync_workouts(days=days)
        results["exercise_templates"] = self.sync_exercise_templates()
        return results

    def _update_sync_metadata(self, data_type: str, result: HevySyncResult):
        """Update sync metadata after a sync operation."""
        from garmin_sync.db.models import SyncMetadata

        metadata = SyncMetadata(
            data_type=data_type,
            last_sync_timestamp=datetime.now().isoformat(),
            last_sync_date=date.today().isoformat(),
            sync_status="success" if result.success else "partial",
            records_synced=result.records_synced,
            error_message="; ".join(result.errors) if result.errors else None,
        )
        self.repo.update_sync_metadata(metadata)
