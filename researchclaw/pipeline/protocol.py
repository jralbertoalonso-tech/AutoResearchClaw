"""Protocol family and profile abstraction for ResearchClaw.

Replaces the scattered ``_is_bibliographic_protocol()`` / ``_is_literature_review()``
checks that were copy-pasted across executor.py and runner.py.  All protocol
detection is now centralised here so that every layer of the pipeline shares
exactly the same decision.

Public API
----------
ProtocolFamily  – coarse grouping (BIBLIOGRAPHIC | EXPERIMENTAL)
ProtocolProfile – fine-grained sub-type within a family
detect_protocol – single entry-point; call once per run, cache the result
is_bibliographic – convenience predicate
is_experimental  – convenience predicate
PROFILE_SKIP_STAGES – maps each profile to the set of pipeline stages it skips

Design notes
------------
* ``detect_protocol`` accepts BOTH the raw (full) topic and the cleaned topic so
  that it can apply the deterministic HARD-SKIP (raw preamble contains PRISMA /
  Póster / etc.) AND the keyword heuristic fallback (cleaned topic contains
  'meta-analysis' / 'systematic review' etc.) – exactly replicating the dual
  ``_hard_skip`` / ``_soft_detect`` logic that was previously in runner.py.

* The function is pure (no side-effects, no I/O) so it is safe to call at
  module load time or in tests.

* executor.py still exposes ``_is_bibliographic_protocol`` and
  ``_is_literature_review`` for callers that have not yet been migrated; they
  now delegate to this module.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import TYPE_CHECKING, FrozenSet

if TYPE_CHECKING:
    from researchclaw.pipeline.stages import Stage


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ProtocolFamily(str, Enum):
    """Coarse protocol grouping — determines which pipeline phases apply."""

    BIBLIOGRAPHIC = "bibliographic"
    EXPERIMENTAL = "experimental"


class ProtocolProfile(str, Enum):
    """Fine-grained sub-type within a family.

    Profiles within the BIBLIOGRAPHIC family share the same stage-skip logic
    but may differ in output templates, quality-gate thresholds, etc.
    """

    # ── Bibliographic family ──────────────────────────────────────────────
    SYSTEMATIC_REVIEW_PRISMA = "systematic_review_prisma"
    """Full PRISMA 2020 systematic review (most rigorous)."""

    NARRATIVE_REVIEW    = "narrative_review"
    """Non-systematic narrative / scoping literature review."""

    SCOPING_REVIEW      = "scoping_review"
    """Scoping review — maps evidence but does not meta-analyse."""

    META_ANALYSIS       = "meta_analysis"
    """Statistical meta-analysis of pooled results."""

    POSTER_ONLY         = "poster_only"
    """Conference poster derived from a bibliographic review."""

    # ── Experimental family ───────────────────────────────────────────────
    EXPERIMENTAL_ML     = "experimental_ml"
    """Machine-learning empirical study with full experiment pipeline."""

    GENERIC             = "generic"
    """Default — experimental pipeline, no strong prior signals."""


# Convenience sets
_BIBLIOGRAPHIC_PROFILES: frozenset[ProtocolProfile] = frozenset({
    ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA,
    ProtocolProfile.NARRATIVE_REVIEW,
    ProtocolProfile.SCOPING_REVIEW,
    ProtocolProfile.META_ANALYSIS,
    ProtocolProfile.POSTER_ONLY,
})

_EXPERIMENTAL_PROFILES: frozenset[ProtocolProfile] = frozenset({
    ProtocolProfile.EXPERIMENTAL_ML,
    ProtocolProfile.GENERIC,
})


# ---------------------------------------------------------------------------
# Hard-skip markers (deterministic, matched against raw topic preamble)
# ---------------------------------------------------------------------------

# Maps each marker (lower-cased) to the most specific matching profile.
# Checked in ORDER — first match wins.
_HARD_SKIP_MARKERS: list[tuple[str, ProtocolProfile]] = [
    # PRISMA variants (most specific first)
    ("prisma 2020",             ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA),
    ("prisma",                  ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA),
    ("systematic review",       ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA),
    ("revisión sistemática",    ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA),
    ("revision sistematica",    ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA),
    # Meta-analysis
    ("meta-analysis",           ProtocolProfile.META_ANALYSIS),
    ("metaanálisis",            ProtocolProfile.META_ANALYSIS),
    ("metaanalisis",            ProtocolProfile.META_ANALYSIS),
    ("meta análisis",           ProtocolProfile.META_ANALYSIS),
    # Poster
    ("póster",                  ProtocolProfile.POSTER_ONLY),
    ("poster",                  ProtocolProfile.POSTER_ONLY),
    # Scoping review
    ("scoping review",          ProtocolProfile.SCOPING_REVIEW),
    ("revisión de alcance",     ProtocolProfile.SCOPING_REVIEW),
    # Narrative review
    ("narrative review",        ProtocolProfile.NARRATIVE_REVIEW),
    ("revisión narrativa",      ProtocolProfile.NARRATIVE_REVIEW),
    ("revision narrativa",      ProtocolProfile.NARRATIVE_REVIEW),
    ("literature review",       ProtocolProfile.NARRATIVE_REVIEW),
    ("revisión bibliográfica",  ProtocolProfile.NARRATIVE_REVIEW),
    ("revision bibliografica",  ProtocolProfile.NARRATIVE_REVIEW),
    ("bibliographic review",    ProtocolProfile.NARRATIVE_REVIEW),
    # Generic bibliographic keywords
    ("systematic literature",   ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA),
    ("evidence synthesis",      ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA),
    ("cochrane",                ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA),
    ("rapid review",            ProtocolProfile.NARRATIVE_REVIEW),
]

# Soft-detect markers (keyword heuristic, applied to CLEANED topic only)
_SOFT_DETECT_KEYWORDS: frozenset[str] = frozenset({
    "meta-analysis",
    "metaanalysis",
    "metaanálisis",
    "systematic review",
    "revisión sistemática",
    "scoping review",
    "literature review",
    "bibliographic review",
    "narrative review",
    "evidence synthesis",
    "literature synthesis",
    "research synthesis",
    "review of",
    "análisis bibliométrico",
    "bibliometric",
    "revisión de la literatura",
})


# ---------------------------------------------------------------------------
# Detection logic
# ---------------------------------------------------------------------------


def detect_protocol(
    full_topic: str,
    clean_topic: str | None = None,
) -> ProtocolProfile:
    """Detect the protocol profile for a run.

    Parameters
    ----------
    full_topic:
        The raw topic string as stored in ``config.research.topic``.  May
        include the guardrails / protocol preamble injected by web_ui.py.
    clean_topic:
        The topic string after stripping the preamble (output of
        ``_clean_topic_for_search``).  If omitted, ``full_topic`` is used for
        both the hard-skip and the soft-detect passes.

    Returns
    -------
    ProtocolProfile
        The most specific profile detected.  Falls back to
        ``ProtocolProfile.GENERIC`` when no bibliographic markers are found.
    """
    if clean_topic is None:
        clean_topic = full_topic

    full_lower  = full_topic.lower()
    clean_lower = clean_topic.lower()

    # ── Pass 1: hard-skip — scan the FULL topic (includes preamble) ───────
    for marker, profile in _HARD_SKIP_MARKERS:
        if marker in full_lower:
            return profile

    # ── Pass 2: soft-detect — scan the CLEAN topic (user intent only) ─────
    for keyword in _SOFT_DETECT_KEYWORDS:
        if keyword in clean_lower:
            # Return the most specific bibliographic default
            return _soft_keyword_to_profile(keyword)

    return ProtocolProfile.GENERIC


def _soft_keyword_to_profile(keyword: str) -> ProtocolProfile:
    """Map a soft-detect keyword to the best matching profile."""
    kw = keyword.lower()
    if "meta" in kw and ("analysis" in kw or "análisis" in kw):
        return ProtocolProfile.META_ANALYSIS
    if "scoping" in kw:
        return ProtocolProfile.SCOPING_REVIEW
    if "narrative" in kw or "narrativa" in kw:
        return ProtocolProfile.NARRATIVE_REVIEW
    if "systematic" in kw or "sistemática" in kw or "sistematica" in kw:
        return ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA
    if "bibliometric" in kw or "bibliométrico" in kw:
        return ProtocolProfile.NARRATIVE_REVIEW
    # Generic bibliographic fallback
    return ProtocolProfile.NARRATIVE_REVIEW


# ---------------------------------------------------------------------------
# Convenience predicates
# ---------------------------------------------------------------------------


def is_bibliographic(profile: ProtocolProfile) -> bool:
    """Return True when the profile belongs to the BIBLIOGRAPHIC family."""
    return profile in _BIBLIOGRAPHIC_PROFILES


def is_experimental(profile: ProtocolProfile) -> bool:
    """Return True when the profile belongs to the EXPERIMENTAL family."""
    return profile in _EXPERIMENTAL_PROFILES


def family_of(profile: ProtocolProfile) -> ProtocolFamily:
    """Return the ProtocolFamily for a given profile."""
    if profile in _BIBLIOGRAPHIC_PROFILES:
        return ProtocolFamily.BIBLIOGRAPHIC
    return ProtocolFamily.EXPERIMENTAL


# ---------------------------------------------------------------------------
# Stage-skip mapping per profile
# ---------------------------------------------------------------------------
# Populated lazily to avoid circular-import at module load time.
# Use ``skip_stages_for(profile)`` instead of accessing this dict directly.

_PROFILE_SKIP_STAGES_CACHE: dict[ProtocolProfile, frozenset] = {}


def skip_stages_for(profile: ProtocolProfile) -> frozenset:
    """Return the set of Stage values that should be skipped for *profile*.

    The result is cached after the first call.  All bibliographic profiles
    skip the same stages (9–15: the full experiment pipeline).  Experimental
    profiles skip nothing.
    """
    if profile in _PROFILE_SKIP_STAGES_CACHE:
        return _PROFILE_SKIP_STAGES_CACHE[profile]

    from researchclaw.pipeline.stages import Stage  # local import — breaks cycle

    _EXPERIMENT_STAGES: frozenset = frozenset({
        Stage.EXPERIMENT_DESIGN,   # 9
        Stage.CODE_GENERATION,     # 10
        Stage.RESOURCE_PLANNING,   # 11
        Stage.EXPERIMENT_RUN,      # 12
        Stage.ITERATIVE_REFINE,    # 13
        Stage.RESULT_ANALYSIS,     # 14
        Stage.RESEARCH_DECISION,   # 15
    })

    result: frozenset
    if is_bibliographic(profile):
        result = _EXPERIMENT_STAGES
    else:
        result = frozenset()

    _PROFILE_SKIP_STAGES_CACHE[profile] = result
    return result


# ---------------------------------------------------------------------------
# Criticality helpers
# ---------------------------------------------------------------------------


class StageCriticality(str, Enum):
    """How a pipeline failure at a given stage should be handled.

    CRITICAL  — failure aborts the whole pipeline (default).
    SOFT_FAIL — failure is logged as a warning; the pipeline continues with a
                degraded result.
    ADVISORY  — failure is logged at INFO level; output is optional.
    """

    CRITICAL  = "critical"
    SOFT_FAIL = "soft_fail"
    ADVISORY  = "advisory"


# Default criticality for each Stage; overridden per-profile where needed.
# Stages not listed here default to CRITICAL.
_DEFAULT_CRITICALITY: dict[int, StageCriticality] = {
    20: StageCriticality.SOFT_FAIL,   # QUALITY_GATE — warn; never block deliverables
    21: StageCriticality.ADVISORY,    # KNOWLEDGE_ARCHIVE — archival; non-blocking
    23: StageCriticality.CRITICAL,    # CITATION_VERIFY — must block by default
}

# Per-profile criticality OVERRIDES (stage_int → StageCriticality)
_PROFILE_CRITICALITY_OVERRIDES: dict[ProtocolProfile, dict[int, StageCriticality]] = {
    # In bibliographic mode CITATION_VERIFY is downgraded to SOFT_FAIL:
    # the pipeline has no LLM-generated experiment metrics to verify — a
    # partial or failed citation check must never kill the paper output.
    ProtocolProfile.SYSTEMATIC_REVIEW_PRISMA: {23: StageCriticality.SOFT_FAIL},
    ProtocolProfile.NARRATIVE_REVIEW:          {23: StageCriticality.SOFT_FAIL},
    ProtocolProfile.SCOPING_REVIEW:            {23: StageCriticality.SOFT_FAIL},
    ProtocolProfile.META_ANALYSIS:             {23: StageCriticality.SOFT_FAIL},
    ProtocolProfile.POSTER_ONLY:               {23: StageCriticality.SOFT_FAIL},
}


def criticality_for(stage_int: int, profile: ProtocolProfile) -> StageCriticality:
    """Return the effective StageCriticality for *stage_int* given *profile*."""
    overrides = _PROFILE_CRITICALITY_OVERRIDES.get(profile, {})
    if stage_int in overrides:
        return overrides[stage_int]
    return _DEFAULT_CRITICALITY.get(stage_int, StageCriticality.CRITICAL)


def is_noncritical_for(stage_int: int, profile: ProtocolProfile) -> bool:
    """Return True when a stage failure should NOT abort the pipeline."""
    c = criticality_for(stage_int, profile)
    return c in (StageCriticality.SOFT_FAIL, StageCriticality.ADVISORY)
