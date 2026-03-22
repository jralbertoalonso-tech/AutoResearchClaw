"""Tests for researchclaw.protocol_registry — Protocol Registry MVP."""

from __future__ import annotations

import pytest

from researchclaw.protocol_registry import (
    REGISTRY,
    IOType,
    Maturity,
    ProtocolDescriptor,
    ProtocolFamily,
    filenames,
    get_by_filename,
    get_protocol,
    list_families,
    list_protocols,
    protocol_ids,
    protocols_by_family,
    summary_table,
)


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------

class TestRegistryIntegrity:
    def test_registry_is_non_empty(self):
        assert len(REGISTRY) >= 12

    def test_all_ids_unique(self):
        ids = [p.id for p in REGISTRY]
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {[x for x in ids if ids.count(x) > 1]}"

    def test_all_ids_snake_case(self):
        import re
        for p in REGISTRY:
            assert re.match(r"^[a-z][a-z0-9_]*$", p.id), f"ID not snake_case: {p.id}"

    def test_all_have_name(self):
        for p in REGISTRY:
            assert p.name, f"Missing name for {p.id}"

    def test_all_have_description(self):
        for p in REGISTRY:
            assert p.description, f"Missing description for {p.id}"

    def test_all_have_family(self):
        for p in REGISTRY:
            assert isinstance(p.family, ProtocolFamily)

    def test_all_have_maturity(self):
        for p in REGISTRY:
            assert isinstance(p.maturity, Maturity)

    def test_all_have_at_least_one_input(self):
        for p in REGISTRY:
            assert len(p.inputs) >= 1, f"No inputs for {p.id}"

    def test_all_have_at_least_one_output(self):
        for p in REGISTRY:
            assert len(p.outputs) >= 1, f"No outputs for {p.id}"

    def test_protocols_are_frozen(self):
        """ProtocolDescriptor should be immutable."""
        p = REGISTRY[0]
        with pytest.raises(AttributeError):
            p.id = "hacked"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# File reference consistency
# ---------------------------------------------------------------------------

class TestFileReferences:
    def test_filenames_end_in_md(self):
        for p in REGISTRY:
            if p.filename:
                assert p.filename.endswith(".md"), f"Non-md filename: {p.filename}"

    def test_all_filenames_unique(self):
        fnames = [p.filename for p in REGISTRY if p.filename]
        assert len(fnames) == len(set(fnames))

    def test_protocols_dir_files_covered(self):
        """Every .md file in protocols/ should map to a registry entry."""
        from pathlib import Path
        protocols_dir = Path(__file__).parent.parent / "protocols"
        if not protocols_dir.exists():
            pytest.skip("protocols/ directory not available")
        disk_files = {f.name for f in protocols_dir.glob("*.md")}
        registered_files = {p.filename for p in REGISTRY if p.filename}
        missing = disk_files - registered_files
        assert not missing, f"Unregistered protocol files: {missing}"

    def test_registry_files_exist_on_disk(self):
        """Every registered filename should exist in protocols/."""
        from pathlib import Path
        protocols_dir = Path(__file__).parent.parent / "protocols"
        if not protocols_dir.exists():
            pytest.skip("protocols/ directory not available")
        for p in REGISTRY:
            if p.filename:
                assert (protocols_dir / p.filename).exists(), \
                    f"File missing: {p.filename} (protocol {p.id})"


# ---------------------------------------------------------------------------
# Lookup functions
# ---------------------------------------------------------------------------

class TestLookups:
    def test_get_protocol_by_id(self):
        p = get_protocol("revision_sistematica_prisma")
        assert p is not None
        assert p.name == "Revisión Sistemática PRISMA"

    def test_get_protocol_missing(self):
        assert get_protocol("nonexistent") is None

    def test_get_by_filename(self):
        p = get_by_filename("Revision_Sistematica_PRISMA.md")
        assert p is not None
        assert p.id == "revision_sistematica_prisma"

    def test_get_by_filename_missing(self):
        assert get_by_filename("Nonexistent.md") is None

    def test_protocol_ids_returns_all(self):
        ids = protocol_ids()
        assert len(ids) == len(REGISTRY)
        assert "revision_sistematica_prisma" in ids
        assert "auditoria_ceim" in ids

    def test_filenames_returns_only_nonempty(self):
        fnames = filenames()
        assert all(f.endswith(".md") for f in fnames)
        # dossier_ceim has no filename
        dossier = get_protocol("dossier_ceim")
        assert dossier is not None
        assert dossier.filename == ""
        assert "" not in fnames


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

class TestFiltering:
    def test_filter_by_family_research(self):
        result = list_protocols(family=ProtocolFamily.RESEARCH)
        assert all(p.family == ProtocolFamily.RESEARCH for p in result)
        assert len(result) >= 2

    def test_filter_by_family_ethics(self):
        result = list_protocols(family=ProtocolFamily.ETHICS)
        assert all(p.family == ProtocolFamily.ETHICS for p in result)
        ids = [p.id for p in result]
        assert "auditoria_ceim" in ids
        assert "dossier_ceim" in ids

    def test_filter_by_maturity_mvp(self):
        result = list_protocols(maturity=Maturity.MVP)
        assert all(p.maturity == Maturity.MVP for p in result)
        ids = [p.id for p in result]
        assert "auditoria_ceim" in ids
        assert "dossier_ceim" in ids

    def test_filter_by_maturity_stable(self):
        result = list_protocols(maturity=Maturity.STABLE)
        assert all(p.maturity == Maturity.STABLE for p in result)
        ids = [p.id for p in result]
        assert "revision_sistematica_prisma" in ids

    def test_filter_by_tag(self):
        result = list_protocols(tag="ceim")
        assert len(result) == 2
        ids = [p.id for p in result]
        assert "auditoria_ceim" in ids
        assert "dossier_ceim" in ids

    def test_filter_by_requires_llm_false(self):
        result = list_protocols(requires_llm=False)
        assert all(not p.requires_llm for p in result)
        ids = [p.id for p in result]
        assert "auditoria_ceim" in ids
        assert "dossier_ceim" in ids
        assert "resumen_congreso" in ids

    def test_filter_combined(self):
        result = list_protocols(
            family=ProtocolFamily.ETHICS,
            requires_llm=False,
        )
        assert len(result) == 2

    def test_filter_no_match(self):
        result = list_protocols(tag="nonexistent_tag")
        assert result == []

    def test_no_filter_returns_all(self):
        result = list_protocols()
        assert len(result) == len(REGISTRY)


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

class TestGrouping:
    def test_list_families(self):
        families = list_families()
        assert ProtocolFamily.RESEARCH in families
        assert ProtocolFamily.CLINICAL in families
        assert ProtocolFamily.DISSEMINATION in families
        assert ProtocolFamily.ETHICS in families

    def test_protocols_by_family_covers_all(self):
        by_family = protocols_by_family()
        total = sum(len(v) for v in by_family.values())
        assert total == len(REGISTRY)

    def test_protocols_by_family_keys(self):
        by_family = protocols_by_family()
        assert set(by_family.keys()) == set(list_families())


# ---------------------------------------------------------------------------
# Protocol metadata validation
# ---------------------------------------------------------------------------

class TestMetadataConsistency:
    def test_generators_have_module_path(self):
        for p in REGISTRY:
            if p.has_dedicated_generator:
                assert p.generator_module, f"{p.id}: generator flag set but no module"

    def test_reviews_have_module_path(self):
        for p in REGISTRY:
            if p.has_review_component:
                assert p.review_module, f"{p.id}: review flag set but no module"

    def test_ui_panels_have_id(self):
        for p in REGISTRY:
            if p.has_ui_panel:
                assert p.ui_panel_id, f"{p.id}: UI panel flag set but no panel ID"

    def test_no_search_without_llm_consistency(self):
        """Protocols that don't require LLM usually don't require search."""
        for p in REGISTRY:
            if not p.requires_llm and p.requires_search:
                # This is technically possible but unusual; flag if it happens
                pytest.fail(
                    f"{p.id}: requires_search=True but requires_llm=False — verify intent"
                )

    def test_ethics_protocols_support_study_types(self):
        for p in list_protocols(family=ProtocolFamily.ETHICS):
            assert p.supports_observational, f"{p.id}: ethics protocol should support observational"
            assert p.supports_qualitative, f"{p.id}: ethics protocol should support qualitative"
            assert p.supports_mixed, f"{p.id}: ethics protocol should support mixed"

    def test_pipeline_profile_values_valid(self):
        """Pipeline profile references should match known values."""
        valid_profiles = {
            "", "systematic_review_prisma", "narrative_review",
            "scoping_review", "meta_analysis", "poster_only",
            "experimental_ml", "generic",
        }
        for p in REGISTRY:
            assert p.pipeline_profile in valid_profiles, \
                f"{p.id}: unknown pipeline_profile '{p.pipeline_profile}'"

    def test_skip_stages_aligned_with_pipeline_profile(self):
        """Protocols that skip stages should reference a bibliographic profile."""
        bibliographic_profiles = {
            "systematic_review_prisma", "narrative_review",
            "scoping_review", "meta_analysis", "poster_only",
        }
        for p in REGISTRY:
            if p.skips_experiment_stages:
                assert p.pipeline_profile in bibliographic_profiles, \
                    f"{p.id}: skips stages but pipeline_profile='{p.pipeline_profile}'"


# ---------------------------------------------------------------------------
# Specific protocol entries
# ---------------------------------------------------------------------------

class TestSpecificProtocols:
    def test_prisma_is_stable(self):
        p = get_protocol("revision_sistematica_prisma")
        assert p is not None
        assert p.maturity == Maturity.STABLE
        assert p.family == ProtocolFamily.RESEARCH
        assert p.requires_llm is True
        assert p.skips_experiment_stages is True

    def test_ceim_review_no_llm(self):
        p = get_protocol("auditoria_ceim")
        assert p is not None
        assert p.requires_llm is False
        assert p.requires_search is False
        assert p.has_review_component is True
        assert p.review_module == "researchclaw.ceim_reviewer"

    def test_ceim_dossier_structured_input(self):
        p = get_protocol("dossier_ceim")
        assert p is not None
        assert IOType.STRUCTURED_FORM in p.inputs
        assert p.requires_llm is False
        assert p.has_dedicated_generator is True
        assert p.generator_module == "researchclaw.ceim_dossier"
        assert p.supports_minors is True
        assert p.supports_biological_samples is True

    def test_poster_has_ui_panel(self):
        p = get_protocol("poster_congreso")
        assert p is not None
        assert p.has_ui_panel is True
        assert p.has_dedicated_generator is True

    def test_abstract_is_mvp(self):
        p = get_protocol("resumen_congreso")
        assert p is not None
        assert p.maturity == Maturity.MVP
        assert p.requires_llm is False

    def test_consulta_clinica_pico_is_mvp(self):
        """Consulta Clínica PICO promoted from SPEC to MVP.

        Uses narrative_review pipeline profile — bibliographic search
        without experiment stages (9-15). Routing verified by
        test_rc_protocol.py::TestResolveProtocol::test_consulta_clinica_pico_by_filename.
        """
        p = get_protocol("consulta_clinica_pico")
        assert p is not None
        assert p.maturity == Maturity.MVP
        assert p.family == ProtocolFamily.CLINICAL
        assert p.pipeline_profile == "narrative_review"
        assert p.skips_experiment_stages is True
        assert IOType.PDF in p.outputs
        assert IOType.DOCX in p.outputs


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

class TestSummaryTable:
    def test_summary_table_markdown(self):
        table = summary_table()
        assert "| ID |" in table
        assert "|---|" in table
        assert "revision_sistematica_prisma" in table
        assert "auditoria_ceim" in table

    def test_summary_table_has_all_entries(self):
        table = summary_table()
        for p in REGISTRY:
            assert p.id in table, f"Missing from summary: {p.id}"

    def test_summary_table_line_count(self):
        table = summary_table()
        lines = table.strip().split("\n")
        # header + separator + one per protocol
        assert len(lines) == 2 + len(REGISTRY)
