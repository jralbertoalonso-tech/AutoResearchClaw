import re

import pytest

from researchclaw.pipeline.contracts import CONTRACTS, StageContract
from researchclaw.pipeline.stages import GATE_STAGES, STAGE_SEQUENCE, Stage
from researchclaw.pipeline.protocol import ProtocolFamily, StageCriticality


def test_contracts_dict_has_exactly_23_entries():
    assert len(CONTRACTS) == 23


def test_every_stage_has_matching_contract_entry():
    assert set(CONTRACTS.keys()) == set(Stage)


@pytest.mark.parametrize("stage", STAGE_SEQUENCE)
def test_each_stage_member_resolves_to_stage_contract(stage: Stage):
    assert isinstance(CONTRACTS[stage], StageContract)


@pytest.mark.parametrize("stage,contract", tuple(CONTRACTS.items()))
def test_contract_stage_field_matches_dict_key(stage: Stage, contract: StageContract):
    assert contract.stage is stage


@pytest.mark.parametrize("contract", tuple(CONTRACTS.values()))
def test_output_files_is_non_empty_for_all_contracts(contract: StageContract):
    assert contract.output_files


@pytest.mark.parametrize("stage,contract", tuple(CONTRACTS.items()))
def test_error_code_starts_with_e_and_contains_stage_number(
    stage: Stage, contract: StageContract
):
    assert contract.error_code.startswith("E")
    assert f"{int(stage):02d}" in contract.error_code
    assert re.match(r"^E\d{2}_[A-Z0-9_]+$", contract.error_code)


@pytest.mark.parametrize("contract", tuple(CONTRACTS.values()))
def test_max_retries_is_non_negative_for_all_contracts(contract: StageContract):
    assert contract.max_retries >= 0


def test_gate_stages_have_expected_max_retries():
    assert CONTRACTS[Stage.LITERATURE_SCREEN].max_retries == 0
    assert CONTRACTS[Stage.EXPERIMENT_DESIGN].max_retries == 0
    assert CONTRACTS[Stage.QUALITY_GATE].max_retries == 0


@pytest.mark.parametrize("stage", tuple(GATE_STAGES))
def test_gate_stage_contracts_are_never_retried(stage: Stage):
    assert CONTRACTS[stage].max_retries == 0


def test_topic_init_contract_has_expected_input_output_files():
    contract = CONTRACTS[Stage.TOPIC_INIT]

    assert contract.input_files == ()
    assert contract.output_files == ("goal.md", "hardware_profile.json")


def test_export_publish_contract_has_expected_outputs():
    contract = CONTRACTS[Stage.EXPORT_PUBLISH]
    # code/ is intentionally absent: it is only produced for empirical protocols.
    # Bibliography-only runs (PRISMA, poster, etc.) produce no experiment code and
    # must not fail at this contract check.  The executor appends "code/" to
    # StageResult.artifacts conditionally at runtime.
    assert "paper_final.md" in contract.output_files
    assert "code/" not in contract.output_files


@pytest.mark.parametrize("contract", tuple(CONTRACTS.values()))
def test_dod_is_non_empty_string_for_all_contracts(contract: StageContract):
    assert isinstance(contract.dod, str)
    assert contract.dod.strip()


@pytest.mark.parametrize("contract", tuple(CONTRACTS.values()))
def test_input_files_is_tuple_of_strings(contract: StageContract):
    assert isinstance(contract.input_files, tuple)
    assert all(isinstance(path, str) and path for path in contract.input_files)


@pytest.mark.parametrize("contract", tuple(CONTRACTS.values()))
def test_output_files_is_tuple_of_strings(contract: StageContract):
    assert isinstance(contract.output_files, tuple)
    assert all(isinstance(path, str) and path for path in contract.output_files)


def test_error_codes_are_unique_across_contracts():
    all_codes = [contract.error_code for contract in CONTRACTS.values()]
    assert len(all_codes) == len(set(all_codes))


def test_contracts_follow_stage_sequence_order():
    assert tuple(CONTRACTS.keys()) == STAGE_SEQUENCE


@pytest.mark.parametrize("stage", STAGE_SEQUENCE)
def test_contract_stage_int_matches_stage_enum_value(stage: Stage):
    assert int(CONTRACTS[stage].stage) == int(stage)


# ---------------------------------------------------------------------------
# New fields: criticality + applicable_families
# ---------------------------------------------------------------------------


def test_quality_gate_criticality_is_soft_fail():
    assert CONTRACTS[Stage.QUALITY_GATE].criticality == StageCriticality.SOFT_FAIL


def test_knowledge_archive_criticality_is_advisory():
    assert CONTRACTS[Stage.KNOWLEDGE_ARCHIVE].criticality == StageCriticality.ADVISORY


def test_citation_verify_criticality_is_critical():
    # Default is CRITICAL; per-profile override happens at runtime in runner.py
    assert CONTRACTS[Stage.CITATION_VERIFY].criticality == StageCriticality.CRITICAL


@pytest.mark.parametrize("stage", [
    Stage.EXPERIMENT_DESIGN,
    Stage.CODE_GENERATION,
    Stage.RESOURCE_PLANNING,
    Stage.EXPERIMENT_RUN,
    Stage.ITERATIVE_REFINE,
    Stage.RESULT_ANALYSIS,
    Stage.RESEARCH_DECISION,
])
def test_experiment_stages_applicable_only_to_experimental_family(stage: Stage):
    contract = CONTRACTS[stage]
    assert contract.applicable_families is not None
    assert ProtocolFamily.EXPERIMENTAL in contract.applicable_families
    assert ProtocolFamily.BIBLIOGRAPHIC not in contract.applicable_families


@pytest.mark.parametrize("stage", [
    Stage.TOPIC_INIT,
    Stage.PROBLEM_DECOMPOSE,
    Stage.SEARCH_STRATEGY,
    Stage.LITERATURE_COLLECT,
    Stage.SYNTHESIS,
    Stage.HYPOTHESIS_GEN,
    Stage.PAPER_OUTLINE,
    Stage.PAPER_DRAFT,
    Stage.EXPORT_PUBLISH,
    Stage.CITATION_VERIFY,
])
def test_common_stages_have_no_family_restriction(stage: Stage):
    """Stages that apply to all protocols must have applicable_families=None."""
    assert CONTRACTS[stage].applicable_families is None, (
        f"{stage.name} should apply to all families (applicable_families=None)"
    )
