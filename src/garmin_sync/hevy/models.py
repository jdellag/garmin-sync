"""Data models for HEVY strength training data."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class HevySet:
    """A single set within an exercise."""

    set_index: int
    set_type: str  # normal, warmup, dropset, failure
    weight_kg: Optional[float] = None
    reps: Optional[int] = None
    distance_meters: Optional[float] = None  # For cardio exercises
    duration_seconds: Optional[int] = None  # For timed exercises
    rpe: Optional[float] = None  # Rate of Perceived Exertion (1-10)
    is_pr: bool = False  # Personal record flag

    @classmethod
    def from_api_response(cls, data: dict, index: int = 0) -> "HevySet":
        """Create HevySet from HEVY API response."""
        return cls(
            set_index=data.get("index", index),
            set_type=data.get("set_type", "normal"),
            weight_kg=data.get("weight_kg"),
            reps=data.get("reps"),
            distance_meters=data.get("distance_meters"),
            duration_seconds=data.get("duration_seconds"),
            rpe=data.get("rpe"),
            is_pr=data.get("is_pr", False),
        )

    @property
    def volume_kg(self) -> float:
        """Calculate volume (weight × reps) for this set."""
        if self.weight_kg and self.reps:
            return self.weight_kg * self.reps
        return 0.0


@dataclass
class HevyExercise:
    """An exercise within a workout, containing multiple sets."""

    exercise_template_id: str
    exercise_name: str
    exercise_type: Optional[str] = None  # barbell, dumbbell, machine, bodyweight, etc.
    muscle_group: Optional[str] = None  # chest, back, legs, shoulders, arms, core
    superset_id: Optional[int] = None
    exercise_order: int = 0
    notes: Optional[str] = None
    sets: list[HevySet] = field(default_factory=list)

    @classmethod
    def from_api_response(cls, data: dict, order: int = 0) -> "HevyExercise":
        """Create HevyExercise from HEVY API response."""
        sets = []
        for idx, set_data in enumerate(data.get("sets", [])):
            sets.append(HevySet.from_api_response(set_data, idx))

        return cls(
            exercise_template_id=data.get("exercise_template_id", ""),
            exercise_name=data.get("title", ""),
            exercise_type=data.get("equipment_type"),
            muscle_group=data.get("muscle_group"),
            superset_id=data.get("superset_id"),
            exercise_order=data.get("index", order),
            notes=data.get("notes"),
            sets=sets,
        )

    @property
    def total_volume_kg(self) -> float:
        """Calculate total volume for this exercise."""
        return sum(s.volume_kg for s in self.sets)

    @property
    def total_sets(self) -> int:
        """Count total sets (excluding warmup)."""
        return len([s for s in self.sets if s.set_type != "warmup"])

    @property
    def total_reps(self) -> int:
        """Count total reps across all sets."""
        return sum(s.reps or 0 for s in self.sets)

    @property
    def max_weight_kg(self) -> Optional[float]:
        """Get max weight used in this exercise."""
        weights = [s.weight_kg for s in self.sets if s.weight_kg]
        return max(weights) if weights else None

    @property
    def has_pr(self) -> bool:
        """Check if any set is a PR."""
        return any(s.is_pr for s in self.sets)


@dataclass
class HevyWorkout:
    """A complete HEVY workout session."""

    id: str
    title: str
    start_time: str  # ISO timestamp
    end_time: Optional[str] = None
    description: Optional[str] = None
    exercises: list[HevyExercise] = field(default_factory=list)
    raw_json: Optional[str] = None
    training_load: Optional[float] = None
    stl_method: Optional[str] = None  # "srpe" | "estimated"

    @classmethod
    def from_api_response(cls, data: dict) -> "HevyWorkout":
        """Create HevyWorkout from HEVY API response."""
        exercises = []
        for idx, ex_data in enumerate(data.get("exercises", [])):
            exercises.append(HevyExercise.from_api_response(ex_data, idx))

        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            start_time=data.get("start_time", ""),
            end_time=data.get("end_time"),
            description=data.get("description"),
            exercises=exercises,
        )

    @property
    def total_volume_kg(self) -> float:
        """Calculate total volume (weight × reps) for the workout."""
        return sum(ex.total_volume_kg for ex in self.exercises)

    @property
    def total_sets(self) -> int:
        """Count total working sets (excluding warmup)."""
        return sum(ex.total_sets for ex in self.exercises)

    @property
    def total_reps(self) -> int:
        """Count total reps across all exercises."""
        return sum(ex.total_reps for ex in self.exercises)

    @property
    def exercise_count(self) -> int:
        """Count number of exercises."""
        return len(self.exercises)

    @property
    def duration_seconds(self) -> Optional[int]:
        """Calculate workout duration in seconds."""
        if not self.start_time or not self.end_time:
            return None
        try:
            from datetime import datetime
            start = datetime.fromisoformat(self.start_time.replace("Z", "+00:00"))
            end = datetime.fromisoformat(self.end_time.replace("Z", "+00:00"))
            return int((end - start).total_seconds())
        except (ValueError, TypeError):
            return None

    @property
    def muscle_groups(self) -> list[str]:
        """Get unique muscle groups targeted in this workout."""
        groups = set()
        for ex in self.exercises:
            if ex.muscle_group:
                groups.add(ex.muscle_group)
        return sorted(groups)

    def volume_by_muscle_group(self) -> dict[str, float]:
        """Calculate volume breakdown by muscle group."""
        volumes: dict[str, float] = {}
        for ex in self.exercises:
            group = ex.muscle_group or "other"
            if group not in volumes:
                volumes[group] = 0.0
            volumes[group] += ex.total_volume_kg
        return volumes


@dataclass
class HevyExerciseTemplate:
    """An exercise template from HEVY's exercise library."""

    id: str
    title: str
    muscle_group: Optional[str] = None
    equipment: Optional[str] = None
    is_custom: bool = False

    @classmethod
    def from_api_response(cls, data: dict) -> "HevyExerciseTemplate":
        """Create HevyExerciseTemplate from HEVY API response."""
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            muscle_group=data.get("primary_muscle_group"),
            equipment=data.get("equipment"),
            is_custom=data.get("is_custom", False),
        )
