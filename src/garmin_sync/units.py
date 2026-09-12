"""Unit conversion helpers.

Units policy: the database stores Garmin's native SI units (meters,
meters/second; HEVY weights in kg). Everything user- or model-facing is
imperial — miles, mph, min/mile pace, feet, lbs. Raw data exports
(``export activities`` / ``export health``) intentionally stay SI.
"""

METERS_PER_MILE = 1609.344
FEET_PER_METER = 3.28084
KG_TO_LBS = 2.20462
MPS_TO_MPH = 3600 / METERS_PER_MILE  # ≈ 2.23694


def meters_to_miles(meters: float) -> float:
    return meters / METERS_PER_MILE


def meters_to_feet(meters: float) -> float:
    return meters * FEET_PER_METER


def mps_to_mph(mps: float) -> float:
    return mps * MPS_TO_MPH


def pace_sec_per_mile(duration_seconds: float, distance_meters: float) -> float:
    """Seconds per mile for a duration/distance pair."""
    return duration_seconds / (distance_meters / METERS_PER_MILE)


def sec_per_km_to_sec_per_mile(sec_per_km: float) -> float:
    """Convert a per-km pace to per-mile (used for stored per-km FIT splits)."""
    return sec_per_km * METERS_PER_MILE / 1000


def format_pace_mile(sec_per_mile: float) -> str:
    """Format seconds-per-mile as ``M:SS/mi``."""
    minutes, seconds = divmod(int(sec_per_mile), 60)
    return f"{minutes}:{seconds:02d}/mi"
