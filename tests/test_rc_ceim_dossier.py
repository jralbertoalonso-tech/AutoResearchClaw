"""Tests for researchclaw.ceim_dossier — CEIm dossier generator."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from researchclaw.ceim_dossier import (
    CEImDossier,
    StudyProfile,
    _generate_ci,
    _generate_data_protection,
    _generate_hip,
    _generate_protocol,
    _generate_samples_annex,
    _generate_assent,
    _list_or_ph,
    _ph,
    _PH,
    _screen_eipd,
    generate_dossier,
    write_dossier,
)
from researchclaw.ceim_reviewer import StudyType


# ---------------------------------------------------------------------------
# Fixtures — reusable profiles
# ---------------------------------------------------------------------------

def _minimal_profile(**overrides) -> StudyProfile:
    """A minimal profile with only required fields."""
    defaults = dict(title="Estudio Mínimo", pi_name="Dr. Test")
    defaults.update(overrides)
    return StudyProfile(**defaults)


def _full_observational_profile() -> StudyProfile:
    return StudyProfile(
        title="Eficacia de intervención X en pacientes con HTA",
        protocol_code="OBS-2026-001",
        version="2.0",
        version_date="2026-03-01",
        sponsor="Hospital Clínico Universitario",
        pi_name="Dra. María García López",
        pi_contact="mgarcia@hcu.es",
        institution="Hospital Clínico Universitario de Valencia",
        ceim_name="CEIm del HCU Valencia",
        ceim_contact="ceim@hcu.es",
        study_type=StudyType.OBSERVATIONAL,
        design_description="Estudio observacional prospectivo de cohortes.",
        primary_objective="Evaluar la eficacia de la intervención X en la reducción de la presión arterial.",
        secondary_objectives=[
            "Analizar efectos secundarios",
            "Evaluar adherencia terapéutica",
        ],
        justification="La HTA afecta al 33% de la población adulta española.",
        hypothesis="La intervención X reduce la PA sistólica en ≥10 mmHg.",
        duration_months=18,
        registry="ClinicalTrials.gov NCT12345678",
        target_population="Adultos con HTA grado I-II",
        age_range="18-75 años",
        estimated_sample_size=200,
        inclusion_criteria=[
            "Diagnóstico de HTA grado I-II (PAS 140-179 mmHg)",
            "Edad entre 18 y 75 años",
            "Capacidad para otorgar consentimiento informado",
        ],
        exclusion_criteria=[
            "HTA secundaria",
            "Enfermedad renal crónica estadio ≥3",
        ],
        intervention_description="Administración diaria de fármaco X 10 mg vía oral.",
        variables_primary="Presión arterial sistólica (mmHg)",
        variables_secondary="PA diastólica, frecuencia cardíaca, adherencia (Morisky)",
        statistical_plan="ANOVA de medidas repetidas, IC 95%, análisis por intención de tratar.",
        sample_size_justification="Cálculo basado en d=0.5, α=0.05, β=0.80 → n=200.",
        known_risks=["Hipotensión leve", "Cefalea transitoria"],
        expected_benefits=["Reducción de riesgo cardiovascular"],
        mitigation_measures=["Monitorización tensional semanal", "Protocolo de escalada de dosis"],
        data_controller="Hospital Clínico Universitario de Valencia",
        legal_basis="Art. 9.2.j RGPD (investigación en interés público)",
        data_retention_years=15,
        has_insurance=True,
        insurance_reference="Póliza AXA nº 12345-INV-2026",
        funding_source="Beca FIS PI26/00123",
    )


def _full_qualitative_profile() -> StudyProfile:
    return StudyProfile(
        title="Vivencias de pacientes con fibromialgia",
        protocol_code="QUAL-2026-002",
        version="1.0",
        version_date="2026-02-15",
        sponsor="Universidad de Barcelona",
        pi_name="Dr. Javier Ruiz Pérez",
        pi_contact="jruiz@ub.edu",
        institution="Facultad de Enfermería, Universidad de Barcelona",
        ceim_name="CEIm del Hospital Clínic",
        ceim_contact="ceim@clinic.cat",
        study_type=StudyType.QUALITATIVE,
        design_description="Estudio cualitativo fenomenológico interpretativo.",
        primary_objective="Comprender las vivencias y significados de la enfermedad en pacientes con fibromialgia.",
        justification="La fibromialgia afecta al 2-4% de la población; la perspectiva del paciente está poco estudiada.",
        duration_months=12,
        target_population="Pacientes diagnosticados de fibromialgia",
        age_range="18-65 años",
        estimated_sample_size=20,
        inclusion_criteria=[
            "Diagnóstico de fibromialgia (criterios ACR 2016)",
            "Capacidad para participar en entrevistas",
        ],
        exclusion_criteria=["Trastorno psiquiátrico grave activo"],
        qualitative_method="Fenomenología interpretativa (IPA)",
        data_collection_techniques=[
            "entrevistas semiestructuradas individuales (60-90 min)",
            "grupo focal (6-8 participantes, 90 min)",
        ],
        analysis_approach="Análisis fenomenológico interpretativo (IPA) según Smith et al.",
        known_risks=["Malestar emocional durante las entrevistas"],
        mitigation_measures=["Protocolo de derivación a psicología clínica"],
        data_controller="Universidad de Barcelona",
        data_retention_years=10,
        has_sensitive_data=True,
        funding_source="Proyecto MINECO PID2026-001",
    )


def _mixed_profile_with_minors_and_samples() -> StudyProfile:
    return StudyProfile(
        title="Impacto del ejercicio en adolescentes con obesidad",
        protocol_code="MIX-2026-003",
        version="1.0",
        version_date="2026-01-10",
        sponsor="Instituto de Salud Carlos III",
        pi_name="Dra. Ana Torres",
        pi_contact="atorres@isciii.es",
        institution="Hospital La Paz, Madrid",
        ceim_name="CEIm del Hospital La Paz",
        ceim_contact="ceim@lapaz.es",
        study_type=StudyType.MIXED,
        design_description="Estudio mixto secuencial explicativo.",
        primary_objective="Evaluar el impacto de un programa de ejercicio en adolescentes con obesidad.",
        secondary_objectives=[
            "Explorar percepciones de los participantes sobre el programa",
            "Analizar biomarcadores metabólicos",
        ],
        justification="La obesidad infantil alcanza el 18% en España.",
        hypothesis="El programa reduce IMC en ≥2 kg/m².",
        duration_months=24,
        target_population="Adolescentes con obesidad (IMC p>95)",
        age_range="12-17 años",
        estimated_sample_size=80,
        inclusion_criteria=[
            "Edad 12-17 años",
            "IMC > percentil 95",
        ],
        exclusion_criteria=["Contraindicación para ejercicio"],
        has_minors=True,
        minor_age_range="12-17",
        has_vulnerable=True,
        intervention_description="Programa de ejercicio supervisado 3x/semana durante 6 meses.",
        variables_primary="IMC (kg/m²)",
        variables_secondary="Glucemia basal, perfil lipídico, calidad de vida (PedsQL)",
        statistical_plan="Modelo mixto de medidas repetidas, p<0.05.",
        sample_size_justification="Basado en meta-análisis previo (d=0.6), n=80.",
        qualitative_method="Análisis temático reflexivo (Braun & Clarke)",
        data_collection_techniques=["entrevistas individuales", "diarios de participantes"],
        analysis_approach="Análisis temático reflexivo de Braun & Clarke.",
        known_risks=["Lesión musculoesquelética leve", "Malestar por extracción sanguínea"],
        expected_benefits=["Mejora de la condición física", "Reducción de factores de riesgo metabólico"],
        mitigation_measures=["Supervisión por fisioterapeuta", "Protocolo de analgesia tópica"],
        data_controller="Instituto de Salud Carlos III",
        has_sensitive_data=True,
        has_biological_samples=True,
        sample_types=["Sangre venosa (10 mL)", "Orina (muestra matutina)"],
        biobank_name="Biobanco Hospital La Paz",
        sample_storage_years=20,
        has_ai_component=True,
        ai_model_description="Modelo predictivo de adherencia basado en datos de actividad.",
        ai_training_data="Datos de acelerómetro y cuestionarios de 500 participantes previos.",
        ai_validation_plan="Validación cruzada 5-fold, AUROC ≥ 0.75.",
        ai_risk_classification="Limitado (Reglamento IA UE)",
        has_international_transfer=True,
        transfer_mechanism="Cláusulas Contractuales Tipo (SCC) de la Comisión Europea",
        has_insurance=True,
        insurance_reference="Póliza MAPFRE nº INV-2026-789",
        funding_source="ISCIII FIS PI26/99999",
    )


# ---------------------------------------------------------------------------
# Tests — placeholder helpers
# ---------------------------------------------------------------------------

class TestPlaceholderHelpers:
    def test_ph_empty_returns_placeholder(self):
        assert _ph("") == _PH
        assert _ph("   ") == _PH

    def test_ph_value_returns_stripped(self):
        assert _ph("  Hello ") == "Hello"

    def test_list_or_ph_empty_numbered(self):
        result = _list_or_ph([])
        assert _PH in result
        assert "1." in result

    def test_list_or_ph_empty_unnumbered(self):
        result = _list_or_ph([], numbered=False)
        assert _PH in result
        assert result.startswith("-")

    def test_list_or_ph_with_items(self):
        result = _list_or_ph(["A", "B", "C"])
        assert "1. A" in result
        assert "2. B" in result
        assert "3. C" in result

    def test_list_or_ph_unnumbered_items(self):
        result = _list_or_ph(["X", "Y"], numbered=False)
        assert "- X" in result
        assert "- Y" in result


# ---------------------------------------------------------------------------
# Tests — StudyProfile
# ---------------------------------------------------------------------------

class TestStudyProfile:
    def test_default_values(self):
        p = StudyProfile()
        assert p.title == ""
        assert p.study_type == StudyType.OBSERVATIONAL
        assert p.has_minors is False
        assert p.has_biological_samples is False
        assert p.data_retention_years == 15

    def test_effective_date_uses_version_date(self):
        p = StudyProfile(version_date="2026-06-01")
        assert p.effective_date() == "2026-06-01"

    def test_effective_date_fallback_to_today(self):
        p = StudyProfile()
        # Should return today's ISO date
        import datetime
        assert p.effective_date() == datetime.date.today().isoformat()


# ---------------------------------------------------------------------------
# Tests — Protocol generation
# ---------------------------------------------------------------------------

class TestGenerateProtocol:
    def test_observational_protocol_structure(self):
        p = _full_observational_profile()
        doc = _generate_protocol(p)
        # Must contain key sections
        assert "# Protocolo del Estudio:" in doc
        assert "## 1. Información General" in doc
        assert "## 2. Justificación" in doc
        assert "## 3. Objetivos" in doc
        assert "## 4. Diseño del Estudio" in doc
        assert "## 5. Selección de Participantes" in doc
        assert "## 6. Intervención / Procedimientos" in doc
        assert "## 7. Variables" in doc
        assert "## 8. Plan de Análisis Estadístico" in doc
        assert "## 9. Seguridad" in doc
        assert "## 10. Protección de Datos" in doc
        assert "## 11. Aspectos Éticos" in doc
        assert "## 12. Cronograma" in doc

    def test_observational_no_placeholders_in_filled_fields(self):
        p = _full_observational_profile()
        doc = _generate_protocol(p)
        assert "Dra. María García López" in doc
        assert "OBS-2026-001" in doc
        assert "Hospital Clínico Universitario" in doc
        assert "NCT12345678" in doc

    def test_observational_has_sample_size_justification(self):
        p = _full_observational_profile()
        doc = _generate_protocol(p)
        assert "Justificación del tamaño muestral" in doc

    def test_qualitative_protocol_uses_saturation(self):
        p = _full_qualitative_profile()
        doc = _generate_protocol(p)
        assert "saturación teórica" in doc
        assert "Justificación del tamaño muestral" not in doc

    def test_qualitative_protocol_has_rigour_section(self):
        p = _full_qualitative_profile()
        doc = _generate_protocol(p)
        assert "Rigor y calidad" in doc
        assert "Triangulación" in doc
        assert "Reflexividad" in doc

    def test_qualitative_protocol_design_section(self):
        p = _full_qualitative_profile()
        doc = _generate_protocol(p)
        assert "Método cualitativo" in doc
        assert "Fenomenología" in doc or "fenomenológico" in doc

    def test_mixed_protocol_has_both_components(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_protocol(p)
        assert "Componente cuantitativo" in doc
        assert "Componente cualitativo" in doc

    def test_protocol_with_samples_has_annex(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_protocol(p)
        assert "Anexo A — Muestras Biológicas" in doc
        assert "Sangre venosa" in doc

    def test_protocol_with_ai_has_annex(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_protocol(p)
        assert "Anexo B — Componente de Inteligencia Artificial" in doc
        assert "Explicabilidad" in doc

    def test_protocol_without_samples_no_annex(self):
        p = _full_observational_profile()
        doc = _generate_protocol(p)
        assert "Anexo A — Muestras" not in doc

    def test_protocol_adverse_events_for_observational(self):
        p = _full_observational_profile()
        doc = _generate_protocol(p)
        assert "Plan de notificación de eventos adversos" in doc
        assert "SAE" in doc

    def test_minimal_profile_fills_placeholders(self):
        p = _minimal_profile()
        doc = _generate_protocol(p)
        count = doc.count(_PH)
        assert count >= 10  # Many fields should show placeholder

    def test_protocol_with_international_transfer(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_protocol(p)
        assert "Transferencia internacional" in doc
        assert "SCC" in doc or "Cláusulas Contractuales" in doc

    def test_protocol_sensitive_data(self):
        p = _full_qualitative_profile()
        doc = _generate_protocol(p)
        assert "especialmente protegidos" in doc


# ---------------------------------------------------------------------------
# Tests — HIP generation
# ---------------------------------------------------------------------------

class TestGenerateHIP:
    def test_hip_structure(self):
        p = _full_observational_profile()
        doc = _generate_hip(p)
        assert "# Hoja de Información al Paciente" in doc
        assert "Naturaleza voluntaria" in doc
        assert "Objetivo del estudio" in doc
        assert "Procedimientos del estudio" in doc
        assert "Riesgos y molestias" in doc
        assert "Beneficios esperados" in doc
        assert "Alternativas" in doc
        assert "Confidencialidad" in doc
        assert "Contacto" in doc

    def test_hip_includes_risks(self):
        p = _full_observational_profile()
        doc = _generate_hip(p)
        assert "Hipotensión leve" in doc
        assert "Cefalea transitoria" in doc

    def test_hip_includes_mitigation(self):
        p = _full_observational_profile()
        doc = _generate_hip(p)
        assert "Monitorización tensional" in doc

    def test_hip_qualitative_procedures(self):
        p = _full_qualitative_profile()
        doc = _generate_hip(p)
        assert "entrevistas semiestructuradas" in doc
        assert "grupo focal" in doc

    def test_hip_biological_samples_section(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_hip(p)
        assert "Uso de muestras biológicas" in doc
        assert "Sangre venosa" in doc

    def test_hip_no_samples_no_section(self):
        p = _full_observational_profile()
        doc = _generate_hip(p)
        assert "Uso de muestras biológicas" not in doc

    def test_hip_compensation_none(self):
        p = _full_observational_profile()
        doc = _generate_hip(p)
        assert "No se prevé compensación" in doc

    def test_hip_compensation_present(self):
        p = _minimal_profile(has_compensation=True, compensation_description="50€ por visita")
        doc = _generate_hip(p)
        assert "50€ por visita" in doc

    def test_hip_international_transfer(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_hip(p)
        assert "Transferencia internacional" in doc

    def test_hip_data_protection_info(self):
        p = _full_observational_profile()
        doc = _generate_hip(p)
        assert "RGPD" in doc
        assert "LOPDGDD" in doc
        assert "seudonimizados" in doc


# ---------------------------------------------------------------------------
# Tests — CI generation
# ---------------------------------------------------------------------------

class TestGenerateCI:
    def test_ci_structure(self):
        p = _full_observational_profile()
        doc = _generate_ci(p)
        assert "# Documento de Consentimiento Informado" in doc
        assert "Declaro que:" in doc
        assert "voluntaria" in doc
        assert "CONSIENTO" in doc
        assert "Participante" in doc
        assert "Investigador" in doc

    def test_ci_five_declarations(self):
        p = _full_observational_profile()
        doc = _generate_ci(p)
        for i in range(1, 6):
            assert f"{i}." in doc

    def test_ci_samples_checkbox(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_ci(p)
        assert "Autorización para uso de muestras biológicas" in doc
        assert "ACEPTO" in doc
        assert "NO ACEPTO" in doc

    def test_ci_no_samples_no_checkbox(self):
        p = _full_observational_profile()
        doc = _generate_ci(p)
        assert "Autorización para uso de muestras" not in doc

    def test_ci_transfer_checkbox(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_ci(p)
        assert "Autorización para transferencia internacional" in doc

    def test_ci_representative_for_minors(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_ci(p)
        assert "representante legal" in doc.lower() or "Representante legal" in doc

    def test_ci_no_representative_for_adults(self):
        p = _full_observational_profile()
        doc = _generate_ci(p)
        assert "representante legal" not in doc.lower()

    def test_ci_separation_note(self):
        p = _full_observational_profile()
        doc = _generate_ci(p)
        assert "separarse de la Hoja de Información" in doc


# ---------------------------------------------------------------------------
# Tests — Assent generation
# ---------------------------------------------------------------------------

class TestGenerateAssent:
    def test_assent_basic_structure(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_assent(p)
        assert "Asentimiento para Menores" in doc
        assert "Información para ti" in doc
        assert "Mi decisión" in doc
        assert "SÍ QUIERO" in doc
        assert "NO QUIERO" in doc

    def test_assent_age_range(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_assent(p)
        assert "12-17" in doc

    def test_assent_plain_language(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_assent(p)
        # Should use informal, youth-friendly language
        assert "No pasa nada" in doc
        assert "chicos y chicas" in doc or "voluntario" in doc

    def test_assent_samples_section(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_assent(p)
        assert "¿Me van a sacar muestras?" in doc
        assert "Sangre venosa" in doc

    def test_assent_no_samples(self):
        p = _minimal_profile(has_minors=True)
        doc = _generate_assent(p)
        assert "¿Me van a sacar muestras?" not in doc

    def test_assent_qualitative_techniques(self):
        p = StudyProfile(
            title="Test",
            study_type=StudyType.QUALITATIVE,
            has_minors=True,
            data_collection_techniques=["entrevista individual"],
        )
        doc = _generate_assent(p)
        assert "entrevista individual" in doc

    def test_assent_risks_shown(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_assent(p)
        assert "Lesión musculoesquelética" in doc


# ---------------------------------------------------------------------------
# Tests — Data Protection appendix
# ---------------------------------------------------------------------------

class TestGenerateDataProtection:
    def test_data_protection_structure(self):
        p = _full_observational_profile()
        doc = _generate_data_protection(p)
        assert "# Apéndice de Protección de Datos" in doc
        assert "Identificación del tratamiento" in doc
        assert "Base legal" in doc
        assert "Categorías de datos" in doc
        assert "Seudonimización" in doc
        assert "Periodo de conservación" in doc
        assert "ARCO+" in doc

    def test_eipd_not_required_simple_study(self):
        p = _full_observational_profile()
        doc = _generate_data_protection(p)
        assert "No requiere EIPD" in doc
        assert "✅" in doc

    def test_eipd_recommended_one_criterion(self):
        p = _full_qualitative_profile()  # has_sensitive_data=True
        doc = _generate_data_protection(p)
        assert "RECOMENDADA" in doc
        assert "⚠️" in doc

    def test_eipd_obligatory_three_criteria(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_data_protection(p)
        assert "OBLIGATORIA" in doc
        assert "❌" in doc

    def test_eipd_criteria_details_listed(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_data_protection(p)
        assert "art. 9" in doc
        assert "nuevas tecnologías" in doc.lower() or "Nuevas tecnologías" in doc
        assert "vulnerables" in doc
        assert "Transferencia internacional" in doc

    def test_biological_samples_category(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_data_protection(p)
        assert "genéticos/biológicos" in doc

    def test_ai_data_category(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_data_protection(p)
        assert "Datos para IA/ML" in doc

    def test_retention_period(self):
        p = StudyProfile(data_retention_years=25)
        doc = _generate_data_protection(p)
        assert "25 años" in doc

    def test_international_transfer_section(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_data_protection(p)
        assert "Transferencia internacional de datos" in doc
        assert "SCC" in doc or "Cláusulas Contractuales" in doc

    def test_eipd_has_seven_criteria_rows(self):
        p = _full_observational_profile()
        doc = _generate_data_protection(p)
        # Table should have 7 numbered criteria rows
        for i in range(1, 8):
            assert f"| {i} |" in doc

    def test_eipd_shows_criteria_count(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_data_protection(p)
        assert "Criterios positivos" in doc

    def test_art9_security_measures_for_sensitive(self):
        p = _full_qualitative_profile()  # has_sensitive_data=True
        doc = _generate_data_protection(p)
        assert "Medidas de seguridad adicionales" in doc
        assert "AES-256" in doc

    def test_no_art9_security_for_simple(self):
        p = _full_observational_profile()  # no sensitive, no samples
        doc = _generate_data_protection(p)
        assert "Medidas de seguridad adicionales" not in doc

    def test_mitigations_section_present(self):
        p = _full_qualitative_profile()
        doc = _generate_data_protection(p)
        assert "Medidas de mitigación recomendadas" in doc

    def test_no_mitigations_for_clean_study(self):
        p = _full_observational_profile()
        doc = _generate_data_protection(p)
        assert "medidas estándar de seudonimización" in doc

    def test_art35_reference(self):
        p = _full_observational_profile()
        doc = _generate_data_protection(p)
        assert "art. 35 RGPD" in doc


# ---------------------------------------------------------------------------
# Tests — _screen_eipd (EIPD screening logic)
# ---------------------------------------------------------------------------

class TestScreenEIPD:
    def test_zero_criteria_clean_study(self):
        p = _full_observational_profile()
        r = _screen_eipd(p)
        assert r["count"] == 0
        assert r["result"] == "No requiere EIPD"
        assert r["icon"] == "✅"
        assert not r["large_scale_health"]

    def test_one_criterion_recommended(self):
        p = _minimal_profile(has_sensitive_data=True)
        r = _screen_eipd(p)
        assert r["count"] == 1
        assert r["result"] == "EIPD RECOMENDADA"
        assert r["icon"] == "⚠️"

    def test_two_criteria_still_recommended(self):
        p = _minimal_profile(has_sensitive_data=True, has_ai_component=True)
        r = _screen_eipd(p)
        assert r["count"] == 2
        assert r["result"] == "EIPD RECOMENDADA"

    def test_three_criteria_obligatory(self):
        p = _minimal_profile(
            has_sensitive_data=True,
            has_ai_component=True,
            has_minors=True,
        )
        r = _screen_eipd(p)
        assert r["count"] == 3
        assert r["result"] == "EIPD OBLIGATORIA"
        assert r["icon"] == "❌"

    def test_biological_samples_infer_art9(self):
        """Biological samples → art. 9 sensitive data, even without has_sensitive_data."""
        p = _minimal_profile(has_biological_samples=True)
        r = _screen_eipd(p)
        assert r["count"] == 1
        c1 = r["criteria"][0]
        assert c1["present"] is True
        assert "biológicos" in c1["detail"]

    def test_both_sensitive_and_samples(self):
        p = _minimal_profile(has_sensitive_data=True, has_biological_samples=True)
        r = _screen_eipd(p)
        c1 = r["criteria"][0]
        assert c1["present"] is True
        assert "salud" in c1["detail"] and "genéticos" in c1["detail"]

    def test_large_scale_health_auto_obligatory(self):
        """n≥500 + health data → EIPD obligatory regardless of other criteria."""
        p = _minimal_profile(
            has_sensitive_data=True,
            estimated_sample_size=600,
        )
        r = _screen_eipd(p)
        assert r["large_scale_health"] is True
        assert r["result"] == "EIPD OBLIGATORIA"
        # Only 1 criterion met, but large-scale rule triggers

    def test_large_scale_below_threshold(self):
        p = _minimal_profile(has_sensitive_data=True, estimated_sample_size=499)
        r = _screen_eipd(p)
        assert r["large_scale_health"] is False
        assert r["result"] == "EIPD RECOMENDADA"

    def test_large_scale_without_health_data(self):
        """Large sample alone (without art. 9 data) doesn't trigger large-scale rule."""
        p = _minimal_profile(estimated_sample_size=1000)
        r = _screen_eipd(p)
        assert r["large_scale_health"] is False
        assert r["result"] == "No requiere EIPD"

    def test_new_fields_profiling(self):
        p = _minimal_profile(has_systematic_profiling=True)
        r = _screen_eipd(p)
        assert r["count"] == 1
        c2 = r["criteria"][1]
        assert c2["present"] is True

    def test_new_fields_data_linkage(self):
        p = _minimal_profile(has_data_linkage=True)
        r = _screen_eipd(p)
        assert r["count"] == 1
        c6 = r["criteria"][5]
        assert c6["present"] is True
        assert "linkage" in c6["detail"]

    def test_new_fields_automated_decisions(self):
        p = _minimal_profile(has_automated_decisions=True)
        r = _screen_eipd(p)
        assert r["count"] == 1
        c7 = r["criteria"][6]
        assert c7["present"] is True
        assert "revisión humana" in c7["detail"]

    def test_automated_decisions_distinct_from_ai(self):
        """AI component and automated decisions are separate criteria."""
        p = _minimal_profile(has_ai_component=True, has_automated_decisions=True)
        r = _screen_eipd(p)
        assert r["count"] == 2
        c3 = r["criteria"][2]  # new technologies
        c7 = r["criteria"][6]  # automated decisions
        assert c3["present"] is True
        assert c7["present"] is True

    def test_seven_criteria_total(self):
        p = _minimal_profile()
        r = _screen_eipd(p)
        assert len(r["criteria"]) == 7

    def test_all_criteria_enabled(self):
        p = StudyProfile(
            has_sensitive_data=True,
            has_systematic_profiling=True,
            has_ai_component=True,
            has_vulnerable=True,
            has_international_transfer=True,
            has_data_linkage=True,
            has_automated_decisions=True,
        )
        r = _screen_eipd(p)
        assert r["count"] == 7
        assert r["result"] == "EIPD OBLIGATORIA"

    def test_mitigations_encryption_for_art9(self):
        p = _minimal_profile(has_sensitive_data=True)
        r = _screen_eipd(p)
        assert any("Cifrado" in m for m in r["mitigations"])

    def test_mitigations_human_review_for_automated(self):
        p = _minimal_profile(has_automated_decisions=True)
        r = _screen_eipd(p)
        assert any("revisión humana" in m for m in r["mitigations"])

    def test_mitigations_xai_for_ai(self):
        p = _minimal_profile(has_ai_component=True)
        r = _screen_eipd(p)
        assert any("explicabilidad" in m for m in r["mitigations"])

    def test_mitigations_salvaguardas_for_vulnerable(self):
        p = _minimal_profile(has_minors=True)
        r = _screen_eipd(p)
        assert any("salvaguardas" in m.lower() for m in r["mitigations"])

    def test_mitigations_transfer_for_international(self):
        p = _minimal_profile(has_international_transfer=True)
        r = _screen_eipd(p)
        assert any("SCC" in m for m in r["mitigations"])

    def test_mitigations_linkage(self):
        p = _minimal_profile(has_data_linkage=True)
        r = _screen_eipd(p)
        assert any("linkage" in m for m in r["mitigations"])

    def test_no_mitigations_clean_study(self):
        p = _minimal_profile()
        r = _screen_eipd(p)
        assert r["mitigations"] == []

    def test_mixed_profile_full_screening(self):
        """Integration: the full mixed profile should trigger 5 of 7 criteria."""
        p = _mixed_profile_with_minors_and_samples()
        r = _screen_eipd(p)
        # C1: sensitive+samples, C3: AI, C4: vulnerable+minors, C5: transfer
        # C2: no profiling, C6: no linkage, C7: no automated decisions
        assert r["count"] == 4
        assert r["result"] == "EIPD OBLIGATORIA"


# ---------------------------------------------------------------------------
# Tests — Samples annex
# ---------------------------------------------------------------------------

class TestGenerateSamplesAnnex:
    def test_samples_annex_structure(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_samples_annex(p)
        assert "# Anexo de Muestras Biológicas" in doc
        assert "Tipos de muestras" in doc
        assert "Finalidad" in doc
        assert "Almacenamiento" in doc
        assert "Consentimiento específico" in doc
        assert "Destrucción" in doc
        assert "Uso futuro" in doc

    def test_samples_annex_types(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_samples_annex(p)
        assert "Sangre venosa" in doc
        assert "Orina" in doc

    def test_samples_annex_biobank(self):
        p = _mixed_profile_with_minors_and_samples()
        doc = _generate_samples_annex(p)
        assert "Biobanco Hospital La Paz" in doc
        assert "20 años" in doc

    def test_samples_annex_empty_types(self):
        p = StudyProfile(has_biological_samples=True)
        doc = _generate_samples_annex(p)
        assert _PH in doc


# ---------------------------------------------------------------------------
# Tests — generate_dossier (integration)
# ---------------------------------------------------------------------------

class TestGenerateDossier:
    def test_observational_generates_four_docs(self):
        p = _full_observational_profile()
        d = generate_dossier(p)
        assert isinstance(d, CEImDossier)
        assert set(d.documents.keys()) == {"protocol", "hip", "ci", "data_protection"}

    def test_qualitative_generates_four_docs(self):
        p = _full_qualitative_profile()
        d = generate_dossier(p)
        assert set(d.documents.keys()) == {"protocol", "hip", "ci", "data_protection"}

    def test_mixed_with_everything_generates_six_docs(self):
        p = _mixed_profile_with_minors_and_samples()
        d = generate_dossier(p)
        expected = {"protocol", "hip", "ci", "data_protection", "assent", "samples_annex"}
        assert set(d.documents.keys()) == expected

    def test_minors_without_samples(self):
        p = _minimal_profile(has_minors=True)
        d = generate_dossier(p)
        assert "assent" in d.documents
        assert "samples_annex" not in d.documents

    def test_samples_without_minors(self):
        p = _minimal_profile(has_biological_samples=True)
        d = generate_dossier(p)
        assert "samples_annex" in d.documents
        assert "assent" not in d.documents

    def test_minimal_profile_all_docs_non_empty(self):
        p = _minimal_profile()
        d = generate_dossier(p)
        for name, content in d.documents.items():
            assert len(content) > 100, f"Document '{name}' is too short"

    def test_document_names_method(self):
        p = _full_observational_profile()
        d = generate_dossier(p)
        assert d.document_names() == list(d.documents.keys())

    def test_profile_preserved(self):
        p = _full_observational_profile()
        d = generate_dossier(p)
        assert d.profile is p
        assert d.profile.title == p.title


# ---------------------------------------------------------------------------
# Tests — write_dossier
# ---------------------------------------------------------------------------

class TestWriteDossier:
    def test_writes_all_files(self):
        p = _mixed_profile_with_minors_and_samples()
        d = generate_dossier(p)
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = write_dossier(d, Path(tmpdir))
            assert len(paths) == 6
            for name, path in paths.items():
                assert path.exists(), f"File for '{name}' not created"
                content = path.read_text(encoding="utf-8")
                assert len(content) > 100

    def test_file_naming_convention(self):
        p = _full_observational_profile()
        d = generate_dossier(p)
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = write_dossier(d, Path(tmpdir))
            filenames = [p.name for p in paths.values()]
            assert "01_protocolo.md" in filenames
            assert "02_hoja_informacion_paciente.md" in filenames
            assert "03_consentimiento_informado.md" in filenames
            assert "05_proteccion_datos.md" in filenames

    def test_creates_output_dir(self):
        p = _minimal_profile()
        d = generate_dossier(p)
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = Path(tmpdir) / "subdir" / "nested"
            paths = write_dossier(d, new_dir)
            assert new_dir.exists()
            assert len(paths) == 4

    def test_content_matches_generate(self):
        p = _full_observational_profile()
        d = generate_dossier(p)
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = write_dossier(d, Path(tmpdir))
            for name, path in paths.items():
                written = path.read_text(encoding="utf-8")
                assert written == d.documents[name]


# ---------------------------------------------------------------------------
# Tests — cross-document consistency
# ---------------------------------------------------------------------------

class TestCrossDocumentConsistency:
    def test_title_consistent_across_docs(self):
        p = _full_observational_profile()
        d = generate_dossier(p)
        for name, content in d.documents.items():
            assert p.title in content or _PH in content, \
                f"Title missing from {name}"

    def test_version_consistent_across_docs(self):
        p = _full_observational_profile()
        d = generate_dossier(p)
        for name, content in d.documents.items():
            assert p.version in content, f"Version missing from {name}"

    def test_ci_references_hip_version(self):
        p = _full_observational_profile()
        d = generate_dossier(p)
        ci = d.documents["ci"]
        assert p.version in ci
        assert "Hoja de Información" in ci

    def test_hip_and_ci_data_protection_aligned(self):
        p = _full_observational_profile()
        d = generate_dossier(p)
        hip = d.documents["hip"]
        dp = d.documents["data_protection"]
        # Both reference same legal basis
        assert p.legal_basis in hip
        assert p.legal_basis in dp

    def test_all_docs_have_footer(self):
        p = _mixed_profile_with_minors_and_samples()
        d = generate_dossier(p)
        for name, content in d.documents.items():
            assert "ResearchClaw" in content, f"Footer missing from {name}"


# ---------------------------------------------------------------------------
# Tests — edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_profile_does_not_crash(self):
        p = StudyProfile()
        d = generate_dossier(p)
        assert len(d.documents) == 4
        for content in d.documents.values():
            assert isinstance(content, str)
            assert len(content) > 50

    def test_unknown_study_type(self):
        p = StudyProfile(study_type=StudyType.UNKNOWN, title="Unknown Study")
        d = generate_dossier(p)
        protocol = d.documents["protocol"]
        assert _PH in protocol  # type label placeholder
        # Should still generate intervention/variables sections
        assert "Variables" in protocol

    def test_all_optional_features_enabled(self):
        """Stress test: enable every optional feature."""
        p = StudyProfile(
            title="Everything Study",
            study_type=StudyType.MIXED,
            has_minors=True,
            has_vulnerable=True,
            has_biological_samples=True,
            sample_types=["Sangre", "Saliva"],
            has_ai_component=True,
            has_sensitive_data=True,
            has_international_transfer=True,
            has_compensation=True,
            has_insurance=True,
        )
        d = generate_dossier(p)
        assert len(d.documents) == 6
        # Protocol should have both annexes
        protocol = d.documents["protocol"]
        assert "Anexo A" in protocol
        assert "Anexo B" in protocol

    def test_very_long_lists(self):
        """Ensure long lists don't break formatting."""
        p = StudyProfile(
            inclusion_criteria=[f"Criterion {i}" for i in range(20)],
            known_risks=[f"Risk {i}" for i in range(15)],
        )
        d = generate_dossier(p)
        protocol = d.documents["protocol"]
        assert "Criterion 19" in protocol
        hip = d.documents["hip"]
        assert "Risk 14" in hip
