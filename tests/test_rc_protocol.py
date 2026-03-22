# pyright: reportPrivateUsage=false
"""Unit tests for researchclaw.pipeline.protocol.

Covers:
- ProtocolFamily / ProtocolProfile enum values and membership helpers
- detect_protocol() hard-skip (raw preamble) and soft-detect (clean topic) paths
- Negative cases: experimental topics must not be classified as bibliographic
- skip_stages_for() returns the right Stage frozenset per profile
- criticality_for() / is_noncritical_for() with per-profile overrides
- StageCriticality enum values
"""
from __future__ import annotations

import pytest

from researchclaw.pipeline.protocol import (
    ProtocolFamily,
    ProtocolProfile,
    StageCriticality,
    criticality_for,
    detect_protocol,
    family_of,
    is_bibliographic,
    is_experimental,
    is_noncritical_for,
    resolve_protocol,
    skip_stages_for,
)
from researchclaw.pipeline.stages import Stage


# ---------------------------------------------------------------------------
# ProtocolFamily / ProtocolProfile helpers
# ---------------------------------------------------------------------------


class TestFamilyHelpers:
    @pytest.mark.parametrize("profile", [
        ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA,
        ProtocolProfile.NARRATIVE_REVIEW,
        ProtocolProfile.SCOPING_REVIEW,
        ProtocolProfile.META_ANALYSIS,
        ProtocolProfile.POSTER_ONLY,
    ])
    def test_is_bibliographic_for_all_bib_profiles(self, profile: ProtocolProfile) -> None:
        assert is_bibliographic(profile) is True
        assert is_experimental(profile) is False
        assert family_of(profile) == ProtocolFamily.BIBLIOGRAPHIC

    @pytest.mark.parametrize("profile", [
        ProtocolProfile.EXPERIMENTAL_ML,
        ProtocolProfile.GENERIC,
    ])
    def test_is_experimental_for_all_exp_profiles(self, profile: ProtocolProfile) -> None:
        assert is_experimental(profile) is True
        assert is_bibliographic(profile) is False
        assert family_of(profile) == ProtocolFamily.EXPERIMENTAL


# ---------------------------------------------------------------------------
# detect_protocol: hard-skip path (raw topic with preamble)
# ---------------------------------------------------------------------------

# Preamble text typically injected by web_ui.py before the '---' separator
_PREAMBLE = (
    "PROTOCOLO: REVISIÓN SISTEMÁTICA PRISMA 2020\n"
    "Este protocolo sigue las directrices PRISMA.\n"
    "\n\n---\n\n"
)


class TestDetectProtocolHardSkip:
    def test_prisma_in_preamble_detected(self) -> None:
        full = _PREAMBLE + "efectos del ejercicio en diabetes"
        clean = "efectos del ejercicio en diabetes"
        profile = detect_protocol(full, clean)
        assert is_bibliographic(profile)

    def test_prisma_keyword_in_full_topic(self) -> None:
        profile = detect_protocol("PRISMA 2020 review of interventions", None)
        assert profile == ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA

    def test_meta_analysis_in_full_topic(self) -> None:
        profile = detect_protocol("meta-analysis of RCTs on hypertension treatment", None)
        assert profile == ProtocolProfile.META_ANALYSIS

    def test_poster_in_full_topic(self) -> None:
        full = "PROTOCOLO PÓSTER CONGRESO — efectos del café\n\n---\n\ntema: café"
        profile = detect_protocol(full, "efectos del café")
        assert profile == ProtocolProfile.POSTER_ONLY

    def test_scoping_review_in_full_topic(self) -> None:
        profile = detect_protocol("Scoping review on AI in medicine", None)
        assert profile == ProtocolProfile.SCOPING_REVIEW

    def test_narrative_review_markers(self) -> None:
        for marker in ("narrative review", "revisión bibliográfica", "bibliographic review"):
            profile = detect_protocol(marker + " of cancer therapies", None)
            assert is_bibliographic(profile), f"Failed for marker: {marker!r}"

    def test_systematic_literature_marker(self) -> None:
        profile = detect_protocol("Systematic literature search on deep learning", None)
        assert profile == ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA

    def test_cochrane_marker(self) -> None:
        profile = detect_protocol("Cochrane review of antidepressants", None)
        assert profile == ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA


# ---------------------------------------------------------------------------
# detect_protocol: soft-detect path (clean topic only)
# ---------------------------------------------------------------------------


class TestDetectProtocolSoftDetect:
    """Clean topic (no preamble) — soft keyword detection."""

    def test_meta_analysis_in_clean_topic(self) -> None:
        profile = detect_protocol("meta-analysis of exercise", "meta-analysis of exercise")
        assert profile == ProtocolProfile.META_ANALYSIS

    def test_systematic_review_in_clean_topic(self) -> None:
        profile = detect_protocol(
            "systematic review of interventions",
            "systematic review of interventions",
        )
        assert is_bibliographic(profile)

    def test_literature_review_in_clean_topic(self) -> None:
        profile = detect_protocol(
            "literature review on climate change",
            "literature review on climate change",
        )
        assert is_bibliographic(profile)

    def test_bibliometric_in_clean_topic(self) -> None:
        profile = detect_protocol("bibliometric analysis of AI papers", None)
        assert is_bibliographic(profile)


# ---------------------------------------------------------------------------
# detect_protocol: experimental topics must NOT be classified as bibliographic
# ---------------------------------------------------------------------------


class TestDetectProtocolExperimental:
    @pytest.mark.parametrize("topic", [
        "Training a transformer for code generation",
        "Novel GAN architecture for image synthesis",
        "Benchmarking LLMs on math reasoning tasks",
        "Implementing a neural network for protein folding",
        "Hyperparameter tuning for ResNet-50 on CIFAR-10",
        "Federated learning with differential privacy",
    ])
    def test_experimental_topic_not_bibliographic(self, topic: str) -> None:
        profile = detect_protocol(topic, topic)
        assert is_experimental(profile), (
            f"Expected EXPERIMENTAL for topic {topic!r}, got {profile!r}"
        )

    def test_generic_is_default(self) -> None:
        profile = detect_protocol("deep learning optimization", "deep learning optimization")
        assert profile == ProtocolProfile.GENERIC


# ---------------------------------------------------------------------------
# skip_stages_for
# ---------------------------------------------------------------------------

_EXPERIMENT_STAGE_NUMS: frozenset[int] = frozenset(range(9, 16))


class TestSkipStagesFor:
    @pytest.mark.parametrize("profile", [
        ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA,
        ProtocolProfile.NARRATIVE_REVIEW,
        ProtocolProfile.SCOPING_REVIEW,
        ProtocolProfile.META_ANALYSIS,
        ProtocolProfile.POSTER_ONLY,
    ])
    def test_bibliographic_skips_stages_9_to_15(self, profile: ProtocolProfile) -> None:
        skipped = skip_stages_for(profile)
        skipped_nums = {int(s) for s in skipped}
        assert skipped_nums == _EXPERIMENT_STAGE_NUMS, (
            f"Profile {profile} should skip exactly stages 9-15, got {skipped_nums}"
        )

    @pytest.mark.parametrize("profile", [
        ProtocolProfile.EXPERIMENTAL_ML,
        ProtocolProfile.GENERIC,
    ])
    def test_experimental_skips_nothing(self, profile: ProtocolProfile) -> None:
        skipped = skip_stages_for(profile)
        assert len(skipped) == 0, f"Profile {profile} should skip nothing, got {skipped}"

    def test_result_is_cached(self) -> None:
        """skip_stages_for must return the same object on repeat calls (cached)."""
        a = skip_stages_for(ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA)
        b = skip_stages_for(ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA)
        assert a is b


# ---------------------------------------------------------------------------
# StageCriticality and criticality_for
# ---------------------------------------------------------------------------


class TestStageCriticality:
    def test_default_criticality_is_critical(self) -> None:
        for stage_num in (1, 2, 3, 4, 5, 6, 7, 8, 16, 17, 18, 19, 22):
            c = criticality_for(stage_num, ProtocolProfile.GENERIC)
            assert c == StageCriticality.CRITICAL, (
                f"Stage {stage_num} should be CRITICAL for GENERIC, got {c}"
            )

    def test_quality_gate_is_soft_fail_for_all_profiles(self) -> None:
        for profile in ProtocolProfile:
            c = criticality_for(20, profile)
            assert c == StageCriticality.SOFT_FAIL, (
                f"QUALITY_GATE (20) should be SOFT_FAIL for {profile}, got {c}"
            )

    def test_knowledge_archive_is_advisory_for_all_profiles(self) -> None:
        for profile in ProtocolProfile:
            c = criticality_for(21, profile)
            assert c == StageCriticality.ADVISORY, (
                f"KNOWLEDGE_ARCHIVE (21) should be ADVISORY for {profile}, got {c}"
            )

    def test_citation_verify_critical_for_experimental(self) -> None:
        for profile in (ProtocolProfile.EXPERIMENTAL_ML, ProtocolProfile.GENERIC):
            c = criticality_for(23, profile)
            assert c == StageCriticality.CRITICAL, (
                f"CITATION_VERIFY (23) should be CRITICAL for {profile}, got {c}"
            )

    @pytest.mark.parametrize("profile", [
        ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA,
        ProtocolProfile.NARRATIVE_REVIEW,
        ProtocolProfile.SCOPING_REVIEW,
        ProtocolProfile.META_ANALYSIS,
        ProtocolProfile.POSTER_ONLY,
    ])
    def test_citation_verify_soft_fail_for_bibliographic(
        self, profile: ProtocolProfile
    ) -> None:
        c = criticality_for(23, profile)
        assert c == StageCriticality.SOFT_FAIL, (
            f"CITATION_VERIFY (23) should be SOFT_FAIL for {profile}, got {c}"
        )


# ---------------------------------------------------------------------------
# is_noncritical_for
# ---------------------------------------------------------------------------


class TestIsNoncriticalFor:
    def test_quality_gate_noncritical_all(self) -> None:
        for profile in ProtocolProfile:
            assert is_noncritical_for(20, profile) is True

    def test_knowledge_archive_noncritical_all(self) -> None:
        for profile in ProtocolProfile:
            assert is_noncritical_for(21, profile) is True

    def test_citation_verify_critical_experimental(self) -> None:
        assert is_noncritical_for(23, ProtocolProfile.GENERIC) is False
        assert is_noncritical_for(23, ProtocolProfile.EXPERIMENTAL_ML) is False

    def test_citation_verify_noncritical_bibliographic(self) -> None:
        for profile in (
            ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA,
            ProtocolProfile.NARRATIVE_REVIEW,
            ProtocolProfile.SCOPING_REVIEW,
            ProtocolProfile.META_ANALYSIS,
            ProtocolProfile.POSTER_ONLY,
        ):
            assert is_noncritical_for(23, profile) is True, (
                f"Expected is_noncritical_for(23, {profile}) = True"
            )

    def test_critical_stage_not_noncritical(self) -> None:
        for stage_num in (3, 4, 6, 7, 8, 17, 22):
            assert is_noncritical_for(stage_num, ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA) is False


# ---------------------------------------------------------------------------
# Integration: detect_protocol → skip_stages_for round-trip
# ---------------------------------------------------------------------------


class TestDetectAndSkipIntegration:
    def test_prisma_topic_skips_experiment_stages(self) -> None:
        full_topic = (
            "PROTOCOLO PRISMA 2020\n\n---\n\n"
            "Effectiveness of mindfulness on anxiety: a systematic review"
        )
        clean_topic = "Effectiveness of mindfulness on anxiety"
        profile = detect_protocol(full_topic, clean_topic)
        assert is_bibliographic(profile)
        skipped_nums = {int(s) for s in skip_stages_for(profile)}
        assert skipped_nums == _EXPERIMENT_STAGE_NUMS

    def test_ml_topic_has_empty_skip_set(self) -> None:
        topic = "Efficient transformers for code completion with RLHF"
        profile = detect_protocol(topic, topic)
        assert is_experimental(profile)
        assert len(skip_stages_for(profile)) == 0

    def test_citation_verify_noncritical_after_prisma_detection(self) -> None:
        profile = detect_protocol("PRISMA meta-analysis of antidepressants", None)
        assert is_noncritical_for(23, profile) is True


# ---------------------------------------------------------------------------
# resolve_protocol — registry-aware resolution
# ---------------------------------------------------------------------------


class TestResolveProtocol:
    """Tests for resolve_protocol() which tries registry first, keywords second."""

    # ── Registry path (deterministic) ──────────────────────────────────────

    def test_prisma_by_filename(self) -> None:
        """Known filename with pipeline_profile → direct resolution."""
        profile = resolve_protocol(protocol_filename="Revision_Sistematica_PRISMA.md")
        assert profile == ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA

    def test_poster_by_filename(self) -> None:
        profile = resolve_protocol(protocol_filename="Poster_Congreso.md")
        assert profile == ProtocolProfile.POSTER_ONLY

    def test_analisis_rapido_by_filename(self) -> None:
        profile = resolve_protocol(protocol_filename="Analisis_Rapido.md")
        assert profile == ProtocolProfile.NARRATIVE_REVIEW

    def test_consulta_clinica_pico_by_filename(self) -> None:
        profile = resolve_protocol(protocol_filename="Consulta_Clinica_PICO.md")
        assert profile == ProtocolProfile.NARRATIVE_REVIEW

    def test_registry_match_ignores_topic_text(self) -> None:
        """When registry resolves, topic text is not scanned."""
        profile = resolve_protocol(
            protocol_filename="Revision_Sistematica_PRISMA.md",
            full_topic="Some random ML experiment with no keywords",
        )
        assert profile == ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA

    # ── Fallback to keywords ───────────────────────────────────────────────

    def test_unknown_filename_falls_back_to_keywords(self) -> None:
        """File not in registry → falls back to detect_protocol()."""
        profile = resolve_protocol(
            protocol_filename="Unknown_Protocol.md",
            full_topic="Systematic review of PRISMA guidelines",
        )
        assert profile == ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA

    def test_no_filename_falls_back_to_keywords(self) -> None:
        """No filename → pure keyword detection."""
        profile = resolve_protocol(
            full_topic="meta-analysis of randomized trials",
        )
        assert profile == ProtocolProfile.META_ANALYSIS

    def test_none_filename_falls_back_to_keywords(self) -> None:
        profile = resolve_protocol(
            protocol_filename=None,
            full_topic="Scoping review of AI in healthcare",
        )
        assert profile == ProtocolProfile.SCOPING_REVIEW

    def test_no_filename_no_keywords_returns_generic(self) -> None:
        profile = resolve_protocol(
            full_topic="Investigating new cancer biomarkers",
        )
        assert profile == ProtocolProfile.GENERIC

    # ── Protocols without pipeline_profile → fallback ──────────────────────

    def test_ceim_filename_no_pipeline_profile(self) -> None:
        """CEIm has no pipeline_profile → falls back to keywords in topic."""
        profile = resolve_protocol(
            protocol_filename="Auditoria_Protocolo_CEIm.md",
            full_topic="Audit CEIm research protocol",
        )
        # CEIm .md doesn't contain bibliographic keywords → GENERIC
        assert profile == ProtocolProfile.GENERIC

    def test_pptx_filename_no_pipeline_profile(self) -> None:
        """PowerPoint has no pipeline_profile → falls back."""
        profile = resolve_protocol(
            protocol_filename="Presentacion_PowerPoint.md",
            full_topic="Create a presentation about diabetes management",
        )
        assert profile == ProtocolProfile.GENERIC

    # ── Consistency: registry and keywords agree ───────────────────────────

    def test_prisma_registry_matches_keyword_detection(self) -> None:
        """For PRISMA, both paths should agree."""
        by_registry = resolve_protocol(
            protocol_filename="Revision_Sistematica_PRISMA.md",
        )
        by_keywords = detect_protocol(
            "Revisión Sistemática PRISMA 2020 sobre...",
        )
        assert by_registry == by_keywords

    def test_poster_registry_matches_keyword_detection(self) -> None:
        by_registry = resolve_protocol(
            protocol_filename="Poster_Congreso.md",
        )
        by_keywords = detect_protocol("Póster de congreso sobre...")
        assert by_registry == by_keywords

    # ── Behavioral properties ──────────────────────────────────────────────

    def test_empty_call_returns_generic(self) -> None:
        """No filename, no topic → GENERIC."""
        profile = resolve_protocol()
        assert profile == ProtocolProfile.GENERIC

    def test_resolve_result_compatible_with_skip_stages(self) -> None:
        """Result of resolve_protocol works with skip_stages_for."""
        profile = resolve_protocol(protocol_filename="Revision_Sistematica_PRISMA.md")
        skipped = skip_stages_for(profile)
        assert len(skipped) > 0  # bibliographic → skips experiment stages

    def test_resolve_result_compatible_with_criticality(self) -> None:
        """Result of resolve_protocol works with criticality_for."""
        profile = resolve_protocol(protocol_filename="Revision_Sistematica_PRISMA.md")
        crit = criticality_for(23, profile)
        assert crit == StageCriticality.SOFT_FAIL
