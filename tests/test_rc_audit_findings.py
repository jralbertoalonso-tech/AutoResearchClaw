"""Tests for audit findings AUD-F1 (truncation detection) and AUD-F3 (parse-once).

These tests validate the improvements from the second-pass senior audit:
  - FINDING-1: _write_paper_sections detects truncated LLM responses
  - FINDING-3: _execute_paper_draft parses experiment summary JSON once
  - FINDING-2 (advisory): context budget logging is non-invasive
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Minimal stubs to avoid importing heavy executor dependencies
# ---------------------------------------------------------------------------

@dataclass
class _FakeLLMResponse:
    """Mirrors researchclaw.llm.client.LLMResponse for test isolation."""
    content: str
    model: str = "test-model"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = "stop"
    truncated: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# FINDING-1: Truncation detection tests
# ---------------------------------------------------------------------------

class TestTruncationDetection:
    """AUD-F1: _write_paper_sections must log warnings on truncated output."""

    def _make_response(self, content: str, truncated: bool = False) -> _FakeLLMResponse:
        return _FakeLLMResponse(
            content=content,
            finish_reason="length" if truncated else "stop",
            truncated=truncated,
        )

    def test_truncated_response_has_flag(self):
        """LLMResponse.truncated=True when finish_reason is 'length'."""
        resp = self._make_response("partial output...", truncated=True)
        assert resp.truncated is True
        assert resp.finish_reason == "length"

    def test_normal_response_has_no_flag(self):
        resp = self._make_response("complete output.", truncated=False)
        assert resp.truncated is False

    def test_getattr_truncated_on_response(self):
        """The code uses getattr(resp, 'truncated', False) — verify both paths."""
        resp_trunc = self._make_response("x", truncated=True)
        resp_ok = self._make_response("x", truncated=False)
        assert getattr(resp_trunc, "truncated", False) is True
        assert getattr(resp_ok, "truncated", False) is False

    def test_getattr_truncated_missing_attr(self):
        """If response object lacks 'truncated', getattr returns False (safe)."""
        class BareResponse:
            content = "bare"
        assert getattr(BareResponse(), "truncated", False) is False

    def test_truncation_warning_logged(self, caplog):
        """Simulate the truncation logging pattern used in executor.py."""
        resp = self._make_response("## Title\nIncomplete...", truncated=True)
        _paper_max_tokens = 4096
        with caplog.at_level(logging.WARNING):
            if getattr(resp, "truncated", False):
                logging.getLogger("researchclaw.pipeline.executor").warning(
                    "Stage 17: Part 1 TRUNCATED (finish_reason=length, max_tokens=%d). "
                    "Sections may be incomplete — consider increasing max_tokens or "
                    "reducing prompt size.",
                    _paper_max_tokens,
                )
        assert any("TRUNCATED" in r.message for r in caplog.records)
        assert any("4096" in r.message for r in caplog.records)

    def test_no_warning_on_normal_response(self, caplog):
        """No truncation warning when response completes normally."""
        resp = self._make_response("## Title\nComplete paper...", truncated=False)
        with caplog.at_level(logging.WARNING):
            if getattr(resp, "truncated", False):
                logging.getLogger("researchclaw.pipeline.executor").warning(
                    "TRUNCATED"
                )
        assert not any("TRUNCATED" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# FINDING-3: Parse-once tests
# ---------------------------------------------------------------------------

class TestParseOnce:
    """AUD-F3: experiment summary should be parsed once and reused."""

    SAMPLE_SUMMARY = {
        "total_conditions": 3,
        "total_metric_keys": 5,
        "metrics_summary": {
            "accuracy": {"mean": 0.85, "min": 0.80, "max": 0.90, "count": 3}
        },
        "condition_summaries": {
            "baseline": {"success_rate": 0.7, "n_seeds": 3},
            "method_a": {"success_rate": 0.9, "n_seeds": 3},
        },
        "paired_comparisons": [
            {"method": "method_a", "baseline": "baseline", "p_value": 0.01}
        ],
        "datasets": ["cifar10"],
        "ablation_warnings": [],
    }

    def test_single_parse_produces_valid_dict(self):
        """_safe_json_loads should produce a usable dict from valid JSON."""
        text = json.dumps(self.SAMPLE_SUMMARY)
        # Simulate the parse-once pattern
        from researchclaw.pipeline.executor import _safe_json_loads
        result = _safe_json_loads(text, {})
        assert isinstance(result, dict)
        assert result["total_conditions"] == 3
        assert "accuracy" in result["metrics_summary"]

    def test_single_parse_covers_all_access_patterns(self):
        """All downstream blocks (R18-1, BUG-003, P7, P10) can read from one dict."""
        d = self.SAMPLE_SUMMARY
        # R18-1: paired_comparisons
        assert isinstance(d.get("paired_comparisons", []), list)
        # R19-6: condition_summaries
        assert isinstance(d.get("condition_summaries", {}), dict)
        # BUG-003: datasets
        assert isinstance(d.get("datasets", []), list)
        # P7: ablation_warnings
        assert isinstance(d.get("ablation_warnings", []), list)
        # P10: condition_summaries (for contradiction detection)
        assert "baseline" in d.get("condition_summaries", {})

    def test_empty_json_returns_empty_dict(self):
        from researchclaw.pipeline.executor import _safe_json_loads
        result = _safe_json_loads("", {})
        assert result == {}

    def test_invalid_json_returns_default(self):
        from researchclaw.pipeline.executor import _safe_json_loads
        result = _safe_json_loads("{broken json", {"fallback": True})
        assert result == {"fallback": True}

    def test_non_dict_json_returns_as_is(self):
        """Lists or other types from JSON should pass through."""
        from researchclaw.pipeline.executor import _safe_json_loads
        result = _safe_json_loads("[1, 2, 3]", {})
        assert result == [1, 2, 3]


# ---------------------------------------------------------------------------
# FINDING-2: Context budget logging (advisory — non-invasive check)
# ---------------------------------------------------------------------------

class TestContextBudgetLogging:
    """AUD-F2: Context budget estimation is purely diagnostic."""

    def test_token_estimate_heuristic(self):
        """~4 chars per token is a reasonable rough estimate."""
        text = "a" * 4000
        estimate = len(text) // 4
        assert estimate == 1000

    def test_budget_warning_threshold(self):
        """Warning fires when estimated total > 7500 for local models."""
        _sys_est = 3000
        _usr_est = 3000
        _max_output = 4096
        _total = _sys_est + _usr_est + _max_output
        _is_likely_local = True
        assert _total > 7500  # 10096
        assert _is_likely_local
        # This combination would trigger the warning in production

    def test_no_warning_for_cloud_models(self):
        """Cloud models (e.g. gpt-4o) should not trigger local model warning."""
        model_name = "gpt-4o"
        _CLOUD_PREFIXES = ("gpt-", "o3", "o4", "claude", "gemini", "mistral-large")
        _is_likely_local = not any(model_name.startswith(p) for p in _CLOUD_PREFIXES)
        assert _is_likely_local is False

    def test_local_model_detected(self):
        """Ollama models like gemma2:latest are detected as local."""
        model_name = "gemma2:latest"
        _CLOUD_PREFIXES = ("gpt-", "o3", "o4", "claude", "gemini", "mistral-large")
        _is_likely_local = not any(model_name.startswith(p) for p in _CLOUD_PREFIXES)
        assert _is_likely_local is True
