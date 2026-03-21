"""Protocol Registry — structured metadata for all ResearchClaw protocols.

Provides a single source of truth for protocol enumeration, classification,
capabilities, and maturity.  This is a **descriptive catalogue** — it does NOT
replicate the runtime detection logic in ``pipeline/protocol.py``, but can be
cross-referenced with it.

Design goals
------------
* Enumerate every protocol available in ``protocols/``
* Describe inputs, outputs, flags, and constraints per protocol
* Classify by family (research, clinical, dissemination, ethics)
* Track implementation maturity (from spec-only to production)
* Prepare the ground for UI integration and pipeline routing

Usage::

    from researchclaw.protocol_registry import REGISTRY, get_protocol, list_protocols
    for p in list_protocols():
        print(f"{p.id}: {p.name} [{p.family.value}] — {p.maturity.value}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ProtocolFamily(str, Enum):
    """Broad classification of protocol purpose."""

    RESEARCH = "research"
    """Literature reviews, systematic reviews, meta-analysis."""

    CLINICAL = "clinical"
    """Clinical consultations, safety profiling, case reports."""

    DISSEMINATION = "dissemination"
    """Posters, presentations, abstracts, patient communication."""

    ETHICS = "ethics"
    """Ethics committee review, dossier generation, regulatory."""


class Maturity(str, Enum):
    """Implementation maturity level."""

    SPEC = "spec"
    """Protocol file exists but no dedicated code integration."""

    MVP = "mvp"
    """Functional implementation exists; tested but may have gaps."""

    STABLE = "stable"
    """Production-ready with full tests and UI integration."""


class IOType(str, Enum):
    """Types of inputs and outputs."""

    TEXT = "text"
    """Free-form text (topic, question, protocol content)."""

    MARKDOWN = "markdown"
    """Structured Markdown document."""

    FILE_UPLOAD = "file_upload"
    """Uploaded file(s) — PDF, DOCX, etc."""

    STRUCTURED_FORM = "structured_form"
    """Structured input via form fields (StudyProfile, etc.)."""

    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    HTML = "html"


# ---------------------------------------------------------------------------
# Protocol descriptor
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProtocolDescriptor:
    """Immutable metadata describing a single protocol."""

    # Identity
    id: str
    """Unique snake_case identifier (e.g. 'revision_sistematica_prisma')."""

    name: str
    """Human-readable display name."""

    name_en: str = ""
    """English display name (optional)."""

    family: ProtocolFamily = ProtocolFamily.RESEARCH
    """Broad classification."""

    description: str = ""
    """One-line description of what this protocol does."""

    # File reference
    filename: str = ""
    """Corresponding file in protocols/ (e.g. 'Revision_Sistematica_PRISMA.md')."""

    # I/O specification
    inputs: tuple[IOType, ...] = (IOType.TEXT,)
    """Required input types."""

    outputs: tuple[IOType, ...] = (IOType.MARKDOWN,)
    """Produced output types."""

    # Capabilities and flags
    requires_llm: bool = True
    """Whether this protocol needs an LLM to execute."""

    requires_search: bool = True
    """Whether this protocol triggers external literature search."""

    has_dedicated_generator: bool = False
    """Whether a dedicated Python module exists (beyond pipeline)."""

    generator_module: str = ""
    """Dotted path to the generator module, if any."""

    has_review_component: bool = False
    """Whether a structured review/check module exists."""

    review_module: str = ""
    """Dotted path to the review module, if any."""

    # Study-type flags (primarily for ethics protocols)
    supports_observational: bool = False
    supports_qualitative: bool = False
    supports_mixed: bool = False
    supports_minors: bool = False
    supports_biological_samples: bool = False
    supports_ai_component: bool = False

    # Pipeline interaction
    pipeline_profile: str = ""
    """Corresponding ProtocolProfile value in pipeline/protocol.py, if any."""

    skips_experiment_stages: bool = False
    """Whether this protocol skips pipeline stages 9-15."""

    # UI interaction
    has_ui_panel: bool = False
    """Whether a dedicated UI panel exists in web_ui.py."""

    ui_panel_id: str = ""
    """Identifier for the UI panel (for routing)."""

    # Maturity
    maturity: Maturity = Maturity.SPEC
    """Current implementation maturity."""

    # Tags for filtering
    tags: tuple[str, ...] = ()
    """Free-form tags for filtering and grouping."""


# ---------------------------------------------------------------------------
# Registry — single source of truth
# ---------------------------------------------------------------------------

REGISTRY: tuple[ProtocolDescriptor, ...] = (
    # ── Research protocols ─────────────────────────────────────────────────
    ProtocolDescriptor(
        id="revision_sistematica_prisma",
        name="Revisión Sistemática PRISMA",
        name_en="PRISMA Systematic Review",
        family=ProtocolFamily.RESEARCH,
        description="Revisión sistemática siguiendo PRISMA 2020 con búsqueda multi-fuente.",
        filename="Revision_Sistematica_PRISMA.md",
        inputs=(IOType.TEXT,),
        outputs=(IOType.MARKDOWN, IOType.PDF, IOType.DOCX),
        requires_llm=True,
        requires_search=True,
        pipeline_profile="systematic_review_prisma",
        skips_experiment_stages=True,
        maturity=Maturity.STABLE,
        tags=("prisma", "bibliographic", "evidence-synthesis"),
    ),
    ProtocolDescriptor(
        id="analisis_rapido",
        name="Análisis Rápido de Evidencia",
        name_en="Rapid Evidence Review",
        family=ProtocolFamily.RESEARCH,
        description="Revisión rápida de alta densidad para consulta clínica urgente.",
        filename="Analisis_Rapido.md",
        inputs=(IOType.TEXT,),
        outputs=(IOType.MARKDOWN, IOType.PDF, IOType.DOCX),
        requires_llm=True,
        requires_search=True,
        pipeline_profile="narrative_review",
        skips_experiment_stages=True,
        maturity=Maturity.SPEC,
        tags=("rapid", "bibliographic", "clinical-query"),
    ),
    ProtocolDescriptor(
        id="seguridad_toxicidad",
        name="Seguridad y Toxicidad",
        name_en="Safety & Toxicity Profiling",
        family=ProtocolFamily.CLINICAL,
        description="Perfil de farmacovigilancia y seguridad de fármacos.",
        filename="Seguridad_y_Toxicidad.md",
        inputs=(IOType.TEXT,),
        outputs=(IOType.MARKDOWN, IOType.PDF, IOType.DOCX),
        requires_llm=True,
        requires_search=True,
        maturity=Maturity.SPEC,
        tags=("pharmacovigilance", "safety", "clinical"),
    ),

    # ── Clinical protocols ─────────────────────────────────────────────────
    ProtocolDescriptor(
        id="consulta_clinica_pico",
        name="Consulta Clínica PICO",
        name_en="PICO Clinical Consultation",
        family=ProtocolFamily.CLINICAL,
        description="Consulta clínica estructurada con metodología PICO.",
        filename="Consulta_Clinica_PICO.md",
        inputs=(IOType.TEXT,),
        outputs=(IOType.MARKDOWN,),
        requires_llm=True,
        requires_search=True,
        maturity=Maturity.SPEC,
        tags=("pico", "clinical-query", "evidence-based"),
    ),
    ProtocolDescriptor(
        id="reporte_caso_care",
        name="Reporte de Caso CARE",
        name_en="CARE Case Report",
        family=ProtocolFamily.CLINICAL,
        description="Reporte de caso clínico siguiendo las directrices CARE 2013.",
        filename="Reporte_Caso_CARE.md",
        inputs=(IOType.TEXT, IOType.FILE_UPLOAD),
        outputs=(IOType.MARKDOWN, IOType.PDF, IOType.DOCX),
        requires_llm=True,
        requires_search=True,
        maturity=Maturity.SPEC,
        tags=("case-report", "care", "clinical"),
    ),

    # ── Dissemination protocols ────────────────────────────────────────────
    ProtocolDescriptor(
        id="articulo_revista_imrad",
        name="Artículo de Revista (IMRaD)",
        name_en="Journal Article (IMRaD)",
        family=ProtocolFamily.DISSEMINATION,
        description="Artículo científico con estructura IMRaD para publicación en revistas.",
        filename="Articulo_Revista_IMRaD.md",
        inputs=(IOType.TEXT, IOType.FILE_UPLOAD),
        outputs=(IOType.MARKDOWN, IOType.PDF, IOType.DOCX),
        requires_llm=True,
        requires_search=True,
        maturity=Maturity.SPEC,
        tags=("imrad", "journal", "publication"),
    ),
    ProtocolDescriptor(
        id="resumen_congreso",
        name="Resumen de Congreso",
        name_en="Conference Abstract",
        family=ProtocolFamily.DISSEMINATION,
        description="Abstract estructurado para congresos (300 palabras, 5 secciones).",
        filename="Resumen_Congreso.md",
        inputs=(IOType.TEXT, IOType.FILE_UPLOAD),
        outputs=(IOType.MARKDOWN,),
        requires_llm=False,
        requires_search=False,
        has_dedicated_generator=True,
        generator_module="researchclaw.abstract_generator",
        maturity=Maturity.MVP,
        tags=("abstract", "congress", "dissemination"),
    ),
    ProtocolDescriptor(
        id="poster_congreso",
        name="Póster de Congreso",
        name_en="Conference Poster",
        family=ProtocolFamily.DISSEMINATION,
        description="Póster A0 de 3 columnas para presentación en congresos.",
        filename="Poster_Congreso.md",
        inputs=(IOType.TEXT, IOType.FILE_UPLOAD),
        outputs=(IOType.MARKDOWN, IOType.PPTX),
        requires_llm=False,
        requires_search=False,
        has_dedicated_generator=True,
        generator_module="researchclaw.poster_generator",
        has_ui_panel=True,
        ui_panel_id="poster_logo_panel",
        pipeline_profile="poster_only",
        skips_experiment_stages=True,
        maturity=Maturity.MVP,
        tags=("poster", "congress", "visual"),
    ),
    ProtocolDescriptor(
        id="presentacion_powerpoint",
        name="Presentación PowerPoint",
        name_en="PowerPoint Presentation",
        family=ProtocolFamily.DISSEMINATION,
        description="Presentación de 10-12 diapositivas para conferencia (10-15 min).",
        filename="Presentacion_PowerPoint.md",
        inputs=(IOType.TEXT,),
        outputs=(IOType.PPTX,),
        requires_llm=True,
        requires_search=True,
        has_dedicated_generator=True,
        generator_module="researchclaw.pptx_generator",
        has_ui_panel=True,
        ui_panel_id="pptx_panel",
        maturity=Maturity.MVP,
        tags=("slides", "presentation", "dissemination"),
    ),
    ProtocolDescriptor(
        id="divulgacion_familias",
        name="Divulgación para Familias",
        name_en="Patient & Family Communication",
        family=ProtocolFamily.DISSEMINATION,
        description="Comunicación médica en lenguaje accesible para pacientes y familias.",
        filename="Divulgacion_Familias.md",
        inputs=(IOType.TEXT,),
        outputs=(IOType.MARKDOWN, IOType.PDF),
        requires_llm=True,
        requires_search=True,
        maturity=Maturity.SPEC,
        tags=("patient-education", "plain-language", "dissemination"),
    ),

    # ── Ethics protocols ───────────────────────────────────────────────────
    ProtocolDescriptor(
        id="auditoria_ceim",
        name="Auditoría CEIm",
        name_en="CEIm Ethics Audit",
        family=ProtocolFamily.ETHICS,
        description="Evaluación ética y metodológica de protocolos para comités de ética.",
        filename="Auditoria_Protocolo_CEIm.md",
        inputs=(IOType.TEXT, IOType.FILE_UPLOAD),
        outputs=(IOType.MARKDOWN,),
        requires_llm=False,
        requires_search=False,
        has_dedicated_generator=False,
        has_review_component=True,
        review_module="researchclaw.ceim_reviewer",
        has_ui_panel=True,
        ui_panel_id="ceim_section",
        supports_observational=True,
        supports_qualitative=True,
        supports_mixed=True,
        maturity=Maturity.MVP,
        tags=("ceim", "ethics", "review", "audit"),
    ),
    ProtocolDescriptor(
        id="dossier_ceim",
        name="Dossier Generator CEIm",
        name_en="CEIm Dossier Generator",
        family=ProtocolFamily.ETHICS,
        description="Generador de borradores de dossier completo para comité de ética.",
        inputs=(IOType.STRUCTURED_FORM,),
        outputs=(IOType.MARKDOWN,),
        requires_llm=False,
        requires_search=False,
        has_dedicated_generator=True,
        generator_module="researchclaw.ceim_dossier",
        has_ui_panel=True,
        ui_panel_id="ceim_section",
        supports_observational=True,
        supports_qualitative=True,
        supports_mixed=True,
        supports_minors=True,
        supports_biological_samples=True,
        supports_ai_component=True,
        maturity=Maturity.MVP,
        tags=("ceim", "ethics", "dossier", "regulatory"),
    ),
)

# Indexing
_BY_ID: dict[str, ProtocolDescriptor] = {p.id: p for p in REGISTRY}
_BY_FILENAME: dict[str, ProtocolDescriptor] = {
    p.filename: p for p in REGISTRY if p.filename
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_protocol(protocol_id: str) -> ProtocolDescriptor | None:
    """Look up a protocol by its unique ID."""
    return _BY_ID.get(protocol_id)


def get_by_filename(filename: str) -> ProtocolDescriptor | None:
    """Look up a protocol by its filename in protocols/."""
    return _BY_FILENAME.get(filename)


def list_protocols(
    *,
    family: ProtocolFamily | None = None,
    maturity: Maturity | None = None,
    tag: str | None = None,
    requires_llm: bool | None = None,
) -> list[ProtocolDescriptor]:
    """List protocols with optional filters.

    All filters are AND-combined.
    """
    result = list(REGISTRY)
    if family is not None:
        result = [p for p in result if p.family == family]
    if maturity is not None:
        result = [p for p in result if p.maturity == maturity]
    if tag is not None:
        result = [p for p in result if tag in p.tags]
    if requires_llm is not None:
        result = [p for p in result if p.requires_llm == requires_llm]
    return result


def list_families() -> list[ProtocolFamily]:
    """Return all families that have at least one registered protocol."""
    return sorted(
        {p.family for p in REGISTRY},
        key=lambda f: f.value,
    )


def protocols_by_family() -> dict[ProtocolFamily, list[ProtocolDescriptor]]:
    """Group protocols by family."""
    result: dict[ProtocolFamily, list[ProtocolDescriptor]] = {}
    for p in REGISTRY:
        result.setdefault(p.family, []).append(p)
    return result


def protocol_ids() -> list[str]:
    """Return all registered protocol IDs."""
    return [p.id for p in REGISTRY]


def filenames() -> list[str]:
    """Return filenames of all protocols that have a file reference."""
    return [p.filename for p in REGISTRY if p.filename]


def summary_table() -> str:
    """Return a Markdown table summarising all protocols."""
    lines = [
        "| ID | Nombre | Familia | LLM | Madurez | Generador | Review |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in REGISTRY:
        gen = "✅" if p.has_dedicated_generator else "—"
        rev = "✅" if p.has_review_component else "—"
        llm = "Sí" if p.requires_llm else "No"
        lines.append(
            f"| `{p.id}` | {p.name} | {p.family.value} | {llm} | "
            f"{p.maturity.value} | {gen} | {rev} |"
        )
    return "\n".join(lines)
