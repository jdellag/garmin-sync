"""Tests for AI analysis module."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from garmin_sync.ai.chat import ChatSession, DataFingerprint, CachedChatContext
from garmin_sync.ai.config import AIConfig, load_config, save_config, DEFAULT_SCHEDULE
from garmin_sync.ai.openai_client import analyze_fitness_data, OpenAIAnalysisError
from garmin_sync.ai.prompt_builder import (
    build_analysis_prompt,
    generate_baseline_summary,
    generate_detailed_7d,
)


class TestAIConfig:
    """Test AI configuration management."""

    def test_default_config(self):
        """Test default AIConfig values."""
        config = AIConfig()

        assert config.api_key is None
        assert config.model == "o3-mini"
        assert config.enabled is True
        assert config.schedule == DEFAULT_SCHEDULE
        assert config.user_context == ""

    def test_is_configured(self):
        """Test is_configured method."""
        config = AIConfig()
        assert not config.is_configured()

        config = AIConfig(api_key="sk-test-key")
        assert config.is_configured()

    def test_load_config_no_file(self, temp_dir):
        """Test loading config when file doesn't exist."""
        config_path = temp_dir / "nonexistent.toml"
        config = load_config(config_path)

        assert config.api_key is None
        assert config.model == "o3-mini"
        assert config.enabled is True

    def test_save_and_load_config(self, temp_dir):
        """Test saving and loading configuration."""
        config_path = temp_dir / "config.toml"

        # Create and save config
        config = AIConfig(
            api_key="sk-test-api-key",
            model="gpt-4o",
            enabled=False,
            schedule="Monday: Rest\nTuesday: Run",
            user_context="Training for marathon",
        )
        save_config(config, config_path)

        # Verify file exists
        assert config_path.exists()

        # Load and verify
        loaded = load_config(config_path)
        assert loaded.api_key == "sk-test-api-key"
        assert loaded.model == "gpt-4o"
        assert loaded.enabled is False
        assert loaded.schedule == "Monday: Rest\nTuesday: Run"
        assert loaded.user_context == "Training for marathon"

    def test_save_creates_directory(self, temp_dir):
        """Test that save_config creates parent directory."""
        config_path = temp_dir / "nested" / "path" / "config.toml"
        config = AIConfig(api_key="test-key")

        save_config(config, config_path)

        assert config_path.exists()
        assert config_path.parent.exists()


class TestPromptBuilder:
    """Test prompt building functions."""

    def test_build_analysis_prompt_basic(self):
        """Test basic prompt generation."""
        baseline = {"activities": {"total_count": 5}}
        detailed = {"current_status": {"hrv_last_night": 45}}

        # Jan 25, 2026 is a Sunday
        prompt = build_analysis_prompt(
            baseline_30d=baseline,
            detailed_7d=detailed,
            current_date=date(2026, 1, 25),
            user_schedule="Monday: Rest",
            user_context="Training for 5K",
        )

        assert "Sunday, January 25, 2026" in prompt
        assert "Monday: Rest" in prompt
        assert "Training for 5K" in prompt
        assert '"total_count": 5' in prompt
        assert '"hrv_last_night": 45' in prompt

    def test_build_analysis_prompt_empty_schedule(self):
        """Test prompt generation with empty schedule."""
        # Jan 25, 2026 is a Sunday
        prompt = build_analysis_prompt(
            baseline_30d={},
            detailed_7d={},
            current_date=date(2026, 1, 25),
            user_schedule="",
            user_context="",
        )

        assert "Sunday, January 25, 2026" in prompt
        assert "My Typical Weekly Schedule" not in prompt
        assert "Additional Context" not in prompt

    def test_generate_baseline_summary(self):
        """Test baseline summary generation."""
        weekly_json = {
            "summary": {
                "activities": 10,
                "duration_hours": 8.5,
                "distance_km": 50.0,
            },
            "recovery": {
                "hrv": {
                    "baseline_28d": 45.5,
                    "baseline_7d": 47.0,
                },
                "resting_hr": {
                    "baseline_28d": 52,
                    "trend": "stable",
                },
                "sleep": {
                    "avg_hours": 7.5,
                    "avg_score": 82,
                    "avg_deep_pct": 15.5,
                    "avg_rem_pct": 22.0,
                },
            },
            "training_load": {
                "chronic_28d": 150.0,
                "ac_ratio": 1.1,
            },
        }

        baseline = generate_baseline_summary(weekly_json)

        assert baseline["activities"]["total_count"] == 10
        assert baseline["activities"]["duration_hours"] == 8.5
        assert baseline["hrv"]["baseline_28d"] == 45.5
        assert baseline["resting_hr"]["baseline_28d"] == 52
        assert baseline["sleep"]["avg_hours"] == 7.5
        assert baseline["training_load"]["chronic_28d_weekly_avg"] == 150.0

    def test_generate_detailed_7d(self):
        """Test detailed 7-day data generation."""
        weekly_json = {
            "recovery": {
                "hrv": {
                    "last_night": 48,
                    "delta_pct": 5.2,
                    "days_below_baseline": 0,
                    "status": "BALANCED",
                    "daily": [{"date": "2026-01-25", "value": 48}],
                },
                "resting_hr": {
                    "current": 51,
                    "delta": -1,
                    "daily": [{"date": "2026-01-25", "value": 51}],
                },
                "training_readiness": {
                    "score": 78,
                    "level": "MODERATE",
                },
                "body_battery": {
                    "avg_morning_high": 85,
                    "avg_evening_low": 25,
                    "avg_overnight_recovery": 60,
                    "daily": [],
                },
                "sleep": {
                    "daily": [{"date": "2026-01-25", "hours": 7.5}],
                },
            },
            "training_load": {
                "acute_7d": 165.0,
                "this_week": 165.0,
                "prev_week": 150.0,
                "change_pct": 10.0,
                "by_type": {"running": {"load": 120}},
                "daily": [{"date": "2026-01-25", "load": 45}],
            },
            "activities": {
                "top_sessions": [{"name": "Morning Run", "distance_m": 8000}],
            },
            "alerts": [{"type": "hrv", "severity": "info", "message": "HRV normal"}],
        }

        detailed = generate_detailed_7d(weekly_json)

        assert detailed["current_status"]["hrv_last_night"] == 48
        assert detailed["current_status"]["training_readiness"]["score"] == 78
        assert detailed["training_load"]["acute_7d"] == 165.0
        assert detailed["body_battery"]["avg_morning_high"] == 85
        assert len(detailed["top_activities"]) == 1
        assert len(detailed["alerts"]) == 1


class TestOpenAIClient:
    """Test OpenAI client functions."""

    def test_analyze_fitness_data_success(self):
        """Test successful API call."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Your recovery looks good."

        with patch("garmin_sync.ai.openai_client.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            result = analyze_fitness_data(
                prompt="Test prompt",
                api_key="sk-test-key",
                model="gpt-4o",
            )

            assert result == "Your recovery looks good."
            mock_openai.assert_called_once_with(api_key="sk-test-key")

    def test_analyze_fitness_data_empty_response(self):
        """Test handling of empty response."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None

        with patch("garmin_sync.ai.openai_client.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response

            with pytest.raises(OpenAIAnalysisError, match="Empty response"):
                analyze_fitness_data(
                    prompt="Test prompt",
                    api_key="sk-test-key",
                )

    def test_analyze_fitness_data_api_error(self):
        """Test handling of API errors."""
        with patch("garmin_sync.ai.openai_client.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.side_effect = Exception("API rate limit")

            with pytest.raises(OpenAIAnalysisError, match="API rate limit"):
                analyze_fitness_data(
                    prompt="Test prompt",
                    api_key="sk-test-key",
                )


class TestAIIntegration:
    """Integration tests for AI module."""

    def test_full_workflow(self, temp_dir):
        """Test full AI analysis workflow."""
        # Setup config
        config_path = temp_dir / "config.toml"
        config = AIConfig(
            api_key="sk-test-key",
            model="gpt-4o",
            schedule="Monday: Rest\nTuesday: Intervals",
            user_context="Marathon training",
        )
        save_config(config, config_path)

        # Load config
        loaded_config = load_config(config_path)
        assert loaded_config.is_configured()

        # Build mock weekly data
        weekly_json = {
            "summary": {"activities": 5, "duration_hours": 6.0, "distance_km": 40.0},
            "recovery": {
                "hrv": {"baseline_28d": 45, "baseline_7d": 46, "last_night": 48,
                        "delta_pct": 4.3, "days_below_baseline": 0, "status": "BALANCED",
                        "daily": []},
                "resting_hr": {"baseline_28d": 52, "current": 51, "delta": -1,
                               "trend": "stable", "daily": []},
                "sleep": {"avg_hours": 7.5, "avg_score": 80, "avg_deep_pct": 15,
                          "avg_rem_pct": 22, "daily": []},
                "body_battery": {"avg_morning_high": 85, "avg_evening_low": 30,
                                  "avg_overnight_recovery": 55, "daily": []},
                "training_readiness": {"score": 75, "level": "MODERATE"},
            },
            "training_load": {"chronic_28d": 150, "ac_ratio": 1.1, "acute_7d": 165,
                              "this_week": 165, "prev_week": 150, "change_pct": 10,
                              "by_type": {}, "daily": []},
            "activities": {"top_sessions": []},
            "alerts": [],
        }

        # Generate data
        baseline = generate_baseline_summary(weekly_json)
        detailed = generate_detailed_7d(weekly_json)

        # Build prompt
        prompt = build_analysis_prompt(
            baseline_30d=baseline,
            detailed_7d=detailed,
            current_date=date(2026, 1, 25),
            user_schedule=loaded_config.schedule,
            user_context=loaded_config.user_context,
        )

        # Verify prompt contains all expected elements
        # Jan 25, 2026 is a Sunday
        assert "Sunday, January 25, 2026" in prompt
        assert "Monday: Rest" in prompt
        assert "Marathon training" in prompt
        assert "baseline_28d" in prompt


class TestChatSessionCaching:
    """Tests for ChatSession context caching."""

    @pytest.fixture
    def mock_repository(self):
        """Create a mock repository."""
        repo = MagicMock()
        repo.get_latest_sync_timestamp.return_value = "2026-03-15T10:00:00+00:00"
        repo.get_hevy_workout_count.return_value = 3
        repo.get_chat_history.return_value = []
        repo.get_chat_token_total.return_value = 0
        repo.get_activities.return_value = []
        repo.get_hevy_workout_details.return_value = []
        repo.get_activities_by_local_date.return_value = []
        return repo

    @pytest.fixture
    def chat_session(self, mock_repository, temp_dir):
        """Create a ChatSession with mock dependencies."""
        config = AIConfig(
            api_key="sk-test-key",
            model="gpt-4o",
            schedule="Monday: Rest",
            user_context="Test context",
        )
        return ChatSession(
            repository=mock_repository,
            ai_config=config,
            reports_dir=temp_dir,
        )

    def test_cache_initially_none(self, chat_session):
        """Test that cache is None when session is created."""
        assert chat_session._cached_context is None

    def test_cache_built_on_first_call(self, chat_session):
        """Test that cache is built on first build_context_messages call."""
        assert chat_session._cached_context is None

        messages = chat_session.build_context_messages()

        assert chat_session._cached_context is not None
        assert len(messages) > 0
        assert messages[0]["role"] == "system"

    def test_cache_reused_on_subsequent_calls(self, chat_session):
        """Test that cache is reused when data hasn't changed."""
        # Build cache
        chat_session.build_context_messages()
        first_cache = chat_session._cached_context
        first_timestamp = first_cache.cache_timestamp

        # Call again
        chat_session.build_context_messages()
        second_cache = chat_session._cached_context

        # Cache should be the same object (same timestamp)
        assert second_cache.cache_timestamp == first_timestamp

    def test_cache_invalidated_on_sync_timestamp_change(self, chat_session, mock_repository):
        """Test that cache is invalidated when sync timestamp changes."""
        # Build initial cache
        chat_session.build_context_messages()
        first_timestamp = chat_session._cached_context.cache_timestamp

        # Simulate a new sync
        mock_repository.get_latest_sync_timestamp.return_value = "2026-03-15T12:00:00+00:00"

        # Build context again
        chat_session.build_context_messages()
        second_timestamp = chat_session._cached_context.cache_timestamp

        # Cache should have been rebuilt (new timestamp)
        assert second_timestamp > first_timestamp

    def test_cache_invalidated_on_hevy_count_change(self, chat_session, mock_repository):
        """Test that cache is invalidated when HEVY workout count changes."""
        # Build initial cache
        chat_session.build_context_messages()
        first_timestamp = chat_session._cached_context.cache_timestamp

        # Simulate new HEVY workout
        mock_repository.get_hevy_workout_count.return_value = 4

        # Build context again
        chat_session.build_context_messages()
        second_timestamp = chat_session._cached_context.cache_timestamp

        # Cache should have been rebuilt
        assert second_timestamp > first_timestamp

    def test_cache_invalidated_on_analysis_file_change(self, chat_session, temp_dir):
        """Test that cache is invalidated when an analysis file is modified."""
        # Create an analysis file
        today = date.today()
        report_date = today - timedelta(days=1)
        report_path = temp_dir / f"analysis-{report_date.isoformat()}.md"
        report_path.write_text("Initial content")

        # Build initial cache
        chat_session.build_context_messages()
        first_timestamp = chat_session._cached_context.cache_timestamp

        # Modify the file
        import time
        time.sleep(0.01)  # Ensure mtime changes
        report_path.write_text("Updated content")

        # Build context again
        chat_session.build_context_messages()
        second_timestamp = chat_session._cached_context.cache_timestamp

        # Cache should have been rebuilt
        assert second_timestamp > first_timestamp

    def test_clear_history_invalidates_cache(self, chat_session):
        """Test that clear_history invalidates the cache."""
        # Build cache
        chat_session.build_context_messages()
        assert chat_session._cached_context is not None

        # Clear history
        chat_session.clear_history()

        # Cache should be None
        assert chat_session._cached_context is None

    def test_context_summary_includes_cache_age(self, chat_session):
        """Test that get_context_summary includes cache age."""
        # Before any cache
        summary = chat_session.get_context_summary()
        assert summary["cache_age_seconds"] is None

        # Build cache
        chat_session.build_context_messages()

        # Check summary includes cache age
        summary = chat_session.get_context_summary()
        assert summary["cache_age_seconds"] is not None
        assert summary["cache_age_seconds"] >= 0

    def test_cached_context_contains_all_components(self, chat_session, temp_dir, mock_repository):
        """Test that cached context contains all expected components."""
        # Create analysis file
        today = date.today()
        report_date = today - timedelta(days=1)
        report_path = temp_dir / f"analysis-{report_date.isoformat()}.md"
        report_path.write_text("Test analysis content")

        # Add mock activities and workouts
        mock_activity = MagicMock()
        mock_activity.activity_name = "Morning Run"
        mock_activity.activity_type = "running"
        mock_activity.start_time = "2026-03-14T08:00:00"
        mock_activity.start_time_local = "2026-03-14T08:00:00"
        mock_activity.duration_seconds = 1800
        mock_activity.distance_meters = 5000
        mock_activity.average_hr = 150
        mock_activity.max_hr = 175
        mock_activity.training_effect_aerobic = 3.0
        mock_activity.training_effect_anaerobic = 1.0
        mock_activity.training_load = 45
        mock_activity.hr_drift = 0.03
        mock_activity.elevation_gain_meters = 50
        mock_activity.avg_cadence = 170
        mock_activity.calories = 350
        mock_repository.get_activities.return_value = [mock_activity]

        mock_repository.get_hevy_workout_details.return_value = [{
            "date": "2026-03-13",
            "time": "17:00",
            "title": "Push Day",
            "duration_minutes": 45,
            "total_volume_lbs": 12500,
            "exercises": [{"name": "Bench Press", "muscle_group": "chest", "sets": "135×10"}],
        }]

        # Build context
        messages = chat_session.build_context_messages()
        cache = chat_session._cached_context

        # Verify cache structure
        assert cache.system_message != ""
        assert len(cache.analyses_messages) == 2  # user + assistant
        assert len(cache.garmin_messages) == 2  # user + assistant
        assert len(cache.hevy_messages) == 2  # user + assistant
        assert cache.token_count > 0
        assert cache.data_fingerprint is not None

    def test_fingerprint_equality(self):
        """Test DataFingerprint equality comparison."""
        fp1 = DataFingerprint(
            last_sync_timestamp="2026-03-15T10:00:00+00:00",
            analysis_file_mtimes={"/path/to/file.md": 1234567890.0},
            hevy_workout_count=3,
        )
        fp2 = DataFingerprint(
            last_sync_timestamp="2026-03-15T10:00:00+00:00",
            analysis_file_mtimes={"/path/to/file.md": 1234567890.0},
            hevy_workout_count=3,
        )
        fp3 = DataFingerprint(
            last_sync_timestamp="2026-03-15T11:00:00+00:00",
            analysis_file_mtimes={"/path/to/file.md": 1234567890.0},
            hevy_workout_count=3,
        )

        # Same values should be equal
        assert fp1.last_sync_timestamp == fp2.last_sync_timestamp
        assert fp1.analysis_file_mtimes == fp2.analysis_file_mtimes
        assert fp1.hevy_workout_count == fp2.hevy_workout_count

        # Different sync timestamp should differ
        assert fp1.last_sync_timestamp != fp3.last_sync_timestamp

    def test_is_cache_valid_returns_false_when_none(self, chat_session):
        """Test _is_cache_valid returns False when cache is None."""
        assert chat_session._cached_context is None
        assert chat_session._is_cache_valid() is False

    def test_is_cache_valid_returns_true_when_unchanged(self, chat_session):
        """Test _is_cache_valid returns True when data unchanged."""
        chat_session.build_context_messages()
        assert chat_session._is_cache_valid() is True

    def test_chat_history_always_fresh(self, chat_session, mock_repository):
        """Test that chat history is always fetched fresh, not cached."""
        # Build cache
        chat_session.build_context_messages()

        # Add a chat message to the mock
        mock_chat_msg = MagicMock()
        mock_chat_msg.role = "user"
        mock_chat_msg.content = "Hello"
        mock_chat_msg.token_estimate = 5
        mock_repository.get_chat_history.return_value = [mock_chat_msg]

        # Build context again (cache should be reused, but chat history fresh)
        messages = chat_session.build_context_messages()

        # Should include the new chat message
        assert any(m.get("content") == "Hello" for m in messages)
