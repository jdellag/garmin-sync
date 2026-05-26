"""FIT file parsing utilities for extracting HR, lap, and split data."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import fitdecode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class LapData:
    """Parsed lap from FIT file."""

    lap_index: int
    start_time: str | None = None
    total_elapsed_time: float | None = None
    total_distance: float | None = None
    avg_speed: float | None = None
    max_speed: float | None = None
    avg_heart_rate: int | None = None
    max_heart_rate: int | None = None
    avg_cadence: float | None = None
    avg_power: float | None = None
    total_ascent: float | None = None
    total_descent: float | None = None
    avg_temperature: float | None = None


@dataclass
class SplitData:
    """Pre-computed pace split."""

    split_index: int
    split_unit: str = "km"
    distance: float = 0.0
    elapsed_time: float = 0.0
    pace_seconds_per_km: float | None = None
    avg_heart_rate: int | None = None
    avg_cadence: float | None = None
    avg_power: float | None = None
    elevation_change: float | None = None


@dataclass
class FitParseResult:
    """Complete parse result from a FIT file."""

    laps: list[LapData] = field(default_factory=list)
    splits: list[SplitData] = field(default_factory=list)
    hr_drift: float | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_get(frame: fitdecode.FitDataMessage, name: str):
    """Return a field value from a FIT frame, or None on any error."""
    try:
        return frame.get_value(name)
    except (KeyError, TypeError, AttributeError):
        return None


def _get_altitude(record: fitdecode.FitDataMessage) -> float | None:
    """Get altitude, preferring enhanced_altitude."""
    alt = _safe_get(record, "enhanced_altitude")
    if alt is not None:
        return float(alt)
    alt = _safe_get(record, "altitude")
    if alt is not None:
        return float(alt)
    return None


def _get_speed(record: fitdecode.FitDataMessage) -> float | None:
    """Get speed, preferring enhanced_speed."""
    spd = _safe_get(record, "enhanced_speed")
    if spd is not None:
        return float(spd)
    spd = _safe_get(record, "speed")
    if spd is not None:
        return float(spd)
    return None


def _get_cadence(record: fitdecode.FitDataMessage) -> float | None:
    """Get cadence, adding fractional_cadence if present.

    Running cadence in FIT is typically half-steps per minute.  Multiply by 2
    to convert to full steps/min.  Cycling cadence is already in rpm and should
    not be doubled — but distinguishing sport type at the record level is
    unreliable, so we leave the raw value and let callers decide.
    """
    cad = _safe_get(record, "cadence")
    if cad is None:
        return None
    result = float(cad)
    frac = _safe_get(record, "fractional_cadence")
    if frac is not None:
        result += float(frac)
    return result


def _format_timestamp(ts) -> str | None:
    """Format a datetime-like value as an ISO string."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.isoformat()
    return str(ts)


def _avg_or_none(values: list) -> float | None:
    """Return the mean of *values*, or None if the list is empty."""
    if not values:
        return None
    return sum(values) / len(values)


def _int_avg_or_none(values: list) -> int | None:
    """Return the rounded integer mean, or None if empty."""
    avg = _avg_or_none(values)
    if avg is None:
        return None
    return round(avg)


# ---------------------------------------------------------------------------
# Split computation
# ---------------------------------------------------------------------------


def _compute_splits(
    records: list[dict],
    unit_meters: float = 1000.0,
) -> list[SplitData]:
    """Compute per-unit (default per-km) pace splits from raw records.

    Each *record* dict is expected to have at least ``distance`` (accumulated
    meters from start) and ``timestamp`` (datetime).  Optional keys:
    ``heart_rate``, ``cadence``, ``power``, ``altitude``.

    Returns an empty list when records lack distance data.
    """

    # Filter to records with usable distance and timestamp.
    usable = [
        r
        for r in records
        if r.get("distance") is not None
        and r["distance"] > 0
        and r.get("timestamp") is not None
    ]
    if not usable:
        return []

    splits: list[SplitData] = []
    split_idx = 1
    boundary = unit_meters  # first boundary at 1 km
    prev_boundary_time: datetime = usable[0]["timestamp"]
    prev_boundary_alt: float | None = usable[0].get("altitude")

    # Accumulate per-split metric samples for averaging.
    hr_acc: list[int] = []
    cad_acc: list[float] = []
    pow_acc: list[float] = []

    def _collect_metrics(rec: dict) -> None:
        if rec.get("heart_rate") is not None:
            hr_acc.append(rec["heart_rate"])
        if rec.get("cadence") is not None:
            cad_acc.append(rec["cadence"])
        if rec.get("power") is not None:
            pow_acc.append(rec["power"])

    i = 0
    while i < len(usable):
        rec = usable[i]
        dist = rec["distance"]

        if dist < boundary:
            _collect_metrics(rec)
            i += 1
            continue

        # --- Crossed or exactly hit the boundary ---
        # Interpolate the exact time at the boundary.
        if i > 0:
            prev_rec = usable[i - 1]
            prev_dist = prev_rec["distance"]
            seg_dist = dist - prev_dist
            if seg_dist > 0:
                frac = (boundary - prev_dist) / seg_dist
            else:
                frac = 1.0
            seg_time = (rec["timestamp"] - prev_rec["timestamp"]).total_seconds()
            boundary_time = prev_rec["timestamp"] + timedelta(
                seconds=seg_time * frac
            )

            # Interpolate altitude at the boundary.
            prev_alt = prev_rec.get("altitude")
            cur_alt = rec.get("altitude")
            if prev_alt is not None and cur_alt is not None:
                boundary_alt = prev_alt + (cur_alt - prev_alt) * frac
            else:
                boundary_alt = cur_alt
        else:
            boundary_time = rec["timestamp"]
            boundary_alt = rec.get("altitude")

        elapsed = (boundary_time - prev_boundary_time).total_seconds()

        # Include this record's metrics in the split averages.
        _collect_metrics(rec)

        elev_change: float | None = None
        if prev_boundary_alt is not None and boundary_alt is not None:
            elev_change = boundary_alt - prev_boundary_alt

        splits.append(
            SplitData(
                split_index=split_idx,
                split_unit="km" if unit_meters == 1000.0 else "mi",
                distance=unit_meters,
                elapsed_time=elapsed,
                pace_seconds_per_km=elapsed if unit_meters == 1000.0 else None,
                avg_heart_rate=_int_avg_or_none(hr_acc),
                avg_cadence=round(_avg_or_none(cad_acc), 1)
                if _avg_or_none(cad_acc) is not None
                else None,
                avg_power=round(_avg_or_none(pow_acc), 1)
                if _avg_or_none(pow_acc) is not None
                else None,
                elevation_change=round(elev_change, 1) if elev_change is not None else None,
            )
        )

        # Reset accumulators for the next split.
        split_idx += 1
        prev_boundary_time = boundary_time
        prev_boundary_alt = boundary_alt
        boundary += unit_meters
        hr_acc = []
        cad_acc = []
        pow_acc = []

        # Don't advance *i* — the same record may straddle multiple
        # boundaries (e.g. a GPS glitch with a huge distance jump).
        # However, if the current record is *still* beyond the next
        # boundary we'll handle it in the next loop iteration.
        # We *do* need to advance if we've exactly consumed this record.
        if dist <= boundary:
            i += 1

    # --- Partial last split ---
    if usable:
        last_dist = usable[-1]["distance"]
        remaining = last_dist - (boundary - unit_meters)
        if remaining > 0 and remaining < unit_meters:
            last_time = usable[-1]["timestamp"]
            elapsed = (last_time - prev_boundary_time).total_seconds()
            if elapsed > 0:
                pace = elapsed / (remaining / 1000.0) if remaining > 0 else None
            else:
                pace = None

            last_alt = usable[-1].get("altitude")
            elev_change = None
            if prev_boundary_alt is not None and last_alt is not None:
                elev_change = last_alt - prev_boundary_alt

            splits.append(
                SplitData(
                    split_index=split_idx,
                    split_unit="km" if unit_meters == 1000.0 else "mi",
                    distance=round(remaining, 1),
                    elapsed_time=round(elapsed, 2),
                    pace_seconds_per_km=round(pace, 2) if pace is not None else None,
                    avg_heart_rate=_int_avg_or_none(hr_acc),
                    avg_cadence=round(_avg_or_none(cad_acc), 1)
                    if _avg_or_none(cad_acc) is not None
                    else None,
                    avg_power=round(_avg_or_none(pow_acc), 1)
                    if _avg_or_none(pow_acc) is not None
                    else None,
                    elevation_change=round(elev_change, 1) if elev_change is not None else None,
                )
            )

    return splits


# ---------------------------------------------------------------------------
# HR drift (from raw HR list — used by both legacy API and parse_fit_full)
# ---------------------------------------------------------------------------


def _compute_hr_drift(hr_samples: list[int]) -> float | None:
    """Compute HR drift from a list of HR values.

    HR Drift = (avg_hr_second_half - avg_hr_first_half) / avg_hr_first_half
    """
    if len(hr_samples) < 10:
        return None

    midpoint = len(hr_samples) // 2
    first_half = hr_samples[:midpoint]
    second_half = hr_samples[midpoint:]

    avg_hr_first = sum(first_half) / len(first_half)
    avg_hr_second = sum(second_half) / len(second_half)

    if avg_hr_first == 0:
        return None

    return (avg_hr_second - avg_hr_first) / avg_hr_first


# ---------------------------------------------------------------------------
# Lap extraction helper
# ---------------------------------------------------------------------------


def _parse_lap(frame: fitdecode.FitDataMessage, index: int) -> LapData:
    """Extract a LapData from a FIT lap message."""
    # Speed: prefer enhanced variant
    avg_spd = _safe_get(frame, "enhanced_avg_speed")
    if avg_spd is None:
        avg_spd = _safe_get(frame, "avg_speed")

    max_spd = _safe_get(frame, "enhanced_max_speed")
    if max_spd is None:
        max_spd = _safe_get(frame, "max_speed")

    # Cadence: try running-specific field first, fall back to generic
    avg_cad = _safe_get(frame, "avg_running_cadence")
    if avg_cad is None:
        avg_cad = _safe_get(frame, "avg_cadence")

    # Start time: prefer start_time, fall back to timestamp
    start_ts = _safe_get(frame, "start_time")
    if start_ts is None:
        start_ts = _safe_get(frame, "timestamp")

    return LapData(
        lap_index=index,
        start_time=_format_timestamp(start_ts),
        total_elapsed_time=_safe_get(frame, "total_elapsed_time"),
        total_distance=_safe_get(frame, "total_distance"),
        avg_speed=float(avg_spd) if avg_spd is not None else None,
        max_speed=float(max_spd) if max_spd is not None else None,
        avg_heart_rate=_safe_get(frame, "avg_heart_rate"),
        max_heart_rate=_safe_get(frame, "max_heart_rate"),
        avg_cadence=float(avg_cad) if avg_cad is not None else None,
        avg_power=float(_safe_get(frame, "avg_power"))
        if _safe_get(frame, "avg_power") is not None
        else None,
        total_ascent=_safe_get(frame, "total_ascent"),
        total_descent=_safe_get(frame, "total_descent"),
        avg_temperature=_safe_get(frame, "avg_temperature"),
    )


# ---------------------------------------------------------------------------
# Main entry point — single-pass FIT parser
# ---------------------------------------------------------------------------


def parse_fit_full(fit_data: bytes) -> FitParseResult:
    """Parse a FIT file in a single pass, returning laps, splits, and HR drift.

    This is the primary entry point for Phase-2 FIT enrichment.  It never
    raises — on any error it returns an empty ``FitParseResult``.

    Args:
        fit_data: Raw FIT file bytes.

    Returns:
        A ``FitParseResult`` with laps, per-km splits, and HR drift.
    """
    try:
        raw_records: list[dict] = []
        laps: list[LapData] = []
        lap_index = 0

        with fitdecode.FitReader(io.BytesIO(fit_data)) as fit:
            for frame in fit:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue

                if frame.name == "record":
                    rec: dict = {
                        "heart_rate": _safe_get(frame, "heart_rate"),
                        "distance": _safe_get(frame, "distance"),
                        "speed": _get_speed(frame),
                        "cadence": _get_cadence(frame),
                        "power": _safe_get(frame, "power"),
                        "altitude": _get_altitude(frame),
                        "timestamp": _safe_get(frame, "timestamp"),
                    }
                    raw_records.append(rec)

                elif frame.name == "lap":
                    laps.append(_parse_lap(frame, lap_index))
                    lap_index += 1

        # HR drift — reuse the same algorithm as the legacy function.
        hr_values = [
            r["heart_rate"]
            for r in raw_records
            if r.get("heart_rate") is not None and r["heart_rate"] > 0
        ]
        hr_drift = _compute_hr_drift(hr_values)

        # Splits
        splits = _compute_splits(raw_records)

        return FitParseResult(laps=laps, splits=splits, hr_drift=hr_drift)

    except Exception:
        logger.warning("FIT file parsing failed", exc_info=True)
        return FitParseResult()


# ---------------------------------------------------------------------------
# Legacy public API — preserved for backward compatibility
# ---------------------------------------------------------------------------


def compute_hr_drift_from_fit(fit_data: bytes) -> Optional[float]:
    """Compute HR drift from FIT file data.

    HR Drift = (avg_hr_second_half - avg_hr_first_half) / avg_hr_first_half

    A higher HR drift (>5%) during steady-state aerobic exercise indicates
    cardiovascular fatigue or insufficient aerobic fitness.

    Args:
        fit_data: Raw FIT file bytes

    Returns:
        HR drift as decimal (0.05 = 5%), or None if cannot compute
    """
    try:
        hr_samples = extract_hr_samples(fit_data)
        return _compute_hr_drift(hr_samples)
    except Exception:
        logger.debug("HR drift computation failed", exc_info=True)
        return None


def extract_hr_samples(fit_data: bytes) -> list[int]:
    """Extract heart rate samples from FIT file.

    Args:
        fit_data: Raw FIT file bytes

    Returns:
        List of HR values (one per record, typically per second)
    """
    hr_samples = []

    with fitdecode.FitReader(io.BytesIO(fit_data)) as fit:
        for frame in fit:
            if isinstance(frame, fitdecode.FitDataMessage):
                if frame.name == "record":
                    # Record messages contain per-second data
                    hr = frame.get_value("heart_rate")
                    if hr is not None and hr > 0:
                        hr_samples.append(hr)

    return hr_samples
