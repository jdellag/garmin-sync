"""Database connection and initialization."""

import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

# Schema version for migrations
SCHEMA_VERSION = 5

SCHEMA_SQL = """
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Sync metadata to track last sync per data type
CREATE TABLE IF NOT EXISTS sync_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_type TEXT NOT NULL UNIQUE,
    last_sync_timestamp TEXT NOT NULL,
    last_sync_date TEXT,
    sync_status TEXT DEFAULT 'success',
    records_synced INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Activities table
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id TEXT NOT NULL UNIQUE,
    activity_name TEXT,
    activity_type TEXT,
    start_time TEXT NOT NULL,
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
    hr_drift REAL,
    raw_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_activities_start_time ON activities(start_time);
CREATE INDEX IF NOT EXISTS idx_activities_activity_type ON activities(activity_type);
CREATE INDEX IF NOT EXISTS idx_activities_activity_id ON activities(activity_id);

-- Daily summaries (steps, calories, etc.)
CREATE TABLE IF NOT EXISTS daily_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    total_steps INTEGER,
    step_goal INTEGER,
    steps_distance_meters REAL,
    total_calories INTEGER,
    active_calories INTEGER,
    bmr_calories INTEGER,
    highly_active_seconds INTEGER,
    active_seconds INTEGER,
    sedentary_seconds INTEGER,
    floors_ascended INTEGER,
    floors_descended INTEGER,
    raw_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_daily_summaries_date ON daily_summaries(date);

-- Heart rate daily data
CREATE TABLE IF NOT EXISTS heart_rate_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    resting_hr INTEGER,
    max_hr INTEGER,
    min_hr INTEGER,
    raw_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_heart_rate_daily_date ON heart_rate_daily(date);

-- Sleep data
CREATE TABLE IF NOT EXISTS sleep_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    sleep_start TEXT,
    sleep_end TEXT,
    total_sleep_seconds INTEGER,
    deep_sleep_seconds INTEGER,
    light_sleep_seconds INTEGER,
    rem_sleep_seconds INTEGER,
    awake_seconds INTEGER,
    sleep_score INTEGER,
    sleep_quality TEXT,
    avg_sleep_stress REAL,
    avg_respiration REAL,
    avg_spo2 REAL,
    avg_hrv REAL,
    raw_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sleep_daily_date ON sleep_daily(date);

-- Stress data
CREATE TABLE IF NOT EXISTS stress_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    overall_stress_level INTEGER,
    rest_stress_duration INTEGER,
    low_stress_duration INTEGER,
    medium_stress_duration INTEGER,
    high_stress_duration INTEGER,
    max_stress_level INTEGER,
    avg_stress_level INTEGER,
    raw_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_stress_daily_date ON stress_daily(date);

-- HRV data
CREATE TABLE IF NOT EXISTS hrv_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    hrv_value REAL,
    hrv_status TEXT,
    baseline_low REAL,
    baseline_high REAL,
    baseline_avg REAL,
    weekly_avg REAL,
    last_night_avg REAL,
    raw_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_hrv_daily_date ON hrv_daily(date);

-- Body Battery data
CREATE TABLE IF NOT EXISTS body_battery_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    charged INTEGER,
    drained INTEGER,
    start_level INTEGER,
    end_level INTEGER,
    min_level INTEGER,
    max_level INTEGER,
    raw_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_body_battery_date ON body_battery_daily(date);

-- Training readiness
CREATE TABLE IF NOT EXISTS training_readiness (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    score INTEGER,
    level TEXT,
    sleep_score INTEGER,
    recovery_score INTEGER,
    hrv_score INTEGER,
    stress_history_score INTEGER,
    training_load_balance_score INTEGER,
    feedback_phrase TEXT,
    raw_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_training_readiness_date ON training_readiness(date);

-- Chat messages for AI conversation history
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    message_type TEXT DEFAULT 'chat',
    token_estimate INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_created ON chat_messages(created_at);

-- HEVY Workouts (strength training sessions)
CREATE TABLE IF NOT EXISTS hevy_workouts (
    id TEXT PRIMARY KEY,
    title TEXT,
    description TEXT,
    start_time TEXT,
    end_time TEXT,
    duration_seconds INTEGER,
    volume_kg REAL,
    set_count INTEGER,
    rep_count INTEGER,
    exercise_count INTEGER,
    raw_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_hevy_workouts_start ON hevy_workouts(start_time);

-- HEVY Exercises within workouts
CREATE TABLE IF NOT EXISTS hevy_exercises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id TEXT NOT NULL,
    exercise_template_id TEXT,
    exercise_name TEXT NOT NULL,
    exercise_type TEXT,
    muscle_group TEXT,
    superset_id INTEGER,
    exercise_order INTEGER,
    notes TEXT,
    FOREIGN KEY (workout_id) REFERENCES hevy_workouts(id)
);

CREATE INDEX IF NOT EXISTS idx_hevy_exercises_workout ON hevy_exercises(workout_id);
CREATE INDEX IF NOT EXISTS idx_hevy_exercises_name ON hevy_exercises(exercise_name);

-- HEVY Sets within exercises
CREATE TABLE IF NOT EXISTS hevy_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id INTEGER NOT NULL,
    set_index INTEGER,
    set_type TEXT,
    weight_kg REAL,
    reps INTEGER,
    distance_meters REAL,
    duration_seconds INTEGER,
    rpe REAL,
    is_pr INTEGER DEFAULT 0,
    FOREIGN KEY (exercise_id) REFERENCES hevy_exercises(id)
);

CREATE INDEX IF NOT EXISTS idx_hevy_sets_exercise ON hevy_sets(exercise_id);

-- Exercise templates (HEVY's exercise library)
CREATE TABLE IF NOT EXISTS hevy_exercise_templates (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    muscle_group TEXT,
    equipment TEXT,
    is_custom INTEGER DEFAULT 0
);

-- Personal records tracking
CREATE TABLE IF NOT EXISTS personal_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value REAL NOT NULL,
    previous_value REAL,
    activity_id TEXT,
    workout_id TEXT,
    exercise_name TEXT,
    date_set TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(category, metric_name, exercise_name)
);
CREATE INDEX IF NOT EXISTS idx_personal_records_category ON personal_records(category);
CREATE INDEX IF NOT EXISTS idx_personal_records_date ON personal_records(date_set);
"""


class Database:
    """SQLite database manager."""

    def __init__(self, db_path: Path | str = ":memory:"):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file, or ":memory:" for in-memory.
        """
        self.db_path = Path(db_path) if db_path != ":memory:" else db_path
        self._connection: sqlite3.Connection | None = None

    @property
    def connection(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._connection is None:
            if self.db_path != ":memory:":
                # Ensure parent directory exists
                self.db_path.parent.mkdir(parents=True, exist_ok=True)

            self._connection = sqlite3.connect(
                str(self.db_path) if isinstance(self.db_path, Path) else self.db_path
            )
            self._connection.row_factory = sqlite3.Row
            # Enable foreign keys
            self._connection.execute("PRAGMA foreign_keys = ON")

            # Restrict database file to owner-only (0o600).
            if self.db_path != ":memory:":
                try:
                    Path(self.db_path).chmod(0o600)
                except OSError as e:
                    print(
                        f"Warning: could not set permissions on {self.db_path}: {e}",
                        file=sys.stderr,
                    )
        return self._connection

    def close(self) -> None:
        """Close the database connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def initialize(self) -> None:
        """Initialize database schema."""
        cursor = self.connection.cursor()
        cursor.executescript(SCHEMA_SQL)

        # Record schema version if not already present
        cursor.execute(
            "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,)
        )
        self.connection.commit()

    def get_schema_version(self) -> int | None:
        """Get current schema version."""
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT MAX(version) FROM schema_version")
            row = cursor.fetchone()
            return row[0] if row else None
        except sqlite3.OperationalError:
            return None

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        """Context manager for database transactions."""
        cursor = self.connection.cursor()
        try:
            yield cursor
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
        return cursor.fetchone() is not None

    def get_table_names(self) -> list[str]:
        """Get all table names in the database."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        return [row[0] for row in cursor.fetchall()]

    def migrate(self) -> None:
        """Run any pending migrations."""
        current_version = self.get_schema_version() or 0

        if current_version < 2:
            self._migrate_v1_to_v2()

        if current_version < 3:
            self._migrate_v2_to_v3()

        if current_version < 4:
            self._migrate_v3_to_v4()

        if current_version < 5:
            self._migrate_v4_to_v5()

    def _migrate_v1_to_v2(self) -> None:
        """Add hr_drift column to activities table."""
        cursor = self.connection.cursor()

        # Check if column already exists
        cursor.execute("PRAGMA table_info(activities)")
        columns = [row[1] for row in cursor.fetchall()]

        if "hr_drift" not in columns:
            cursor.execute("ALTER TABLE activities ADD COLUMN hr_drift REAL")

        # Update schema version
        cursor.execute(
            "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
            (2,)
        )
        self.connection.commit()

    def _migrate_v2_to_v3(self) -> None:
        """Add chat_messages table for AI conversation history."""
        cursor = self.connection.cursor()

        # Create chat_messages table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                message_type TEXT DEFAULT 'chat',
                token_estimate INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_messages_created "
            "ON chat_messages(created_at)"
        )

        # Update schema version
        cursor.execute(
            "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
            (3,)
        )
        self.connection.commit()

    def _migrate_v3_to_v4(self) -> None:
        """Add HEVY strength training tables."""
        cursor = self.connection.cursor()

        # Create hevy_workouts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hevy_workouts (
                id TEXT PRIMARY KEY,
                title TEXT,
                description TEXT,
                start_time TEXT,
                end_time TEXT,
                duration_seconds INTEGER,
                volume_kg REAL,
                set_count INTEGER,
                rep_count INTEGER,
                exercise_count INTEGER,
                raw_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_hevy_workouts_start "
            "ON hevy_workouts(start_time)"
        )

        # Create hevy_exercises table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hevy_exercises (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workout_id TEXT NOT NULL,
                exercise_template_id TEXT,
                exercise_name TEXT NOT NULL,
                exercise_type TEXT,
                muscle_group TEXT,
                superset_id INTEGER,
                exercise_order INTEGER,
                notes TEXT,
                FOREIGN KEY (workout_id) REFERENCES hevy_workouts(id)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_hevy_exercises_workout "
            "ON hevy_exercises(workout_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_hevy_exercises_name "
            "ON hevy_exercises(exercise_name)"
        )

        # Create hevy_sets table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hevy_sets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exercise_id INTEGER NOT NULL,
                set_index INTEGER,
                set_type TEXT,
                weight_kg REAL,
                reps INTEGER,
                distance_meters REAL,
                duration_seconds INTEGER,
                rpe REAL,
                is_pr INTEGER DEFAULT 0,
                FOREIGN KEY (exercise_id) REFERENCES hevy_exercises(id)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_hevy_sets_exercise "
            "ON hevy_sets(exercise_id)"
        )

        # Create hevy_exercise_templates table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hevy_exercise_templates (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                muscle_group TEXT,
                equipment TEXT,
                is_custom INTEGER DEFAULT 0
            )
        """)

        # Update schema version
        cursor.execute(
            "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
            (4,)
        )
        self.connection.commit()

    def _migrate_v4_to_v5(self) -> None:
        """Add personal_records table for PR tracking."""
        cursor = self.connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS personal_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                value REAL NOT NULL,
                previous_value REAL,
                activity_id TEXT,
                workout_id TEXT,
                exercise_name TEXT,
                date_set TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(category, metric_name, exercise_name)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_personal_records_category "
            "ON personal_records(category)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_personal_records_date "
            "ON personal_records(date_set)"
        )

        # Update schema version
        cursor.execute(
            "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
            (5,)
        )
        self.connection.commit()
