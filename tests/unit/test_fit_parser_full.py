"""Tests for the expanded FIT parser (parse_fit_full, splits, laps)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

import fitdecode

from garmin_sync.sync.fit_parser import (
    FitParseResult,
    LapData,
    SplitData,
    _avg_or_none,
    _compute_hr_drift,
    _compute_splits,
    _int_avg_or_none,
    parse_fit_full,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_records(
    count: int,
    *,
    start_dist: float = 0.0,
    dist_per_record: float = 3.0,  # ~3 m/s running pace
    start_hr: int = 140,
    hr_step: int = 0,
    start_alt: float = 100.0,
    alt_step: float = 0.0,
    cadence: float | None = 85.0,
    power: float | None = None,
    start_time: datetime | None = None,
) -> list[dict]:
    """Create synthetic record dicts for split/HR tests."""
    t0 = start_time or datetime(2024, 6, 1, 7, 0, 0)
    records = []
    for i in range(count):
        records.append(
            {
                "timestamp": t0 + timedelta(seconds=i),
                "distance": start_dist + i * dist_per_record,
                "heart_rate": start_hr + i * hr_step,
                "cadence": cadence,
                "power": power,
                "altitude": start_alt + i * alt_step,
                "speed": dist_per_record,
            }
        )
    return records


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestAvgHelpers:
    def test_avg_or_none_empty(self):
        assert _avg_or_none([]) is None

    def test_avg_or_none_values(self):
        assert _avg_or_none([2.0, 4.0, 6.0]) == pytest.approx(4.0)

    def test_int_avg_or_none_empty(self):
        assert _int_avg_or_none([]) is None

    def test_int_avg_or_none_rounds(self):
        assert _int_avg_or_none([140, 141]) == 140  # 140.5 rounds to 140 (banker's rounding)
        assert _int_avg_or_none([141, 142]) == 142  # 141.5 rounds to 142


# ---------------------------------------------------------------------------
# HR drift computation
# ---------------------------------------------------------------------------


class TestHRDriftInternal:
    def test_positive_drift(self):
        # First half avg 100, second half avg 110 -> drift = 0.10
        samples = [100] * 20 + [110] * 20
        assert _compute_hr_drift(samples) == pytest.approx(0.10)

    def test_negative_drift(self):
        samples = [110] * 20 + [100] * 20
        drift = _compute_hr_drift(samples)
        assert drift is not None
        assert drift < 0

    def test_too_few_samples(self):
        assert _compute_hr_drift([140, 142, 145]) is None

    def test_zero_hr_first_half(self):
        assert _compute_hr_drift([0] * 20 + [100] * 20) is None


# ---------------------------------------------------------------------------
# Split computation
# ---------------------------------------------------------------------------


class TestComputeSplits:
    def test_empty_records(self):
        assert _compute_splits([]) == []

    def test_no_distance_field(self):
        records = [{"timestamp": datetime.now(), "heart_rate": 140}]
        assert _compute_splits(records) == []

    def test_single_km_split(self):
        """Records covering just over 1 km should produce 1 full split."""
        # i goes 0..334, distance = i * 3.0, so record 334 = 1002 m
        records = _make_records(
            count=335,
            dist_per_record=3.0,
        )
        splits = _compute_splits(records)
        assert len(splits) >= 1
        first = splits[0]
        assert first.split_index == 1
        assert first.split_unit == "km"
        assert first.distance == 1000.0

    def test_two_km_splits(self):
        """Records covering 2+ km should produce at least 2 full splits."""
        records = _make_records(count=700, dist_per_record=3.5)
        splits = _compute_splits(records)
        full_splits = [s for s in splits if s.distance == 1000.0]
        assert len(full_splits) >= 2

    def test_partial_last_split(self):
        """Partial distance after last full km is included as a short split."""
        # 1500 m total = 1 full km + 500 m partial
        records = _make_records(count=500, dist_per_record=3.0)
        splits = _compute_splits(records)
        last = splits[-1]
        assert last.distance < 1000.0
        assert last.split_index == 2  # second split is the partial

    def test_split_has_avg_hr(self):
        records = _make_records(count=400, dist_per_record=3.0, start_hr=150)
        splits = _compute_splits(records)
        assert splits[0].avg_heart_rate is not None
        assert splits[0].avg_heart_rate > 0

    def test_split_has_cadence(self):
        records = _make_records(count=400, dist_per_record=3.0, cadence=90.0)
        splits = _compute_splits(records)
        assert splits[0].avg_cadence is not None
        assert splits[0].avg_cadence == pytest.approx(90.0)

    def test_split_has_power(self):
        records = _make_records(count=400, dist_per_record=3.0, power=200.0)
        splits = _compute_splits(records)
        assert splits[0].avg_power is not None
        assert splits[0].avg_power == pytest.approx(200.0)

    def test_split_elevation_change(self):
        """Splits capture altitude change."""
        records = _make_records(
            count=400,
            dist_per_record=3.0,
            start_alt=50.0,
            alt_step=0.1,  # climbing ~0.1 m per record
        )
        splits = _compute_splits(records)
        assert splits[0].elevation_change is not None
        assert splits[0].elevation_change > 0

    def test_treadmill_no_distance(self):
        """Indoor activities without distance produce no splits."""
        t0 = datetime(2024, 6, 1, 7, 0)
        records = [
            {
                "timestamp": t0 + timedelta(seconds=i),
                "distance": None,
                "heart_rate": 150,
            }
            for i in range(600)
        ]
        assert _compute_splits(records) == []

    def test_pace_seconds_per_km(self):
        """Full km splits have pace in seconds per km."""
        # 1000 m at 3 m/s = 333.3 s per km
        records = _make_records(count=400, dist_per_record=3.0)
        splits = _compute_splits(records)
        first = splits[0]
        assert first.pace_seconds_per_km is not None
        # 1000 m / 3 m/s ≈ 333.3 seconds
        assert 330 < first.pace_seconds_per_km < 340


# ---------------------------------------------------------------------------
# parse_fit_full — integration-style tests with mock FIT reader
# ---------------------------------------------------------------------------


class TestParseFitFull:
    def test_empty_fit_returns_empty(self):
        """Corrupt or empty data returns empty result without raising."""
        result = parse_fit_full(b"")
        assert result.laps == []
        assert result.splits == []
        assert result.hr_drift is None

    def test_corrupt_fit_returns_empty(self):
        result = parse_fit_full(b"\x00\x01\x02\x03garbage")
        assert isinstance(result, FitParseResult)

    @patch("garmin_sync.sync.fit_parser.fitdecode.FitReader")
    def test_records_produce_hr_drift(self, mock_reader_cls):
        """Records with HR data produce an HR drift value."""
        t0 = datetime(2024, 6, 1, 7, 0)
        frames = []
        for i in range(100):
            frame = MagicMock(spec=fitdecode.FitDataMessage)
            frame.name = "record"

            hr = 140 if i < 50 else 155  # noticeable drift

            def make_get_value(hr_val, idx):
                mapping = {
                    "heart_rate": hr_val,
                    "distance": idx * 3.0,
                    "speed": 3.0,
                    "cadence": 85,
                    "power": None,
                    "altitude": 100.0,
                    "timestamp": t0 + timedelta(seconds=idx),
                    "enhanced_altitude": 100.0,
                    "enhanced_speed": 3.0,
                    "fractional_cadence": None,
                }

                def get_value(name):
                    if name in mapping:
                        return mapping[name]
                    raise KeyError(name)

                return get_value

            frame.get_value = make_get_value(hr, i)
            frames.append(frame)

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=iter(frames))
        ctx.__exit__ = MagicMock(return_value=False)
        mock_reader_cls.return_value = ctx

        result = parse_fit_full(b"fake_fit_data")

        assert result.hr_drift is not None
        assert result.hr_drift > 0  # Second half HR higher

    @patch("garmin_sync.sync.fit_parser.fitdecode.FitReader")
    def test_lap_frames_produce_laps(self, mock_reader_cls):
        """Lap messages are extracted as LapData objects."""
        frame = MagicMock(spec=fitdecode.FitDataMessage)
        frame.name = "lap"

        mapping = {
            "start_time": datetime(2024, 6, 1, 7, 0),
            "total_elapsed_time": 300.0,
            "total_distance": 1000.0,
            "enhanced_avg_speed": 3.3,
            "enhanced_max_speed": 4.0,
            "avg_heart_rate": 150,
            "max_heart_rate": 165,
            "avg_running_cadence": 88,
            "avg_power": None,
            "total_ascent": 10.0,
            "total_descent": 5.0,
            "avg_temperature": 22.0,
            "avg_cadence": None,
            "avg_speed": None,
            "max_speed": None,
            "timestamp": None,
        }

        def get_value(name):
            if name in mapping:
                return mapping[name]
            raise KeyError(name)

        frame.get_value = get_value

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=iter([frame]))
        ctx.__exit__ = MagicMock(return_value=False)
        mock_reader_cls.return_value = ctx

        result = parse_fit_full(b"fake")

        assert len(result.laps) == 1
        lap = result.laps[0]
        assert lap.lap_index == 0
        assert lap.total_distance == 1000.0
        assert lap.avg_heart_rate == 150
        assert lap.total_ascent == 10.0

    @patch("garmin_sync.sync.fit_parser.fitdecode.FitReader")
    def test_no_laps_returns_empty_list(self, mock_reader_cls):
        """FIT file with only records and no lap messages."""
        frame = MagicMock(spec=fitdecode.FitDataMessage)
        frame.name = "record"

        mapping = {
            "heart_rate": 140,
            "distance": 500.0,
            "speed": 3.0,
            "cadence": 85,
            "power": None,
            "altitude": 100.0,
            "timestamp": datetime(2024, 6, 1, 7, 0),
            "enhanced_altitude": 100.0,
            "enhanced_speed": 3.0,
            "fractional_cadence": None,
        }

        def get_value(name):
            if name in mapping:
                return mapping[name]
            raise KeyError(name)

        frame.get_value = get_value

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=iter([frame]))
        ctx.__exit__ = MagicMock(return_value=False)
        mock_reader_cls.return_value = ctx

        result = parse_fit_full(b"fake")
        assert result.laps == []


# ---------------------------------------------------------------------------
# FitParseResult / dataclass basics
# ---------------------------------------------------------------------------


class TestFitParseResultDataclass:
    def test_default_empty(self):
        r = FitParseResult()
        assert r.laps == []
        assert r.splits == []
        assert r.hr_drift is None

    def test_with_values(self):
        lap = LapData(lap_index=0, avg_heart_rate=150)
        split = SplitData(split_index=1, distance=1000.0, elapsed_time=300.0)
        r = FitParseResult(laps=[lap], splits=[split], hr_drift=0.05)
        assert len(r.laps) == 1
        assert len(r.splits) == 1
        assert r.hr_drift == 0.05


class TestLapDataDefaults:
    def test_defaults(self):
        lap = LapData(lap_index=0)
        assert lap.start_time is None
        assert lap.total_distance is None
        assert lap.avg_heart_rate is None


class TestSplitDataDefaults:
    def test_defaults(self):
        split = SplitData(split_index=1)
        assert split.split_unit == "km"
        assert split.distance == 0.0
        assert split.elapsed_time == 0.0
        assert split.pace_seconds_per_km is None
