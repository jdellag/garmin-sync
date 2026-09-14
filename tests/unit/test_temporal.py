"""Tests for garmin_sync.temporal: one clock, date math done in code."""

from datetime import date, datetime, timedelta, timezone

import pytest

from garmin_sync import temporal

NY = "America/New_York"

USER_SCHEDULE = (
    "Monday: Rest day or easy recovery\n"
    "Tuesday: Speed/interval workout\n"
    "Wednesday: Easy run\n"
    "Thursday: Tempo or threshold run\n"
    "Friday: Rest or cross-training\n"
    "Saturday: Long run\n"
    "Sunday: Easy run or rest"
)


class TestLabels:
    def test_short_date_has_no_zero_padding(self):
        assert temporal.short_date(date(2026, 9, 4)) == "Fri Sep 4"

    @pytest.mark.parametrize(
        "d, expected",
        [
            (date(2026, 9, 14), "Mon Sep 14 (today)"),
            (date(2026, 9, 13), "Sun Sep 13 (yesterday)"),
            (date(2026, 9, 15), "Tue Sep 15 (tomorrow)"),
            (date(2026, 9, 11), "Fri Sep 11 (3 days ago)"),
            (date(2026, 9, 17), "Thu Sep 17 (in 3 days)"),
        ],
    )
    def test_day_label(self, d, expected):
        assert temporal.day_label(d, date(2026, 9, 14)) == expected

    def test_timestamp_label(self):
        dt = datetime(2026, 9, 11, 20, 41, tzinfo=temporal.get_zone(NY))
        assert temporal.timestamp_label(dt) == "Fri Sep 11, 8:41 PM EDT"

    @pytest.mark.parametrize(
        "seconds, expected",
        [
            (30, "just now"),
            (40 * 60, "40 min ago"),
            (9 * 3600, "9 hours ago"),
            (60 * 3600, "2.5 days ago"),
        ],
    )
    def test_age_phrase(self, seconds, expected):
        ref = datetime(2026, 9, 14, 21, 0, tzinfo=timezone.utc)
        assert temporal.age_phrase(ref - timedelta(seconds=seconds), ref) == expected


class TestStoredTimestamps:
    def test_sqlite_utc_timestamp_lands_on_the_local_day(self):
        # Stored as 00:41 UTC on Sep 12, but it was Friday evening in New York.
        local = temporal.from_utc_naive("2026-09-12 00:41:42", NY)
        assert temporal.timestamp_label(local) == "Fri Sep 11, 8:41 PM EDT"

    def test_naive_local_sync_timestamp(self):
        local = temporal.from_local_naive("2026-09-14T08:02:39.937500", NY)
        assert (local.hour, local.minute) == (8, 2)
        assert local.utcoffset() == timedelta(hours=-4)

    def test_aware_timestamp_is_converted_to_local(self):
        local = temporal.from_local_naive("2026-03-15T10:00:00+00:00", NY)
        assert (local.hour, local.minute) == (6, 0)

    @pytest.mark.parametrize("value", [None, "", "not a timestamp"])
    def test_unparseable_values_return_none(self, value):
        assert temporal.from_utc_naive(value, NY) is None
        assert temporal.from_local_naive(value, NY) is None

    def test_unknown_zone_falls_back_without_crashing(self):
        assert temporal.now("Not/AZone").tzinfo is not None


class TestCalendar:
    def test_next_weekday_is_strictly_after(self):
        sunday = date(2026, 9, 13)
        assert temporal.next_weekday("Monday", sunday) == date(2026, 9, 14)
        assert temporal.next_weekday("sun", sunday) == date(2026, 9, 20)
        assert temporal.next_weekday("Someday", sunday) is None

    def test_resolve_month_day_handles_year_rollover(self):
        assert temporal.resolve_month_day("Jan", 1, date(2026, 12, 31)) == date(2027, 1, 1)
        assert temporal.resolve_month_day("Sep", 15, date(2026, 9, 14)) == date(2026, 9, 15)
        assert temporal.resolve_month_day("Foo", 1, date(2026, 9, 14)) is None

    def test_map_schedule_to_dates(self):
        week = temporal.map_schedule_to_dates(USER_SCHEDULE, date(2026, 9, 14))
        assert len(week) == 7
        assert week[0] == (date(2026, 9, 14), "Rest day or easy recovery")
        assert week[1] == (date(2026, 9, 15), "Speed/interval workout")
        assert week[-1] == (date(2026, 9, 20), "Easy run or rest")

    def test_schedule_without_weekdays_maps_to_nothing(self):
        assert temporal.map_schedule_to_dates("Run when I can", date(2026, 9, 14)) == []

    def test_annotate_relative_words(self):
        text = "If today feels normal, rest tomorrow; yesterday was hard."
        assert temporal.annotate_relative_words(text, date(2026, 9, 14)) == (
            "If today [Mon Sep 14] feels normal, rest tomorrow [Tue Sep 15]; "
            "yesterday [Sun Sep 13] was hard."
        )
