# pyright: reportPrivateUsage=false
"""Tests for researchclaw.utils.env_bootstrap.

Covers:
- bootstrap_env() loads variables from an explicit .env file
- override=True replaces existing stale empty-string env vars
- override=False does NOT replace existing set values
- no .env file → function completes without error (graceful no-op)
- missing python-dotenv → function completes without error (graceful no-op)
- _find_dotenv() walks up from a subdirectory and locates .env
- variables are visible in os.environ after bootstrap
- bootstrap_env is idempotent (safe to call multiple times)
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_dotenv(directory: Path, content: str) -> Path:
    p = directory / ".env"
    p.write_text(content, encoding="utf-8")
    return p


def _reload_bootstrap_module():
    """Reload env_bootstrap so _bootstrapped guard resets."""
    import researchclaw.utils.env_bootstrap as m
    # Reset module-level guard so subsequent tests start fresh
    m._bootstrapped = False
    return m


# ---------------------------------------------------------------------------
# _find_dotenv
# ---------------------------------------------------------------------------


class TestFindDotenv:
    def test_finds_dotenv_in_same_directory(self, tmp_path: Path) -> None:
        from researchclaw.utils.env_bootstrap import _find_dotenv

        dot = _write_dotenv(tmp_path, "KEY=value\n")
        found = _find_dotenv(start=tmp_path)
        assert found == dot

    def test_finds_dotenv_in_parent_directory(self, tmp_path: Path) -> None:
        from researchclaw.utils.env_bootstrap import _find_dotenv

        _write_dotenv(tmp_path, "KEY=value\n")
        sub = tmp_path / "subdir" / "nested"
        sub.mkdir(parents=True)
        found = _find_dotenv(start=sub)
        assert found == tmp_path / ".env"

    def test_returns_none_when_no_dotenv(self, tmp_path: Path) -> None:
        from researchclaw.utils.env_bootstrap import _find_dotenv

        # tmp_path has no .env; assume no .env exists further up in a temp tree
        isolated = tmp_path / "no_dotenv_here"
        isolated.mkdir()
        # We can't guarantee the filesystem above has no .env, so just test
        # the function is callable and returns a Path or None without crashing.
        result = _find_dotenv(start=isolated)
        assert result is None or result.name == ".env"


# ---------------------------------------------------------------------------
# bootstrap_env: explicit dotenv_path
# ---------------------------------------------------------------------------


class TestBootstrapEnvExplicitPath:
    def test_loads_key_from_explicit_dotenv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dot = _write_dotenv(tmp_path, "RC_TEST_BOOTSTRAP_VAR=hello123\n")
        monkeypatch.delenv("RC_TEST_BOOTSTRAP_VAR", raising=False)

        m = _reload_bootstrap_module()
        m.bootstrap_env(dotenv_path=dot)

        assert os.environ.get("RC_TEST_BOOTSTRAP_VAR") == "hello123"

    def test_override_true_replaces_stale_empty_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dot = _write_dotenv(tmp_path, "RC_TEST_STALE_KEY=fresh_value\n")
        # Simulate stale empty shell export
        monkeypatch.setenv("RC_TEST_STALE_KEY", "")

        m = _reload_bootstrap_module()
        m.bootstrap_env(dotenv_path=dot, override=True)

        assert os.environ.get("RC_TEST_STALE_KEY") == "fresh_value"

    def test_override_false_does_not_replace_existing_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dot = _write_dotenv(tmp_path, "RC_TEST_EXISTING_KEY=from_dotenv\n")
        monkeypatch.setenv("RC_TEST_EXISTING_KEY", "already_set")

        m = _reload_bootstrap_module()
        m.bootstrap_env(dotenv_path=dot, override=False)

        assert os.environ.get("RC_TEST_EXISTING_KEY") == "already_set"

    def test_multiple_keys_loaded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dot = _write_dotenv(
            tmp_path,
            "RC_KEY_A=value_a\nRC_KEY_B=value_b\nRC_KEY_C=value_c\n",
        )
        for k in ("RC_KEY_A", "RC_KEY_B", "RC_KEY_C"):
            monkeypatch.delenv(k, raising=False)

        m = _reload_bootstrap_module()
        m.bootstrap_env(dotenv_path=dot)

        assert os.environ.get("RC_KEY_A") == "value_a"
        assert os.environ.get("RC_KEY_B") == "value_b"
        assert os.environ.get("RC_KEY_C") == "value_c"


# ---------------------------------------------------------------------------
# bootstrap_env: no .env file
# ---------------------------------------------------------------------------


class TestBootstrapEnvNoDotenv:
    def test_no_dotenv_file_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        """bootstrap_env with a non-existent path completes without exception."""
        m = _reload_bootstrap_module()
        non_existent = tmp_path / "does_not_exist.env"
        # Providing a non-existent explicit path should not raise
        # (dotenv silently skips missing files)
        try:
            m.bootstrap_env(dotenv_path=non_existent)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"bootstrap_env raised unexpectedly: {exc}")

    def test_auto_detect_no_env_does_not_raise(self) -> None:
        """bootstrap_env with no explicit path and no .env in tree should not raise."""
        m = _reload_bootstrap_module()
        # Override _find_dotenv to always return None (simulate no .env in tree)
        original = m._find_dotenv
        try:
            m._find_dotenv = lambda start=None: None
            m.bootstrap_env()  # must not raise
        finally:
            m._find_dotenv = original


# ---------------------------------------------------------------------------
# bootstrap_env: python-dotenv not installed
# ---------------------------------------------------------------------------


class TestBootstrapEnvNoDotenvPackage:
    def test_missing_dotenv_package_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If python-dotenv is not installed, bootstrap_env must be a silent no-op."""
        dot = _write_dotenv(tmp_path, "RC_TEST_NODOTENV_VAR=should_not_load\n")
        monkeypatch.delenv("RC_TEST_NODOTENV_VAR", raising=False)

        m = _reload_bootstrap_module()

        # Simulate dotenv not being installed by patching the import
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "dotenv":
                raise ImportError("No module named 'dotenv'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        m.bootstrap_env(dotenv_path=dot)  # must not raise

        # Variable must NOT have been loaded (dotenv not available)
        assert os.environ.get("RC_TEST_NODOTENV_VAR") is None


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestBootstrapEnvIdempotency:
    def test_calling_twice_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dot = _write_dotenv(tmp_path, "RC_IDEMPOTENT_KEY=stable\n")
        monkeypatch.delenv("RC_IDEMPOTENT_KEY", raising=False)

        m = _reload_bootstrap_module()
        m.bootstrap_env(dotenv_path=dot)
        m.bootstrap_env(dotenv_path=dot)  # second call must not raise

        assert os.environ.get("RC_IDEMPOTENT_KEY") == "stable"

    def test_second_call_does_not_overwrite_manual_change(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After bootstrap, manually changed env vars survive a second bootstrap
        call when override=False."""
        dot = _write_dotenv(tmp_path, "RC_MANUAL_KEY=original\n")
        monkeypatch.delenv("RC_MANUAL_KEY", raising=False)

        m = _reload_bootstrap_module()
        m.bootstrap_env(dotenv_path=dot, override=False)
        # Manually override
        os.environ["RC_MANUAL_KEY"] = "manually_changed"
        # Second call with override=False should not revert
        m.bootstrap_env(dotenv_path=dot, override=False)

        assert os.environ.get("RC_MANUAL_KEY") == "manually_changed"
