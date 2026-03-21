"""CEIm-style structured review of research protocols and papers.

Generates a structured methodological and ethical evaluation inspired by
Spanish CEIm (Comité de Ética de la Investigación con Medicamentos)
review criteria, CASPe qualitative appraisal, and standard biomedical
research evaluation frameworks.

No LLM call required — pure extraction and rule-based assessment from
the protocol/paper Markdown text.

Adapts the review by study type:
- **observational / biomedical / EOm**: design, variables, sample size,
  bias, data protection, consent, safety
- **qualitative**: CASPe-inspired criteria — clarity, congruence,
  participant selection, reflexivity, rigour, transferability
- **mixed**: combines both frameworks

Usage:
    from researchclaw.ceim_reviewer import generate_ceim_review
    review = generate_ceim_review(protocol_md)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# Reuse proven extractors
from researchclaw.poster_generator import (
    _parse_sections,
    _extract_sentences,
)


# ---------------------------------------------------------------------------
# Study type classification
# ---------------------------------------------------------------------------

class StudyType(Enum):
    OBSERVATIONAL = "observational"
    QUALITATIVE = "qualitative"
    MIXED = "mixed"
    UNKNOWN = "unknown"


def _is_systematic_review(text: str) -> bool:
    """Detect if the text describes a systematic review or meta-analysis."""
    tl = text.lower()
    sr_keywords = [
        "systematic review", "revisión sistemática",
        "meta-analysis", "meta-análisis", "metaanálisis",
        "prisma", "prospero", "scoping review",
        "revisión de alcance",
    ]
    return sum(1 for k in sr_keywords if k in tl) >= 2


# Items not applicable to systematic reviews (no direct participants).
_SR_NA_ITEMS: frozenset[str] = frozenset([
    "B2",  # Sample size calculation — SR aggregates existing studies
    "B4",  # Safety/SAE plan — SR doesn't administer interventions
    "C1",  # Informed consent — no direct participants
    "C2",  # Patient information sheet — no direct participants
    "C3",  # Data protection RGPD — SR uses published aggregate data
    "C4",  # Liability insurance — no direct participants
    "D1",  # Monitoring / quality control of interventions
    "D2",  # Early stopping criteria
    "D4",  # Biological samples
])


_QUALITATIVE_KEYWORDS = frozenset([
    "cualitativ", "qualitative", "fenomenolog", "phenomenolog",
    "etnograf", "ethnograph", "grounded theory", "teoría fundamentada",
    "narrativ", "hermenéutic", "hermeneutic", "focus group",
    "grupo focal", "entrevista en profundidad", "in-depth interview",
    "análisis temático", "thematic analysis", "discourse analysis",
    "análisis del discurso", "investigación-acción", "action research",
    "estudio de caso cualitativo", "qualitative case study",
    "saturación", "saturation", "codificación", "coding",
    "muestreo intencional", "purposive sampling",
    "muestreo teórico", "theoretical sampling",
])

_OBSERVATIONAL_KEYWORDS = frozenset([
    "observacional", "observational", "ensayo", "trial", "rct",
    "randomized", "aleatoriz", "cohorte", "cohort", "caso-control",
    "case-control", "transversal", "cross-sectional", "meta-analy",
    "meta-análisis", "revisión sistemática", "systematic review",
    "biomédic", "biomedic", "eom", "medicamento", "drug",
    "intervención", "intervention", "placebo", "doble ciego",
    "double-blind", "tamaño muestral", "sample size",
    "variable primaria", "primary endpoint", "primary outcome",
    "incidencia", "incidence", "prevalencia", "prevalence",
    "odds ratio", "hazard ratio", "riesgo relativo",
    "regresión", "regression", "análisis de supervivencia",
    "survival analysis", "picos", "prisma", "strobe", "consort",
])


def classify_study_type(text: str) -> StudyType:
    """Classify the study type from protocol/paper text."""
    tl = text.lower()
    qual_hits = sum(1 for k in _QUALITATIVE_KEYWORDS if k in tl)
    obs_hits = sum(1 for k in _OBSERVATIONAL_KEYWORDS if k in tl)

    if qual_hits >= 3 and obs_hits >= 3:
        return StudyType.MIXED
    if qual_hits >= 2:
        return StudyType.QUALITATIVE
    if obs_hits >= 2:
        return StudyType.OBSERVATIONAL
    # Fallback: default to observational (most common)
    return StudyType.OBSERVATIONAL if obs_hits >= 1 else StudyType.UNKNOWN


# ---------------------------------------------------------------------------
# Section detection — map protocol headings to review slots
# ---------------------------------------------------------------------------

_SECTION_MAP: dict[str, frozenset[str]] = {
    "title": frozenset([
        "title", "título", "titulo",
    ]),
    "abstract": frozenset([
        "abstract", "resumen",
    ]),
    "justification": frozenset([
        "introduction", "introducción", "introduccion", "background",
        "antecedentes", "justificación", "justificacion", "justification",
        "rationale", "motivation", "knowledge gap", "state of the art",
        "estado del arte", "marco teórico", "theoretical framework",
    ]),
    "objectives": frozenset([
        "objective", "objetivos", "objetivo", "objectives", "purpose",
        "aim", "aims", "hipótesis", "hipotesis", "hypothesis",
        "research question", "pregunta de investigación",
    ]),
    "design": frozenset([
        "design", "diseño", "diseno", "study design", "diseño del estudio",
        "type of study", "tipo de estudio", "paradigm", "paradigma",
    ]),
    "population": frozenset([
        "population", "población", "poblacion", "participants",
        "participantes", "selection", "selección", "seleccion",
        "inclusion", "exclusion", "criteria", "criterios",
        "eligibility", "elegibilidad", "sample", "muestra",
        "recruitment", "reclutamiento",
    ]),
    "methods": frozenset([
        "method", "methods", "métodos", "metodos", "methodology",
        "metodología", "metodologia", "procedure", "procedimiento",
        "search strategy", "estrategia de búsqueda",
        "data collection", "recogida de datos", "recolección",
        "instruments", "instrumentos", "intervention", "intervención",
        "data extraction", "data analysis", "análisis",
        "statistical", "estadístic",
    ]),
    "qualitative_methods": frozenset([
        "qualitative method", "método cualitativo", "técnicas cualitativas",
        "entrevista", "interview", "focus group", "grupo focal",
        "observación participante", "participant observation",
        "análisis temático", "thematic analysis", "coding", "codificación",
        "reflexividad", "reflexivity", "rigour", "rigor", "trustworthiness",
        "credibilidad", "transferibilidad", "transferability",
        "dependabilidad", "confirmabilidad",
    ]),
    "results": frozenset([
        "results", "resultados", "hallazgos", "findings", "outcomes",
    ]),
    "discussion": frozenset([
        "discussion", "discusión", "discusion",
    ]),
    "limitations": frozenset([
        "limitation", "limitaciones", "limitación",
    ]),
    "conclusions": frozenset([
        "conclusion", "conclusions", "conclusión", "conclusiones",
    ]),
    "ethics": frozenset([
        "ethic", "étic", "etic",
        "comité de ética", "ethics committee", "ceim", "ceic",
        "declaración de helsinki", "helsinki", "belmont",
        "buenas prácticas clínicas", "gcp", "good clinical practice",
    ]),
    "data_protection": frozenset([
        "protección de datos", "data protection", "rgpd", "gdpr",
        "lopd", "confidencial", "confidentiality", "anonimiz",
        "anonymi", "pseudonimi", "seudonimi",
    ]),
    "consent": frozenset([
        "consentimiento informado", "informed consent",
        "hoja de información", "patient information",
        "asentimiento", "assent",
    ]),
    "samples": frozenset([
        "muestra biológica", "biological sample", "biobanco", "biobank",
        "tejido", "tissue", "sangre", "blood", "suero", "serum",
        "biopsia", "biopsy",
    ]),
    "safety": frozenset([
        "seguridad", "safety", "adverse", "adverso",
        "riesgo", "risk", "beneficio", "benefit",
        "evento adverso", "adverse event", "sae", "susar",
    ]),
    "references": frozenset([
        "reference", "referencias", "bibliograf",
    ]),
}


def _match_heading_to_review_slot(heading: str) -> str | None:
    """Return the review slot name for a protocol heading, or None."""
    h = heading.lower().strip()
    h = re.sub(r"^\d+\.?\s*", "", h)
    h = h.replace("**", "").strip()
    for slot_name, keywords in _SECTION_MAP.items():
        if any(k in h for k in keywords):
            return slot_name
    return None


# ---------------------------------------------------------------------------
# Checklist items — adapted from CEIm Auditoria protocol
# ---------------------------------------------------------------------------

@dataclass
class ChecklistItem:
    """A single checklist evaluation item."""
    id: str
    category: str
    description: str
    critical: bool = False
    status: str = "N/A"  # ✅ | ⚠️ | ❌ | N/A
    finding: str = ""
    recommendation: str = ""


# --- Observational / Biomedical checklist ---

_OBSERVATIONAL_CHECKLIST: list[dict] = [
    # Block A — Identification and Design
    {"id": "A1", "cat": "Identificación y Diseño",
     "desc": "Título completo y registro del estudio",
     "critical": True,
     "positive_kw": ["clinicaltrials", "eudract", "ctis", "isrctn", "registro",
                     "registry", "código de protocolo", "protocol code",
                     "prospero", "crd42"],
     "section": "title"},
    {"id": "A2", "cat": "Identificación y Diseño",
     "desc": "Justificación científica con gap de conocimiento explícito",
     "critical": True,
     "positive_kw": ["gap", "laguna", "desconoce", "unknown", "unclear",
                     "necesidad", "need", "no se ha estudiado", "limited evidence"],
     "section": "justification"},
    {"id": "A3", "cat": "Identificación y Diseño",
     "desc": "Diseño metodológico apropiado y justificado",
     "critical": False,
     "positive_kw": ["rct", "ensayo", "cohorte", "cohort", "caso-control",
                     "case-control", "transversal", "cross-sectional",
                     "revisión sistemática", "systematic review"],
     "section": "design"},
    {"id": "A4", "cat": "Identificación y Diseño",
     "desc": "Objetivos primarios y secundarios con variable principal definida",
     "critical": True,
     "positive_kw": ["objetivo primario", "primary objective", "primary outcome",
                     "variable principal", "primary endpoint",
                     "objetivo secundario", "secondary"],
     "section": "objectives"},
    {"id": "A5", "cat": "Identificación y Diseño",
     "desc": "Cronograma y viabilidad",
     "critical": False,
     "positive_kw": ["cronograma", "timeline", "schedule", "duración",
                     "duration", "meses", "months", "feasibility", "viabilidad"],
     "section": "methods"},

    # Block B — Participants and Safety
    {"id": "B1", "cat": "Participantes y Seguridad",
     "desc": "Criterios de inclusión/exclusión explícitos",
     "critical": True,
     "positive_kw": ["inclusión", "inclusion", "exclusión", "exclusion",
                     "criterio", "criteria", "elegibilidad", "eligibility"],
     "section": "population"},
    {"id": "B2", "cat": "Participantes y Seguridad",
     "desc": "Cálculo del tamaño muestral justificado",
     "critical": True,
     "positive_kw": ["tamaño muestral", "sample size", "potencia", "power",
                     "alfa", "alpha", "0.05", "80%", "mcid", "efecto mínimo"],
     "section": "methods"},
    {"id": "B3", "cat": "Participantes y Seguridad",
     "desc": "Plan de análisis estadístico",
     "critical": False,
     "positive_kw": ["análisis estadístico", "statistical analysis",
                     "itt", "intention to treat", "per protocol",
                     "datos perdidos", "missing data", "regresión",
                     "regression", "intervalo de confianza", "confidence interval"],
     "section": "methods"},
    {"id": "B4", "cat": "Participantes y Seguridad",
     "desc": "Plan de seguridad (eventos adversos)",
     "critical": True,
     "positive_kw": ["evento adverso", "adverse event", "sae", "susar",
                     "seguridad", "safety", "dsmb", "comité de seguridad",
                     "data safety", "reporte", "reporting"],
     "section": "safety"},
    {"id": "B5", "cat": "Participantes y Seguridad",
     "desc": "Balance beneficio-riesgo explícito",
     "critical": False,
     "positive_kw": ["beneficio", "benefit", "riesgo", "risk",
                     "balance", "minimización", "mitigation"],
     "section": "safety"},

    # Block C — Ethics and Regulatory
    {"id": "C1", "cat": "Aspectos Éticos y Regulatorios",
     "desc": "Consentimiento informado completo",
     "critical": True,
     "positive_kw": ["consentimiento informado", "informed consent",
                     "firma", "signature", "voluntari", "voluntary",
                     "derecho de retirada", "right to withdraw"],
     "section": "consent"},
    {"id": "C2", "cat": "Aspectos Éticos y Regulatorios",
     "desc": "Hoja de información al paciente (HIP) en lenguaje claro",
     "critical": True,
     "positive_kw": ["hoja de información", "patient information",
                     "información al paciente", "hip",
                     "lenguaje claro", "plain language"],
     "section": "consent"},
    {"id": "C3", "cat": "Aspectos Éticos y Regulatorios",
     "desc": "Protección de datos (RGPD/LOPDGDD)",
     "critical": True,
     "positive_kw": ["rgpd", "gdpr", "lopd", "protección de datos",
                     "data protection", "responsable del tratamiento",
                     "data controller", "arco", "conservación",
                     "retention", "base legal", "legal basis"],
     "section": "data_protection"},
    {"id": "C4", "cat": "Aspectos Éticos y Regulatorios",
     "desc": "Seguro de responsabilidad civil",
     "critical": False,
     "positive_kw": ["seguro", "insurance", "responsabilidad civil",
                     "liability", "rd 1090", "póliza", "policy"],
     "section": "ethics"},
    {"id": "C5", "cat": "Aspectos Éticos y Regulatorios",
     "desc": "Declaración de conflictos de interés",
     "critical": False,
     "positive_kw": ["conflicto de interés", "conflict of interest",
                     "financiación", "funding", "sponsor", "promotor"],
     "section": "ethics"},

    # Block D — Quality
    {"id": "D1", "cat": "Calidad y Buenas Prácticas",
     "desc": "Monitorización y control de calidad",
     "critical": False,
     "positive_kw": ["monitorización", "monitoring", "calidad", "quality",
                     "edc", "cuaderno", "crf", "case report"],
     "section": "methods"},
    {"id": "D2", "cat": "Calidad y Buenas Prácticas",
     "desc": "Criterios de parada anticipada",
     "critical": False,
     "positive_kw": ["parada", "stopping", "futilidad", "futility",
                     "interrupción", "termination", "interim"],
     "section": "methods"},
    {"id": "D3", "cat": "Calidad y Buenas Prácticas",
     "desc": "Plan de publicación y política de autoría",
     "critical": False,
     "positive_kw": ["publicación", "publication", "autoría", "authorship",
                     "icmje", "resultados negativos", "negative results"],
     "section": "ethics"},
    {"id": "D4", "cat": "Calidad y Buenas Prácticas",
     "desc": "Muestras biológicas (si aplica)",
     "critical": False,
     "positive_kw": ["muestra biológica", "biological sample", "biobanco",
                     "biobank", "almacenamiento", "storage",
                     "destrucción", "destruction", "tejido", "tissue"],
     "section": "samples"},
    {"id": "D5", "cat": "Calidad y Buenas Prácticas",
     "desc": "Poblaciones vulnerables (menores, embarazadas)",
     "critical": False,
     "positive_kw": ["menor", "minor", "pediátric", "pediatric", "niño",
                     "child", "adolescente", "adolescent", "embarazada",
                     "pregnant", "vulnerable", "incapacitad", "asentimiento",
                     "assent", "representante legal", "legal guardian"],
     "section": "consent"},
]

# --- Qualitative CASPe-inspired checklist ---

_QUALITATIVE_CHECKLIST: list[dict] = [
    {"id": "Q1", "cat": "Claridad y Objetivos",
     "desc": "Claridad de los objetivos de la investigación",
     "critical": True,
     "positive_kw": ["objetivo", "objective", "pregunta de investigación",
                     "research question", "propósito", "purpose",
                     "explorar", "explore", "comprender", "understand",
                     "describir", "describe", "interpretar", "interpret"],
     "section": "objectives"},
    {"id": "Q2", "cat": "Congruencia Metodológica",
     "desc": "Congruencia entre pregunta, método y paradigma epistemológico",
     "critical": True,
     "positive_kw": ["paradigma", "paradigm", "epistemolog",
                     "constructivism", "constructivismo",
                     "fenomenolog", "phenomenol", "hermenéutic",
                     "interpretativ", "crítico", "critical",
                     "pragmatis", "congruencia", "coherencia", "coherence"],
     "section": "methods"},
    {"id": "Q3", "cat": "Congruencia Metodológica",
     "desc": "Adecuación del método cualitativo al objetivo",
     "critical": True,
     "positive_kw": ["grounded theory", "teoría fundamentada",
                     "fenomenología", "phenomenology", "etnografía",
                     "ethnography", "estudio de caso", "case study",
                     "investigación-acción", "action research",
                     "narrativ", "análisis del discurso", "discourse"],
     "section": "methods"},
    {"id": "Q4", "cat": "Participantes",
     "desc": "Selección de participantes justificada y coherente",
     "critical": True,
     "positive_kw": ["muestreo intencional", "purposive", "purposeful",
                     "muestreo teórico", "theoretical sampling",
                     "bola de nieve", "snowball", "conveniencia",
                     "convenience", "criterio de selección",
                     "saturación", "saturation", "informantes clave",
                     "key informant"],
     "section": "population"},
    {"id": "Q5", "cat": "Recogida de Datos",
     "desc": "Técnicas de recogida de datos adecuadas y descritas",
     "critical": True,
     "positive_kw": ["entrevista", "interview", "grupo focal",
                     "focus group", "observación", "observation",
                     "diario de campo", "field notes", "grabación",
                     "recording", "transcripción", "transcription",
                     "guía de entrevista", "interview guide",
                     "documento", "document analysis"],
     "section": "methods"},
    {"id": "Q6", "cat": "Reflexividad",
     "desc": "Reflexividad del investigador explicitada",
     "critical": False,
     "positive_kw": ["reflexividad", "reflexivity", "posición del investigador",
                     "researcher position", "sesgo del investigador",
                     "researcher bias", "preconcepciones", "preconceptions",
                     "bracketing", "epojé", "epoché", "subjetividad",
                     "subjectivity", "influencia del investigador"],
     "section": "qualitative_methods"},
    {"id": "Q7", "cat": "Ética",
     "desc": "Consideraciones éticas adecuadas para investigación cualitativa",
     "critical": True,
     "positive_kw": ["consentimiento", "consent", "confidencialidad",
                     "confidentiality", "anonimato", "anonymity",
                     "comité de ética", "ethics committee",
                     "vulnerabilidad", "vulnerability",
                     "relación investigador-participante",
                     "power", "poder"],
     "section": "ethics"},
    {"id": "Q8", "cat": "Rigor del Análisis",
     "desc": "Rigor y transparencia del análisis cualitativo",
     "critical": True,
     "positive_kw": ["codificación", "coding", "categoría", "category",
                     "tema", "theme", "análisis temático", "thematic",
                     "triangulación", "triangulation", "audit trail",
                     "member checking", "verificación por participantes",
                     "peer debriefing", "intercodificador",
                     "intercoder", "nvivo", "atlas.ti", "maxqda"],
     "section": "methods"},
    {"id": "Q9", "cat": "Claridad de Resultados",
     "desc": "Resultados presentados con claridad y evidencia suficiente",
     "critical": False,
     "positive_kw": ["cita textual", "verbatim", "quote",
                     "extracto", "excerpt", "ilustra", "illustrate",
                     "evidencia", "evidence", "ejemplo", "example",
                     "narrativa", "narrative", "descripción densa",
                     "thick description"],
     "section": "results"},
    {"id": "Q10", "cat": "Transferibilidad",
     "desc": "Aplicabilidad y transferibilidad de los hallazgos",
     "critical": False,
     "positive_kw": ["transferibilidad", "transferability",
                     "aplicabilidad", "applicability", "generalizab",
                     "contexto", "context", "implicación", "implication",
                     "recomendación", "recommendation", "práctica",
                     "practice", "política", "policy"],
     "section": "conclusions"},
]


# ---------------------------------------------------------------------------
# Keyword presence detector
# ---------------------------------------------------------------------------

# Patterns that negate a keyword when they appear BEFORE it.
# These are matched against the window that INCLUDES up to the keyword start,
# so the keyword itself may be the next word after the negation phrase.
_NEGATION_PRE: list[re.Pattern[str]] = [
    # Spanish
    re.compile(r"\bno\s+(se\s+)?(obtuvo|proporcionó|describe|reportó|incluyó|"
               r"realizó|especifica|menciona|aplica|existe|presenta|dispone)\b"),
    re.compile(r"\bsin\s+(el|la|los|las)\s+$"),  # "sin la " right before keyword
    re.compile(r"\bsin\s+$"),                      # "sin " right before keyword
    re.compile(r"\bno\s+se\s+ha(n)?\s+(obtenido|proporcionado|descrito|incluido|"
               r"realizado|especificado|mencionado|presentado)\b"),
    re.compile(r"\bausencia\s+de\s+$"),            # "ausencia de " right before keyword
    re.compile(r"\bausencia\s+de\b"),
    # English
    re.compile(r"\bwithout\s+(the\s+)?$"),         # "without " right before keyword
    re.compile(r"\babsence\s+of\s+$"),
    re.compile(r"\babsence\s+of\b"),
    re.compile(r"\bdid\s+not\b"),
    re.compile(r"\bnot\s+\w+ed\b"),                # "not obtained", "not provided"
]

# Patterns that negate a keyword when they appear AFTER it
_NEGATION_POST: list[re.Pattern[str]] = [
    re.compile(r"\bwas\s+not\s+(obtained|provided|described|reported|included|"
               r"available|applicable|mentioned|performed|conducted)\b"),
    re.compile(r"\bwere\s+not\s+(obtained|provided|described)\b"),
    re.compile(r"\bno\s+(fue|fueron)\s+(obtenid|proporcionad|descrit|incluid|"
               r"realizad|especificad|mencionad)\w*\b"),
]


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _get_sentence_around(text: str, pos: int) -> tuple[str, str]:
    """Return (pre, post) text within the same sentence as position *pos*."""
    # Find sentence start: look backwards for sentence boundary
    search_start = max(0, pos - 200)
    segment = text[search_start:pos]
    # Find last sentence boundary in the segment
    boundaries = list(_SENTENCE_SPLIT.finditer(segment))
    if boundaries:
        sent_start = search_start + boundaries[-1].end()
    else:
        sent_start = search_start

    # Find sentence end: look forwards for sentence boundary
    search_end = min(len(text), pos + 200)
    segment_post = text[pos:search_end]
    m = _SENTENCE_SPLIT.search(segment_post)
    sent_end = pos + m.start() if m else search_end

    pre = text[sent_start:pos]
    post = text[pos:sent_end]
    return pre, post


def _is_negated(text: str, keyword: str) -> bool:
    """Check if a keyword appears only in negated contexts.

    Uses sentence-level scope to avoid cross-sentence false positives.
    """
    tl = text.lower()
    kl = keyword.lower()
    # Find all positions where the keyword appears
    start = 0
    positions = []
    while True:
        idx = tl.find(kl, start)
        if idx == -1:
            break
        positions.append(idx)
        start = idx + 1

    if not positions:
        return False

    # Check each occurrence — if ANY occurrence is non-negated, return False
    for pos in positions:
        pre_window, post_window = _get_sentence_around(tl, pos)
        # post_window starts at keyword; we only want text after keyword
        post_after_kw = post_window[len(kl):]

        negated_pre = any(p.search(pre_window) for p in _NEGATION_PRE)
        negated_post = any(p.search(post_after_kw) for p in _NEGATION_POST)

        if not negated_pre and not negated_post:
            return False  # At least one non-negated occurrence

    return True  # All occurrences are negated


def _detect_keywords(text: str, keywords: list[str]) -> list[str]:
    """Return which keywords are found in the text (case-insensitive).

    Filters out keywords that appear only in negated contexts.
    """
    tl = text.lower()
    found = []
    for k in keywords:
        if k in tl and not _is_negated(text, k):
            found.append(k)
    return found


# ---------------------------------------------------------------------------
# Checklist evaluation engine
# ---------------------------------------------------------------------------

_RELATED_SLOTS: dict[str, list[str]] = {
    "methods": ["qualitative_methods", "design"],
    "qualitative_methods": ["methods", "design"],
    "ethics": ["consent", "data_protection"],
    "consent": ["ethics"],
    "data_protection": ["ethics"],
    "safety": ["ethics", "methods"],
}


def _evaluate_checklist(
    slot_texts: dict[str, str],
    full_text: str,
    checklist: list[dict],
) -> list[ChecklistItem]:
    """Evaluate a checklist against extracted section texts."""
    items: list[ChecklistItem] = []

    for spec in checklist:
        section_key = spec["section"]
        # Primary section text + related slots
        section_text = slot_texts.get(section_key, "")
        for related in _RELATED_SLOTS.get(section_key, []):
            related_text = slot_texts.get(related, "")
            if related_text:
                section_text = (section_text + "\n\n" + related_text).strip()
        # Also search in full text as fallback (criteria may appear anywhere)
        search_text = section_text if section_text else full_text
        positive_kw = spec.get("positive_kw", [])

        found = _detect_keywords(search_text, positive_kw)
        # Also check full text for spillover
        found_full = _detect_keywords(full_text, positive_kw) if not found else found

        item = ChecklistItem(
            id=spec["id"],
            category=spec["cat"],
            description=spec["desc"],
            critical=spec.get("critical", False),
        )

        if section_text and len(found) >= 2:
            item.status = "✅"
            item.finding = f"Presente en sección dedicada ({len(found)} indicadores: {', '.join(found[:3])})"
        elif section_text and len(found) == 1:
            item.status = "⚠️"
            item.finding = f"Mencionado parcialmente ({found[0]}), pero insuficientemente desarrollado"
            item.recommendation = "Ampliar y explicitar los criterios requeridos"
        elif not section_text and len(found_full) >= 2:
            item.status = "⚠️"
            item.finding = f"No tiene sección dedicada, pero se menciona en el texto ({len(found_full)} indicadores)"
            item.recommendation = "Crear sección específica para mejorar la trazabilidad"
        elif not section_text and len(found_full) == 1:
            item.status = "⚠️"
            item.finding = f"Mención mínima encontrada ({found_full[0]}), sin desarrollo"
            item.recommendation = "Desarrollar una sección explícita con todos los elementos requeridos"
        else:
            item.status = "❌"
            item.finding = "No se identifica información sobre este criterio"
            item.recommendation = "Incorporar sección o contenido que aborde este requisito"

        items.append(item)

    return items


# ---------------------------------------------------------------------------
# Strength / weakness extraction
# ---------------------------------------------------------------------------

_STRENGTH_PATTERNS = [
    (r"\b(systematic|sistemátic)\b.*\b(search|review|búsqueda|revisión)\b", "Búsqueda/revisión sistemática"),
    (r"\b(PRISMA|CONSORT|STROBE|CARE|SPIRIT|MOOSE)\b", "Adherencia a guías de reporte"),
    (r"\b(doble ciego|double.blind|triple.blind)\b", "Enmascaramiento"),
    (r"\b(aleatoriz|randomiz)\b", "Aleatorización"),
    (r"\b(multicent|multicenter|multicéntrico)\b", "Estudio multicéntrico"),
    (r"\b(validat|validación|validated)\b.*\b(instrument|escala|scale|tool)\b", "Instrumentos validados"),
    (r"\b(triangulación|triangulation)\b", "Triangulación"),
    (r"\b(member\s+checking|verificación por participantes)\b", "Verificación por participantes"),
    (r"\b(sample size.*calculat|cálculo.*tamaño muestral|power.*analysis)\b", "Cálculo de tamaño muestral"),
    (r"\b(risk.of.bias|riesgo de sesgo|GRADE|Newcastle.Ottawa)\b", "Evaluación de calidad/sesgos"),
    (r"\b(intention.to.treat|ITT|por intención de tratar)\b", "Análisis por intención de tratar"),
    (r"\b(rgpd|gdpr|protección de datos|data protection)\b", "Protección de datos"),
    (r"\b(comité de ética|ethics committee|ceim|ceic|irb)\b", "Aprobación ética"),
]

_WEAKNESS_PATTERNS = [
    (r"\b(no\s+(se\s+)?(describe|especifica|justifica|menciona|detalla))\b", "Información no descrita/justificada"),
    (r"\b(limitaci|limitation|limitations)\b", "Limitaciones reconocidas"),
    (r"\b(sesgo|bias)\b.*\b(posible|potential|riesgo|risk|selection|selección)\b|\b(potential|posible|risk|riesgo)\b.*\b(sesgo|bias)\b", "Riesgo de sesgo identificado"),
    (r"\b(tamaño muestral.*(pequeño|insuficiente|limitado)|small\s+sample)\b", "Tamaño muestral potencialmente insuficiente"),
    (r"\b(heterogene|heterogeneidad)\b", "Heterogeneidad"),
    (r"\b(pérdida|attrition|pérdidas|dropout|abandono)\b", "Pérdidas de seguimiento"),
    (r"\b(no\s+(se\s+)?aleatoriz|non.randomized|no\s+randomized)\b", "Sin aleatorización"),
    (r"\b(single.center|un\s+solo\s+centro|unicéntrico|monocéntric)\b", "Estudio unicéntrico"),
]


def _extract_strengths(text: str) -> list[str]:
    """Extract methodological strengths from the text."""
    strengths = []
    tl = text.lower()
    for pattern, label in _STRENGTH_PATTERNS:
        if re.search(pattern, tl, re.I):
            strengths.append(label)
    return strengths


def _extract_weaknesses(text: str) -> list[str]:
    """Extract methodological weaknesses from the text."""
    weaknesses = []
    tl = text.lower()
    for pattern, label in _WEAKNESS_PATTERNS:
        if re.search(pattern, tl, re.I):
            weaknesses.append(label)
    return weaknesses


# ---------------------------------------------------------------------------
# Project summary extraction
# ---------------------------------------------------------------------------

def _extract_project_summary(
    slot_texts: dict[str, str],
    title: str,
    study_type: StudyType,
) -> str:
    """Build a brief project summary from extracted sections."""
    parts = []
    if title:
        parts.append(f"**Título**: {title}")

    parts.append(f"**Tipo de estudio identificado**: {study_type.value}")

    obj = slot_texts.get("objectives", "")
    if obj:
        sents = _extract_sentences(obj, max_count=2)
        if sents:
            parts.append(f"**Objetivo**: {sents[0]}")

    pop = slot_texts.get("population", "")
    if pop:
        sents = _extract_sentences(pop, max_count=1)
        if sents:
            parts.append(f"**Población**: {sents[0]}")

    design = slot_texts.get("design", "") or slot_texts.get("methods", "")
    if design:
        sents = _extract_sentences(design, max_count=1)
        if sents:
            parts.append(f"**Diseño/Método**: {sents[0]}")

    return "\n".join(parts) if parts else "No se pudo extraer resumen del proyecto."


# ---------------------------------------------------------------------------
# Global recommendation logic
# ---------------------------------------------------------------------------

def _compute_recommendation(items: list[ChecklistItem]) -> tuple[str, str]:
    """Compute global recommendation from checklist items.

    Returns (recommendation, justification).
    """
    n_ok = sum(1 for i in items if i.status == "✅")
    n_partial = sum(1 for i in items if i.status == "⚠️")
    n_fail = sum(1 for i in items if i.status == "❌")
    n_na = sum(1 for i in items if i.status == "N/A")

    total_evaluated = len(items) - n_na
    critical_fails = [i for i in items if i.critical and i.status == "❌"]
    critical_partial = [i for i in items if i.critical and i.status == "⚠️"]

    if critical_fails:
        rec = "REVISIÓN MAYOR NECESARIA"
        justification = (
            f"Se identifican {len(critical_fails)} criterio(s) crítico(s) no cumplido(s): "
            f"{', '.join(i.id + ' — ' + i.description for i in critical_fails)}. "
            f"Estos elementos son esenciales para la aprobación ética y metodológica. "
            f"Resumen: ✅ {n_ok} | ⚠️ {n_partial} | ❌ {n_fail} de {total_evaluated} evaluados."
        )
    elif n_fail > 0 or len(critical_partial) >= 2:
        rec = "ACLARACIONES REQUERIDAS"
        justification = (
            f"El protocolo cumple parcialmente los criterios de revisión. "
            f"Se requieren aclaraciones en {n_partial + n_fail} punto(s). "
            f"Resumen: ✅ {n_ok} | ⚠️ {n_partial} | ❌ {n_fail} de {total_evaluated} evaluados."
        )
    elif n_partial > 0:
        rec = "FAVORABLE CON OBSERVACIONES MENORES"
        justification = (
            f"El protocolo es globalmente sólido con {n_ok} criterios cumplidos. "
            f"Se sugieren mejoras menores en {n_partial} punto(s). "
            f"Resumen: ✅ {n_ok} | ⚠️ {n_partial} | ❌ {n_fail} de {total_evaluated} evaluados."
        )
    else:
        rec = "FAVORABLE"
        justification = (
            f"El protocolo cumple satisfactoriamente todos los criterios evaluados. "
            f"Resumen: ✅ {n_ok} de {total_evaluated} evaluados."
        )

    return rec, justification


# ---------------------------------------------------------------------------
# Ethical considerations extractor
# ---------------------------------------------------------------------------

_ETHICAL_MARKERS = {
    "Poblaciones vulnerables": [
        "menor", "minor", "pediátric", "pediatric", "niño", "child",
        "adolescente", "adolescent", "embarazada", "pregnant",
        "vulnerable", "incapacitad", "discapacidad", "disability",
    ],
    "Consentimiento/Asentimiento": [
        "consentimiento", "consent", "asentimiento", "assent",
        "representante legal", "legal guardian", "tutor",
    ],
    "Confidencialidad": [
        "anonimato", "anonymity", "confidencial", "confidentiality",
        "pseudonimi", "seudonimi", "anonimiz", "anonymiz",
    ],
    "Muestras biológicas": [
        "muestra biológica", "biological sample", "biobanco", "biobank",
        "tejido", "tissue", "sangre", "blood", "genétic", "genetic",
    ],
    "Compensación": [
        "compensación", "compensation", "remuneración", "payment",
        "gratificación", "incentivo", "incentive",
    ],
}


def _extract_ethical_considerations(text: str) -> dict[str, list[str]]:
    """Extract ethical considerations organized by category."""
    tl = text.lower()
    considerations: dict[str, list[str]] = {}
    for category, keywords in _ETHICAL_MARKERS.items():
        found = [k for k in keywords if k in tl]
        if found:
            considerations[category] = found
    return considerations


# ---------------------------------------------------------------------------
# Public API — main review generator
# ---------------------------------------------------------------------------

@dataclass
class CEImReview:
    """Structured CEIm-style review result."""
    title: str
    study_type: StudyType
    project_summary: str
    strengths: list[str]
    weaknesses: list[str]
    checklist: list[ChecklistItem]
    ethical_considerations: dict[str, list[str]]
    recommendation: str
    recommendation_justification: str
    slot_texts: dict[str, str] = field(default_factory=dict)


def generate_ceim_review(
    protocol_md: str,
    force_study_type: StudyType | None = None,
) -> CEImReview:
    """Generate a structured CEIm-style review from protocol/paper Markdown.

    Parameters
    ----------
    protocol_md:      Full protocol or paper content in Markdown.
    force_study_type: Override automatic study type classification.

    Returns
    -------
    CEImReview dataclass with all review sections.
    """
    # 1. Parse sections
    raw_sections = _parse_sections(protocol_md)

    # 2. Classify study type
    study_type = force_study_type or classify_study_type(protocol_md)

    # 3. Map headings to review slots
    slot_texts: dict[str, str] = {}
    title = ""

    for heading, body in raw_sections:
        h_lower = heading.lower().strip()

        # Extract title
        if h_lower in ("title", "título", "titulo"):
            title = body.strip().split("\n")[0].strip()
            continue

        slot = _match_heading_to_review_slot(heading)
        if slot:
            existing = slot_texts.get(slot, "")
            slot_texts[slot] = (existing + "\n\n" + body).strip() if existing else body

    # Fallback title from H1
    if not title:
        for line in protocol_md.splitlines():
            s = line.strip()
            if s.startswith("# ") and not s.startswith("## "):
                title = s[2:].strip()
                break

    # 4. Build project summary
    project_summary = _extract_project_summary(slot_texts, title, study_type)

    # 5. Extract strengths and weaknesses
    strengths = _extract_strengths(protocol_md)
    weaknesses = _extract_weaknesses(protocol_md)

    # 6. Evaluate checklist (adaptive by study type)
    if study_type == StudyType.QUALITATIVE:
        checklist_items = _evaluate_checklist(slot_texts, protocol_md, _QUALITATIVE_CHECKLIST)
    elif study_type == StudyType.MIXED:
        # Combine both checklists
        obs_items = _evaluate_checklist(slot_texts, protocol_md, _OBSERVATIONAL_CHECKLIST)
        qual_items = _evaluate_checklist(slot_texts, protocol_md, _QUALITATIVE_CHECKLIST)
        checklist_items = obs_items + qual_items
    else:
        # Observational / biomedical / unknown
        checklist_items = _evaluate_checklist(slot_texts, protocol_md, _OBSERVATIONAL_CHECKLIST)

    # 6b. Mark N/A items for systematic reviews
    is_sr = _is_systematic_review(protocol_md)
    if is_sr:
        for item in checklist_items:
            if item.id in _SR_NA_ITEMS and item.status in ("❌", "⚠️"):
                item.status = "N/A"
                item.finding = "No aplica a revisiones sistemáticas (sin participantes directos)"
                item.recommendation = ""

    # 7. Ethical considerations
    ethical = _extract_ethical_considerations(protocol_md)

    # 8. Global recommendation
    recommendation, justification = _compute_recommendation(checklist_items)

    return CEImReview(
        title=title,
        study_type=study_type,
        project_summary=project_summary,
        strengths=strengths,
        weaknesses=weaknesses,
        checklist=checklist_items,
        ethical_considerations=ethical,
        recommendation=recommendation,
        recommendation_justification=justification,
        slot_texts=slot_texts,
    )


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def render_ceim_review_md(review: CEImReview) -> str:
    """Render a CEImReview as a structured Markdown document."""
    lines: list[str] = []

    # Header
    lines.append("# Valoración Estructurada Tipo CEIm / Pre-CEIm")
    lines.append("")
    lines.append("> **Aviso**: Esta revisión es una valoración estructurada automatizada ")
    lines.append("> inspirada en los criterios CEIm. No constituye un dictamen oficial ")
    lines.append("> de un Comité de Ética de la Investigación.")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 1. Project summary
    lines.append("## 1. Resumen del Proyecto")
    lines.append("")
    lines.append(review.project_summary)
    lines.append("")

    # 2. Study type adequacy
    lines.append("## 2. Adecuación del Tipo de Estudio")
    lines.append("")
    type_labels = {
        StudyType.OBSERVATIONAL: "Observacional / Biomédico",
        StudyType.QUALITATIVE: "Cualitativo",
        StudyType.MIXED: "Mixto (cuantitativo + cualitativo)",
        StudyType.UNKNOWN: "No clasificado con certeza",
    }
    lines.append(f"**Tipo detectado**: {type_labels.get(review.study_type, review.study_type.value)}")
    lines.append("")
    if review.study_type == StudyType.QUALITATIVE:
        lines.append("Se aplica checklist inspirado en **CASPe** y criterios de rigor cualitativo.")
    elif review.study_type == StudyType.MIXED:
        lines.append("Se aplican **ambos** checklists: biomédico (20 ítems) + cualitativo CASPe (10 ítems).")
    else:
        lines.append("Se aplica checklist basado en los **criterios CEIm** para estudios biomédicos.")
    lines.append("")

    # 3. Strengths
    lines.append("## 3. Fortalezas Identificadas")
    lines.append("")
    if review.strengths:
        for s in review.strengths:
            lines.append(f"- ✅ {s}")
    else:
        lines.append("- No se identificaron fortalezas metodológicas explícitas en el texto.")
    lines.append("")

    # 4. Weaknesses
    lines.append("## 4. Debilidades Metodológicas")
    lines.append("")
    if review.weaknesses:
        for w in review.weaknesses:
            lines.append(f"- ⚠️ {w}")
    else:
        lines.append("- No se identificaron debilidades explícitas. Esto no excluye debilidades latentes.")
    lines.append("")

    # 5. Checklist table
    lines.append("## 5. Checklist de Evaluación")
    lines.append("")

    n_ok = sum(1 for i in review.checklist if i.status == "✅")
    n_partial = sum(1 for i in review.checklist if i.status == "⚠️")
    n_fail = sum(1 for i in review.checklist if i.status == "❌")
    n_na = sum(1 for i in review.checklist if i.status == "N/A")
    lines.append(f"**Resumen**: ✅ {n_ok} | ⚠️ {n_partial} | ❌ {n_fail} | N/A {n_na}")
    lines.append("")
    lines.append("| Ítem | Criterio | Estado | Hallazgo | Recomendación |")
    lines.append("|------|----------|--------|----------|---------------|")
    for item in review.checklist:
        crit = " ⭐" if item.critical else ""
        lines.append(
            f"| {item.id}{crit} | {item.description} | {item.status} | "
            f"{item.finding} | {item.recommendation} |"
        )
    lines.append("")

    # 6. Ethical considerations
    lines.append("## 6. Consideraciones Éticas")
    lines.append("")
    if review.ethical_considerations:
        for category, keywords in review.ethical_considerations.items():
            lines.append(f"### {category}")
            lines.append(f"Indicadores encontrados: {', '.join(keywords[:5])}")
            lines.append("")
    else:
        lines.append("No se identificaron marcadores éticos específicos en el texto.")
    lines.append("")

    # 7. Risk/benefit (from checklist)
    lines.append("## 7. Balance Riesgo-Beneficio")
    lines.append("")
    safety_text = review.slot_texts.get("safety", "")
    if safety_text:
        sents = _extract_sentences(safety_text, max_count=3)
        for s in sents:
            lines.append(f"- {s}")
    else:
        lines.append("- No se identificó sección específica de riesgo-beneficio en el protocolo.")
    lines.append("")

    # 8. Data protection
    lines.append("## 8. Protección de Datos y Confidencialidad")
    lines.append("")
    dp_text = review.slot_texts.get("data_protection", "")
    if dp_text:
        sents = _extract_sentences(dp_text, max_count=3)
        for s in sents:
            lines.append(f"- {s}")
    else:
        lines.append("- No se identificó sección de protección de datos en el protocolo.")
    lines.append("")

    # 9. Consent
    lines.append("## 9. Consentimiento / Asentimiento")
    lines.append("")
    consent_text = review.slot_texts.get("consent", "")
    if consent_text:
        sents = _extract_sentences(consent_text, max_count=3)
        for s in sents:
            lines.append(f"- {s}")
    else:
        lines.append("- No se identificó documentación de consentimiento informado.")
    lines.append("")

    # 10. Biological samples
    lines.append("## 10. Muestras Biológicas")
    lines.append("")
    samples_text = review.slot_texts.get("samples", "")
    if samples_text:
        sents = _extract_sentences(samples_text, max_count=2)
        for s in sents:
            lines.append(f"- {s}")
    else:
        lines.append("- No aplica o no se identificaron referencias a muestras biológicas.")
    lines.append("")

    # 11. Observations
    lines.append("## 11. Observaciones / Preguntas al Investigador")
    lines.append("")
    fail_items = [i for i in review.checklist if i.status in ("❌", "⚠️")]
    if fail_items:
        for idx, item in enumerate(fail_items[:10], 1):
            lines.append(f"{idx}. **{item.id} — {item.description}**: {item.recommendation}")
    else:
        lines.append("No se generaron observaciones adicionales.")
    lines.append("")

    # 12. Global recommendation
    lines.append("## 12. Recomendación Global Razonada")
    lines.append("")
    lines.append(f"### **{review.recommendation}**")
    lines.append("")
    lines.append(review.recommendation_justification)
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*Valoración generada por ResearchClaw — CEIm Review Module*")

    return "\n".join(lines)


def generate_ceim_review_file(
    protocol_md: str,
    output_path: Path,
    force_study_type: StudyType | None = None,
) -> Path:
    """Generate CEIm review and write to a Markdown file.

    Returns the path to the generated file.
    """
    review = generate_ceim_review(protocol_md, force_study_type=force_study_type)
    md = render_ceim_review_md(review)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(md, encoding="utf-8")
    return output_path
