"""Tests for database module."""

import sqlite3

import pytest

from garmin_sync.db.database import Database, SCHEMA_VERSION
from garmin_sync.db.models import (
    Activity,
    DailySummary,
    HeartRateDaily,
    RespirationDaily,
    SleepDaily,
    SpO2Daily,
    SyncMetadata,
)
from garmin_sync.db.repository import Repository


class TestDatabase:
    """Test Database class."""

    def test_in_memory_database(self):
        """Test creating an in-memory database."""
        db = Database(":memory:")
        db.initialize()

        assert db.connection is not None
        assert db.get_schema_version() == SCHEMA_VERSION

        db.close()

    def test_file_database(self, temp_db_path):
        """Test creating a file-based database."""
        db = Database(temp_db_path)
        db.initialize()

        assert temp_db_path.exists()
        assert db.get_schema_version() == SCHEMA_VERSION

        db.close()

    def test_table_creation(self):
        """Test that all expected tables are created."""
        db = Database(":memory:")
        db.initialize()

        expected_tables = [
            "activities",
            "body_battery_daily",
            "daily_summaries",
            "heart_rate_daily",
            "hrv_daily",
            "schema_version",
            "sleep_daily",
            "stress_daily",
            "sync_metadata",
            "training_readiness",
        ]

        actual_tables = db.get_table_names()

        for table in expected_tables:
            assert table in actual_tables, f"Table {table} not found"

        db.close()

    def test_table_exists(self):
        """Test table_exists method."""
        db = Database(":memory:")
        db.initialize()

        assert db.table_exists("activities") is True
        assert db.table_exists("nonexistent_table") is False

        db.close()

    def test_transaction_commit(self):
        """Test that transactions commit on success."""
        db = Database(":memory:")
        db.initialize()

        with db.transaction() as cursor:
            cursor.execute(
                "INSERT INTO sync_metadata (data_type, last_sync_timestamp) VALUES (?, ?)",
                ("test_type", "2024-01-01T00:00:00Z")
            )

        # Verify data was committed
        cursor = db.connection.cursor()
        cursor.execute("SELECT * FROM sync_metadata WHERE data_type = 'test_type'")
        row = cursor.fetchone()
        assert row is not None
        assert row["data_type"] == "test_type"

        db.close()

    def test_transaction_rollback(self):
        """Test that transactions rollback on error."""
        db = Database(":memory:")
        db.initialize()

        with pytest.raises(Exception):
            with db.transaction() as cursor:
                cursor.execute(
                    "INSERT INTO sync_metadata (data_type, last_sync_timestamp) VALUES (?, ?)",
                    ("test_type", "2024-01-01T00:00:00Z")
                )
                raise Exception("Test error")

        # Verify data was rolled back
        cursor = db.connection.cursor()
        cursor.execute("SELECT * FROM sync_metadata WHERE data_type = 'test_type'")
        row = cursor.fetchone()
        assert row is None

        db.close()

    def test_parent_directory_creation(self, temp_dir):
        """Test that parent directories are created for database file."""
        db_path = temp_dir / "subdir1" / "subdir2" / "test.db"
        db = Database(db_path)

        # Access connection to trigger directory creation
        _ = db.connection
        db.initialize()

        assert db_path.exists()
        db.close()


class TestRepository:
    """Test Repository class."""

    @pytest.fixture
    def repo(self):
        """Create a repository with in-memory database."""
        db = Database(":memory:")
        db.initialize()
        return Repository(db)

    def test_sync_metadata_crud(self, repo):
        """Test sync metadata create, read, update."""
        # Create
        metadata = SyncMetadata(
            data_type="activities",
            last_sync_timestamp="2024-01-15T10:30:00Z",
            last_sync_date="2024-01-15",
            sync_status="success",
            records_synced=50,
        )
        repo.update_sync_metadata(metadata)

        # Read
        retrieved = repo.get_sync_metadata("activities")
        assert retrieved is not None
        assert retrieved.data_type == "activities"
        assert retrieved.last_sync_timestamp == "2024-01-15T10:30:00Z"
        assert retrieved.records_synced == 50

        # Update
        metadata.last_sync_timestamp = "2024-01-16T08:00:00Z"
        metadata.records_synced = 75
        repo.update_sync_metadata(metadata)

        retrieved = repo.get_sync_metadata("activities")
        assert retrieved.last_sync_timestamp == "2024-01-16T08:00:00Z"
        assert retrieved.records_synced == 75

    def test_sync_metadata_not_found(self, repo):
        """Test getting non-existent sync metadata."""
        result = repo.get_sync_metadata("nonexistent")
        assert result is None

    def test_activity_crud(self, repo):
        """Test activity CRUD operations."""
        activity = Activity(
            activity_id="12345",
            activity_name="Morning Run",
            activity_type="running",
            start_time="2024-01-15T07:00:00Z",
            duration_seconds=3600.0,
            distance_meters=10000.0,
            average_hr=145,
            max_hr=165,
            calories=500,
        )

        # Create
        repo.upsert_activity(activity)

        # Check exists
        assert repo.activity_exists("12345") is True
        assert repo.activity_exists("99999") is False

        # Read
        retrieved = repo.get_activity("12345")
        assert retrieved is not None
        assert retrieved.activity_name == "Morning Run"
        assert retrieved.distance_meters == 10000.0
        assert retrieved.average_hr == 145

        # Update
        activity.activity_name = "Updated Run"
        activity.calories = 550
        repo.upsert_activity(activity)

        retrieved = repo.get_activity("12345")
        assert retrieved.activity_name == "Updated Run"
        assert retrieved.calories == 550

    def test_activity_filtering(self, repo):
        """Test activity filtering by date and type."""
        activities = [
            Activity(
                activity_id="1",
                activity_type="running",
                start_time="2024-01-10T07:00:00Z",
            ),
            Activity(
                activity_id="2",
                activity_type="cycling",
                start_time="2024-01-12T08:00:00Z",
            ),
            Activity(
                activity_id="3",
                activity_type="running",
                start_time="2024-01-15T06:00:00Z",
            ),
        ]

        for a in activities:
            repo.upsert_activity(a)

        # Filter by date range
        results = repo.get_activities(start_date="2024-01-11", end_date="2024-01-16")
        assert len(results) == 2

        # Filter by type
        results = repo.get_activities(activity_type="running")
        assert len(results) == 2

        # Combined filter
        results = repo.get_activities(
            start_date="2024-01-11",
            activity_type="running"
        )
        assert len(results) == 1
        assert results[0].activity_id == "3"

    def test_get_activity_ids(self, repo):
        """Test getting activity IDs for deduplication."""
        activities = [
            Activity(activity_id="a1", start_time="2024-01-10T07:00:00Z"),
            Activity(activity_id="a2", start_time="2024-01-12T07:00:00Z"),
            Activity(activity_id="a3", start_time="2024-01-15T07:00:00Z"),
        ]

        for a in activities:
            repo.upsert_activity(a)

        # All IDs
        ids = repo.get_activity_ids()
        assert ids == {"a1", "a2", "a3"}

        # IDs since date
        ids = repo.get_activity_ids(since_date="2024-01-11")
        assert ids == {"a2", "a3"}

    def test_daily_summary_crud(self, repo):
        """Test daily summary CRUD."""
        summary = DailySummary(
            date="2024-01-15",
            total_steps=10000,
            step_goal=8000,
            total_calories=2500,
        )

        repo.upsert_daily_summary(summary)

        retrieved = repo.get_daily_summary("2024-01-15")
        assert retrieved is not None
        assert retrieved.total_steps == 10000
        assert retrieved.step_goal == 8000

    def test_sleep_crud(self, repo):
        """Test sleep data CRUD."""
        sleep = SleepDaily(
            date="2024-01-15",
            total_sleep_seconds=28800,  # 8 hours
            deep_sleep_seconds=7200,    # 2 hours
            sleep_score=85,
            sleep_quality="GOOD",
        )

        repo.upsert_sleep(sleep)

        retrieved = repo.get_sleep("2024-01-15")
        assert retrieved is not None
        assert retrieved.total_sleep_seconds == 28800
        assert retrieved.sleep_score == 85
        assert retrieved.sleep_quality == "GOOD"


class TestModels:
    """Test data models."""

    def test_activity_from_api_response(self):
        """Test creating Activity from API response."""
        api_data = {
            "activityId": 12345,
            "activityName": "Morning Run",
            "activityType": {"typeKey": "running"},
            "startTimeGMT": "2024-01-15T07:00:00.0",
            "duration": 3600.5,
            "distance": 10000.0,
            "averageHR": 145,
            "maxHR": 165,
            "calories": 500,
            "elevationGain": 150.0,
            "aerobicTrainingEffect": 3.5,
        }

        activity = Activity.from_api_response(api_data)

        assert activity.activity_id == "12345"
        assert activity.activity_name == "Morning Run"
        assert activity.activity_type == "running"
        assert activity.duration_seconds == 3600.5
        assert activity.distance_meters == 10000.0
        assert activity.average_hr == 145
        assert activity.training_effect_aerobic == 3.5

    def test_daily_summary_from_api_response(self):
        """Test creating DailySummary from API response."""
        api_data = {
            "calendarDate": "2024-01-15",
            "totalSteps": 10000,
            "dailyStepGoal": 8000,
            "totalKilocalories": 2500,
            "activeKilocalories": 800,
        }

        summary = DailySummary.from_api_response(api_data)

        assert summary.date == "2024-01-15"
        assert summary.total_steps == 10000
        assert summary.step_goal == 8000
        assert summary.total_calories == 2500

    def test_sleep_from_api_response(self):
        """Test creating SleepDaily from API response."""
        api_data = {
            "dailySleepDTO": {
                "calendarDate": "2024-01-15",
                "sleepTimeSeconds": 28800,
                "deepSleepSeconds": 7200,
                "lightSleepSeconds": 14400,
                "remSleepSeconds": 5400,
                "awakeSleepSeconds": 1800,
            },
            "sleepScores": {
                "overall": {
                    "value": 85,
                    "qualifierKey": "GOOD",
                }
            }
        }

        sleep = SleepDaily.from_api_response(api_data)

        assert sleep.date == "2024-01-15"
        assert sleep.total_sleep_seconds == 28800
        assert sleep.deep_sleep_seconds == 7200
        assert sleep.sleep_score == 85
        assert sleep.sleep_quality == "GOOD"

    def test_hrv_from_api_response_handles_null_summary(self):
        """Garmin returns {hrvSummary: null, ...} for early dates; must not raise."""
        from garmin_sync.db.models import HRVDaily

        # Explicit None on the summary key (not just missing).
        hrv = HRVDaily.from_api_response({"hrvSummary": None})
        assert hrv.hrv_value is None
        assert hrv.baseline_low is None

        # Summary present but baseline is None.
        hrv2 = HRVDaily.from_api_response({
            "hrvSummary": {
                "calendarDate": "2022-10-21",
                "weeklyAvg": 55,
                "baseline": None,
            }
        })
        assert hrv2.date == "2022-10-21"
        assert hrv2.hrv_value == 55
        assert hrv2.baseline_low is None


class TestHRDrift:
    """Test HR drift related database functionality."""

    @pytest.fixture
    def repo(self):
        """Create a repository with in-memory database."""
        db = Database(":memory:")
        db.initialize()
        return Repository(db)

    def test_activity_hr_drift_field(self):
        """Test Activity dataclass has hr_drift field."""
        activity = Activity(
            activity_id="123",
            hr_drift=0.05,
        )
        assert activity.hr_drift == 0.05

    def test_activity_hr_drift_stored_in_db(self, repo):
        """Test HR drift is persisted to database."""
        activity = Activity(
            activity_id="123",
            start_time="2024-01-15T07:00:00Z",
            activity_type="running",
            hr_drift=0.08,
        )
        repo.upsert_activity(activity)

        retrieved = repo.get_activity("123")
        assert retrieved is not None
        assert retrieved.hr_drift == pytest.approx(0.08)

    def test_activity_hr_drift_null_when_not_set(self, repo):
        """Test HR drift is None when not set."""
        activity = Activity(
            activity_id="456",
            start_time="2024-01-15T07:00:00Z",
            activity_type="running",
        )
        repo.upsert_activity(activity)

        retrieved = repo.get_activity("456")
        assert retrieved.hr_drift is None

    def test_activity_hr_drift_update(self, repo):
        """Test HR drift can be updated via upsert."""
        activity = Activity(
            activity_id="789",
            start_time="2024-01-15T07:00:00Z",
            activity_type="running",
            hr_drift=0.05,
        )
        repo.upsert_activity(activity)

        # Update with new hr_drift value
        activity.hr_drift = 0.12
        repo.upsert_activity(activity)

        retrieved = repo.get_activity("789")
        assert retrieved.hr_drift == pytest.approx(0.12)

    def test_hr_drift_column_exists_in_schema(self):
        """Test hr_drift column exists in activities table."""
        db = Database(":memory:")
        db.initialize()

        cursor = db.connection.cursor()
        cursor.execute("PRAGMA table_info(activities)")
        columns = [row[1] for row in cursor.fetchall()]

        assert "hr_drift" in columns
        db.close()


class TestSchemaMigration:
    """Test database schema migration."""

    def test_schema_version_is_7(self):
        """Test schema version is 7."""
        assert SCHEMA_VERSION == 7

    def test_migrate_v1_to_v2_adds_hr_drift(self, temp_dir):
        """Test migration adds hr_drift column to activities."""
        db_path = temp_dir / "test.db"

        # Create a v1 database manually (without hr_drift column)
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")
        conn.execute("""
            CREATE TABLE activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id TEXT NOT NULL UNIQUE,
                activity_name TEXT,
                activity_type TEXT,
                start_time TEXT,
                start_time_local TEXT,
                timezone TEXT,
                duration_seconds REAL,
                moving_duration_seconds REAL,
                distance_meters REAL,
                average_speed_mps REAL,
                max_speed_mps REAL,
                average_hr INTEGER,
                max_hr INTEGER,
                min_hr INTEGER,
                elevation_gain_meters REAL,
                elevation_loss_meters REAL,
                calories INTEGER,
                training_effect_aerobic REAL,
                training_effect_anaerobic REAL,
                training_load REAL,
                vo2_max REAL,
                avg_cadence REAL,
                max_cadence REAL,
                average_power REAL,
                max_power REAL,
                normalized_power REAL,
                device_name TEXT,
                has_fit_file INTEGER DEFAULT 0,
                fit_file_path TEXT,
                raw_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

        # Now open with Database and run migration
        db = Database(db_path)
        db.migrate()

        # Verify column was added
        cursor = db.connection.cursor()
        cursor.execute("PRAGMA table_info(activities)")
        columns = [row[1] for row in cursor.fetchall()]

        assert "hr_drift" in columns

        # Verify schema version was updated (should be 4 after all migrations)
        assert db.get_schema_version() == SCHEMA_VERSION

        db.close()

    def test_migrate_idempotent(self):
        """Test migration is idempotent - running twice doesn't fail."""
        db = Database(":memory:")
        db.initialize()

        # Run migration again (should be no-op since already at v4)
        db.migrate()

        assert db.get_schema_version() == SCHEMA_VERSION
        db.close()

    def test_migrate_v2_to_v3_adds_chat_messages(self, temp_dir):
        """Test migration adds chat_messages table."""
        db_path = temp_dir / "test.db"

        # Create a v2 database manually (without chat_messages table)
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("INSERT INTO schema_version (version) VALUES (2)")
        # Create minimal activities table with hr_drift (v2 schema)
        conn.execute("""
            CREATE TABLE activities (
                id INTEGER PRIMARY KEY,
                activity_id TEXT,
                hr_drift REAL
            )
        """)
        conn.commit()
        conn.close()

        # Now open with Database and run migration
        db = Database(db_path)
        db.migrate()

        # Verify chat_messages table was created
        cursor = db.connection.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_messages'"
        )
        assert cursor.fetchone() is not None

        # Verify schema version was updated (should be 4 after all migrations)
        assert db.get_schema_version() == SCHEMA_VERSION

        db.close()

    def test_migrate_v3_to_v4_adds_hevy_tables(self, temp_dir):
        """Test migration adds HEVY tables."""
        db_path = temp_dir / "test.db"

        # Create a v3 database manually (without HEVY tables)
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("INSERT INTO schema_version (version) VALUES (3)")
        # Create minimal activities table
        conn.execute("""
            CREATE TABLE activities (
                id INTEGER PRIMARY KEY,
                activity_id TEXT,
                hr_drift REAL
            )
        """)
        # Create chat_messages table
        conn.execute("""
            CREATE TABLE chat_messages (
                id INTEGER PRIMARY KEY,
                role TEXT,
                content TEXT
            )
        """)
        conn.commit()
        conn.close()

        # Now open with Database and run migration
        db = Database(db_path)
        db.migrate()

        # Verify HEVY tables were created
        cursor = db.connection.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hevy_workouts'"
        )
        assert cursor.fetchone() is not None

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hevy_exercises'"
        )
        assert cursor.fetchone() is not None

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hevy_sets'"
        )
        assert cursor.fetchone() is not None

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='hevy_exercise_templates'"
        )
        assert cursor.fetchone() is not None

        # Verify schema version was updated
        assert db.get_schema_version() == SCHEMA_VERSION

        db.close()


class TestUpsertCoalesce:
    """Test COALESCE semantics in upsert operations."""

    @pytest.fixture
    def repo(self):
        """Create a repository with in-memory database."""
        db = Database(":memory:")
        db.initialize()
        return Repository(db)

    def test_activity_upsert_preserves_fit_fields_on_api_resync(self, repo):
        """COALESCE columns (fit_file_path, hr_drift) survive a re-upsert where
        the API-sourced row has None for those fields.  has_fit_file uses
        COALESCE too, but since the dataclass default is False (-> 0 in SQL),
        COALESCE sees a non-NULL 0 and picks it.  fit_file_path and hr_drift
        default to None (-> NULL in SQL), so COALESCE falls through to the
        existing row's value."""
        activity = Activity(
            activity_id="coalesce-1",
            activity_type="running",
            start_time="2024-06-01T07:00:00Z",
            has_fit_file=True,
            fit_file_path="/data/file.fit",
            hr_drift=5.2,
        )
        repo.upsert_activity(activity)

        # Simulate an API re-sync that doesn't know about FIT fields.
        # fit_file_path=None and hr_drift=None map to SQL NULL so COALESCE
        # preserves the originals.
        resync = Activity(
            activity_id="coalesce-1",
            activity_type="running",
            start_time="2024-06-01T07:00:00Z",
            fit_file_path=None,
            hr_drift=None,
        )
        repo.upsert_activity(resync)

        retrieved = repo.get_activity("coalesce-1")
        assert retrieved.fit_file_path == "/data/file.fit"
        assert retrieved.hr_drift == pytest.approx(5.2)

    def test_activity_upsert_updates_all_api_fields(self, repo):
        """Direct-assignment columns update to new values on re-upsert."""
        original = Activity(
            activity_id="direct-1",
            activity_type="running",
            start_time="2024-06-01T07:00:00Z",
            training_load=100.0,
            vo2_max=45.5,
            elevation_gain_meters=200.0,
            training_effect_aerobic=3.5,
        )
        repo.upsert_activity(original)

        updated = Activity(
            activity_id="direct-1",
            activity_type="running",
            start_time="2024-06-01T07:00:00Z",
            training_load=150.0,
            vo2_max=48.0,
            elevation_gain_meters=250.0,
            training_effect_aerobic=4.0,
        )
        repo.upsert_activity(updated)

        retrieved = repo.get_activity("direct-1")
        assert retrieved.training_load == pytest.approx(150.0)
        assert retrieved.vo2_max == pytest.approx(48.0)
        assert retrieved.elevation_gain_meters == pytest.approx(250.0)
        assert retrieved.training_effect_aerobic == pytest.approx(4.0)

    def test_heart_rate_upsert_preserves_on_null_resync(self, repo):
        """heart_rate_daily COALESCE preserves values when re-upserted with None."""
        repo.upsert_heart_rate(HeartRateDaily(
            date="2024-06-01", resting_hr=60, max_hr=180, min_hr=45,
        ))

        # Re-upsert with all None values
        repo.upsert_heart_rate(HeartRateDaily(
            date="2024-06-01", resting_hr=None, max_hr=None, min_hr=None,
        ))

        cursor = repo.db.connection.cursor()
        cursor.execute("SELECT * FROM heart_rate_daily WHERE date = ?", ("2024-06-01",))
        row = cursor.fetchone()
        assert row["resting_hr"] == 60
        assert row["max_hr"] == 180
        assert row["min_hr"] == 45

    def test_respiration_upsert_preserves_on_null_resync(self, repo):
        """respiration_daily COALESCE preserves values when re-upserted with None."""
        repo.upsert_respiration_daily(RespirationDaily(
            date="2024-06-01", avg_respiration=15.0, max_respiration=20.0, min_respiration=12.0,
        ))

        repo.upsert_respiration_daily(RespirationDaily(
            date="2024-06-01", avg_respiration=None, max_respiration=None, min_respiration=None,
        ))

        cursor = repo.db.connection.cursor()
        cursor.execute("SELECT * FROM respiration_daily WHERE date = ?", ("2024-06-01",))
        row = cursor.fetchone()
        assert row["avg_respiration"] == pytest.approx(15.0)
        assert row["max_respiration"] == pytest.approx(20.0)
        assert row["min_respiration"] == pytest.approx(12.0)

    def test_spo2_upsert_preserves_on_null_resync(self, repo):
        """spo2_daily COALESCE preserves values when re-upserted with None."""
        repo.upsert_spo2_daily(SpO2Daily(
            date="2024-06-01", avg_spo2=97.0, min_spo2=94.0, max_spo2=99.0,
        ))

        repo.upsert_spo2_daily(SpO2Daily(
            date="2024-06-01", avg_spo2=None, min_spo2=None, max_spo2=None,
        ))

        cursor = repo.db.connection.cursor()
        cursor.execute("SELECT * FROM spo2_daily WHERE date = ?", ("2024-06-01",))
        row = cursor.fetchone()
        assert row["avg_spo2"] == pytest.approx(97.0)
        assert row["min_spo2"] == pytest.approx(94.0)
        assert row["max_spo2"] == pytest.approx(99.0)

    def test_activity_fit_parsed_uses_max_semantics(self, repo):
        """fit_parsed uses MAX(excluded, existing) so once set to True it sticks."""
        activity = Activity(
            activity_id="max-1",
            activity_type="running",
            start_time="2024-06-01T07:00:00Z",
            fit_parsed=True,
        )
        repo.upsert_activity(activity)

        # Re-upsert with fit_parsed=False (e.g. from API resync)
        resync = Activity(
            activity_id="max-1",
            activity_type="running",
            start_time="2024-06-01T07:00:00Z",
            fit_parsed=False,
        )
        repo.upsert_activity(resync)

        retrieved = repo.get_activity("max-1")
        assert retrieved.fit_parsed is True

    def test_sleep_upsert_preserves_stages_on_null_resync(self, repo):
        """sleep_daily COALESCE preserves sleep stage fields on partial resync."""
        repo.upsert_sleep(SleepDaily(
            date="2024-06-01",
            total_sleep_seconds=28800,
            deep_sleep_seconds=7200,
            rem_sleep_seconds=5400,
            sleep_score=85,
        ))

        # Re-upsert with only the score (e.g. batch endpoint doesn't include stages)
        repo.upsert_sleep(SleepDaily(
            date="2024-06-01",
            sleep_score=87,
        ))

        retrieved = repo.get_sleep("2024-06-01")
        assert retrieved.deep_sleep_seconds == 7200
        assert retrieved.rem_sleep_seconds == 5400
        assert retrieved.total_sleep_seconds == 28800
        assert retrieved.sleep_score == 87  # Updated to new value


class TestSleepEpochConversion:
    """Test SleepDaily.from_api_response epoch-millis conversion."""

    def test_sleep_from_api_converts_epoch_millis(self):
        """Epoch millisecond timestamps are converted to ISO 8601 strings."""
        data = {
            "dailySleepDTO": {
                "calendarDate": "2024-01-25",
                "sleepStartTimestampGMT": 1706223000000,
                "sleepEndTimestampGMT": 1706252400000,
                "sleepTimeSeconds": 28800,
            },
            "sleepScores": {"overall": {"value": 80, "qualifierKey": "GOOD"}},
        }

        sleep = SleepDaily.from_api_response(data)

        assert isinstance(sleep.sleep_start, str)
        assert "2024-01-25" in sleep.sleep_start
        assert isinstance(sleep.sleep_end, str)
        assert "2024-01-26" in sleep.sleep_end

    def test_sleep_from_api_handles_none_epoch(self):
        """Missing epoch fields produce None, not an error."""
        data = {
            "dailySleepDTO": {
                "calendarDate": "2024-01-25",
                "sleepTimeSeconds": 28800,
            },
            "sleepScores": {},
        }

        sleep = SleepDaily.from_api_response(data)

        assert sleep.sleep_start is None
        assert sleep.sleep_end is None

    def test_epoch_helper_passes_through_iso_strings(self):
        """Garmin may return an already-ISO timestamp; it must pass through
        rather than being discarded (int('2024-..')/1000 would raise -> None)."""
        from garmin_sync.db.models import _epoch_ms_to_iso

        # Already-ISO input passes through unchanged (regression).
        assert _epoch_ms_to_iso("2024-01-25T07:00:00.0") == "2024-01-25T07:00:00.0"
        # Epoch-ms still converts to a Z-suffixed UTC string.
        converted = _epoch_ms_to_iso(1706223000000)
        assert converted.endswith("Z") and "2024-01-2" in converted
        # None / overflow degrade to None, never crash.
        assert _epoch_ms_to_iso(None) is None
        assert _epoch_ms_to_iso(10 ** 30) is None


class TestHevyUpsertAndDateFilters:
    """Regression: HEVY re-upsert column coverage + date-only end_date bounds."""

    @pytest.fixture
    def repo(self):
        db = Database(":memory:")
        db.initialize()
        db.migrate()
        return Repository(db)

    def _wk(self, title, start, end, n_ex):
        from garmin_sync.hevy.models import HevyWorkout, HevyExercise, HevySet
        exs = [
            HevyExercise(
                exercise_template_id=f"t{i}", exercise_name=f"Ex{i}",
                sets=[HevySet(set_index=0, set_type="normal", weight_kg=60, reps=10)],
            )
            for i in range(n_ex)
        ]
        return HevyWorkout(id="w1", title=title, start_time=start, end_time=end, exercises=exs)

    def test_reupsert_updates_time_and_count_columns(self, repo):
        """Re-upserting an edited workout updates start_time, duration_seconds
        and exercise_count — these were omitted from ON CONFLICT DO UPDATE and
        went stale (internally inconsistent with the child exercise rows)."""
        repo.upsert_hevy_workout(
            self._wk("A", "2026-05-01T10:00:00+00:00", "2026-05-01T11:00:00+00:00", 1)
        )
        repo.upsert_hevy_workout(
            self._wk("A edited", "2026-05-01T09:00:00+00:00", "2026-05-01T11:00:00+00:00", 2)
        )
        row = repo.db.connection.execute(
            "SELECT start_time, duration_seconds, exercise_count "
            "FROM hevy_workouts WHERE id='w1'"
        ).fetchone()
        assert row["duration_seconds"] == 7200       # was 3600
        assert row["exercise_count"] == 2            # was 1
        assert row["start_time"].startswith("2026-05-01T09")

    def test_get_activities_date_only_end_date_includes_day(self, repo):
        """A date-only end_date must include same-day activities (regression for
        the lexical comparison dropping the end day)."""
        repo.db.connection.execute(
            "INSERT INTO activities (activity_id, start_time, start_time_local, "
            "training_load) VALUES (?, ?, ?, ?)",
            ("a1", "2026-05-16T07:00:00", "2026-05-16T07:00:00", 100.0),
        )
        repo.db.connection.commit()
        got = repo.get_activities(start_date="2026-05-10", end_date="2026-05-16")
        assert len(got) == 1
