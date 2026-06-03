"""Tests for the split config layout (config.toml + profile.toml)."""

import os
import stat

import pytest
import tomli_w

from garmin_sync.ai.config import (
    AIConfig,
    DEFAULT_SCHEDULE,
    load_config,
    migrate_config_if_needed,
    save_config,
)
from garmin_sync.config.paths import default_profile_path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def config_dir(tmp_path):
    """Return a temp directory containing config.toml and profile.toml paths."""
    return tmp_path / "config"


@pytest.fixture()
def config_path(config_dir):
    return config_dir / "config.toml"


@pytest.fixture()
def profile_path(config_dir):
    return config_dir / "profile.toml"


def _write_toml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        tomli_w.dump(data, f)


# ---------------------------------------------------------------------------
# Path helper
# ---------------------------------------------------------------------------


class TestDefaultProfilePath:
    def test_ends_with_profile_toml(self):
        result = default_profile_path()
        assert result.name == "profile.toml"

    def test_parent_is_config_dir(self):
        result = default_profile_path()
        assert result.parent.name == "garmin-sync"


# ---------------------------------------------------------------------------
# load_config — split layout
# ---------------------------------------------------------------------------


class TestLoadSplitLayout:
    """Both config.toml and profile.toml present."""

    def test_loads_secrets_from_config(self, config_path, profile_path):
        _write_toml(config_path, {
            "openai": {"api_key": "sk-test123", "model": "gpt-4o", "enabled": True, "use_tools": False},
            "hevy": {"api_key": "hv-abc", "enabled": True, "sync_days": 14},
        })
        _write_toml(profile_path, {
            "training": {"schedule": "Mon: run", "user_context": "5K goal", "timezone": "US/Pacific"},
        })

        cfg = load_config(config_path, profile_path)

        assert cfg.api_key == "sk-test123"
        assert cfg.model == "gpt-4o"
        assert cfg.use_tools is False
        assert cfg.hevy.api_key == "hv-abc"
        assert cfg.hevy.sync_days == 14

    def test_loads_profile_from_profile_toml(self, config_path, profile_path):
        _write_toml(config_path, {"openai": {"api_key": "sk-x"}})
        _write_toml(profile_path, {
            "training": {"schedule": "Mon: run", "user_context": "5K goal", "timezone": "US/Pacific"},
        })

        cfg = load_config(config_path, profile_path)

        assert cfg.schedule == "Mon: run"
        assert cfg.user_context == "5K goal"
        assert cfg.timezone == "US/Pacific"


# ---------------------------------------------------------------------------
# load_config — legacy fallback
# ---------------------------------------------------------------------------


class TestLoadLegacyFallback:
    """Only old-style config.toml with [analysis] section, no profile.toml."""

    def test_reads_analysis_from_config(self, config_path, profile_path):
        _write_toml(config_path, {
            "openai": {"api_key": "sk-old"},
            "analysis": {"schedule": "Tue: tempo", "user_context": "marathon", "timezone": "US/Eastern"},
        })
        # profile_path does NOT exist

        cfg = load_config(config_path, profile_path)

        assert cfg.api_key == "sk-old"
        assert cfg.schedule == "Tue: tempo"
        assert cfg.user_context == "marathon"
        assert cfg.timezone == "US/Eastern"


# ---------------------------------------------------------------------------
# load_config — no files at all
# ---------------------------------------------------------------------------


class TestLoadNoFiles:
    def test_returns_defaults(self, config_path, profile_path):
        cfg = load_config(config_path, profile_path)

        assert cfg.api_key is None
        assert cfg.model == "o3-mini"
        assert cfg.schedule == DEFAULT_SCHEDULE
        assert cfg.timezone == "America/New_York"


# ---------------------------------------------------------------------------
# save_config — creates both files
# ---------------------------------------------------------------------------


class TestSaveConfig:
    def test_creates_both_files(self, config_path, profile_path):
        cfg = AIConfig(api_key="sk-new", schedule="Wed: rest", user_context="base building")

        save_config(cfg, config_path, profile_path)

        assert config_path.exists()
        assert profile_path.exists()

    def test_config_has_no_schedule(self, config_path, profile_path):
        cfg = AIConfig(api_key="sk-new", schedule="Wed: rest")

        save_config(cfg, config_path, profile_path)

        import tomli as tomllib
        with open(config_path, "rb") as f:
            data = tomllib.load(f)

        assert "analysis" not in data
        assert "training" not in data
        assert "schedule" not in data.get("openai", {})

    def test_profile_has_no_secrets(self, config_path, profile_path):
        cfg = AIConfig(api_key="sk-secret", schedule="Thu: hills")
        cfg.hevy.api_key = "hv-secret"

        save_config(cfg, config_path, profile_path)

        raw = profile_path.read_text()
        assert "sk-secret" not in raw
        assert "hv-secret" not in raw

    def test_profile_has_training_data(self, config_path, profile_path):
        cfg = AIConfig(schedule="Fri: long run", user_context="ultra prep", timezone="Europe/London")

        save_config(cfg, config_path, profile_path)

        import tomli as tomllib
        with open(profile_path, "rb") as f:
            data = tomllib.load(f)

        training = data["training"]
        assert training["schedule"] == "Fri: long run"
        assert training["user_context"] == "ultra prep"
        assert training["timezone"] == "Europe/London"

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions only")
    def test_config_permissions(self, config_path, profile_path):
        cfg = AIConfig(api_key="sk-x")

        save_config(cfg, config_path, profile_path)

        config_mode = stat.S_IMODE(config_path.stat().st_mode)
        profile_mode = stat.S_IMODE(profile_path.stat().st_mode)

        assert config_mode == 0o600
        assert profile_mode == 0o644

    def test_config_never_world_readable_during_write(self, config_path, profile_path, monkeypatch):
        """Regression: the API key must never sit in a world-readable file.
        Re-save over a pre-existing 0o644 file and assert the mode is ALREADY
        0o600 at the instant the secret is written (not merely chmod'd after)."""
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("old = 1")
        config_path.chmod(0o644)  # pre-existing loose-mode file

        import garmin_sync.ai.config as cfg
        orig_dump = cfg.tomli_w.dump
        modes_at_write = []

        def spy_dump(data, f):
            modes_at_write.append(stat.S_IMODE(config_path.stat().st_mode))
            return orig_dump(data, f)

        monkeypatch.setattr(cfg.tomli_w, "dump", spy_dump)
        save_config(AIConfig(api_key="sk-secret"), config_path, profile_path)

        # First dump is config.toml (the secret file); it must be 0o600 already.
        assert modes_at_write[0] == 0o600
        assert stat.S_IMODE(config_path.stat().st_mode) == 0o600

    def test_strength_rejects_invalid_targets(self, config_path, profile_path):
        """bool / negative / zero strength targets are ignored (isinstance(True,
        int) is True in Python); valid positive ints are applied."""
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text(
            "[strength]\nchest = true\nbiceps = -5\nlats = 0\nquadriceps = 16\n"
        )
        cfg = load_config(config_path, profile_path)
        assert cfg.strength.get_target("chest") == 14        # bool ignored, default kept
        assert cfg.strength.get_target("quadriceps") == 16   # valid override applied

    def test_roundtrip(self, config_path, profile_path):
        original = AIConfig(
            api_key="sk-round",
            model="gpt-4o",
            enabled=False,
            use_tools=True,
            schedule="Sat: race",
            user_context="taper week",
            timezone="Asia/Tokyo",
        )
        original.hevy.api_key = "hv-round"
        original.hevy.sync_days = 60

        save_config(original, config_path, profile_path)
        loaded = load_config(config_path, profile_path)

        assert loaded.api_key == original.api_key
        assert loaded.model == original.model
        assert loaded.enabled == original.enabled
        assert loaded.schedule == original.schedule
        assert loaded.user_context == original.user_context
        assert loaded.timezone == original.timezone
        assert loaded.hevy.api_key == original.hevy.api_key
        assert loaded.hevy.sync_days == original.hevy.sync_days


# ---------------------------------------------------------------------------
# migrate_config_if_needed
# ---------------------------------------------------------------------------


class TestMigration:
    def test_migrates_analysis_to_profile(self, config_path, profile_path):
        _write_toml(config_path, {
            "openai": {"api_key": "sk-mig"},
            "analysis": {"schedule": "Sun: easy", "user_context": "recovery week", "timezone": "US/Central"},
            "hevy": {"api_key": "hv-mig"},
        })

        result = migrate_config_if_needed(config_path, profile_path)

        assert result is True
        assert profile_path.exists()

        # profile.toml has the training data
        import tomli as tomllib
        with open(profile_path, "rb") as f:
            pdata = tomllib.load(f)
        assert pdata["training"]["schedule"] == "Sun: easy"

        # config.toml no longer has [analysis]
        with open(config_path, "rb") as f:
            cdata = tomllib.load(f)
        assert "analysis" not in cdata
        assert cdata["openai"]["api_key"] == "sk-mig"
        assert cdata["hevy"]["api_key"] == "hv-mig"

    def test_idempotent(self, config_path, profile_path):
        _write_toml(config_path, {
            "openai": {"api_key": "sk-x"},
            "analysis": {"schedule": "Mon: rest"},
        })

        assert migrate_config_if_needed(config_path, profile_path) is True
        assert migrate_config_if_needed(config_path, profile_path) is False

    def test_no_op_when_profile_exists(self, config_path, profile_path):
        _write_toml(config_path, {
            "openai": {"api_key": "sk-x"},
            "analysis": {"schedule": "old schedule"},
        })
        _write_toml(profile_path, {
            "training": {"schedule": "new schedule"},
        })

        result = migrate_config_if_needed(config_path, profile_path)

        assert result is False
        # profile.toml unchanged
        import tomli as tomllib
        with open(profile_path, "rb") as f:
            pdata = tomllib.load(f)
        assert pdata["training"]["schedule"] == "new schedule"

    def test_no_op_when_no_analysis_section(self, config_path, profile_path):
        _write_toml(config_path, {"openai": {"api_key": "sk-x"}})

        result = migrate_config_if_needed(config_path, profile_path)

        assert result is False
        assert not profile_path.exists()


# ---------------------------------------------------------------------------
# Strength set targets
# ---------------------------------------------------------------------------


class TestStrengthTargets:
    """Test that strength set targets load with defaults and user overrides."""

    def test_strength_targets_load_defaults(self, config_path, profile_path):
        """No [strength] section in profile means all defaults are used."""
        _write_toml(config_path, {"openai": {"api_key": "sk-x"}})
        _write_toml(profile_path, {
            "training": {"schedule": "Mon: run"},
        })

        cfg = load_config(config_path, profile_path)

        assert cfg.strength.weekly_set_targets["quadriceps"] == 12
        assert cfg.strength.weekly_set_targets["biceps"] == 12
        # Fallback for an unknown group
        assert cfg.strength.get_target("unknown_group") == 6

    def test_strength_targets_user_override_merges(self, config_path, profile_path):
        """User overrides in [strength] merge on top of defaults."""
        _write_toml(config_path, {"openai": {"api_key": "sk-x"}})
        _write_toml(profile_path, {
            "training": {"schedule": "Mon: run"},
            "strength": {"quadriceps": 16, "upper_back": 14},
        })

        cfg = load_config(config_path, profile_path)

        # Overridden values
        assert cfg.strength.weekly_set_targets["quadriceps"] == 16  # user override
        assert cfg.strength.weekly_set_targets["upper_back"] == 14  # user override
        # Default preserved
        assert cfg.strength.weekly_set_targets["chest"] == 14
