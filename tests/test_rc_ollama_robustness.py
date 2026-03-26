"""Tests for Ollama / local-model robustness improvements.

Covers the four surgical changes in feat/ollama-local-robustness:

  C1  – llm/client.py: from_rc_config() auto-extends HTTP timeout to 600 s
        for localhost/127.0.0.1 backends; keeps 300 s for cloud endpoints.

  C2a – executor.py: _execute_peer_review() writes a fallback reviews.md and
        returns DONE when the LLM call raises (timeout / model failure), so the
        run survives with paper_draft.md as a provisional deliverable.

  C2b – executor.py: _execute_literature_screen() caps candidates_text to
        30 000 chars for local models before the json-mode LLM call.

  C2c – executor.py: _execute_knowledge_extract() caps the assembled shortlist
        context to 30 000 chars for local models before the json-mode LLM call.
"""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from researchclaw.llm.client import LLMClient, LLMConfig, LLMResponse
from researchclaw.pipeline import executor as rc_executor
from researchclaw.pipeline.stages import Stage, StageStatus


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

_CLOUD_PREFIXES = ("gpt-", "o3", "o4", "claude", "gemini", "mistral-large")


def _make_rc_config_ns(
    *,
    base_url: str = "http://localhost:11434/v1",
    primary_model: str = "gemma3:12b",
    fallback_models: tuple[str, ...] = (),
    api_key: str = "ollama",
    api_key_env: str = "OPENAI_API_KEY",
) -> SimpleNamespace:
    """Minimal rc_config SimpleNamespace accepted by LLMClient.from_rc_config."""
    return SimpleNamespace(
        llm=SimpleNamespace(
            base_url=base_url,
            api_key=api_key,
            api_key_env=api_key_env,
            primary_model=primary_model,
            fallback_models=list(fallback_models),
            provider="openai-compatible",
        )
    )


class _FakeLLMClient:
    """Minimal LLMClient-compatible fake that always raises on chat()."""

    def __init__(self, *, raise_exc: Exception | None = None, response: str = "{}"):
        self._raise = raise_exc
        self._response = response
        self.config = SimpleNamespace(
            base_url="http://localhost:11434/v1",
            primary_model="gemma3:12b",
        )

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> LLMResponse:  # noqa: ANN401
        if self._raise is not None:
            raise self._raise
        return LLMResponse(content=self._response, model="gemma3:12b")


def _make_adapters():
    from researchclaw.adapters import AdapterBundle
    return AdapterBundle()


def _make_rc_config(tmp_path: Path, primary_model: str = "gemma3:12b"):
    from researchclaw.config import RCConfig
    data = {
        "project": {"name": "rc-test-robustness", "mode": "docs-first"},
        "research": {
            "topic": "test topic",
            "domains": ["ml"],
            "daily_paper_count": 2,
            "quality_threshold": 7.0,
        },
        "runtime": {"timezone": "UTC"},
        "notifications": {
            "channel": "local",
            "on_stage_start": False,
            "on_stage_fail": False,
            "on_gate_required": False,
        },
        "knowledge_base": {"backend": "markdown", "root": str(tmp_path / "kb")},
        "openclaw_bridge": {"use_memory": False, "use_message": False},
        "llm": {
            "provider": "openai-compatible",
            "base_url": "http://localhost:11434/v1",
            "api_key_env": "RC_TEST_KEY",
            "api_key": "ollama",
            "primary_model": primary_model,
            "fallback_models": [],
        },
        "security": {"hitl_required_stages": []},
        "experiment": {"mode": "sandbox"},
    }
    return RCConfig.from_dict(data, project_root=tmp_path, check_paths=False)


# ===========================================================================
# C1: auto-extend HTTP timeout for localhost backends
# ===========================================================================

class TestLocalBackendTimeout:
    """C1 – from_rc_config() sets timeout_sec=600 for local endpoints."""

    def test_localhost_gets_600s_timeout(self):
        rc = _make_rc_config_ns(base_url="http://localhost:11434/v1")
        client = LLMClient.from_rc_config(rc)
        assert client.config.timeout_sec == 600, (
            "Expected 600 s for localhost backend, got "
            f"{client.config.timeout_sec}"
        )

    def test_127_0_0_1_gets_600s_timeout(self):
        rc = _make_rc_config_ns(base_url="http://127.0.0.1:1234/v1")
        client = LLMClient.from_rc_config(rc)
        assert client.config.timeout_sec == 600

    def test_cloud_endpoint_keeps_300s_timeout(self):
        rc = _make_rc_config_ns(base_url="https://api.openai.com/v1")
        client = LLMClient.from_rc_config(rc)
        assert client.config.timeout_sec == 300, (
            "Cloud endpoint must keep default 300 s, got "
            f"{client.config.timeout_sec}"
        )

    def test_openrouter_endpoint_keeps_300s_timeout(self):
        rc = _make_rc_config_ns(base_url="https://openrouter.ai/api/v1")
        client = LLMClient.from_rc_config(rc)
        assert client.config.timeout_sec == 300

    def test_lm_studio_default_port_gets_600s_timeout(self):
        rc = _make_rc_config_ns(base_url="http://localhost:1234/v1")
        client = LLMClient.from_rc_config(rc)
        assert client.config.timeout_sec == 600


# ===========================================================================
# C2a: PEER_REVIEW graceful fallback
# ===========================================================================

class TestPeerReviewFallback:
    """C2a – _execute_peer_review() returns DONE with fallback reviews on LLM error."""

    def _run_peer_review(
        self,
        tmp_path: Path,
        llm: _FakeLLMClient,
        draft_content: str = "# Draft\n\nSome content.\n",
    ):
        config = _make_rc_config(tmp_path)
        adapters = _make_adapters()

        # Create the run_dir with the required input artifact paper_draft.md
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        stage17_dir = run_dir / "stage-17"
        stage17_dir.mkdir()
        (stage17_dir / "paper_draft.md").write_text(draft_content, encoding="utf-8")

        stage_dir = run_dir / "stage-18"
        stage_dir.mkdir()

        result = rc_executor._execute_peer_review(
            stage_dir, run_dir, config, adapters, llm=llm
        )
        return result, stage_dir

    def test_fallback_on_runtime_error_returns_done(self, tmp_path: Path):
        """RuntimeError (e.g. all models failed) must not crash the stage."""
        llm = _FakeLLMClient(raise_exc=RuntimeError("All models failed"))
        result, stage_dir = self._run_peer_review(tmp_path, llm)

        assert result.status == StageStatus.DONE, (
            f"Expected DONE after LLM error, got {result.status}"
        )

    def test_fallback_on_timeout_returns_done(self, tmp_path: Path):
        """urllib timeout (OSError subclass) must not crash the stage."""
        llm = _FakeLLMClient(
            raise_exc=urllib.error.URLError("timed out")
        )
        result, stage_dir = self._run_peer_review(tmp_path, llm)
        assert result.status == StageStatus.DONE

    def test_fallback_writes_reviews_md(self, tmp_path: Path):
        """Even on LLM failure, reviews.md must be written (non-empty)."""
        llm = _FakeLLMClient(raise_exc=RuntimeError("Timeout"))
        _, stage_dir = self._run_peer_review(tmp_path, llm)

        reviews_path = stage_dir / "reviews.md"
        assert reviews_path.exists(), "reviews.md must exist after fallback"
        content = reviews_path.read_text(encoding="utf-8")
        assert len(content) > 50, "Fallback reviews.md must be non-trivial"

    def test_fallback_reviews_marks_inference_failure(self, tmp_path: Path):
        """Fallback content must clearly indicate inference failure (not fake reviews)."""
        llm = _FakeLLMClient(raise_exc=RuntimeError("connection timed out"))
        _, stage_dir = self._run_peer_review(tmp_path, llm)

        content = (stage_dir / "reviews.md").read_text(encoding="utf-8")
        # Must mention failure / timeout so the user knows it is a fallback
        assert any(
            kw in content.lower() for kw in ("unavailable", "timeout", "error", "failed")
        ), "Fallback reviews must contain a failure notice"

    def test_successful_llm_call_still_works(self, tmp_path: Path):
        """A working LLM must not be affected — normal path unchanged."""
        llm = _FakeLLMClient(
            response="# Reviews\n\n## Reviewer A\n- Strengths: solid.\n"
        )
        result, stage_dir = self._run_peer_review(tmp_path, llm)

        assert result.status == StageStatus.DONE
        content = (stage_dir / "reviews.md").read_text(encoding="utf-8")
        assert "Reviewer A" in content

    def test_no_llm_uses_template(self, tmp_path: Path):
        """llm=None path must still produce reviews.md (existing behaviour)."""
        config = _make_rc_config(tmp_path)
        adapters = _make_adapters()
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        stage17_dir = run_dir / "stage-17"
        stage17_dir.mkdir()
        (stage17_dir / "paper_draft.md").write_text("# Draft\n", encoding="utf-8")
        stage_dir = run_dir / "stage-18"
        stage_dir.mkdir()

        result = rc_executor._execute_peer_review(
            stage_dir, run_dir, config, adapters, llm=None
        )
        assert result.status == StageStatus.DONE
        assert (stage_dir / "reviews.md").exists()


# ===========================================================================
# C2b: candidates_text cap in LITERATURE_SCREEN for local models
# ===========================================================================

class TestLiteratureScreenLocalCap:
    """C2b – candidates_text is capped for local models; cloud models are unaffected."""

    _CHAR_LIMIT = 30_000

    def _make_big_candidates_jsonl(self, n: int = 80) -> str:
        rows = []
        for i in range(n):
            rows.append(json.dumps({
                "title": f"Paper {i}: A Very Long Title About Something Research-Related",
                "abstract": (
                    "We propose a method for test topic using deep learning. "
                    "Our experiments on benchmark datasets demonstrate state-of-the-art "
                    "performance across multiple evaluation metrics. " * 4
                ),
                "year": 2023,
                "source": "arxiv",
                "keyword_overlap": 3,
            }))
        return "\n".join(rows)

    def _run_lit_screen(
        self,
        tmp_path: Path,
        llm: _FakeLLMClient,
        candidates_jsonl: str,
    ):
        config = _make_rc_config(tmp_path, primary_model=llm.config.primary_model)
        adapters = _make_adapters()

        run_dir = tmp_path / "run"
        run_dir.mkdir()
        stage04_dir = run_dir / "stage-04"
        stage04_dir.mkdir()
        (stage04_dir / "candidates.jsonl").write_text(candidates_jsonl, encoding="utf-8")

        stage_dir = run_dir / "stage-05"
        stage_dir.mkdir()

        # Intercept the _chat_with_prompt call to capture what the LLM receives
        captured_user: list[str] = []
        _orig_chat = llm.chat

        def _spy_chat(messages, **kwargs):
            captured_user.extend(m["content"] for m in messages if m["role"] == "user")
            return _orig_chat(messages, **kwargs)

        llm.chat = _spy_chat  # type: ignore[method-assign]

        rc_executor._execute_literature_screen(
            stage_dir, run_dir, config, adapters, llm=llm
        )
        return captured_user

    def test_local_model_candidates_capped(self, tmp_path: Path):
        """For a local model the user prompt must not exceed the 30 000-char limit."""
        big_candidates = self._make_big_candidates_jsonl(80)
        assert len(big_candidates) > self._CHAR_LIMIT, "Precondition: input is big"

        llm = _FakeLLMClient(
            response=json.dumps({"shortlist": []}),  # empty → fallback kicks in
        )
        llm.config = SimpleNamespace(
            base_url="http://localhost:11434/v1",
            primary_model="gemma3:12b",  # local
        )
        captured = self._run_lit_screen(tmp_path, llm, big_candidates)

        combined = "\n".join(captured)
        # The candidates portion is embedded in the user prompt; the whole prompt
        # should stay well under 40 000 chars (30 000 cap + prompt overhead).
        assert len(combined) < 40_000, (
            f"Local model prompt too large: {len(combined)} chars"
        )

    def test_cloud_model_candidates_not_capped(self, tmp_path: Path):
        """Cloud models must receive the full candidates_text (no cap applied)."""
        big_candidates = self._make_big_candidates_jsonl(80)

        llm = _FakeLLMClient(response=json.dumps({"shortlist": []}))
        llm.config = SimpleNamespace(
            base_url="https://api.openai.com/v1",
            primary_model="gpt-4o",  # cloud
        )
        captured = self._run_lit_screen(tmp_path, llm, big_candidates)

        combined = "\n".join(captured)
        # Cloud path is uncapped; the big candidates text must still be present
        assert len(combined) > self._CHAR_LIMIT, (
            "Cloud model must not have its candidates_text capped"
        )

    def test_small_local_input_unchanged(self, tmp_path: Path):
        """If candidates_text is already within budget, nothing is truncated."""
        small_candidates = self._make_big_candidates_jsonl(5)
        assert len(small_candidates) < self._CHAR_LIMIT

        llm = _FakeLLMClient(response=json.dumps({"shortlist": []}))
        llm.config = SimpleNamespace(
            base_url="http://localhost:11434/v1",
            primary_model="gemma3:12b",
        )
        captured = self._run_lit_screen(tmp_path, llm, small_candidates)
        # All 5 papers still present in prompt
        for i in range(5):
            assert f"Paper {i}:" in "\n".join(captured)


# ===========================================================================
# C2c: shortlist context cap in KNOWLEDGE_EXTRACT for local models
# ===========================================================================

class TestKnowledgeExtractLocalCap:
    """C2c – shortlist context is capped for local models; cloud models are unaffected."""

    _CHAR_LIMIT = 30_000

    def _make_big_shortlist_jsonl(self, n: int = 50) -> str:
        rows = []
        for i in range(n):
            rows.append(json.dumps({
                "title": f"Shortlisted Paper {i}: Extended Knowledge Source",
                "abstract": (
                    "This paper presents a comprehensive analysis of test topic. "
                    "We evaluate on multiple benchmarks and show significant gains. "
                    "Our approach leverages deep learning to achieve state-of-the-art "
                    "performance across all evaluated settings and datasets. " * 6
                ),
                "year": 2023,
                "source": "arxiv",
                "relevance_score": 0.9,
                "quality_score": 0.85,
                "keep_reason": "High relevance",
            }))
        return "\n".join(rows)

    def _run_knowledge_extract(
        self,
        tmp_path: Path,
        llm: _FakeLLMClient,
        shortlist_jsonl: str,
    ):
        config = _make_rc_config(tmp_path, primary_model=llm.config.primary_model)
        adapters = _make_adapters()

        run_dir = tmp_path / "run"
        run_dir.mkdir()
        stage05_dir = run_dir / "stage-05"
        stage05_dir.mkdir()
        (stage05_dir / "shortlist.jsonl").write_text(shortlist_jsonl, encoding="utf-8")

        stage_dir = run_dir / "stage-06"
        stage_dir.mkdir()

        captured_user: list[str] = []
        _orig_chat = llm.chat

        def _spy_chat(messages, **kwargs):
            captured_user.extend(m["content"] for m in messages if m["role"] == "user")
            return _orig_chat(messages, **kwargs)

        llm.chat = _spy_chat  # type: ignore[method-assign]

        rc_executor._execute_knowledge_extract(
            stage_dir, run_dir, config, adapters, llm=llm
        )
        return captured_user

    def test_local_model_shortlist_capped(self, tmp_path: Path):
        big_shortlist = self._make_big_shortlist_jsonl(50)
        assert len(big_shortlist) > self._CHAR_LIMIT, "Precondition: input is big"

        llm = _FakeLLMClient(response=json.dumps({"cards": []}))
        llm.config = SimpleNamespace(
            base_url="http://localhost:11434/v1",
            primary_model="gemma3:12b",
        )
        captured = self._run_knowledge_extract(tmp_path, llm, big_shortlist)

        combined = "\n".join(captured)
        assert len(combined) < 40_000, (
            f"Local model shortlist prompt too large: {len(combined)} chars"
        )

    def test_cloud_model_shortlist_not_capped(self, tmp_path: Path):
        big_shortlist = self._make_big_shortlist_jsonl(50)

        llm = _FakeLLMClient(response=json.dumps({"cards": []}))
        llm.config = SimpleNamespace(
            base_url="https://api.openai.com/v1",
            primary_model="gpt-4o",
        )
        captured = self._run_knowledge_extract(tmp_path, llm, big_shortlist)

        combined = "\n".join(captured)
        assert len(combined) > self._CHAR_LIMIT, (
            "Cloud model must not have its shortlist capped"
        )

    def test_small_local_shortlist_unchanged(self, tmp_path: Path):
        small_shortlist = self._make_big_shortlist_jsonl(3)
        assert len(small_shortlist) < self._CHAR_LIMIT

        llm = _FakeLLMClient(response=json.dumps({"cards": []}))
        llm.config = SimpleNamespace(
            base_url="http://localhost:11434/v1",
            primary_model="gemma3:12b",
        )
        captured = self._run_knowledge_extract(tmp_path, llm, small_shortlist)
        for i in range(3):
            assert f"Shortlisted Paper {i}:" in "\n".join(captured)

    def test_truncation_marker_added_when_capped(self, tmp_path: Path):
        """When the shortlist is truncated, a visible marker must be appended."""
        big_shortlist = self._make_big_shortlist_jsonl(50)

        captured_user: list[str] = []
        llm = _FakeLLMClient(response=json.dumps({"cards": []}))
        llm.config = SimpleNamespace(
            base_url="http://localhost:11434/v1",
            primary_model="gemma3:12b",
        )
        _orig_chat = llm.chat

        def _spy_chat(messages, **kwargs):
            captured_user.extend(m["content"] for m in messages if m["role"] == "user")
            return _orig_chat(messages, **kwargs)

        llm.chat = _spy_chat  # type: ignore[method-assign]

        config = _make_rc_config(tmp_path, primary_model="gemma3:12b")
        adapters = _make_adapters()
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        stage05_dir = run_dir / "stage-05"
        stage05_dir.mkdir()
        (stage05_dir / "shortlist.jsonl").write_text(big_shortlist, encoding="utf-8")
        stage_dir = run_dir / "stage-06"
        stage_dir.mkdir()

        rc_executor._execute_knowledge_extract(
            stage_dir, run_dir, config, adapters, llm=llm
        )
        combined = "\n".join(captured_user)
        assert "truncated" in combined.lower(), (
            "Truncation marker must appear in prompt when shortlist is capped"
        )


# ===========================================================================
# Integration smoke: existing guardrails not weakened
# ===========================================================================

class TestGuardrailsPreserved:
    """Verify that anti-fabrication and criticality contracts are intact."""

    def test_peer_review_contract_criticality_unchanged(self):
        """PEER_REVIEW must remain CRITICAL in contracts (fallback is in executor, not contract)."""
        from researchclaw.pipeline.contracts import CONTRACTS
        from researchclaw.pipeline.protocol import StageCriticality

        contract = CONTRACTS[Stage.PEER_REVIEW]
        assert contract.criticality == StageCriticality.CRITICAL, (
            "PEER_REVIEW contract criticality must stay CRITICAL — "
            "fallback is executor-level, not contract-level"
        )

    def test_quality_gate_still_soft_fail(self):
        """QUALITY_GATE must remain SOFT_FAIL (unchanged)."""
        from researchclaw.pipeline.contracts import CONTRACTS
        from researchclaw.pipeline.protocol import StageCriticality

        contract = CONTRACTS[Stage.QUALITY_GATE]
        assert contract.criticality == StageCriticality.SOFT_FAIL

    def test_literature_screen_contract_max_retries_zero(self):
        """LITERATURE_SCREEN gate contract must be unchanged (max_retries=0)."""
        from researchclaw.pipeline.contracts import CONTRACTS

        contract = CONTRACTS[Stage.LITERATURE_SCREEN]
        assert contract.max_retries == 0
