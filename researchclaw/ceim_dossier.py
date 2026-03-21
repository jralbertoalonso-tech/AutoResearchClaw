"""CEIm dossier generator — structured draft production for ethics committee submissions.

Generates structured Markdown drafts of the full CEIm dossier based on a
``StudyProfile`` input and the official CEIm template structure from
``protocols/Auditoria_Protocolo_CEIm.md``.

Documents produced:
1. **Protocol / Project** — study protocol following EOm template
2. **HIP** — Patient Information Sheet
3. **CI** — Informed Consent document
4. **Assent (12-17)** — if minors are involved
5. **Data Protection appendix** — RGPD / LOPDGDD section
6. **Biological samples annex** — if applicable
7. **AI addendum** — if AI/ML component present

Each document adapts its content based on study type (observational,
qualitative, mixed), population flags (minors, vulnerable), and
optional features (biological samples, AI, sensitive data).

No LLM required — pure template-filling with structured placeholders.

Usage::

    from researchclaw.ceim_dossier import generate_dossier, StudyProfile
    profile = StudyProfile(
        title="My Study Title",
        pi_name="Dr. García",
        ...
    )
    dossier = generate_dossier(profile)
    # dossier.documents is a dict[str, str] of Markdown texts
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from researchclaw.ceim_reviewer import StudyType


# ---------------------------------------------------------------------------
# Study profile — input dataclass
# ---------------------------------------------------------------------------

@dataclass
class StudyProfile:
    """Structured input describing the study for dossier generation."""

    # Identification
    title: str = ""
    protocol_code: str = ""
    version: str = "1.0"
    version_date: str = ""
    sponsor: str = ""
    pi_name: str = ""
    pi_contact: str = ""
    institution: str = ""
    ceim_name: str = ""
    ceim_contact: str = ""

    # Study design
    study_type: StudyType = StudyType.OBSERVATIONAL
    design_description: str = ""
    primary_objective: str = ""
    secondary_objectives: list[str] = field(default_factory=list)
    justification: str = ""
    hypothesis: str = ""
    duration_months: int = 0
    registry: str = ""  # ClinicalTrials.gov, PROSPERO, etc.

    # Population
    target_population: str = ""
    age_range: str = ""
    estimated_sample_size: int = 0
    inclusion_criteria: list[str] = field(default_factory=list)
    exclusion_criteria: list[str] = field(default_factory=list)
    has_minors: bool = False
    has_vulnerable: bool = False
    minor_age_range: str = "12-17"

    # Methodology
    intervention_description: str = ""
    variables_primary: str = ""
    variables_secondary: str = ""
    statistical_plan: str = ""
    sample_size_justification: str = ""

    # Qualitative-specific
    qualitative_method: str = ""  # phenomenology, grounded theory, etc.
    data_collection_techniques: list[str] = field(default_factory=list)
    analysis_approach: str = ""

    # Safety
    known_risks: list[str] = field(default_factory=list)
    expected_benefits: list[str] = field(default_factory=list)
    mitigation_measures: list[str] = field(default_factory=list)

    # Data protection
    data_controller: str = ""
    legal_basis: str = "Art. 9.2.j RGPD (investigación en interés público)"
    data_retention_years: int = 15
    has_international_transfer: bool = False
    transfer_mechanism: str = ""  # SCC, BCR, etc.
    has_sensitive_data: bool = False

    # Optional features
    has_biological_samples: bool = False
    sample_types: list[str] = field(default_factory=list)
    biobank_name: str = ""
    sample_storage_years: int = 0

    has_ai_component: bool = False
    ai_model_description: str = ""
    ai_training_data: str = ""
    ai_validation_plan: str = ""
    ai_risk_classification: str = ""  # high/limited/minimal per EU AI Act

    # Financial
    has_compensation: bool = False
    compensation_description: str = ""
    funding_source: str = ""
    has_insurance: bool = False
    insurance_reference: str = ""

    def effective_date(self) -> str:
        return self.version_date or datetime.date.today().isoformat()


# ---------------------------------------------------------------------------
# Placeholder formatter
# ---------------------------------------------------------------------------

_PH = "[COMPLETAR]"


def _ph(value: str) -> str:
    """Return value or placeholder if empty."""
    return value.strip() if value and value.strip() else _PH


def _list_or_ph(items: list[str], numbered: bool = True) -> str:
    """Format a list or return placeholder."""
    if not items:
        return f"1. {_PH}\n2. {_PH}\n" if numbered else f"- {_PH}\n"
    lines = []
    for i, item in enumerate(items, 1):
        prefix = f"{i}." if numbered else "-"
        lines.append(f"{prefix} {item}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Document generators
# ---------------------------------------------------------------------------

def _generate_protocol(p: StudyProfile) -> str:
    """Generate the study protocol/project document."""
    lines = [
        f"# Protocolo del Estudio: {_ph(p.title)}",
        "",
        f"**Código de protocolo**: {_ph(p.protocol_code)}",
        f"**Versión**: {_ph(p.version)} — Fecha: {p.effective_date()}",
        f"**Promotor**: {_ph(p.sponsor)}",
        f"**Investigador principal**: {_ph(p.pi_name)}",
        f"**Centro**: {_ph(p.institution)}",
        "",
        "---",
        "",
        "## 1. Información General",
        "",
        f"- **Título completo**: {_ph(p.title)}",
        f"- **Código de protocolo**: {_ph(p.protocol_code)}",
        f"- **Versión / Fecha**: {_ph(p.version)} / {p.effective_date()}",
        f"- **Promotor**: {_ph(p.sponsor)}",
        f"- **Investigador principal**: {_ph(p.pi_name)}",
        f"- **Centro(s) participante(s)**: {_ph(p.institution)}",
        f"- **Registro**: {_ph(p.registry)}",
        "",
        "## 2. Justificación y Necesidad Clínica",
        "",
        _ph(p.justification),
        "",
        f"**Hipótesis**: {_ph(p.hypothesis)}",
        "",
        "## 3. Objetivos",
        "",
        f"### Objetivo primario",
        f"{_ph(p.primary_objective)}",
        "",
        "### Objetivos secundarios",
        _list_or_ph(p.secondary_objectives),
        "",
        "## 4. Diseño del Estudio",
        "",
    ]

    # Adapt design section by study type
    type_labels = {
        StudyType.OBSERVATIONAL: "Observacional / Biomédico",
        StudyType.QUALITATIVE: "Cualitativo",
        StudyType.MIXED: "Mixto (cuantitativo + cualitativo)",
        StudyType.UNKNOWN: _PH,
    }
    lines.append(f"**Tipo de estudio**: {type_labels.get(p.study_type, _PH)}")
    lines.append("")
    lines.append(_ph(p.design_description))
    lines.append("")

    if p.study_type == StudyType.QUALITATIVE:
        lines += [
            f"**Método cualitativo**: {_ph(p.qualitative_method)}",
            f"**Paradigma epistemológico**: {_PH}",
            "",
            "### Técnicas de recogida de datos",
            _list_or_ph(p.data_collection_techniques, numbered=False),
            "",
            f"### Estrategia de análisis",
            f"{_ph(p.analysis_approach)}",
            "",
        ]
    elif p.study_type == StudyType.MIXED:
        lines += [
            "### Componente cuantitativo",
            f"{_ph(p.design_description)}",
            "",
            "### Componente cualitativo",
            f"**Método**: {_ph(p.qualitative_method)}",
            f"**Técnicas**: {_list_or_ph(p.data_collection_techniques, numbered=False)}",
            "",
        ]

    lines += [
        "## 5. Selección de Participantes",
        "",
        f"**Población diana**: {_ph(p.target_population)}",
        f"**Rango de edad**: {_ph(p.age_range)}",
        f"**Tamaño muestral estimado**: {p.estimated_sample_size or _PH}",
        "",
    ]

    if p.study_type != StudyType.QUALITATIVE:
        lines += [
            f"**Justificación del tamaño muestral**: {_ph(p.sample_size_justification)}",
            "",
        ]
    else:
        lines += [
            "**Criterio de saturación**: Se continuará el reclutamiento hasta "
            "alcanzar la saturación teórica de los datos.",
            "",
        ]

    lines += [
        "### Criterios de inclusión",
        _list_or_ph(p.inclusion_criteria),
        "",
        "### Criterios de exclusión",
        _list_or_ph(p.exclusion_criteria),
        "",
    ]

    # Methodology section
    if p.study_type in (StudyType.OBSERVATIONAL, StudyType.MIXED, StudyType.UNKNOWN):
        lines += [
            "## 6. Intervención / Procedimientos",
            "",
            _ph(p.intervention_description),
            "",
            "## 7. Variables",
            "",
            f"**Variable principal**: {_ph(p.variables_primary)}",
            f"**Variables secundarias**: {_ph(p.variables_secondary)}",
            "",
            "## 8. Plan de Análisis Estadístico",
            "",
            _ph(p.statistical_plan),
            "",
        ]
    else:
        lines += [
            "## 6. Procedimiento de Recogida de Datos",
            "",
            _list_or_ph(p.data_collection_techniques, numbered=False),
            "",
            "## 7. Plan de Análisis Cualitativo",
            "",
            _ph(p.analysis_approach),
            "",
            "### Rigor y calidad",
            "",
            "- **Triangulación**: " + _PH,
            "- **Verificación por participantes (member checking)**: " + _PH,
            "- **Reflexividad del investigador**: " + _PH,
            "- **Auditoría de análisis (audit trail)**: " + _PH,
            "",
        ]

    # Safety
    lines += [
        "## 9. Seguridad — Balance Riesgo-Beneficio",
        "",
        "### Riesgos previsibles",
        _list_or_ph(p.known_risks, numbered=False),
        "",
        "### Beneficios esperados",
        _list_or_ph(p.expected_benefits, numbered=False),
        "",
        "### Medidas de minimización del riesgo",
        _list_or_ph(p.mitigation_measures, numbered=False),
        "",
    ]

    if p.study_type in (StudyType.OBSERVATIONAL, StudyType.MIXED, StudyType.UNKNOWN):
        lines += [
            "### Plan de notificación de eventos adversos",
            "",
            f"- **Definición de SAE**: {_PH}",
            "- **Plazo de reporte al CEIm**: Eventos graves en ≤7 días; "
            "otros en ≤15 días",
            f"- **Responsable del reporte**: {_ph(p.pi_name)}",
            f"- **DSMB**: {_PH}",
            "",
        ]

    # Data protection
    lines += [
        "## 10. Protección de Datos",
        "",
        f"- **Responsable del tratamiento**: {_ph(p.data_controller)}",
        f"- **Base legal**: {p.legal_basis}",
        f"- **Periodo de conservación**: {p.data_retention_years} años",
        "- **Derechos ARCO+**: Los participantes podrán ejercer sus "
        "derechos de acceso, rectificación, cancelación, oposición, "
        "limitación y portabilidad ante el responsable del tratamiento.",
        "",
    ]

    if p.has_international_transfer:
        lines += [
            f"- **Transferencia internacional**: Sí — mecanismo: {_ph(p.transfer_mechanism)}",
            "",
        ]

    if p.has_sensitive_data:
        lines += [
            "- **Datos especialmente protegidos**: Sí — se aplican medidas "
            "de seguridad reforzadas conforme al art. 9 RGPD.",
            "",
        ]

    # Ethics
    lines += [
        "## 11. Aspectos Éticos y Legales",
        "",
        "- El estudio se llevará a cabo conforme a la **Declaración de Helsinki** "
        "(última revisión), el **Informe Belmont**, las **ICH E6 GCP** "
        "y la legislación española vigente.",
        f"- **Seguro de responsabilidad civil**: {'Sí — ' + _ph(p.insurance_reference) if p.has_insurance else _PH}",
        f"- **Financiación**: {_ph(p.funding_source)}",
        "- **Conflictos de interés**: Los investigadores declaran "
        f"{'no tener' if not p.funding_source else _PH} conflictos de interés.",
        "",
        "## 12. Cronograma",
        "",
        f"**Duración estimada**: {p.duration_months or _PH} meses",
        "",
        "| Fase | Inicio | Fin |",
        "|------|--------|-----|",
        f"| Preparación y aprobación CEIm | {_PH} | {_PH} |",
        f"| Reclutamiento | {_PH} | {_PH} |",
        f"| Recogida de datos | {_PH} | {_PH} |",
        f"| Análisis | {_PH} | {_PH} |",
        f"| Publicación | {_PH} | {_PH} |",
        "",
        "## 13. Plan de Publicación",
        "",
        "Los resultados se publicarán independientemente de su dirección "
        "(positivos, negativos o no concluyentes). Se seguirá la política "
        "de autoría del ICMJE.",
        "",
    ]

    # Conditional appendices
    if p.has_biological_samples:
        lines += [
            "## Anexo A — Muestras Biológicas",
            "",
            f"- **Tipos de muestra**: {', '.join(p.sample_types) if p.sample_types else _PH}",
            f"- **Biobanco**: {_ph(p.biobank_name)}",
            f"- **Tiempo de almacenamiento**: {p.sample_storage_years or _PH} años",
            "- **Consentimiento específico**: Se solicitará autorización "
            "separada en el documento de CI.",
            "- **Destrucción**: Las muestras se destruirán al finalizar "
            "el periodo de almacenamiento o a solicitud del participante.",
            "",
        ]

    if p.has_ai_component:
        lines += [
            "## Anexo B — Componente de Inteligencia Artificial",
            "",
            f"- **Descripción del modelo**: {_ph(p.ai_model_description)}",
            f"- **Datos de entrenamiento**: {_ph(p.ai_training_data)}",
            f"- **Plan de validación**: {_ph(p.ai_validation_plan)}",
            f"- **Clasificación de riesgo (Reglamento IA UE)**: {_ph(p.ai_risk_classification)}",
            "- **Evaluación de sesgos**: " + _PH,
            "- **Explicabilidad (XAI)**: " + _PH,
            "- **Responsabilidad clínica**: " + _PH,
            "- **Plan de vigilancia post-implantación**: " + _PH,
            "",
        ]

    lines += [
        "---",
        "",
        "*Documento generado por ResearchClaw — CEIm Dossier Generator*",
    ]

    return "\n".join(lines)


def _generate_hip(p: StudyProfile) -> str:
    """Generate the Patient Information Sheet (HIP)."""
    lines = [
        f"# Hoja de Información al Paciente",
        "",
        f"**Título del estudio**: {_ph(p.title)}",
        f"**Código de protocolo**: {_ph(p.protocol_code)}",
        f"**Versión**: {_ph(p.version)} — Fecha: {p.effective_date()}",
        f"**Promotor**: {_ph(p.sponsor)}",
        "",
        "---",
        "",
        "## Naturaleza voluntaria de la participación",
        "",
        "Le invitamos a participar en un estudio de investigación. "
        "Antes de decidir si desea participar, es importante que entienda "
        "por qué se realiza este estudio y en qué consiste. Por favor, "
        "lea esta información con atención y pregunte todo lo que no "
        "entienda. **Su participación es completamente voluntaria**. "
        "Si decide no participar, o si decide retirarse más adelante, "
        "esto no afectará a su atención médica habitual.",
        "",
        "## Objetivo del estudio",
        "",
        _ph(p.primary_objective),
        "",
        "## Procedimientos del estudio",
        "",
    ]

    if p.study_type == StudyType.QUALITATIVE:
        lines += [
            "Si acepta participar, le pediremos que:",
            "",
        ]
        if p.data_collection_techniques:
            for technique in p.data_collection_techniques:
                lines.append(f"- Participe en {technique}")
        else:
            lines.append(f"- {_PH}")
        lines += [
            "",
            f"La duración estimada de su participación será de {_PH}.",
            "",
        ]
    else:
        lines += [
            "Si acepta participar, se le pedirá que:",
            "",
            _ph(p.intervention_description),
            "",
            f"La duración estimada de su participación será de "
            f"{p.duration_months or _PH} meses.",
            "",
        ]

    # Risks
    lines += [
        "## Riesgos y molestias",
        "",
    ]
    if p.known_risks:
        lines.append("Los riesgos conocidos de este estudio incluyen:")
        lines.append("")
        for risk in p.known_risks:
            lines.append(f"- {risk}")
    else:
        lines.append(f"Los riesgos conocidos incluyen: {_PH}")
    lines.append("")

    if p.mitigation_measures:
        lines.append("Para minimizar estos riesgos, se tomarán las siguientes medidas:")
        lines.append("")
        for m in p.mitigation_measures:
            lines.append(f"- {m}")
        lines.append("")

    # Benefits
    lines += [
        "## Beneficios esperados",
        "",
    ]
    if p.expected_benefits:
        for b in p.expected_benefits:
            lines.append(f"- {b}")
    else:
        lines.append(
            "Es posible que usted no obtenga un beneficio directo por "
            "participar en este estudio. Sin embargo, la información "
            "obtenida podría beneficiar a futuros pacientes."
        )
    lines.append("")

    # Alternatives
    lines += [
        "## Alternativas a la participación",
        "",
        "Si decide no participar, recibirá la atención médica habitual "
        "disponible para su condición. Su decisión no afectará en ningún "
        "caso a la calidad de su asistencia sanitaria.",
        "",
    ]

    # Data protection
    lines += [
        "## Confidencialidad y protección de datos",
        "",
        "Sus datos personales serán tratados conforme al **Reglamento General "
        "de Protección de Datos (RGPD)** y la **Ley Orgánica 3/2018 (LOPDGDD)**.",
        "",
        f"- **Responsable del tratamiento**: {_ph(p.data_controller)}",
        f"- **Base legal**: {p.legal_basis}",
        f"- **Periodo de conservación**: {p.data_retention_years} años",
        "- **Derechos**: Usted puede ejercer sus derechos de acceso, "
        "rectificación, supresión, oposición, limitación del tratamiento "
        "y portabilidad dirigiéndose al responsable del tratamiento.",
        "",
        "Sus datos serán codificados (seudonimizados) de forma que solo "
        "el equipo investigador podrá vincularlos con su identidad.",
        "",
    ]

    if p.has_international_transfer:
        lines += [
            "**Transferencia internacional de datos**: Sus datos podrán "
            f"ser transferidos fuera del EEE mediante {_ph(p.transfer_mechanism)}.",
            "",
        ]

    # Biological samples
    if p.has_biological_samples:
        lines += [
            "## Uso de muestras biológicas",
            "",
            "Para este estudio se le solicitará la obtención de las "
            "siguientes muestras:",
            "",
        ]
        if p.sample_types:
            for s in p.sample_types:
                lines.append(f"- {s}")
        else:
            lines.append(f"- {_PH}")
        lines += [
            "",
            f"Las muestras se conservarán en {_ph(p.biobank_name)} "
            f"durante un máximo de {p.sample_storage_years or _PH} años.",
            "Usted podrá solicitar la destrucción de sus muestras en "
            "cualquier momento.",
            "En el documento de consentimiento informado, se le pedirá "
            "autorización específica para el uso de sus muestras.",
            "",
        ]

    # Compensation
    lines += [
        "## Compensación económica",
        "",
    ]
    if p.has_compensation:
        lines.append(_ph(p.compensation_description))
    else:
        lines.append("No se prevé compensación económica por la participación en este estudio.")
    lines.append("")

    # Contact
    lines += [
        "## Contacto",
        "",
        "Para cualquier pregunta sobre el estudio, puede contactar con:",
        "",
        f"- **Investigador principal**: {_ph(p.pi_name)} — {_ph(p.pi_contact)}",
        f"- **Comité de Ética**: {_ph(p.ceim_name)} — {_ph(p.ceim_contact)}",
        "",
        f"**Duración del estudio**: {p.duration_months or _PH} meses",
        "",
        "---",
        "",
        "*Documento generado por ResearchClaw — CEIm Dossier Generator*",
    ]

    return "\n".join(lines)


def _generate_ci(p: StudyProfile) -> str:
    """Generate the Informed Consent document (CI)."""
    lines = [
        "# Documento de Consentimiento Informado",
        "",
        f"**Título del estudio**: {_ph(p.title)}",
        f"**Código de protocolo**: {_ph(p.protocol_code)}",
        f"**Versión**: {_ph(p.version)} — Fecha: {p.effective_date()}",
        "",
        "---",
        "",
        "Yo, _________________________________________________ (nombre y apellidos),",
        "",
        "Declaro que:",
        "",
        "1. He leído la Hoja de Información al Paciente "
        f"(versión {_ph(p.version)}, fecha {p.effective_date()}).",
        "2. He tenido oportunidad de hacer preguntas sobre el estudio "
        "y he recibido respuestas satisfactorias.",
        "3. Comprendo que mi participación es **voluntaria** y que puedo "
        "retirarme en cualquier momento, sin dar explicaciones y sin "
        "que esto afecte a mi atención médica.",
        "4. He sido informado/a de los riesgos y beneficios del estudio.",
        "5. Comprendo que mis datos serán tratados conforme al RGPD y la LOPDGDD.",
        "",
    ]

    # Biological samples checkbox
    if p.has_biological_samples:
        lines += [
            "---",
            "",
            "### Autorización para uso de muestras biológicas",
            "",
            "- [ ] **ACEPTO** que se obtengan y conserven muestras biológicas "
            f"({', '.join(p.sample_types) if p.sample_types else _PH}) "
            f"en {_ph(p.biobank_name)} durante un máximo de "
            f"{p.sample_storage_years or _PH} años para los fines "
            "descritos en la hoja de información.",
            "",
            "- [ ] **NO ACEPTO** la obtención y conservación de muestras biológicas.",
            "",
        ]

    # Data transfer checkbox
    if p.has_international_transfer:
        lines += [
            "---",
            "",
            "### Autorización para transferencia internacional de datos",
            "",
            "- [ ] **ACEPTO** que mis datos sean transferidos fuera del "
            f"Espacio Económico Europeo mediante {_ph(p.transfer_mechanism)}.",
            "",
            "- [ ] **NO ACEPTO** la transferencia internacional de mis datos.",
            "",
        ]

    # Signatures
    lines += [
        "---",
        "",
        "**CONSIENTO** participar en el estudio descrito.",
        "",
        "| | Participante | Investigador |",
        "|---|---|---|",
        "| **Nombre** | _________________ | _________________ |",
        f"| **Firma** | | |",
        "| **Fecha y hora** | ____/____/________ ____:____ | ____/____/________ ____:____ |",
        "",
    ]

    if p.has_vulnerable or p.has_minors:
        lines += [
            "---",
            "",
            "### Firma del representante legal / testigo",
            "",
            "| | Representante legal / Testigo |",
            "|---|---|",
            "| **Nombre** | _________________ |",
            "| **Relación** | _________________ |",
            "| **Firma** | |",
            "| **Fecha y hora** | ____/____/________ ____:____ |",
            "",
        ]

    lines += [
        "---",
        "",
        "> **Nota**: Este documento debe separarse de la Hoja de Información al "
        "Paciente. La firma del CI nunca debe estar en la misma página "
        "que el texto informativo.",
        "",
        "*Documento generado por ResearchClaw — CEIm Dossier Generator*",
    ]

    return "\n".join(lines)


def _generate_assent(p: StudyProfile) -> str:
    """Generate the Assent document for minors (12-17 years)."""
    lines = [
        f"# Documento de Asentimiento para Menores ({p.minor_age_range} años)",
        "",
        f"**Título del estudio**: {_ph(p.title)}",
        f"**Versión**: {_ph(p.version)} — Fecha: {p.effective_date()}",
        "",
        "---",
        "",
        "## Información para ti",
        "",
        "Te invitamos a participar en un estudio de investigación. "
        "Antes de decidir si quieres participar, queremos que entiendas "
        "de qué se trata. Puedes preguntar todo lo que quieras.",
        "",
        "### ¿De qué trata este estudio?",
        "",
        _ph(p.primary_objective),
        "",
        "### ¿Qué me van a pedir que haga?",
        "",
    ]

    if p.study_type == StudyType.QUALITATIVE:
        lines += [
            "Te pediremos que:",
            "",
        ]
        if p.data_collection_techniques:
            for t in p.data_collection_techniques:
                lines.append(f"- Participes en {t}")
        else:
            lines.append(f"- {_PH}")
        lines.append("")
    else:
        lines.append(_ph(p.intervention_description))
        lines.append("")

    lines += [
        "### ¿Hay algún riesgo?",
        "",
    ]
    if p.known_risks:
        for r in p.known_risks:
            lines.append(f"- {r}")
    else:
        lines.append(_PH)
    lines.append("")

    lines += [
        "### ¿Me va a servir de algo?",
        "",
    ]
    if p.expected_benefits:
        for b in p.expected_benefits:
            lines.append(f"- {b}")
    else:
        lines.append(
            "Puede que a ti no te ayude directamente, pero lo que "
            "aprendamos podría ayudar a otros chicos y chicas en el futuro."
        )
    lines.append("")

    lines += [
        "### ¿Y si no quiero participar?",
        "",
        "**No pasa nada**. Participar es totalmente voluntario. "
        "Si dices que sí ahora pero luego cambias de opinión, puedes "
        "dejarlo cuando quieras. Nadie se va a enfadar contigo y tu "
        "atención médica seguirá siendo la misma.",
        "",
        "### ¿Van a saber otros lo que yo diga?",
        "",
        "No. Todo lo que nos cuentes será **confidencial**. Solo el "
        "equipo de investigación podrá ver tus datos, y siempre se "
        "guardarán con un código, no con tu nombre.",
        "",
    ]

    if p.has_biological_samples:
        lines += [
            "### ¿Me van a sacar muestras?",
            "",
            "Sí, te pediremos:",
            "",
        ]
        if p.sample_types:
            for s in p.sample_types:
                lines.append(f"- {s}")
        else:
            lines.append(f"- {_PH}")
        lines += [
            "",
            "Si no quieres que se guarden tus muestras, puedes decirlo.",
            "",
        ]

    # Assent signature
    lines += [
        "---",
        "",
        "## Mi decisión",
        "",
        "He leído (o me han leído) esta información y he podido hacer preguntas.",
        "",
        "- [ ] **SÍ QUIERO** participar en este estudio.",
        "- [ ] **NO QUIERO** participar en este estudio.",
        "",
        "| | |",
        "|---|---|",
        "| **Mi nombre** | _________________ |",
        "| **Mi firma** | |",
        "| **Fecha** | ____/____/________ |",
        "",
        "---",
        "",
        "*Documento generado por ResearchClaw — CEIm Dossier Generator*",
    ]

    return "\n".join(lines)


def _generate_data_protection(p: StudyProfile) -> str:
    """Generate the Data Protection appendix (RGPD/LOPDGDD)."""
    # EIPD screening
    eipd_criteria = 0
    eipd_details = []
    if p.has_sensitive_data:
        eipd_criteria += 1
        eipd_details.append(
            "Tratamiento de datos de categorías especiales (art. 9 RGPD)"
        )
    if p.has_ai_component:
        eipd_criteria += 1
        eipd_details.append("Uso de nuevas tecnologías (IA/ML)")
    if p.has_vulnerable or p.has_minors:
        eipd_criteria += 1
        eipd_details.append("Datos de personas vulnerables/menores")
    if p.has_international_transfer:
        eipd_criteria += 1
        eipd_details.append("Transferencia internacional de datos")

    if eipd_criteria >= 3:
        eipd_result = "EIPD OBLIGATORIA"
        eipd_icon = "❌"
    elif eipd_criteria >= 1:
        eipd_result = "EIPD RECOMENDADA"
        eipd_icon = "⚠️"
    else:
        eipd_result = "No requiere EIPD"
        eipd_icon = "✅"

    lines = [
        "# Apéndice de Protección de Datos",
        "",
        f"**Estudio**: {_ph(p.title)}",
        f"**Versión**: {_ph(p.version)} — Fecha: {p.effective_date()}",
        "",
        "---",
        "",
        "## 1. Identificación del tratamiento",
        "",
        f"- **Responsable del tratamiento**: {_ph(p.data_controller)}",
        f"- **Delegado de Protección de Datos (DPO)**: {_PH}",
        f"- **Investigador principal**: {_ph(p.pi_name)}",
        f"- **Centro**: {_ph(p.institution)}",
        "",
        "## 2. Base legal del tratamiento",
        "",
        f"El tratamiento de datos personales se realiza al amparo del "
        f"**{p.legal_basis}**, en conjunción con la **Ley 14/2007 de "
        f"Investigación Biomédica** y la **LOPDGDD 3/2018**.",
        "",
        "## 3. Categorías de datos",
        "",
        "| Categoría | Descripción |",
        "|---|---|",
        "| Datos identificativos | Nombre, fecha de nacimiento, código de participante |",
        f"| Datos de salud | {'Sí — ' + _PH if p.has_sensitive_data else 'Datos clínicos relacionados con el estudio'} |",
    ]

    if p.has_biological_samples:
        lines.append(
            f"| Datos genéticos/biológicos | Derivados de muestras: "
            f"{', '.join(p.sample_types) if p.sample_types else _PH} |"
        )
    if p.has_ai_component:
        lines.append(
            "| Datos para IA/ML | Datos utilizados para entrenamiento "
            "o validación del modelo |"
        )
    lines.append("")

    lines += [
        "## 4. Seudonimización y seguridad",
        "",
        "Los datos se **seudonimizarán** mediante un código alfanumérico. "
        "El fichero de vinculación (código ↔ identidad) se almacenará "
        "en un sistema cifrado, accesible únicamente por el investigador "
        "principal.",
        "",
        "## 5. Periodo de conservación",
        "",
        f"Los datos se conservarán durante **{p.data_retention_years} años** "
        "tras la finalización del estudio, conforme a la legislación vigente.",
        "",
        "## 6. Derechos de los participantes (ARCO+)",
        "",
        "Los participantes podrán ejercer los siguientes derechos:",
        "",
        "- **Acceso**: Conocer qué datos se tratan.",
        "- **Rectificación**: Corregir datos inexactos.",
        "- **Supresión**: Solicitar la eliminación de sus datos.",
        "- **Oposición**: Oponerse al tratamiento.",
        "- **Limitación**: Restringir el tratamiento.",
        "- **Portabilidad**: Recibir sus datos en formato estructurado.",
        "",
        "Para ejercer estos derechos, contactar con: "
        f"{_ph(p.data_controller)}",
        "",
    ]

    if p.has_international_transfer:
        lines += [
            "## 7. Transferencia internacional de datos",
            "",
            f"Se prevé la transferencia de datos fuera del Espacio Económico "
            f"Europeo. El mecanismo de garantía es: **{_ph(p.transfer_mechanism)}**.",
            "",
        ]

    lines += [
        f"## {'7' if not p.has_international_transfer else '8'}. "
        "Cribado EIPD (Evaluación de Impacto en la Protección de Datos)",
        "",
        "| Criterio | Presente |",
        "|---|---|",
        f"| Datos sensibles a gran escala | {'Sí' if p.has_sensitive_data else 'No'} |",
        f"| Nuevas tecnologías (IA) | {'Sí' if p.has_ai_component else 'No'} |",
        f"| Personas vulnerables/menores | {'Sí' if (p.has_vulnerable or p.has_minors) else 'No'} |",
        f"| Transferencia internacional | {'Sí' if p.has_international_transfer else 'No'} |",
        f"| Perfilado sistemático | {_PH} |",
        f"| Combinación de bases de datos | {_PH} |",
        f"| Decisiones automatizadas | {'Sí — componente IA' if p.has_ai_component else 'No'} |",
        "",
        f"**Resultado**: {eipd_icon} **{eipd_result}**",
        "",
    ]
    if eipd_details:
        lines.append("Criterios presentes:")
        for d in eipd_details:
            lines.append(f"- {d}")
        lines.append("")

    lines += [
        "---",
        "",
        "*Documento generado por ResearchClaw — CEIm Dossier Generator*",
    ]

    return "\n".join(lines)


def _generate_samples_annex(p: StudyProfile) -> str:
    """Generate the Biological Samples annex."""
    lines = [
        "# Anexo de Muestras Biológicas",
        "",
        f"**Estudio**: {_ph(p.title)}",
        f"**Versión**: {_ph(p.version)} — Fecha: {p.effective_date()}",
        "",
        "---",
        "",
        "## 1. Tipos de muestras",
        "",
    ]
    if p.sample_types:
        for s in p.sample_types:
            lines.append(f"- {s}")
    else:
        lines.append(f"- {_PH}")
    lines.append("")

    lines += [
        "## 2. Finalidad",
        "",
        _PH,
        "",
        "## 3. Almacenamiento",
        "",
        f"- **Biobanco / instalación**: {_ph(p.biobank_name)}",
        f"- **Periodo de almacenamiento**: {p.sample_storage_years or _PH} años",
        "- **Condiciones**: " + _PH,
        "",
        "## 4. Consentimiento específico",
        "",
        "Se solicitará autorización específica mediante casilla separada "
        "en el documento de consentimiento informado. El participante "
        "podrá rechazar la obtención de muestras y seguir participando "
        "en el estudio si el diseño lo permite.",
        "",
        "## 5. Destrucción",
        "",
        "Las muestras se destruirán al finalizar el periodo de "
        "almacenamiento, o antes si el participante lo solicita. "
        "Se emitirá certificado de destrucción.",
        "",
        "## 6. Uso futuro",
        "",
        "Las muestras podrán ser utilizadas en investigaciones futuras "
        "relacionadas, siempre que cuenten con la aprobación del CEIm "
        "y el consentimiento del participante no lo excluya expresamente.",
        "",
        "---",
        "",
        "*Documento generado por ResearchClaw — CEIm Dossier Generator*",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dossier result
# ---------------------------------------------------------------------------

@dataclass
class CEImDossier:
    """Complete CEIm dossier output."""
    profile: StudyProfile
    documents: dict[str, str]

    def document_names(self) -> list[str]:
        return list(self.documents.keys())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_dossier(profile: StudyProfile) -> CEImDossier:
    """Generate the full CEIm dossier from a study profile.

    Returns a CEImDossier with all applicable documents.
    Only generates documents that apply to the study configuration.
    """
    docs: dict[str, str] = {}

    # Always generated
    docs["protocol"] = _generate_protocol(profile)
    docs["hip"] = _generate_hip(profile)
    docs["ci"] = _generate_ci(profile)
    docs["data_protection"] = _generate_data_protection(profile)

    # Conditional
    if profile.has_minors:
        docs["assent"] = _generate_assent(profile)
    if profile.has_biological_samples:
        docs["samples_annex"] = _generate_samples_annex(profile)

    return CEImDossier(profile=profile, documents=docs)


def write_dossier(dossier: CEImDossier, output_dir: Path) -> dict[str, Path]:
    """Write all dossier documents to a directory.

    Returns a mapping of document name → file path.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    filenames = {
        "protocol": "01_protocolo.md",
        "hip": "02_hoja_informacion_paciente.md",
        "ci": "03_consentimiento_informado.md",
        "assent": "04_asentimiento_menores.md",
        "data_protection": "05_proteccion_datos.md",
        "samples_annex": "06_anexo_muestras.md",
    }

    paths: dict[str, Path] = {}
    for doc_name, content in dossier.documents.items():
        fname = filenames.get(doc_name, f"{doc_name}.md")
        path = output_dir / fname
        path.write_text(content, encoding="utf-8")
        paths[doc_name] = path

    return paths
