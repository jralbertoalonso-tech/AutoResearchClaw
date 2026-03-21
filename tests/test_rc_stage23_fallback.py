# pyright: reportPrivateUsage=false, reportUnknownParameterType=false
"""Tests for Stage 23 (CITATION_VERIFY) fallback and safety mechanisms.

Covers:
- verify_citations() raises a generic exception → fallback to original bib
- verify_citations() raises urllib.error.HTTPError 429 → fallback to original bib
- verify_citations() raises a TimeoutError → fallback to original bib
- verify_citations() succeeds but returns empty verified_bib → SAFETY-1 preserves original
- references_verified.bib written as 0 bytes → SAFETY-2 overwrites with original
- No references.bib present → empty verification report, DONE status
- Stage returns DONE status (not FAILED) in all fallback cases
- verification_report.json is always written
- references_verified.bib is always non-empty when source bib had content
"""
from __future__ import annotations

import json
import textwrap
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from researchclaw.adapters import AdapterBundle
from researchclaw.config import RCConfig
from researchclaw.pipeline.executor import _execute_citation_verify
from researchclaw.pipeline.stages import Stage, StageStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_BIB = textwrap.dedent("""\
    @article{vaswani2017attention,
      title = {Attention Is All You Need},
      author = {Ashish Vaswani and Noam Shazeer},
      year = {2017},
      eprint = {1706.03762},
      archivePrefix = {arXiv},
    }

    @inproceedings{devlin2019bert,
      title = {BERT: Pre-training of Deep Bidirectional Transformers},
      author = {Jacob Devlin},
      year = {2019},
      doi = {10.18653/v1/N19-1423},
      booktitle = {NAACL},
    }
""")

_SAMPLE_PAPER = textwrap.dedent("""\
    # My Paper

    ## Abstract
    This paper reviews attention mechanisms \\cite{vaswani2017attention}
    and BERT representations \\cite{devlin2019bert}.
""")


@pytest.fixture()
def rc_config(tmp_path: Path) -> RCConfig:
    data = {
        "project": {"name": "stage23-test", "mode": "docs-first"},
        "research": {"topic": "attention mechanisms in NLP"},
        "runtime": {"timezone": "UTC"},
        "notifications": {"channel": "local"},
        "knowledge_base": {"backend": "markdown", "root": str(tmp_path / "kb")},
        "openclaw_bridge": {},
        "llm": {
            "provider": "openai-compatible",
            "base_url": "http://localhost:1234/v1",
            "api_key_env": "RC_TEST_KEY",
            "api_key": "inline",
        },
    }
    return RCConfig.from_dict(data, project_root=tmp_path, check_paths=False)


@pytest.fixture()
def run_dir(tmp_path: Path) -> Path:
    rd = tmp_path / "run"
    rd.mkdir()
    return rd


@pytest.fixture()
def stage_dir(run_dir: Path) -> Path:
    sd = run_dir / "stage-23"
    sd.mkdir()
    return sd


def _write_prior_bib(run_dir: Path, content: str) -> None:
    """Write references.bib in the stage-22 directory (prior artifact)."""
    s22 = run_dir / "stage-22"
    s22.mkdir(exist_ok=True)
    (s22 / "references.bib").write_text(content, encoding="utf-8")


def _write_prior_paper(run_dir: Path, content: str) -> None:
    """Write paper_final.md in the stage-22 directory (prior artifact)."""
    s22 = run_dir / "stage-22"
    s22.mkdir(exist_ok=True)
    (s22 / "paper_final.md").write_text(content, encoding="utf-8")


def _run_stage23(
    stage_dir: Path,
    run_dir: Path,
    rc_config: RCConfig,
):
    adapters = AdapterBundle()
    return _execute_citation_verify(
        stage_dir=stage_dir,
        run_dir=run_dir,
        config=rc_config,
        adapters=adapters,
        llm=None,
        prompts=None,
    )


# ---------------------------------------------------------------------------
# No references.bib — must succeed with empty report
# ---------------------------------------------------------------------------


class TestNoBibFile:
    def test_missing_bib_returns_done(
        self, stage_dir: Path, run_dir: Path, rc_config: RCConfig
    ) -> None:
        result = _run_stage23(stage_dir, run_dir, rc_config)
        assert result.status == StageStatus.DONE

    def test_missing_bib_writes_verification_report(
        self, stage_dir: Path, run_dir: Path, rc_config: RCConfig
    ) -> None:
        _run_stage23(stage_dir, run_dir, rc_config)
        rpt = stage_dir / "verification_report.json"
        assert rpt.exists()
        data = json.loads(rpt.read_text(encoding="utf-8"))
        assert data["summary"]["total"] == 0

    def test_missing_bib_writes_empty_verified_bib(
        self, stage_dir: Path, run_dir: Path, rc_config: RCConfig
    ) -> None:
        _run_stage23(stage_dir, run_dir, rc_config)
        vbib = stage_dir / "references_verified.bib"
        assert vbib.exists()


# ---------------------------------------------------------------------------
# Exception fallback paths
# ---------------------------------------------------------------------------


def _make_mock_report() -> MagicMock:
    """Create a minimal VerificationReport mock."""
    r = MagicMock()
    r.verified = 2
    r.suspicious = 0
    r.hallucinated = 0
    r.skipped = 0
    r.integrity_score = 1.0
    r.results = []
    r.to_dict.return_value = {
        "summary": {
            "total": 2,
            "verified": 2,
            "suspicious": 0,
            "hallucinated": 0,
            "skipped": 0,
            "integrity_score": 1.0,
        },
        "results": [],
    }
    return r


class TestExceptionFallback:
    """verify_citations() raises → original bib preserved, stage DONE."""

    def _check_fallback_invariants(
        self,
        stage_dir: Path,
        original_bib: str,
    ) -> None:
        vbib_path = stage_dir / "references_verified.bib"
        rpt_path  = stage_dir / "verification_report.json"

        assert vbib_path.exists(), "references_verified.bib must exist after fallback"
        assert rpt_path.exists(),  "verification_report.json must exist after fallback"

        vbib_content = vbib_path.read_text(encoding="utf-8")
        assert vbib_content.strip(), "references_verified.bib must not be empty"
        # Fallback must preserve original bib entries
        for entry_key in ("vaswani2017attention", "devlin2019bert"):
            assert entry_key in vbib_content, (
                f"Original entry '{entry_key}' must be in fallback bib"
            )

    def test_generic_exception_falls_back(
        self,
        stage_dir: Path,
        run_dir: Path,
        rc_config: RCConfig,
    ) -> None:
        _write_prior_bib(run_dir, _SAMPLE_BIB)
        with patch(
            "researchclaw.literature.verify.verify_citations",
            side_effect=RuntimeError("Connection refused"),
        ):
            result = _run_stage23(stage_dir, run_dir, rc_config)

        assert result.status == StageStatus.DONE
        self._check_fallback_invariants(stage_dir, _SAMPLE_BIB)

    def test_http_429_falls_back(
        self,
        stage_dir: Path,
        run_dir: Path,
        rc_config: RCConfig,
    ) -> None:
        _write_prior_bib(run_dir, _SAMPLE_BIB)
        err = urllib.error.HTTPError(
            "https://api.example.com", 429, "Too Many Requests", Message(), None
        )
        with patch(
            "researchclaw.literature.verify.verify_citations",
            side_effect=err,
        ):
            result = _run_stage23(stage_dir, run_dir, rc_config)

        assert result.status == StageStatus.DONE
        self._check_fallback_invariants(stage_dir, _SAMPLE_BIB)

    def test_timeout_error_falls_back(
        self,
        stage_dir: Path,
        run_dir: Path,
        rc_config: RCConfig,
    ) -> None:
        _write_prior_bib(run_dir, _SAMPLE_BIB)
        with patch(
            "researchclaw.literature.verify.verify_citations",
            side_effect=TimeoutError("API timed out after 30s"),
        ):
            result = _run_stage23(stage_dir, run_dir, rc_config)

        assert result.status == StageStatus.DONE
        self._check_fallback_invariants(stage_dir, _SAMPLE_BIB)

    def test_exception_fallback_report_has_skipped_entries(
        self,
        stage_dir: Path,
        run_dir: Path,
        rc_config: RCConfig,
    ) -> None:
        _write_prior_bib(run_dir, _SAMPLE_BIB)
        with patch(
            "researchclaw.literature.verify.verify_citations",
            side_effect=OSError("Network unreachable"),
        ):
            _run_stage23(stage_dir, run_dir, rc_config)

        rpt = json.loads((stage_dir / "verification_report.json").read_text())
        # All entries should be reported as skipped
        assert rpt["summary"]["skipped"] == rpt["summary"]["total"]
        assert rpt["summary"]["total"] > 0


# ---------------------------------------------------------------------------
# SAFETY-1: verify_citations succeeds but verified_bib becomes empty
# ---------------------------------------------------------------------------


class TestSafety1EmptyVerifiedBib:
    def test_empty_verified_bib_falls_back_to_original(
        self,
        stage_dir: Path,
        run_dir: Path,
        rc_config: RCConfig,
    ) -> None:
        """If all entries are filtered out, the original bib must be preserved."""
        _write_prior_bib(run_dir, _SAMPLE_BIB)

        mock_report = _make_mock_report()

        # filter_verified_bibtex returns empty string (all filtered as hallucinated)
        with (
            patch(
                "researchclaw.literature.verify.verify_citations",
                return_value=mock_report,
            ),
            patch(
                "researchclaw.literature.verify.filter_verified_bibtex",
                return_value="",
            ),
        ):
            result = _run_stage23(stage_dir, run_dir, rc_config)

        assert result.status == StageStatus.DONE

        vbib = (stage_dir / "references_verified.bib").read_text(encoding="utf-8")
        assert vbib.strip(), "SAFETY-1 must preserve non-empty bib"
        # Original entries must survive
        assert "vaswani2017attention" in vbib or "devlin2019bert" in vbib


# ---------------------------------------------------------------------------
# Artifacts always present in StageResult
# ---------------------------------------------------------------------------


class TestStageResultArtifacts:
    def test_artifacts_always_include_bib_and_report_on_success(
        self,
        stage_dir: Path,
        run_dir: Path,
        rc_config: RCConfig,
    ) -> None:
        _write_prior_bib(run_dir, _SAMPLE_BIB)
        mock_report = _make_mock_report()

        with (
            patch(
                "researchclaw.literature.verify.verify_citations",
                return_value=mock_report,
            ),
            patch(
                "researchclaw.literature.verify.filter_verified_bibtex",
                return_value=_SAMPLE_BIB,
            ),
        ):
            result = _run_stage23(stage_dir, run_dir, rc_config)

        assert "verification_report.json" in result.artifacts
        assert "references_verified.bib" in result.artifacts

    def test_artifacts_present_on_exception_fallback(
        self,
        stage_dir: Path,
        run_dir: Path,
        rc_config: RCConfig,
    ) -> None:
        _write_prior_bib(run_dir, _SAMPLE_BIB)
        with patch(
            "researchclaw.literature.verify.verify_citations",
            side_effect=RuntimeError("Boom"),
        ):
            result = _run_stage23(stage_dir, run_dir, rc_config)

        assert "references_verified.bib" in result.artifacts
        assert "verification_report.json" in result.artifacts

    def test_artifacts_present_when_no_bib(
        self,
        stage_dir: Path,
        run_dir: Path,
        rc_config: RCConfig,
    ) -> None:
        result = _run_stage23(stage_dir, run_dir, rc_config)
        assert "references_verified.bib" in result.artifacts
        assert "verification_report.json" in result.artifacts
