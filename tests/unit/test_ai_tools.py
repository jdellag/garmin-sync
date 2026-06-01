"""Tests for AI tool calling integration."""

import json
import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch, call

from garmin_sync.db.database import Database
from garmin_sync.db.models import Activity
from garmin_sync.db.repository import Repository
from garmin_sync.reports.aggregators import DataAggregator
from garmin_sync.tools.executor import ToolExecutor
from garmin_sync.ai.tools import TOOLS, get_tool_names


class TestToolDefinitions:
    """Test OpenAI tool schema definitions."""

    def test_tools_is_list(self):
        """Test that TOOLS is a non-empty list."""
        assert isinstance(TOOLS, list)
        assert len(TOOLS) == 12

    def test_all_tools_have_required_structure(self):
        """Test that all tools have correct OpenAI function schema structure."""
        for tool in TOOLS:
            assert tool["type"] == "function"
            assert "function" in tool
            func = tool["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func
            assert func["parameters"]["type"] == "object"

    def test_tool_names_match(self):
        """Test that get_tool_names returns correct names."""
        names = get_tool_names()
        assert len(names) == 12
        assert "get_recent_activities" in names
        assert "get_recovery_status" in names
        assert "get_training_load_analysis" in names
        assert "get_strength_training_summary" in names
        assert "get_exercise_progression" in names
        assert "get_workout_details" in names
        assert "get_weekly_comparison" in names
        assert "get_cardio_performance" in names
        assert "get_longitudinal_summary" in names
        assert "get_anomaly_report" in names
        assert "get_periodization_status" in names
        assert "sync_garmin_data" in names

    def test_get_exercise_progression_has_required_param(self):
        """Test that exercise_name is required for get_exercise_progression."""
        for tool in TOOLS:
            if tool["function"]["name"] == "get_exercise_progression":
                params = tool["function"]["parameters"]
                assert "exercise_name" in params.get("required", [])


class TestToolExecutor:
    """Test ToolExecutor class."""

    @pytest.fixture
    def mock_repo(self):
        """Create mock repository."""
        repo = MagicMock()
        repo.get_latest_sync_timestamp.return_value = "2026-03-16T10:00:00Z"
        repo.get_hevy_workout_count.return_value = 0
        repo.get_recent_prs.return_value = []
        repo.db = MagicMock()
        return repo

    @pytest.fixture
    def mock_aggregator(self):
        """Create mock aggregator."""
        agg = MagicMock()
        agg.get_hrv_context.return_value = {
            "baseline_7d": 65,
            "last_night": 62,
            "delta_from_baseline": -4.6,
            "status": "BALANCED",
            "days_below_baseline": 1,
        }
        agg.get_sleep_consistency.return_value = {
            "avg_sleep_seconds": 28800,
            "sleep_time_variance_mins": 30,
            "avg_deep_pct": 18.5,
            "avg_rem_pct": 22.0,
        }
        agg.get_body_battery_recovery.return_value = {
            "avg_overnight_recovery": 60,
            "avg_morning_high": 85,
        }
        agg.get_resting_hr_trend.return_value = {
            "current": 48,
            "baseline_28d": 50,
            "delta": -2,
            "trend": "falling",
        }
        agg.get_training_readiness_latest.return_value = {
            "score": 75,
            "level": "MODERATE",
        }
        agg.get_training_load_trend.return_value = {
            "acute_load_7d": 200,
            "chronic_load_28d": 220,
            "acute_chronic_ratio": 0.91,
            "week_change_pct": 5.0,
            "by_type": {"running": {"load": 150, "count": 3}},
        }
        agg.get_strength_volume_summary.return_value = {
            "total_sessions": 3,
            "total_volume_kg": 5000,
            "total_sets": 45,
            "by_muscle_group": {"chest": {"volume_kg": 1500, "sets": 12}},
            "recent_workouts": [],
        }
        agg.get_strength_exercise_progression.return_value = {
            "exercise": "Bench Press",
            "sessions": [{"date": "2026-03-15", "max_weight": 80, "est_1rm": 90}],
            "current_1rm": 90,
            "progression_pct": 5.0,
        }
        agg.get_rpe_analysis.return_value = {
            "sessions": [],
            "overall_avg_rpe": None,
            "rpe_coverage_pct": 0.0,
            "overreaching_flag": False,
        }
        agg.get_exercise_rpe_trend.return_value = {
            "sessions": [],
            "rpe_trend": None,
        }
        agg.get_stress_recovery_correlation.return_value = {
            "days_analyzed": 0,
            "avg_stress_training_days": None,
            "avg_stress_rest_days": None,
            "high_stress_poor_recovery_days": 0,
            "patterns": [],
        }
        agg.get_sleep_performance_correlation.return_value = {
            "data_points": 0,
            "sleep_score_stats": None,
            "by_sleep_grade": {},
            "hrv_performance_link": None,
            "insight": None,
        }
        agg.get_strength_prs.return_value = []
        mock_comparison = MagicMock()
        mock_comparison.current = {"activities": 5}
        mock_comparison.previous = {"activities": 4}
        mock_comparison.changes = {"activities": 25.0}
        agg.get_weekly_comparison.return_value = mock_comparison
        return agg

    @pytest.fixture
    def executor(self, mock_repo, mock_aggregator):
        """Create ToolExecutor with mocks."""
        return ToolExecutor(mock_repo, mock_aggregator)

    def test_execute_dispatches_to_method(self, executor, mock_repo):
        """Test that execute dispatches to correct method."""
        mock_repo.get_activities.return_value = []
        result = executor.execute("get_recent_activities", {"days": 7})
        assert isinstance(result, list)

    def test_execute_unknown_tool_raises(self, executor):
        """Test that unknown tool raises ValueError."""
        with pytest.raises(ValueError, match="Unknown tool"):
            executor.execute("unknown_tool", {})

    def test_get_recent_activities(self, executor, mock_repo):
        """Test get_recent_activities returns serialized activities."""
        mock_activity = Activity(
            activity_id="123",
            activity_name="Morning Run",
            activity_type="running",
            start_time="2026-03-16T07:00:00Z",
            duration_seconds=3600,
            distance_meters=10000,
            average_hr=145,
            max_hr=165,
            training_load=75.5,
        )
        mock_repo.get_activities.return_value = [mock_activity]

        result = executor.get_recent_activities(days=7)

        assert len(result) == 1
        assert result[0]["activity_id"] == "123"
        assert result[0]["name"] == "Morning Run"
        assert result[0]["type"] == "running"
        # Should have calculated pace for running
        assert "pace_min_per_km" in result[0]

    def test_get_recovery_status(self, executor):
        """Test get_recovery_status aggregates metrics."""
        result = executor.get_recovery_status()

        assert "hrv" in result
        assert "sleep" in result
        assert "body_battery" in result
        assert "resting_hr" in result
        assert "training_readiness" in result
        assert "last_sync" in result

    def test_get_training_load_analysis(self, executor):
        """Test get_training_load_analysis returns risk assessment."""
        result = executor.get_training_load_analysis()

        assert result["acute_load_7d"] == 200
        assert result["chronic_load_28d"] == 220
        assert result["acute_chronic_ratio"] == 0.91
        assert result["risk_assessment"] == "optimal"

    def test_get_strength_training_summary(self, executor, mock_repo):
        """Test get_strength_training_summary with data."""
        mock_repo.get_hevy_workout_count.return_value = 3

        result = executor.get_strength_training_summary(days=7)

        assert result["configured"] is True
        assert result["total_sessions"] == 3
        assert result["total_volume_lbs"] > 0  # Converted from kg
        assert "by_muscle_group" in result

    def test_get_strength_training_summary_no_data(self, executor, mock_repo):
        """Test get_strength_training_summary with no workouts."""
        mock_repo.get_hevy_workout_count.return_value = 0

        result = executor.get_strength_training_summary(days=7)

        assert result["total_sessions"] == 0
        assert "message" in result

    def test_get_exercise_progression(self, executor):
        """Test get_exercise_progression returns progression data."""
        result = executor.get_exercise_progression("Bench Press", days=90)

        assert result["exercise"] == "Bench Press"
        assert result["found"] is True
        assert len(result["sessions"]) == 1
        assert result["current_1rm_lbs"] == 198  # 90 kg * 2.20462

    def test_get_workout_details(self, executor, mock_repo):
        """Test get_workout_details delegates to repository."""
        mock_repo.get_hevy_workout_details.return_value = [{"title": "Push"}]

        result = executor.get_workout_details(days=7)

        assert len(result) == 1
        assert result[0]["title"] == "Push"
        mock_repo.get_hevy_workout_details.assert_called_once_with(days=7)

    def test_get_weekly_comparison(self, executor):
        """Test get_weekly_comparison returns comparison data."""
        result = executor.get_weekly_comparison()

        assert "current_week" in result
        assert "previous_week" in result
        assert "changes_pct" in result

    def test_sync_garmin_data(self, executor, mock_repo):
        """Test sync_garmin_data calls sync manager."""
        mock_sync_result = MagicMock()
        mock_sync_result.records_synced = 5
        mock_sync_result.errors = []

        mock_sync_manager = MagicMock()
        mock_sync_manager.sync_all.return_value = {"activities": mock_sync_result}

        with patch("garmin_sync.sync.sync_manager.SyncManager", return_value=mock_sync_manager):
            result = executor.sync_garmin_data(days=1)

        assert result["success"] is True
        assert result["synced"]["activities"] == 5


class TestChatWithTools:
    """Test chat_with_tools function."""

    @pytest.fixture
    def mock_executor(self):
        """Create mock tool executor."""
        executor = MagicMock()
        executor.execute.return_value = {"result": "test data"}
        return executor

    def test_chat_with_tools_no_tool_calls(self):
        """Test chat_with_tools when model doesn't call tools."""
        from garmin_sync.ai.openai_client import chat_with_tools

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Here is my response"
        mock_response.choices[0].message.tool_calls = None

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch("garmin_sync.ai.openai_client.OpenAI", return_value=mock_client):
            result = chat_with_tools(
                messages=[{"role": "user", "content": "Hello"}],
                tools=TOOLS,
                api_key="test-key",
            )

        assert result == "Here is my response"

    def test_chat_with_tools_with_tool_call(self, mock_executor):
        """Test chat_with_tools when model makes a tool call."""
        from garmin_sync.ai.openai_client import chat_with_tools

        # First response has a tool call
        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function.name = "get_recovery_status"
        tool_call.function.arguments = "{}"

        first_response = MagicMock()
        first_response.choices = [MagicMock()]
        first_response.choices[0].message.content = None
        first_response.choices[0].message.tool_calls = [tool_call]

        # Second response is final
        second_response = MagicMock()
        second_response.choices = [MagicMock()]
        second_response.choices[0].message.content = "Based on the data..."
        second_response.choices[0].message.tool_calls = None

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [first_response, second_response]

        with patch("garmin_sync.ai.openai_client.OpenAI", return_value=mock_client):
            result = chat_with_tools(
                messages=[{"role": "user", "content": "What's my recovery status?"}],
                tools=TOOLS,
                api_key="test-key",
                tool_executor=mock_executor,
            )

        assert result == "Based on the data..."
        mock_executor.execute.assert_called_once_with("get_recovery_status", {})

    def test_chat_with_tools_malformed_json_arguments(self, mock_executor):
        """A tool call with invalid JSON arguments must not crash the turn: it
        yields a synthetic error result for its tool_call_id so the model can
        recover. Regression for json.loads sitting outside the try/except."""
        from garmin_sync.ai.openai_client import chat_with_tools

        bad_call = MagicMock()
        bad_call.id = "call_bad"
        bad_call.function.name = "get_recovery_status"
        bad_call.function.arguments = "{not valid json"  # malformed

        first_response = MagicMock()
        first_response.choices = [MagicMock()]
        first_response.choices[0].message.content = None
        first_response.choices[0].message.tool_calls = [bad_call]

        second_response = MagicMock()
        second_response.choices = [MagicMock()]
        second_response.choices[0].message.content = "Recovered."
        second_response.choices[0].message.tool_calls = None

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [first_response, second_response]

        with patch("garmin_sync.ai.openai_client.OpenAI", return_value=mock_client):
            result = chat_with_tools(
                messages=[{"role": "user", "content": "status?"}],
                tools=TOOLS,
                api_key="test-key",
                tool_executor=mock_executor,
            )

        assert result == "Recovered."             # turn survived, no exception
        mock_executor.execute.assert_not_called()  # never reached execution
        # The follow-up request must still answer the bad call's tool_call_id.
        second_messages = mock_client.chat.completions.create.call_args_list[1].kwargs["messages"]
        tool_msgs = [m for m in second_messages if m.get("role") == "tool"]
        assert any(m["tool_call_id"] == "call_bad" for m in tool_msgs)
        assert any("invalid JSON" in m["content"] for m in tool_msgs)

    def test_chat_with_tools_max_calls_limit(self, mock_executor):
        """Test that tool calls are limited to max_tool_calls."""
        from garmin_sync.ai.openai_client import chat_with_tools

        # Create tool call response
        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function.name = "get_recovery_status"
        tool_call.function.arguments = "{}"

        tool_response = MagicMock()
        tool_response.choices = [MagicMock()]
        tool_response.choices[0].message.content = None
        tool_response.choices[0].message.tool_calls = [tool_call]

        # Final response without tools
        final_response = MagicMock()
        final_response.choices = [MagicMock()]
        final_response.choices[0].message.content = "Final answer"
        final_response.choices[0].message.tool_calls = None

        mock_client = MagicMock()
        # Return tool responses until limit, then final
        mock_client.chat.completions.create.side_effect = [
            tool_response, tool_response, tool_response, final_response
        ]

        with patch("garmin_sync.ai.openai_client.OpenAI", return_value=mock_client):
            result = chat_with_tools(
                messages=[{"role": "user", "content": "Test"}],
                tools=TOOLS,
                api_key="test-key",
                tool_executor=mock_executor,
                max_tool_calls=3,
            )

        assert result == "Final answer"
        assert mock_executor.execute.call_count == 3

    def test_chat_with_tools_no_executor_raises(self):
        """Test that missing executor raises when tools are called."""
        from garmin_sync.ai.openai_client import chat_with_tools, OpenAIAnalysisError

        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function.name = "get_recovery_status"
        tool_call.function.arguments = "{}"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None
        mock_response.choices[0].message.tool_calls = [tool_call]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch("garmin_sync.ai.openai_client.OpenAI", return_value=mock_client):
            # ValueError gets wrapped in OpenAIAnalysisError
            with pytest.raises(OpenAIAnalysisError, match="no tool_executor provided"):
                chat_with_tools(
                    messages=[{"role": "user", "content": "Test"}],
                    tools=TOOLS,
                    api_key="test-key",
                    tool_executor=None,
                )

    def test_chat_with_tools_handles_tool_error(self, mock_executor):
        """Test that tool execution errors are handled gracefully."""
        from garmin_sync.ai.openai_client import chat_with_tools

        mock_executor.execute.side_effect = Exception("Tool failed")

        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function.name = "get_recovery_status"
        tool_call.function.arguments = "{}"

        first_response = MagicMock()
        first_response.choices = [MagicMock()]
        first_response.choices[0].message.content = None
        first_response.choices[0].message.tool_calls = [tool_call]

        second_response = MagicMock()
        second_response.choices = [MagicMock()]
        second_response.choices[0].message.content = "Sorry, there was an error"
        second_response.choices[0].message.tool_calls = None

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [first_response, second_response]

        with patch("garmin_sync.ai.openai_client.OpenAI", return_value=mock_client):
            result = chat_with_tools(
                messages=[{"role": "user", "content": "Test"}],
                tools=TOOLS,
                api_key="test-key",
                tool_executor=mock_executor,
            )

        assert result == "Sorry, there was an error"


class TestChatSessionWithTools:
    """Test ChatSession tool calling integration."""

    @pytest.fixture
    def db(self):
        """Create in-memory database."""
        db = Database(":memory:")
        db.initialize()
        db.migrate()
        return db

    @pytest.fixture
    def repo(self, db):
        """Create repository."""
        return Repository(db)

    @pytest.fixture
    def ai_config(self):
        """Create AI config with tools enabled."""
        from garmin_sync.ai.config import AIConfig
        return AIConfig(
            api_key="test-key",
            model="o3-mini",
            use_tools=True,
        )

    @pytest.fixture
    def session(self, repo, ai_config, tmp_path):
        """Create chat session."""
        from garmin_sync.ai.chat import ChatSession
        return ChatSession(
            repository=repo,
            ai_config=ai_config,
            reports_dir=tmp_path,
        )

    def test_session_tools_enabled_by_default(self, session):
        """Test that tools are enabled by default when config says so."""
        assert session.use_tools is True

    def test_session_tools_toggle(self, session):
        """Test that tools can be toggled."""
        session.use_tools = False
        assert session.use_tools is False
        session.use_tools = True
        assert session.use_tools is True

    def test_context_summary_includes_tool_status(self, session):
        """Test that context summary includes tool information."""
        ctx = session.get_context_summary()

        assert "tools_enabled" in ctx
        assert "tool_count" in ctx
        # bumped to 12 after adding anomaly_report + periodization_status
        assert ctx["tools_enabled"] is True
        assert ctx["tool_count"] == 12

    def test_context_summary_tools_disabled(self, session):
        """Test context summary when tools are disabled."""
        session.use_tools = False
        ctx = session.get_context_summary()

        assert ctx["tools_enabled"] is False
        assert ctx["tool_count"] == 0

    def test_tool_executor_lazy_init(self, session):
        """Test that tool executor is lazily initialized."""
        # Accessing tool_executor should create it
        executor = session.tool_executor
        assert isinstance(executor, ToolExecutor)

        # Second access should return same instance
        assert session.tool_executor is executor

    def test_system_message_changes_with_tools(self, session):
        """Test that system message changes based on tool status."""
        from garmin_sync.ai.openai_client import (
            COACH_SYSTEM_MESSAGE,
            COACH_SYSTEM_MESSAGE_WITH_TOOLS,
        )

        # With tools enabled
        session.use_tools = True
        session._cached_context = None  # Force rebuild
        messages = session.build_context_messages()
        system_msg = messages[0]["content"]
        assert "tools" in system_msg.lower()

        # With tools disabled
        session.use_tools = False
        session._cached_context = None  # Force rebuild
        messages = session.build_context_messages()
        system_msg = messages[0]["content"]
        assert "tools" not in system_msg.lower() or "access to tools" not in system_msg.lower()


class TestAIConfigWithTools:
    """Test AIConfig use_tools setting."""

    def test_default_use_tools_is_true(self):
        """Test that use_tools defaults to True."""
        from garmin_sync.ai.config import AIConfig
        config = AIConfig()
        assert config.use_tools is True

    def test_load_config_with_use_tools(self, tmp_path):
        """Test loading config with use_tools setting."""
        from garmin_sync.ai.config import load_config, save_config, AIConfig

        config_path = tmp_path / "config.toml"

        # Save config with use_tools=False
        config = AIConfig(api_key="test", use_tools=False)
        save_config(config, config_path)

        # Load and verify
        loaded = load_config(config_path)
        assert loaded.use_tools is False

    def test_save_config_includes_use_tools(self, tmp_path):
        """Test that save_config includes use_tools."""
        from garmin_sync.ai.config import load_config, save_config, AIConfig

        config_path = tmp_path / "config.toml"

        config = AIConfig(api_key="test", use_tools=True)
        save_config(config, config_path)

        # Read raw content
        content = config_path.read_text()
        assert "use_tools" in content


class TestToolModelDefault:
    """Test that tool calling uses gpt-5.4 by default."""

    def test_default_tool_model_is_gpt_5_4(self):
        """Test that DEFAULT_TOOL_MODEL is gpt-5.4."""
        from garmin_sync.ai.openai_client import DEFAULT_TOOL_MODEL
        assert DEFAULT_TOOL_MODEL == "gpt-5.4"

    def test_chat_with_tools_uses_default_model(self):
        """Test that chat_with_tools uses gpt-5.4 when model is None."""
        from garmin_sync.ai.openai_client import chat_with_tools

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response"
        mock_response.choices[0].message.tool_calls = None

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch("garmin_sync.ai.openai_client.OpenAI", return_value=mock_client):
            chat_with_tools(
                messages=[{"role": "user", "content": "Test"}],
                tools=TOOLS,
                api_key="test-key",
                model=None,  # Should use default
            )

        # Check the model used
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "gpt-5.4"


class TestLongitudinalTool:
    """Test get_longitudinal_summary at the executor + schema level."""

    def test_schema_no_required_args(self):
        """Tool should be callable with no arguments."""
        for tool in TOOLS:
            if tool["function"]["name"] == "get_longitudinal_summary":
                assert tool["function"]["parameters"].get("required", []) == []
                props = tool["function"]["parameters"]["properties"]
                assert "start_year" in props
                assert "end_year" in props
                assert "granularity" in props
                return
        raise AssertionError("get_longitudinal_summary not in TOOLS")

    def test_executor_composes_dict_with_expected_keys(self):
        """Executor should call all four aggregator methods and return composed dict."""
        from garmin_sync.tools.executor import ToolExecutor

        repo = MagicMock()
        repo.db = MagicMock()
        # Stub the MIN(date) lookup for default start_year resolution
        cursor = MagicMock()
        cursor.fetchone.return_value = {"d": "2022-01-01"}
        repo.db.connection.cursor.return_value = cursor

        agg = MagicMock()
        agg.get_aerobic_efficiency_by_period.return_value = {"granularity": "year", "periods": []}
        agg.get_yearly_health_baselines.return_value = {"years": []}
        agg.get_volume_by_period.return_value = {"granularity": "year", "periods": []}
        agg.get_hr_drift_by_period.return_value = {"periods": []}

        executor = ToolExecutor(repo, agg)
        result = executor.get_longitudinal_summary()

        assert set(result.keys()) == {
            "aerobic_efficiency",
            "health_baselines",
            "volume",
            "hr_drift",
            "range",
        }
        assert result["range"]["start_year"] == 2022
        assert result["range"]["granularity"] == "year"
        agg.get_aerobic_efficiency_by_period.assert_called_once()
        agg.get_yearly_health_baselines.assert_called_once()
        agg.get_volume_by_period.assert_called_once()
        agg.get_hr_drift_by_period.assert_called_once()

    def test_executor_rejects_invalid_granularity(self):
        """Invalid granularity falls back to 'year' rather than raising."""
        from garmin_sync.tools.executor import ToolExecutor

        repo = MagicMock()
        repo.db = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = {"d": "2023-01-01"}
        repo.db.connection.cursor.return_value = cursor

        agg = MagicMock()
        agg.get_aerobic_efficiency_by_period.return_value = {"granularity": "year", "periods": []}
        agg.get_yearly_health_baselines.return_value = {"years": []}
        agg.get_volume_by_period.return_value = {"granularity": "year", "periods": []}
        agg.get_hr_drift_by_period.return_value = {"periods": []}

        executor = ToolExecutor(repo, agg)
        result = executor.get_longitudinal_summary(granularity="month")

        assert result["range"]["granularity"] == "year"


class TestToolExecutorExecutionPaths:
    """Test individual tool execution paths."""

    @pytest.fixture
    def mock_repo(self):
        """Create mock repository."""
        repo = MagicMock()
        repo.get_latest_sync_timestamp.return_value = "2026-03-16T10:00:00Z"
        repo.get_hevy_workout_count.return_value = 0
        repo.get_recent_prs.return_value = []
        repo.db = MagicMock()
        return repo

    @pytest.fixture
    def mock_aggregator(self):
        """Create mock aggregator."""
        agg = MagicMock()
        agg.get_hrv_context.return_value = {
            "baseline_7d": 65,
            "last_night": 62,
            "delta_from_baseline": -4.6,
            "status": "BALANCED",
            "days_below_baseline": 1,
        }
        agg.get_sleep_consistency.return_value = {
            "avg_sleep_seconds": 28800,
            "sleep_time_variance_mins": 30,
            "avg_deep_pct": 18.5,
            "avg_rem_pct": 22.0,
        }
        agg.get_body_battery_recovery.return_value = {
            "avg_overnight_recovery": 60,
            "avg_morning_high": 85,
        }
        agg.get_resting_hr_trend.return_value = {
            "current": 48,
            "baseline_28d": 50,
            "delta": -2,
            "trend": "falling",
        }
        agg.get_training_readiness_latest.return_value = {
            "score": 75,
            "level": "MODERATE",
        }
        agg.get_training_load_trend.return_value = {
            "acute_load_7d": 200,
            "chronic_load_28d": 220,
            "acute_chronic_ratio": 0.91,
            "week_change_pct": 5.0,
            "by_type": {"running": {"load": 150, "count": 3}},
        }
        agg.get_sleep_respiration_trends.return_value = {}
        agg.get_allday_respiration_spo2.return_value = {}
        agg.get_stress_recovery_correlation.return_value = {}
        agg.get_sleep_performance_correlation.return_value = {}
        return agg

    @pytest.fixture
    def executor(self, mock_repo, mock_aggregator):
        """Create ToolExecutor with mocks."""
        return ToolExecutor(mock_repo, mock_aggregator)

    @patch("garmin_sync.reports.anomaly_detector.AnomalyDetector")
    def test_get_recovery_status_includes_anomaly_enrichment(
        self, mock_detector_cls, executor
    ):
        """Test that recovery status includes anomalies when present."""
        mock_detector_cls.return_value.detect_anomalies.return_value = [
            {"check": "hrv_crash", "severity": "warning", "message": "test", "data": {}},
        ]
        result = executor.get_recovery_status()
        assert len(result["anomalies"]) == 1

    @patch("garmin_sync.reports.anomaly_detector.AnomalyDetector")
    def test_get_recovery_status_anomaly_failure_surfaces_error(
        self, mock_detector_cls, executor
    ):
        """Test that anomaly detection failure surfaces an error key."""
        mock_detector_cls.side_effect = RuntimeError("boom")
        result = executor.get_recovery_status()
        assert "anomaly_error" in result
        assert "anomalies" not in result

    @patch("garmin_sync.reports.anomaly_detector.AnomalyDetector")
    def test_get_anomaly_report_returns_structured_summary(
        self, mock_detector_cls, executor
    ):
        """Test that anomaly report returns correct summary counts."""
        mock_detector_cls.return_value.detect_anomalies.return_value = [
            {"check": "training_overload", "severity": "critical", "message": "A:C > 1.5", "data": {}},
            {"check": "hrv_crash", "severity": "warning", "message": "HRV dropped", "data": {}},
            {"check": "rhr_spike", "severity": "warning", "message": "RHR elevated", "data": {}},
        ]
        result = executor.get_anomaly_report()
        assert result["total"] == 3
        assert result["summary"]["critical"] == 1
        assert result["summary"]["warning"] == 2

    @patch("garmin_sync.reports.anomaly_detector.AnomalyDetector")
    def test_get_anomaly_report_empty_when_healthy(self, mock_detector_cls, executor):
        """Test that anomaly report is empty when no anomalies detected."""
        mock_detector_cls.return_value.detect_anomalies.return_value = []
        result = executor.get_anomaly_report()
        assert result["total"] == 0
        assert result["anomalies"] == []

    @patch("garmin_sync.reports.periodization.PeriodizationAnalyzer")
    def test_get_periodization_status_returns_all_sections(
        self, mock_analyzer_cls, executor
    ):
        """Test that periodization status returns phase, readiness, and deload."""
        mock_analyzer_cls.return_value.get_periodization_summary.return_value = {
            "phase": {"phase": "build"},
            "readiness": {"score": 72},
            "deload": {"recommended": False},
        }
        result = executor.get_periodization_status()
        assert "phase" in result
        assert result["phase"]["phase"] == "build"
        assert "readiness" in result
        assert result["readiness"]["score"] == 72
        assert "deload" in result
        assert result["deload"]["recommended"] is False

    @pytest.mark.parametrize(
        "ratio,expected",
        [
            (0.5, "detraining"),
            (1.0, "optimal"),
            (1.4, "building"),
            (1.8, "high_risk"),
            (None, "insufficient_data"),
        ],
    )
    def test_get_training_load_risk_levels(
        self, ratio, expected, mock_repo, mock_aggregator
    ):
        """Test that A:C ratio maps to correct risk assessment."""
        mock_aggregator.get_training_load_trend.return_value = {
            "acute_load_7d": 200 if ratio is not None else None,
            "chronic_load_28d": 220 if ratio is not None else None,
            "acute_chronic_ratio": ratio,
            "week_change_pct": 5.0,
            "by_type": {},
        }
        executor = ToolExecutor(mock_repo, mock_aggregator)
        result = executor.get_training_load_analysis()
        assert result["risk_assessment"] == expected


class TestToolDescriptionQuality:
    """Verify tool descriptions include prerequisite info."""

    def test_hevy_tools_mention_hevy_in_description(self):
        """Check that HEVY-dependent tools mention HEVY in their description."""
        hevy_tools = {
            "get_exercise_progression",
            "get_workout_details",
            "get_strength_training_summary",
        }
        for tool in TOOLS:
            name = tool["function"]["name"]
            if name in hevy_tools:
                desc = tool["function"]["description"].lower()
                assert "hevy" in desc, (
                    f"Tool {name!r} description should mention HEVY"
                )

    def test_longitudinal_tool_mentions_multi_year(self):
        """Check that get_longitudinal_summary mentions multi-year."""
        for tool in TOOLS:
            if tool["function"]["name"] == "get_longitudinal_summary":
                desc = tool["function"]["description"].lower()
                assert "multi-year" in desc, (
                    "get_longitudinal_summary description should mention multi-year"
                )
                return
        raise AssertionError("get_longitudinal_summary not in TOOLS")


class TestParallelToolCallLimit:
    """Test that parallel tool calls respect the per-round limit."""

    def test_parallel_tool_calls_respect_limit(self):
        """When the model returns 4 parallel calls but max_tool_calls=2,
        only the first 2 should be executed."""
        from garmin_sync.ai.openai_client import chat_with_tools

        # Build 4 parallel tool calls
        tool_calls = []
        for i in range(4):
            tc = MagicMock()
            tc.id = f"call_{i}"
            tc.function.name = "get_recent_activities"
            tc.function.arguments = '{"days": 7}'
            tool_calls.append(tc)

        first_response = MagicMock()
        first_response.choices = [MagicMock()]
        first_response.choices[0].message.content = None
        first_response.choices[0].message.tool_calls = tool_calls

        final_response = MagicMock()
        final_response.choices = [MagicMock()]
        final_response.choices[0].message.content = "Here are results"
        final_response.choices[0].message.tool_calls = None

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            first_response, final_response,
        ]

        mock_executor = MagicMock()
        mock_executor.execute.return_value = [{"id": "1"}]

        with patch("garmin_sync.ai.openai_client.OpenAI", return_value=mock_client):
            result = chat_with_tools(
                messages=[{"role": "user", "content": "Show activities"}],
                tools=TOOLS,
                api_key="test-key",
                tool_executor=mock_executor,
                max_tool_calls=2,
            )

        assert result == "Here are results"
        assert mock_executor.execute.call_count == 2

    def test_skipped_tools_get_error_results(self):
        """Skipped tool calls (past the limit) get an error tool result
        containing 'Tool call limit reached'."""
        from garmin_sync.ai.openai_client import chat_with_tools

        tool_calls = []
        for i in range(4):
            tc = MagicMock()
            tc.id = f"call_{i}"
            tc.function.name = "get_recent_activities"
            tc.function.arguments = '{"days": 7}'
            tool_calls.append(tc)

        first_response = MagicMock()
        first_response.choices = [MagicMock()]
        first_response.choices[0].message.content = None
        first_response.choices[0].message.tool_calls = tool_calls

        final_response = MagicMock()
        final_response.choices = [MagicMock()]
        final_response.choices[0].message.content = "Done"
        final_response.choices[0].message.tool_calls = None

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            first_response, final_response,
        ]

        mock_executor = MagicMock()
        mock_executor.execute.return_value = []

        with patch("garmin_sync.ai.openai_client.OpenAI", return_value=mock_client):
            chat_with_tools(
                messages=[{"role": "user", "content": "Test"}],
                tools=TOOLS,
                api_key="test-key",
                tool_executor=mock_executor,
                max_tool_calls=2,
            )

        # The second API call should receive tool results for all 4 calls
        second_call_messages = mock_client.chat.completions.create.call_args_list[1][1]["messages"]
        tool_messages = [m for m in second_call_messages if m.get("role") == "tool"]
        assert len(tool_messages) == 4

        # The last 2 should contain the limit error
        error_messages = [
            m for m in tool_messages
            if "Tool call limit reached" in m.get("content", "")
        ]
        assert len(error_messages) == 2


class TestStrengthSummaryWithTargets:
    """Test that get_strength_training_summary includes target_sets."""

    def test_strength_summary_includes_target_sets(self):
        """target_sets should be present in by_muscle_group entries."""
        mock_repo = MagicMock()
        mock_repo.get_hevy_workout_count.return_value = 3
        mock_repo.get_recent_prs.return_value = []
        mock_repo.db = MagicMock()

        mock_agg = MagicMock()
        mock_agg.get_strength_volume_summary.return_value = {
            "total_sessions": 3,
            "total_volume_kg": 5000,
            "total_sets": 45,
            "by_muscle_group": {"chest": {"volume_kg": 100, "sets": 9}},
            "recent_workouts": [],
        }
        mock_agg.get_rpe_analysis.return_value = {
            "rpe_coverage_pct": 0.0,
        }
        mock_agg.get_strength_prs.return_value = []

        executor = ToolExecutor(mock_repo, mock_agg)
        result = executor.get_strength_training_summary(days=7)

        assert "by_muscle_group" in result
        chest = result["by_muscle_group"]["chest"]
        assert "target_sets" in chest
        assert isinstance(chest["target_sets"], int)
        assert chest["target_sets"] > 0
