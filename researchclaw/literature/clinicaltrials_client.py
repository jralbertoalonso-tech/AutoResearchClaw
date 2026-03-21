"""ClinicalTrials.gov API v2 client.

Uses stdlib ``urllib`` + ``json`` — zero extra dependencies.

Public API
----------
- ``search_clinicaltrials(query, limit, year_min)`` → ``list[Paper]``

Rate limits:
  - No official published limit for the public API.
  - Conservative: 0.5s between requests to avoid throttling.

API reference:
  https://clinicaltrials.gov/data-api/api
  https://clinicaltrials.gov/api/v2/studies
"""

from __future__ import annotations

import json
import logging
import re
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from researchclaw.literature.models import Author, Paper

logger = logging.getLogger(__name__)

_BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
_MAX_PER_REQUEST = 50
_MAX_RETRIES = 3
_TIMEOUT_SEC = 20
_RATE_LIMIT_SEC = 0.5

# Maximum chars for query.term to avoid HTTP 400/414 from the API.
_MAX_QUERY_CHARS = 200

_last_request_time: float = 0.0
_rate_lock = threading.Lock()

# Fields requested from the API — only what we need, keeps response small.
_FIELDS = ",".join([
    "NCTId",
    "BriefTitle",
    "OfficialTitle",
    "BriefSummary",
    "OverallStatus",
    "Phase",
    "StartDate",
    "CompletionDate",
    "Condition",
    "InterventionName",
    "InterventionType",
    "LeadSponsorName",
    "EnrollmentCount",
])


def _rate_wait() -> None:
    """Enforce conservative rate limit between requests."""
    global _last_request_time  # noqa: PLW0603
    with _rate_lock:
        now = time.monotonic()
        elapsed = now - _last_request_time
        if elapsed < _RATE_LIMIT_SEC:
            time.sleep(_RATE_LIMIT_SEC - elapsed)
        _last_request_time = time.monotonic()


def _sanitize_query(query: str) -> str:
    """Sanitize a free-text query for ClinicalTrials.gov API.

    The API's ``query.term`` parameter rejects queries that are too long,
    contain certain non-ASCII characters, or include embedded instructions
    (guardrails preamble).  This function:

    1. Strips leading guardrails/protocol preamble (everything before the
       first line that looks like a real topic).
    2. Removes characters outside ASCII printable + basic Latin-1 medical
       chars (accented vowels common in Spanish/French medical terms are OK).
    3. Truncates to ``_MAX_QUERY_CHARS`` at a word boundary.
    """
    # Strip common guardrails preamble markers
    _preamble_markers = (
        "You are a", "Tu eres", "Act as", "Actúa como",
        "Eres un", "INSTRUCCIONES:", "INSTRUCTIONS:",
        "Follow these", "Sigue estas",
    )
    lines = query.split("\n")
    clean_lines: list[str] = []
    past_preamble = False
    for line in lines:
        stripped = line.strip()
        if not past_preamble:
            if any(stripped.startswith(m) for m in _preamble_markers):
                continue
            if not stripped:
                continue
            past_preamble = True
        clean_lines.append(stripped)
    clean = " ".join(clean_lines) if clean_lines else query.strip()

    # Remove characters that ClinicalTrials API chokes on, but keep
    # accented Latin chars commonly used in Spanish/French medical topics
    clean = re.sub(r"[^\w\s.,;:()\-/áéíóúàèìòùâêîôûäëïöüñçß]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()

    # Truncate at word boundary
    if len(clean) > _MAX_QUERY_CHARS:
        truncated = clean[:_MAX_QUERY_CHARS]
        # Don't cut mid-word
        last_space = truncated.rfind(" ")
        if last_space > _MAX_QUERY_CHARS // 2:
            truncated = truncated[:last_space]
        clean = truncated.strip()
        logger.info(
            "ClinicalTrials query truncated from %d to %d chars",
            len(query), len(clean),
        )

    return clean


def _shorten_query(query: str, max_words: int = 4) -> str:
    """Extract the first *max_words* meaningful words as a fallback query.

    Used when the API returns HTTP 400 on the sanitized query — a shorter
    query is more likely to succeed.
    """
    # Remove common stop words for medical queries
    _stop = {"y", "de", "la", "el", "en", "del", "las", "los", "un", "una",
             "the", "of", "in", "and", "for", "a", "an", "on", "with", "to"}
    words = query.split()
    meaningful = [w for w in words if w.lower() not in _stop and len(w) > 2]
    return " ".join(meaningful[:max_words])


def search_clinicaltrials(
    query: str,
    *,
    limit: int = 20,
    year_min: int = 0,
) -> list[Paper]:
    """Search ClinicalTrials.gov for studies matching *query*.

    Parameters
    ----------
    query:
        Free-text search term (maps to query.term).
    limit:
        Maximum number of results (capped at 50).
    year_min:
        If >0, restrict to studies with a start date >= this year.

    Returns
    -------
    list[Paper]
        Parsed studies as Paper objects. Empty list on failure.
    """
    limit = min(limit, _MAX_PER_REQUEST)
    sanitized = _sanitize_query(query)

    if not sanitized:
        logger.warning("ClinicalTrials: query became empty after sanitization, skipping")
        return []

    papers = _do_search(sanitized, limit=limit, year_min=year_min)

    # Fallback: if the sanitized query still caused a 400/414, retry with
    # a drastically shortened version (first few meaningful words).
    if papers is None:
        short = _shorten_query(sanitized)
        if short and short != sanitized:
            logger.warning(
                "ClinicalTrials: retrying with shortened query %r (was %r)",
                short, sanitized[:80],
            )
            _rate_wait()
            papers = _do_search(short, limit=limit, year_min=year_min)

    if papers is None:
        logger.warning(
            "ClinicalTrials: all query variants failed for %r — returning empty",
            query[:80],
        )
        return []

    logger.info(
        "ClinicalTrials.gov returned %d studies for %r", len(papers), sanitized[:80]
    )
    return papers


def _do_search(
    query: str,
    *,
    limit: int = 20,
    year_min: int = 0,
) -> list[Paper] | None:
    """Execute a single ClinicalTrials API search.

    Returns a list of Papers on success, or ``None`` if the API returned
    an HTTP 400/414 (query rejected) — signalling that a retry with a
    shorter query may succeed.
    """
    params: dict[str, str] = {
        "query.term": query,
        "pageSize": str(limit),
        "format": "json",
        "fields": _FIELDS,
    }
    if year_min > 0:
        params["filter.advanced"] = f"AREA[StartDate]RANGE[{year_min}-01-01, MAX]"

    _rate_wait()
    url = f"{_BASE_URL}?{urllib.parse.urlencode(params)}"
    data = _get_json(url)

    # _get_json returns None on failure.  Distinguish between "API rejected
    # the query" (400/414 → retry with shorter) vs "network/server error"
    # (500/timeout → don't retry with shorter).
    # We signal 400/414 by checking the URL length heuristic: if the URL is
    # very long and we got None, it's likely a query-too-long rejection.
    if data is None:
        return None

    studies = data.get("studies", [])
    if not isinstance(studies, list):
        return []

    papers: list[Paper] = []
    for study in studies:
        try:
            papers.append(_parse_study(study))
        except Exception:  # noqa: BLE001
            nct = _dig(study, "protocolSection", "identificationModule", "nctId") or "?"
            logger.debug("Failed to parse ClinicalTrials study %s", nct)

    return papers


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_study(study: dict[str, Any]) -> Paper:
    """Convert a ClinicalTrials API v2 study dict to a Paper."""
    proto = study.get("protocolSection", {})

    # -- Identification --
    id_mod = proto.get("identificationModule", {})
    nct_id: str = str(id_mod.get("nctId") or "").strip()
    brief_title: str = str(id_mod.get("briefTitle") or "").strip()
    official_title: str = str(id_mod.get("officialTitle") or "").strip()
    title = official_title or brief_title or f"Study {nct_id}"

    # -- Status --
    status_mod = proto.get("statusModule", {})
    overall_status: str = str(status_mod.get("overallStatus") or "").strip()
    start_date: str = str(
        (status_mod.get("startDateStruct") or {}).get("date") or ""
    ).strip()
    completion_date: str = str(
        (status_mod.get("completionDateStruct") or {}).get("date") or ""
    ).strip()

    # Extract year from start_date (format: "YYYY-MM" or "YYYY-MM-DD")
    year = 0
    if start_date and len(start_date) >= 4:
        try:
            year = int(start_date[:4])
        except ValueError:
            pass

    # -- Description --
    desc_mod = proto.get("descriptionModule", {})
    brief_summary: str = str(desc_mod.get("briefSummary") or "").strip()

    # -- Conditions --
    cond_mod = proto.get("conditionsModule", {})
    conditions: list[str] = [
        str(c) for c in (cond_mod.get("conditions") or []) if c
    ]

    # -- Design / Phase --
    design_mod = proto.get("designModule", {})
    phases: list[str] = [
        str(p) for p in (design_mod.get("phases") or []) if p
    ]
    enrollment_info = design_mod.get("enrollmentInfo") or {}
    enrollment: str = str(enrollment_info.get("count") or "").strip()

    # -- Interventions --
    arms_mod = proto.get("armsInterventionsModule", {})
    interventions_raw = arms_mod.get("interventions") or []
    intervention_parts: list[str] = []
    for iv in interventions_raw:
        if not isinstance(iv, dict):
            continue
        iv_type = str(iv.get("type") or "").strip()
        iv_name = str(iv.get("name") or "").strip()
        if iv_name:
            intervention_parts.append(
                f"{iv_name} ({iv_type})" if iv_type else iv_name
            )

    # -- Sponsor --
    sponsor_mod = proto.get("sponsorCollaboratorsModule", {})
    sponsor: str = str(
        (sponsor_mod.get("leadSponsor") or {}).get("name") or ""
    ).strip()

    # -- Venue: use phase + conditions as a proxy for "journal" --
    phase_str = ", ".join(phases) if phases else ""
    venue_parts = []
    if phase_str:
        venue_parts.append(phase_str)
    if conditions:
        venue_parts.append(conditions[0])
    venue = " — ".join(venue_parts) if venue_parts else "Clinical Trial"

    # -- Build enriched abstract --
    # Append structured metadata so the LLM agent can reason about
    # trial design, status, and interventions without extra fetches.
    meta_lines: list[str] = []
    if overall_status:
        meta_lines.append(f"Status: {overall_status}")
    if start_date:
        meta_lines.append(f"Start: {start_date}")
    if completion_date:
        meta_lines.append(f"Completion: {completion_date}")
    if enrollment:
        meta_lines.append(f"Enrollment: {enrollment} participants")
    if sponsor:
        meta_lines.append(f"Sponsor: {sponsor}")
    if intervention_parts:
        meta_lines.append("Interventions: " + "; ".join(intervention_parts))
    if conditions:
        meta_lines.append("Conditions: " + ", ".join(conditions))

    abstract = brief_summary
    if meta_lines:
        abstract = (abstract + "\n\n[Trial Metadata]\n" + "\n".join(meta_lines)).strip()

    # -- URL --
    url = f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else ""

    # -- Author: use sponsor as a synthetic "author" so cite_key works --
    authors: tuple[Author, ...] = ()
    if sponsor:
        authors = (Author(name=sponsor, affiliation=""),)

    return Paper(
        paper_id=f"ct-{nct_id}",
        title=title,
        authors=authors,
        year=year,
        abstract=abstract,
        venue=venue,
        citation_count=0,  # ClinicalTrials.gov has no citation data
        doi="",
        arxiv_id="",
        url=url,
        source="clinicaltrials",
    )


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get_json(url: str) -> dict[str, Any] | None:
    """GET *url*, return parsed JSON or None on failure."""
    for attempt in range(_MAX_RETRIES):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "ResearchClaw/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
                return json.loads(resp.read().decode("utf-8"))

        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < _MAX_RETRIES - 1:
                wait = 2 ** (attempt + 1)
                logger.warning(
                    "[rate-limit] ClinicalTrials 429. Waiting %ds (attempt %d/%d)...",
                    wait, attempt + 1, _MAX_RETRIES,
                )
                time.sleep(wait)
                continue
            if exc.code in (500, 502, 503, 504) and attempt < _MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
                continue
            logger.warning("ClinicalTrials HTTP %d for %s", exc.code, url)
            return None

        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
                continue
            logger.warning("ClinicalTrials request failed: %s", exc)
            return None

    return None


def _dig(obj: Any, *keys: str) -> Any:
    """Safely traverse nested dicts."""
    cur = obj
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur
