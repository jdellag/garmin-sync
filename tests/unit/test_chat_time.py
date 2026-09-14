"""Tests for how chat conveys time: session headers, the "now" note, freshness."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from garmin_sync import temporal
from garmin_sync.ai.chat import ChatSession
from garmin_sync.ai.config import AIConfig
from garmin_sync.db.models import ChatMessage

NY = temporal.get_zone("America/New_York")
MONDAY_EVENING = datetime(2026, 9, 14, 17, 45, tzinfo=NY)


def _message(role, content, created_at):
    return ChatMessage(role=role, content=content, created_at=created_at, token_estimate=10)


@pytest.fixture(autouse=True)
def frozen_now():
    with patch.object(temporal, "now", return_value=MONDAY_EVENING):
        yield


@pytest.fixture
def repo():
    repo = MagicMock()
    repo.get_latest_sync_timestamp.return_value = "2026-09-14T08:02:39.937500"
    repo.get_hevy_workout_count.return_value = 0
    repo.get_activities.return_value = []
    repo.get_hevy_workout_details.return_value = []
    repo.get_activities_by_local_date.return_value = []
    # created_at is SQLite CURRENT_TIMESTAMP (UTC): Fri Sep 11 8:41 PM and
    # Sat Sep 12 5:47 PM in New York, then the question just asked.
    repo.get_chat_history.return_value = [
        _message("user", "regenerate todays workout", "2026-09-12 00:41:42"),
        _message("assistant", "Today should be a recovery-focused day.", "2026-09-12 00:41:48"),
        _message("user", "Give me my top running speeds", "2026-09-12 21:47:04"),
        _message("assistant", "Your top recorded speeds are...", "2026-09-12 21:47:10"),
        _message("user", "What did we talk about last time?", "2026-09-14 21:44:30"),
    ]
    return repo


@pytest.fixture
def session(repo, tmp_path):
    config = AIConfig(
        api_key="sk-test",
        schedule="Monday: Rest day\nTuesday: Intervals",
        timezone="America/New_York",
    )
    return ChatSession(repository=repo, ai_config=config, reports_dir=tmp_path, use_tools=False)


def _headers(messages):
    return [
        m["content"]
        for m in messages
        if m["role"] == "developer" and m["content"].startswith("Session started")
    ]


def test_session_headers_use_local_wall_clock_times(session):
    assert _headers(session.build_context_messages()) == [
        "Session started Fri Sep 11, 8:41 PM EDT.",
        "Session started Sat Sep 12, 5:47 PM EDT.",
        "Session started Mon Sep 14, 5:44 PM EDT.",
    ]


def test_now_note_sits_right_before_the_latest_question(session):
    messages = session.build_context_messages()

    assert messages[-1] == {"role": "user", "content": "What did we talk about last time?"}
    note = messages[-2]
    assert note["role"] == "developer"
    assert "Current time: Mon Sep 14, 5:45 PM EDT." in note["content"]
    assert (
        "Earlier sessions in this conversation: Fri Sep 11 (3 days ago), Sat Sep 12 (2 days ago)."
        in note["content"]
    )
    assert "Data last synced today at 8:02 AM (10 hours ago)." in note["content"]


def test_stored_messages_are_replayed_verbatim(session):
    replayed = [
        (m["role"], m["content"])
        for m in session.build_context_messages()
        if m["role"] in ("user", "assistant")
    ]
    assert replayed[0] == ("user", "regenerate todays workout")
    assert all("EDT" not in content for _, content in replayed)


def test_crossing_local_midnight_starts_a_new_session(session, repo):
    # 11:50 PM and 12:10 AM in New York: 20 minutes apart, different dates
    repo.get_chat_history.return_value = [
        _message("user", "late question", "2026-09-14 03:50:00"),
        _message("assistant", "late answer", "2026-09-14 03:51:00"),
        _message("user", "after midnight", "2026-09-14 04:10:00"),
    ]
    assert _headers(session.build_context_messages()) == [
        "Session started Sun Sep 13, 11:50 PM EDT.",
        "Session started Mon Sep 14, 12:10 AM EDT.",
    ]


def test_system_message_has_no_clock_but_a_dated_schedule(session):
    system = session.build_context_messages()[0]["content"]
    assert "Current date" not in system
    assert "Data last synced" not in system
    assert "- Mon Sep 14 (today): Rest day" in system
    assert "- Tue Sep 15 (tomorrow): Intervals" in system


def test_stale_sync_is_flagged(session, repo):
    repo.get_latest_sync_timestamp.return_value = "2026-09-12T08:00:00"
    note = session.build_context_messages()[-2]["content"]
    assert "⚠️ Data last synced Sat Sep 12 at 8:00 AM (2.4 days ago)." in note


def test_history_without_timestamps_still_gets_a_now_note(session, repo):
    repo.get_chat_history.return_value = [_message("user", "hello", None)]
    messages = session.build_context_messages()
    assert _headers(messages) == []
    assert messages[-2]["content"].startswith("Current time: Mon Sep 14, 5:45 PM EDT.")


SUNDAY_REPORT = """# Fitness Analysis - Sunday, September 13, 2026

## 1. Today's call
Today: **Rest day; no run.**

Key numbers: **RHR 75 (+30 vs baseline)**.

## 3. Week ahead
- **Tuesday:** If morning markers normalize, 35–45 min easy Zone 2.

**Morning signal that changes the plan:** resume running only if RHR is back near baseline.
"""


def test_earlier_reports_contribute_decisions_not_numbers(session, tmp_path):
    (tmp_path / "analysis-2026-09-13.md").write_text(SUNDAY_REPORT)
    (tmp_path / "analysis-2026-09-14.md").write_text(
        "# Fitness Analysis - Monday\n\nToday: easy 35 min run"
    )

    system = session.build_context_messages()[0]["content"]

    assert "### Decisions from the analysis written Sun Sep 13 (yesterday)" in system
    assert "- Call for Sun Sep 13 (yesterday): Rest day; no run" in system
    assert (
        "- Planned Tue Sep 15 (tomorrow): If morning markers normalize, 35–45 min easy Zone 2."
        in system
    )
    assert "RHR 75" not in system
    assert "### Analysis written Mon Sep 14 (today)\n# Fitness Analysis - Monday" in system
