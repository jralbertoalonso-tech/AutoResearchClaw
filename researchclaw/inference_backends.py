"""Inference backend registry for AutoResearchClaw.

Provides a declarative, centralised registry of local and cloud LLM backends
so that ``web_ui.py`` can discover models, perform health checks, and write
valid ``config.yaml`` patches without hardcoding provider-specific logic.

Usage
-----
>>> from researchclaw.inference_backends import get_backend, list_models, health_ok
>>> b = get_backend("ollama")
>>> health_ok(b)        # True if the local server is up
>>> list_models(b)      # ["gemma2:latest", "qwen2.5:14b", ...]

For config generation::

    from researchclaw.inference_backends import write_config_for_backend
    tmp_path = write_config_for_backend(
        backend=get_backend("lmstudio"),
        model="mistral-nemo:latest",
        base_config_path=Path("config.yaml"),
    )
"""
from __future__ import annotations

import json
import logging
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# InferenceBackend descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InferenceBackend:
    """Descriptor for a single inference backend (local or cloud).

    Fields
    ------
    id:
        Machine-readable key (``"ollama"``, ``"lmstudio"``, …).
    name:
        Human-readable label shown in the UI.
    provider:
        Value written to ``config.yaml → llm.provider``.
        Must match the set understood by ``researchclaw.llm``:
        ``"openai-compatible"``, ``"openai"``, ``"anthropic"``, …
    base_url:
        API endpoint used for chat completions.
        For local backends this is the OpenAI-compatible URL (e.g.
        ``http://localhost:11434/v1``).
    models_url:
        Endpoint for listing available models, or ``None`` if the backend
        does not expose a model-list API.
    models_response_key:
        JSON key in the models response that contains the list.
        Ollama uses ``"models"``; OpenAI-compatible servers use ``"data"``.
    model_name_field:
        Field inside each model object that holds the model name string.
        Ollama: ``"name"``; OpenAI-compatible: ``"id"``.
    api_key_default:
        Placeholder API key value written to the config when the backend
        does not require a real secret (``"ollama"`` / ``"lm-studio"``).
    api_key_env:
        Environment variable name to inject the real API key for cloud
        backends (``"OPENAI_API_KEY"``, ``"ANTHROPIC_API_KEY"``, …).
    requires_api_key:
        ``False`` for fully-local backends (Ollama, LM Studio).
        ``True`` for cloud providers that reject requests without a token.
    health_check_url:
        URL used by ``health_ok()`` to probe liveness.  A successful HTTP
        response (any 2xx) means the backend is available.
        ``None`` for cloud providers (always assumed reachable).
    fallback_models:
        Static list returned by ``list_models()`` when the server is
        unreachable or returns an empty list.
    """

    id: str
    name: str
    provider: str
    base_url: str
    models_url: str | None = None
    models_response_key: str = "data"
    model_name_field: str = "id"
    api_key_default: str = ""
    api_key_env: str = "OPENAI_API_KEY"
    requires_api_key: bool = False
    health_check_url: str | None = None
    fallback_models: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Backend registry
# ---------------------------------------------------------------------------

BACKENDS: tuple[InferenceBackend, ...] = (
    # ── Local backends ─────────────────────────────────────────────────────
    InferenceBackend(
        id="ollama",
        name="Ollama (Local)",
        provider="openai-compatible",
        base_url="http://localhost:11434/v1",
        models_url="http://localhost:11434/api/tags",
        models_response_key="models",
        model_name_field="name",
        api_key_default="ollama",
        api_key_env="OPENAI_API_KEY",
        requires_api_key=False,
        health_check_url="http://localhost:11434",
        fallback_models=("gemma2:latest", "qwen2.5-coder:14b", "qwen2.5-coder:7b"),
    ),
    InferenceBackend(
        id="lmstudio",
        name="LM Studio (Local)",
        provider="openai-compatible",
        base_url="http://localhost:1234/v1",
        models_url="http://localhost:1234/v1/models",
        models_response_key="data",
        model_name_field="id",
        api_key_default="lm-studio",
        api_key_env="OPENAI_API_KEY",
        requires_api_key=False,
        health_check_url="http://localhost:1234/v1/models",
        fallback_models=("local-model",),
    ),
    # ── Cloud backends ──────────────────────────────────────────────────────
    InferenceBackend(
        id="openai",
        name="OpenAI (Cloud)",
        provider="openai",
        base_url="https://api.openai.com/v1",
        models_url=None,
        api_key_default="",
        api_key_env="OPENAI_API_KEY",
        requires_api_key=True,
        health_check_url=None,
        fallback_models=("gpt-4o", "gpt-4o-mini"),
    ),
    InferenceBackend(
        id="anthropic",
        name="Anthropic (Cloud)",
        provider="anthropic",
        base_url="https://api.anthropic.com",
        models_url=None,
        api_key_default="",
        api_key_env="ANTHROPIC_API_KEY",
        requires_api_key=True,
        health_check_url=None,
        fallback_models=("claude-opus-4-6", "claude-sonnet-4-6"),
    ),
    InferenceBackend(
        id="openrouter",
        name="OpenRouter (Cloud)",
        provider="openai-compatible",
        base_url="https://openrouter.ai/api/v1",
        models_url=None,
        api_key_default="",
        api_key_env="OPENROUTER_API_KEY",
        requires_api_key=True,
        health_check_url=None,
        fallback_models=("openai/gpt-4o", "anthropic/claude-3-5-sonnet"),
    ),
    InferenceBackend(
        id="openai-compatible",
        name="OpenAI-compatible (Custom)",
        provider="openai-compatible",
        base_url="",  # user-provided
        models_url=None,
        api_key_default="",
        api_key_env="OPENAI_API_KEY",
        requires_api_key=False,
        health_check_url=None,
        fallback_models=(),
    ),
)

# Fast lookup by id
_BACKEND_BY_ID: dict[str, InferenceBackend] = {b.id: b for b in BACKENDS}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_backend(backend_id: str) -> InferenceBackend | None:
    """Return the :class:`InferenceBackend` with the given *backend_id*, or
    ``None`` if not found.

    >>> get_backend("ollama").name
    'Ollama (Local)'
    >>> get_backend("unknown") is None
    True
    """
    return _BACKEND_BY_ID.get(backend_id)


def all_backends() -> tuple[InferenceBackend, ...]:
    """Return the full ordered registry tuple."""
    return BACKENDS


def health_ok(backend: InferenceBackend, timeout: float = 3.0) -> bool:
    """Return ``True`` if the backend's health-check URL responds with 2xx.

    Cloud backends (``health_check_url is None``) are assumed always
    reachable — this function returns ``True`` for them.

    Parameters
    ----------
    backend:
        The backend to probe.
    timeout:
        HTTP timeout in seconds (default 3 s to keep the UI snappy).
    """
    if backend.health_check_url is None:
        return True  # cloud — no local server to check

    try:
        with urllib.request.urlopen(
            backend.health_check_url, timeout=timeout
        ) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def list_models(
    backend: InferenceBackend,
    timeout: float = 5.0,
    *,
    custom_base_url: str = "",
) -> list[str]:
    """Return available models for the given backend.

    Behaviour
    ---------
    - If ``backend.models_url`` is set, performs an HTTP GET and parses the
      JSON response using ``backend.models_response_key`` / ``backend.model_name_field``.
    - If the request fails or the list is empty, returns ``list(backend.fallback_models)``.
    - If ``backend.models_url`` is ``None`` (cloud without model API), returns
      ``list(backend.fallback_models)`` directly.
    - For the ``"openai-compatible"`` custom backend, *custom_base_url* overrides
      the stored ``base_url`` so the caller can query arbitrary servers.

    Parameters
    ----------
    backend:
        The backend to query.
    timeout:
        HTTP timeout in seconds.
    custom_base_url:
        Override for the base_url (used by the generic openai-compatible backend).
    """
    models_url = backend.models_url

    # For the generic openai-compatible backend, construct a models URL from the
    # caller-supplied base_url.
    if not models_url and custom_base_url:
        base = custom_base_url.rstrip("/")
        models_url = f"{base}/models"

    if not models_url:
        return list(backend.fallback_models)

    try:
        with urllib.request.urlopen(models_url, timeout=timeout) as resp:
            data: dict[str, Any] = json.loads(resp.read().decode())

        raw_list = data.get(backend.models_response_key, [])
        if not isinstance(raw_list, list):
            raise ValueError(f"Expected list under '{backend.models_response_key}'")

        names = [
            item[backend.model_name_field]
            for item in raw_list
            if isinstance(item, dict) and backend.model_name_field in item
        ]
        return names if names else list(backend.fallback_models)

    except Exception as exc:
        logger.debug(
            "list_models(%s): could not fetch from %s — %s",
            backend.id,
            models_url,
            exc,
        )
        return list(backend.fallback_models)


def write_config_for_backend(
    backend: InferenceBackend,
    model: str,
    base_config_path: Path,
    *,
    api_key: str = "",
    custom_base_url: str = "",
    tmp_dir: Path | None = None,
) -> Path:
    """Write a temporary ``config.yaml`` patched for the selected backend/model.

    Generates a **structurally-correct YAML** file by loading the base config,
    updating only the ``llm`` section, and dumping via PyYAML — no fragile
    regex substitutions.

    Parameters
    ----------
    backend:
        The target backend descriptor.
    model:
        The model name to write into ``llm.primary_model``.
    base_config_path:
        Path to the project's ``config.yaml`` used as the base template.
    api_key:
        API key value to write literally into ``llm.api_key``.  If blank,
        ``backend.api_key_default`` is used for local backends.
    custom_base_url:
        Override for ``llm.base_url``.  Required for the generic
        ``openai-compatible`` backend; ignored for all others.
    tmp_dir:
        Directory for the temporary file (defaults to same dir as
        *base_config_path*).

    Returns
    -------
    Path
        The temporary config file path.  The caller is responsible for
        cleaning it up.

    Raises
    ------
    FileNotFoundError
        If *base_config_path* does not exist.
    ValueError
        If *backend* is the generic openai-compatible backend and no URL is
        provided via *custom_base_url* or the backend's own ``base_url``.
    """
    if not base_config_path.exists():
        raise FileNotFoundError(
            f"Base config not found: {base_config_path}"
        )

    # Determine the effective base_url
    effective_base_url = (
        custom_base_url.strip()
        or backend.base_url
    )
    if not effective_base_url:
        raise ValueError(
            f"Backend '{backend.id}' requires a base_url but none was provided. "
            "Pass custom_base_url= when calling write_config_for_backend()."
        )

    # Determine the effective api_key
    effective_api_key = api_key.strip() or backend.api_key_default

    # Load base config as a plain dict (preserves all unrelated sections)
    raw = yaml.safe_load(base_config_path.read_text(encoding="utf-8")) or {}

    # Patch only the llm sub-dict
    llm: dict[str, Any] = raw.get("llm", {}) or {}
    llm["provider"] = backend.provider
    llm["base_url"] = effective_base_url
    llm["api_key"] = effective_api_key
    llm["api_key_env"] = backend.api_key_env
    llm["primary_model"] = model
    # Clear fallback list so it doesn't override the chosen model
    llm["fallback_models"] = []
    raw["llm"] = llm

    # Write to a named temp file in the requested directory
    out_dir = tmp_dir or base_config_path.parent
    prefix = f".rc_backend_{backend.id}_"
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".yaml",
        prefix=prefix,
        dir=out_dir,
        delete=False,
        encoding="utf-8",
    ) as fh:
        yaml.dump(raw, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)
        tmp_path = Path(fh.name)

    logger.debug(
        "write_config_for_backend: wrote %s (backend=%s model=%s base_url=%s)",
        tmp_path.name,
        backend.id,
        model,
        effective_base_url,
    )
    return tmp_path
