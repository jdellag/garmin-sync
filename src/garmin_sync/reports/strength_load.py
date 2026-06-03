"""Strength Training Load (STL) calculator.

Computes per-workout training load from HEVY data using a hybrid
sRPE / estimation approach, producing values in arbitrary units
comparable to Garmin's EPOC-based ``activityTrainingLoad``.

**Method — *modified* sRPE (after Foster et al., 2001):**

    STL = session_RPE × duration_minutes × scale_factor

sRPE itself is well validated for resistance training (Day et al. 2004,
ICC 0.88 vs %1RM; McGuigan & Foster 2004, ICC 0.95), so the approach is sound.
But note two deliberate deviations from the canonical method:

1. **Volume-weighted per-set RPE, not a single whole-session rating.** Foster's
   validated sRPE is ONE global "how hard was the session?" CR-10 rating
   (~30 min post) × duration. We instead volume-weight the per-set RPEs HEVY
   logs (Σ rpe·weight·reps / Σ weight·reps). This is a reasonable adaptation to
   the available data, but it is *modified* sRPE — a single session rating and a
   per-set mean diverge (Sweet et al. 2004).
2. **Estimated session RPE when <50 % of sets are logged** (base 5.0 ± PR /
   failure / volume / exercise-count adjustments). This estimation heuristic is
   our own, NOT a validated instrument — it's a pragmatic proxy, not science.

**Scientific context:** Combining EPOC-derived cardio load with sRPE-derived
strength load (downstream, in the A:C ratio) is approximate — the scales
overlap by coincidence (~50–400 AU) rather than by calibration. Accepted
because Garmin's EPOC underestimates strength (wrist-sensor limitation) and a
coarse signal beats zero representation. Consumers should always show the
cardio/strength breakdown alongside the headline total, and treat the combined
number as a monitoring signal, not a calibrated measurement.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from garmin_sync.hevy.models import HevyWorkout

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

STL_SCALE_FACTOR: float = 1.0
"""Multiplier applied after sRPE × duration.  Start at 1.0; adjust if
empirical observation shows systematic over/under-counting."""

MIN_RPE_COVERAGE: float = 0.50
"""Fraction of working sets that must have RPE logged before the
volume-weighted sRPE path is used.  Below this threshold the
estimation heuristics take over."""

DEFAULT_RPE: float = 5.0
"""Moderate baseline for estimated session RPE."""

RPE_CLAMP: tuple[float, float] = (4.0, 9.0)
"""Hard bounds for the estimated session RPE."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_stl(
    sets: list[dict],
    duration_seconds: Optional[int],
    exercise_count: int = 0,
) -> tuple[Optional[float], str]:
    """Compute Strength Training Load for a single workout.

    Args:
        sets: List of set dicts, each with optional keys:
              ``weight_kg``, ``reps``, ``rpe``, ``set_type``, ``is_pr``.
        duration_seconds: Workout duration (start → end).
        exercise_count: Number of distinct exercises in the workout.

    Returns:
        ``(training_load, method)`` where *method* is ``"srpe"``,
        ``"estimated"``, or ``"no_data"`` when the workout cannot
        be scored.
    """
    if not duration_seconds or duration_seconds <= 0:
        return None, "no_data"

    working = [s for s in sets if s.get("set_type") != "warmup"]
    if not working:
        return None, "no_data"

    duration_minutes = duration_seconds / 60.0

    # --- Decide RPE path ---
    rpe_sets = [s for s in working if s.get("rpe") is not None]
    coverage = len(rpe_sets) / len(working)

    if coverage >= MIN_RPE_COVERAGE:
        session_rpe = _volume_weighted_rpe(rpe_sets)
        method = "srpe"
    else:
        session_rpe = estimate_session_rpe(working, exercise_count)
        method = "estimated"

    stl = round(session_rpe * duration_minutes * STL_SCALE_FACTOR, 1)
    return stl, method


def estimate_session_rpe(
    working_sets: list[dict],
    exercise_count: int = 0,
) -> float:
    """Estimate session RPE from workout characteristics.

    Used when user-logged RPE data is absent or too sparse
    (< :data:`MIN_RPE_COVERAGE`).

    Heuristics (base 5.0 ± adjustments):

    - +1.0  any set has ``is_pr``
    - +0.5  any ``set_type`` is ``"failure"`` or ``"dropset"``
    - +0.5  ≥ 20 working sets
    - +0.5  ≥ 6 exercises
    - −0.5  < 10 working sets

    Result is clamped to :data:`RPE_CLAMP`.
    """
    rpe = DEFAULT_RPE

    # PR day — harder effort
    if any(s.get("is_pr") for s in working_sets):
        rpe += 1.0

    # Intensity techniques
    intensity_types = {"failure", "dropset"}
    if any(s.get("set_type") in intensity_types for s in working_sets):
        rpe += 0.5

    # Volume adjustments
    n_sets = len(working_sets)
    if n_sets >= 20:
        rpe += 0.5
    elif n_sets < 10:
        rpe -= 0.5

    # Exercise variety
    if exercise_count >= 6:
        rpe += 0.5

    return max(RPE_CLAMP[0], min(RPE_CLAMP[1], rpe))


def compute_stl_from_workout(workout: HevyWorkout) -> tuple[Optional[float], str]:
    """Convenience wrapper that accepts a :class:`HevyWorkout` model.

    Extracts sets as dicts and delegates to :func:`compute_stl`.
    """
    duration = workout.duration_seconds
    if duration is None:
        return None, "no_data"

    sets: list[dict] = []
    for exercise in workout.exercises:
        for s in exercise.sets:
            sets.append({
                "weight_kg": s.weight_kg,
                "reps": s.reps,
                "rpe": s.rpe,
                "set_type": s.set_type,
                "is_pr": s.is_pr,
            })

    return compute_stl(sets, duration, workout.exercise_count)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _volume_weighted_rpe(rpe_sets: list[dict]) -> float:
    """Compute volume-weighted mean RPE across sets with RPE data.

    Weight each set's RPE by its volume (weight_kg × reps).  Sets
    with zero volume (bodyweight, etc.) contribute with equal weight.
    """
    weighted_sum = 0.0
    weight_total = 0.0

    for s in rpe_sets:
        rpe = s["rpe"]
        vol = (s.get("weight_kg") or 0) * (s.get("reps") or 0)
        if vol > 0:
            weighted_sum += rpe * vol
            weight_total += vol
        else:
            # Bodyweight / zero-weight set — use unit weight so RPE
            # still counts, just unweighted.
            weighted_sum += rpe
            weight_total += 1.0

    if weight_total <= 0:
        return DEFAULT_RPE

    return weighted_sum / weight_total
