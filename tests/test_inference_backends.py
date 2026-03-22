"""Unit tests for researchclaw.inference_backends.

Covers:
- InferenceBackend registry completeness and field invariants
- get_backend() lookup (hit and miss)
- health_ok() — mocked HTTP layer
- list_models() — Ollama format, OpenAI-compatible format, fallback paths
- write_config_for_backend() — YAML generation, field correctness, error paths
"""
from __future__ import annotations

import json
import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from researchclaw.inference_backends import (
    BACKENDS,
    InferenceBackend,
    all_backends,
    get_backend,
    health_ok,
    list_models,
    write_config_for_backend,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def minimal_config(tmp_path: Path) -> Path:
    """Minimal config.yaml with an llm section."""
    cfg = {
        "project": {"name": "test"},
        "llm": {
            "provider": "openai-compatible",
            "base_url": "http://localhost:11434/v1",
            "api_key": "ollama",
            "api_key_env": "OPENAI_API_KEY",
            "primary_model": "old-model",
            "fallback_models": ["fallback-a", "fallback-b"],
        },
        "research": {"topic": "test topic"},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(cfg), encoding="utf-8")
    return config_path


# ---------------------------------------------------------------------------
# Registry invariants
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_all_backends_returns_tuple(self) -> None:
        result = all_backends()
        assert isinstance(result, tuple)
        assert len(result) > 0

    def test_all_ids_are_unique(self) -> None:
        ids = [b.id for b in BACKENDS]
        assert len(ids) == len(set(ids)), "Duplicate backend IDs in registry"

    def test_required_backends_present(self) -> None:
        ids = {b.id for b in BACKENDS}
        for required in ("ollama", "lmstudio", "openai", "anthropic"):
            assert required in ids, f"Backend '{required}' missing from registry"

    def test_all_backends_have_name(self) -> None:
        for b in BACKENDS:
            assert b.name.strip(), f"Backend '{b.id}' has empty name"

    def test_all_backends_have_provider(self) -> None:
        for b in BACKENDS:
            assert b.provider.strip(), f"Backend '{b.id}' has empty provider"

    def test_local_backends_have_health_check(self) -> None:
        """Local backends (requires_api_key=False) should have a health check URL."""
        for b in BACKENDS:
            if not b.requires_api_key and b.id != "openai-compatible":
                assert b.health_check_url is not None, (
                    f"Local backend '{b.id}' missing health_check_url"
                )

    def test_cloud_backends_have_fallback_models(self) -> None:
        for b in BACKENDS:
            if b.requires_api_key:
                assert len(b.fallback_models) > 0, (
                    f"Cloud backend '{b.id}' has no fallback_models"
                )

    def test_ollama_uses_openai_compatible_provider(self) -> None:
        b = get_backend("ollama")
        assert b is not None
        assert b.provider == "openai-compatible"

    def test_lmstudio_uses_openai_compatible_provider(self) -> None:
        b = get_backend("lmstudio")
        assert b is not None
        assert b.provider == "openai-compatible"

    def test_anthropic_backend_provider(self) -> None:
        b = get_backend("anthropic")
        assert b is not None
        assert b.provider == "anthropic"


# ---------------------------------------------------------------------------
# get_backend()
# ---------------------------------------------------------------------------


class TestGetBackend:
    def test_known_id_returns_descriptor(self) -> None:
        b = get_backend("ollama")
        assert isinstance(b, InferenceBackend)
        assert b.id == "ollama"
        assert b.name == "Ollama (Local)"

    def test_lmstudio_lookup(self) -> None:
        b = get_backend("lmstudio")
        assert b is not None
        assert b.id == "lmstudio"
        assert "localhost:1234" in b.base_url

    def test_openai_lookup(self) -> None:
        b = get_backend("openai")
        assert b is not None
        assert b.requires_api_key is True

    def test_unknown_id_returns_none(self) -> None:
        assert get_backend("no-such-backend") is None

    def test_empty_id_returns_none(self) -> None:
        assert get_backend("") is None


# ---------------------------------------------------------------------------
# health_ok()
# ---------------------------------------------------------------------------


class TestHealthOk:
    def test_cloud_backend_always_healthy(self) -> None:
        """Cloud backends (health_check_url=None) always return True."""
        b = get_backend("openai")
        assert b is not None
        assert b.health_check_url is None
        assert health_ok(b) is True

    def test_local_backend_healthy_on_200(self) -> None:
        b = get_backend("ollama")
        assert b is not None
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert health_ok(b) is True

    def test_local_backend_unhealthy_on_connection_error(self) -> None:
        b = get_backend("ollama")
        assert b is not None
        with patch(
            "urllib.request.urlopen",
            side_effect=ConnectionRefusedError("refused"),
        ):
            assert health_ok(b) is False

    def test_local_backend_unhealthy_on_timeout(self) -> None:
        import socket
        b = get_backend("lmstudio")
        assert b is not None
        with patch(
            "urllib.request.urlopen",
            side_effect=socket.timeout("timed out"),
        ):
            assert health_ok(b) is False

    def test_health_check_url_is_used(self) -> None:
        """Verify the correct URL is passed to urlopen."""
        b = get_backend("ollama")
        assert b is not None
        called_urls: list[str] = []

        def fake_urlopen(url: str, timeout: float) -> MagicMock:
            called_urls.append(url)
            raise ConnectionRefusedError

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            health_ok(b)

        assert called_urls == [b.health_check_url]


# ---------------------------------------------------------------------------
# list_models()
# ---------------------------------------------------------------------------


def _make_response(payload: dict) -> MagicMock:
    """Build a mock urlopen() context manager response."""
    body = json.dumps(payload).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


class TestListModels:
    # ── Ollama response format ──

    def test_ollama_parses_models_key(self) -> None:
        b = get_backend("ollama")
        assert b is not None
        payload = {
            "models": [
                {"name": "gemma2:latest"},
                {"name": "qwen2.5-coder:14b"},
            ]
        }
        with patch("urllib.request.urlopen", return_value=_make_response(payload)):
            result = list_models(b)
        assert result == ["gemma2:latest", "qwen2.5-coder:14b"]

    def test_ollama_empty_list_returns_fallback(self) -> None:
        b = get_backend("ollama")
        assert b is not None
        with patch("urllib.request.urlopen", return_value=_make_response({"models": []})):
            result = list_models(b)
        assert result == list(b.fallback_models)

    # ── LM Studio / OpenAI-compatible response format ──

    def test_lmstudio_parses_data_key(self) -> None:
        b = get_backend("lmstudio")
        assert b is not None
        payload = {
            "data": [
                {"id": "mistral-nemo:latest"},
                {"id": "phi-4"},
            ]
        }
        with patch("urllib.request.urlopen", return_value=_make_response(payload)):
            result = list_models(b)
        assert result == ["mistral-nemo:latest", "phi-4"]

    def test_lmstudio_fallback_on_connection_error(self) -> None:
        b = get_backend("lmstudio")
        assert b is not None
        with patch("urllib.request.urlopen", side_effect=OSError("refused")):
            result = list_models(b)
        assert result == list(b.fallback_models)

    # ── Cloud backend (no models_url) ──

    def test_cloud_backend_returns_fallback_directly(self) -> None:
        b = get_backend("openai")
        assert b is not None
        assert b.models_url is None
        # urlopen should NOT be called
        with patch("urllib.request.urlopen") as mock_open:
            result = list_models(b)
        mock_open.assert_not_called()
        assert result == list(b.fallback_models)

    # ── Custom openai-compatible with custom_base_url ──

    def test_custom_base_url_constructs_models_endpoint(self) -> None:
        b = get_backend("openai-compatible")
        assert b is not None
        called_urls: list[str] = []

        def fake_urlopen(url: str, timeout: float) -> MagicMock:
            called_urls.append(url)
            return _make_response({"data": [{"id": "my-model"}]})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = list_models(b, custom_base_url="http://my-server:8000/v1")

        assert called_urls == ["http://my-server:8000/v1/models"]
        assert result == ["my-model"]

    def test_backend_without_models_url_and_no_custom_url_returns_fallback(self) -> None:
        b = get_backend("openai")
        assert b is not None
        result = list_models(b)
        assert result == list(b.fallback_models)


# ---------------------------------------------------------------------------
# write_config_for_backend()
# ---------------------------------------------------------------------------


class TestWriteConfigForBackend:
    def test_ollama_config_fields(self, minimal_config: Path, tmp_path: Path) -> None:
        b = get_backend("ollama")
        assert b is not None
        tmp = write_config_for_backend(
            backend=b,
            model="gemma2:latest",
            base_config_path=minimal_config,
            tmp_dir=tmp_path,
        )
        data = yaml.safe_load(tmp.read_text())
        llm = data["llm"]
        assert llm["provider"] == "openai-compatible"
        assert llm["base_url"] == "http://localhost:11434/v1"
        assert llm["api_key"] == "ollama"           # api_key_default
        assert llm["primary_model"] == "gemma2:latest"
        assert llm["fallback_models"] == []         # cleared
        tmp.unlink()

    def test_lmstudio_config_fields(self, minimal_config: Path, tmp_path: Path) -> None:
        b = get_backend("lmstudio")
        assert b is not None
        tmp = write_config_for_backend(
            backend=b,
            model="mistral-nemo:latest",
            base_config_path=minimal_config,
            tmp_dir=tmp_path,
        )
        data = yaml.safe_load(tmp.read_text())
        llm = data["llm"]
        assert llm["base_url"] == "http://localhost:1234/v1"
        assert llm["api_key"] == "lm-studio"
        assert llm["primary_model"] == "mistral-nemo:latest"
        tmp.unlink()

    def test_cloud_backend_uses_provided_api_key(
        self, minimal_config: Path, tmp_path: Path
    ) -> None:
        b = get_backend("openai")
        assert b is not None
        tmp = write_config_for_backend(
            backend=b,
            model="gpt-4o",
            base_config_path=minimal_config,
            api_key="sk-test-key",
            tmp_dir=tmp_path,
        )
        data = yaml.safe_load(tmp.read_text())
        llm = data["llm"]
        assert llm["provider"] == "openai"
        assert llm["api_key"] == "sk-test-key"
        assert llm["primary_model"] == "gpt-4o"
        tmp.unlink()

    def test_custom_base_url_overrides_backend_url(
        self, minimal_config: Path, tmp_path: Path
    ) -> None:
        b = get_backend("openai-compatible")
        assert b is not None
        tmp = write_config_for_backend(
            backend=b,
            model="my-model",
            base_config_path=minimal_config,
            custom_base_url="http://custom-server:8080/v1",
            tmp_dir=tmp_path,
        )
        data = yaml.safe_load(tmp.read_text())
        assert data["llm"]["base_url"] == "http://custom-server:8080/v1"
        tmp.unlink()

    def test_other_config_sections_preserved(
        self, minimal_config: Path, tmp_path: Path
    ) -> None:
        """Non-llm sections (project, research, …) must be untouched."""
        b = get_backend("ollama")
        assert b is not None
        tmp = write_config_for_backend(
            backend=b,
            model="gemma2:latest",
            base_config_path=minimal_config,
            tmp_dir=tmp_path,
        )
        data = yaml.safe_load(tmp.read_text())
        assert data["project"]["name"] == "test"
        assert data["research"]["topic"] == "test topic"
        tmp.unlink()

    def test_generated_yaml_is_valid(
        self, minimal_config: Path, tmp_path: Path
    ) -> None:
        b = get_backend("ollama")
        assert b is not None
        tmp = write_config_for_backend(
            backend=b,
            model="gemma2:latest",
            base_config_path=minimal_config,
            tmp_dir=tmp_path,
        )
        # Must parse without error
        data = yaml.safe_load(tmp.read_text())
        assert isinstance(data, dict)
        tmp.unlink()

    def test_missing_base_config_raises(self, tmp_path: Path) -> None:
        b = get_backend("ollama")
        assert b is not None
        with pytest.raises(FileNotFoundError):
            write_config_for_backend(
                backend=b,
                model="gemma2:latest",
                base_config_path=tmp_path / "nonexistent.yaml",
            )

    def test_openai_compatible_without_url_raises(
        self, minimal_config: Path, tmp_path: Path
    ) -> None:
        """Generic openai-compatible backend has no default URL — must raise."""
        b = get_backend("openai-compatible")
        assert b is not None
        assert not b.base_url  # confirm no default URL
        with pytest.raises(ValueError, match="base_url"):
            write_config_for_backend(
                backend=b,
                model="any-model",
                base_config_path=minimal_config,
                tmp_dir=tmp_path,
                # No custom_base_url provided
            )

    def test_tmp_file_prefix_contains_backend_id(
        self, minimal_config: Path, tmp_path: Path
    ) -> None:
        b = get_backend("lmstudio")
        assert b is not None
        tmp = write_config_for_backend(
            backend=b,
            model="phi-4",
            base_config_path=minimal_config,
            tmp_dir=tmp_path,
        )
        assert "lmstudio" in tmp.name
        tmp.unlink()

    def test_api_key_env_written_correctly(
        self, minimal_config: Path, tmp_path: Path
    ) -> None:
        b = get_backend("anthropic")
        assert b is not None
        tmp = write_config_for_backend(
            backend=b,
            model="claude-sonnet-4-6",
            base_config_path=minimal_config,
            api_key="sk-ant-test",
            tmp_dir=tmp_path,
        )
        data = yaml.safe_load(tmp.read_text())
        assert data["llm"]["api_key_env"] == "ANTHROPIC_API_KEY"
        tmp.unlink()
