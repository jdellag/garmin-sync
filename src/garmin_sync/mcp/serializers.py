"""Serialization helpers for MCP responses."""

from dataclasses import asdict, is_dataclass
from typing import Any


def serialize_activity(activity) -> dict:
    """Convert Activity dataclass to JSON-safe dict.

    Excludes the raw_json field to reduce response size.
    """
    d = asdict(activity)
    d.pop("raw_json", None)
    return d


def serialize_list(items: list) -> list[dict]:
    """Convert list of dataclasses to dicts."""
    return [serialize_activity(item) for item in items]
