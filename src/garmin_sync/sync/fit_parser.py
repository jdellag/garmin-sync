"""FIT file parsing utilities for extracting HR data."""

import io
from typing import Optional

import fitdecode


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

        if len(hr_samples) < 10:  # Need reasonable number of samples
            return None

        # Split into halves
        midpoint = len(hr_samples) // 2
        first_half = hr_samples[:midpoint]
        second_half = hr_samples[midpoint:]

        # Calculate averages
        avg_hr_first = sum(first_half) / len(first_half)
        avg_hr_second = sum(second_half) / len(second_half)

        if avg_hr_first == 0:
            return None

        return (avg_hr_second - avg_hr_first) / avg_hr_first

    except Exception:
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
