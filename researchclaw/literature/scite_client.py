"""scite.ai MCP client for Smart Citation evidence extraction.

Connects to the scite.ai Model Context Protocol endpoint (JSON-RPC 2.0)
and exposes three public functions:

- ``search_scite(query, limit, year_min, api_key)`` → ``list[SciteResult]``
- ``filter_retracted(papers, api_key)`` → ``list[Paper]`` (removes retracted)
- ``get_smart_citations_for_doi(doi, api_key)`` → ``list[SmartCitation]``

Smart Citations are real, quoted snippets from citing papers — they are used
in Stage 06 (KNOWLEDGE_EXTRACT) as anti-hallucination evidence anchors.

MCP endpoint: POST https://api.scite.ai/mcp
Auth: Bearer token via SCITE_API_KEY environment variable.
Protocol: JSON-RPC 2.0, tool name: ``search_literature``.

References:
  - https://scite.ai/api-access
  - MCP manifest supplied by user (JSON-RPC 2.0 over HTTP)
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# Bootstrap .env so SCITE_API_KEY is available before the first HTTP call.
# override=True so a value in .env wins over a stale empty shell export.
try:
    from researchclaw.utils.env_bootstrap import bootstrap_env as _bootstrap_env
    _bootstrap_env(override=True)
except Exception:  # noqa: BLE001
    try:
        from pathlib import Path as _Path
        from dotenv import load_dotenv as _load_dotenv  # type: ignore[import]
        _load_dotenv(_Path(__file__).resolve().parent.parent.parent / ".env", override=True)
    except ImportError:
        pass

from researchclaw.literature.models import Author, Paper

logger = logging.getLogger(__name__)

_MCP_ENDPOINT = "https://api.scite.ai/mcp"
_TOOL_NAME = "search_literature"
_TIMEOUT_SEC = 30
_MAX_RETRIES = 2
_RETRY_DELAY = 2.0


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SmartCitation:
    """A single Smart Citation — a real quoted text snippet from a citing paper.

    Fields map directly to scite's ``hits[].citations[]`` response objects.
    """

    source_doi: str
    target_doi: str
    snippet: str          # Exact quoted sentence(s) from the citing paper
    section: str = ""     # Section of the citing paper (e.g. "methods")
    citation_type: str = ""  # "supporting" | "contrasting" | "mentioning"

    def to_evidence_line(self) -> str:
        """Format as a single evidence line for LLM context injection."""
        tag = f"[{self.citation_type.upper()}]" if self.citation_type else ""
        section_tag = f" ({self.section})" if self.section else ""
        return f'{tag}{section_tag} "{self.snippet}" — cited by {self.source_doi}'


@dataclass
class SciteResult:
    """A single paper result from the scite.ai API.

    Combines bibliographic metadata with scite-specific fields:
    tally (supporting/contrasting counts), Smart Citations, and
    retraction notices.
    """

    doi: str
    title: str
    authors: list[str] = field(default_factory=list)
    journal: str = ""
    year: int = 0
    abstract: str = ""
    is_oa: bool = False
    url: str = ""

    # scite-specific
    tally_total: int = 0
    tally_supporting: int = 0
    tally_contrasting: int = 0
    tally_mentioning: int = 0
    tally_citing_publications: int = 0
    retraction_notices: list[dict[str, Any]] = field(default_factory=list)
    smart_citations: list[SmartCitation] = field(default_factory=list)
    fulltext_excerpts: list[str] = field(default_factory=list)

    @property
    def is_retracted(self) -> bool:
        """Return True if scite has detected retraction notices for this paper."""
        return len(self.retraction_notices) > 0

    def to_paper(self) -> Paper:
        """Convert to the shared ``Paper`` dataclass used throughout the pipeline."""
        authors_tuple = tuple(
            Author(name=a, affiliation="") for a in self.authors if a
        )
        paper_id = f"scite:{self.doi}" if self.doi else f"scite:{self.title[:40]}"
        return Paper(
            paper_id=paper_id,
            title=self.title,
            authors=authors_tuple,
            year=self.year,
            abstract=self.abstract,
            venue=self.journal,
            citation_count=self.tally_citing_publications,
            doi=self.doi,
            arxiv_id="",
            url=self.url,
            source="scite",
        )

    def to_evidence_block(self) -> str:
        """Return a compact evidence block for LLM context injection."""
        lines = [
            f"## {self.title}",
            f"DOI: {self.doi} | Year: {self.year} | Journal: {self.journal}",
            f"Citations — supporting: {self.tally_supporting}, "
            f"contrasting: {self.tally_contrasting}, "
            f"mentioning: {self.tally_mentioning}",
        ]
        if self.abstract:
            lines.append(f"Abstract: {self.abstract[:400]}")
        if self.smart_citations:
            lines.append("Smart Citations (exact quoted text):")
            for sc in self.smart_citations[:5]:
                lines.append(f"  • {sc.to_evidence_line()}")
        if self.fulltext_excerpts:
            lines.append("Full-text excerpts:")
            for ex in self.fulltext_excerpts[:3]:
                lines.append(f"  › {ex[:200]}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal HTTP helpers
# ---------------------------------------------------------------------------


def _get_api_key(api_key: str = "") -> str:
    """Resolve API key: argument → SCITE_API_KEY env var."""
    return api_key or os.environ.get("SCITE_API_KEY", "")


def _mcp_call(
    method_params: dict[str, Any],
    api_key: str,
    *,
    request_id: int = 1,
) -> dict[str, Any]:
    """Send a single JSON-RPC 2.0 request to the scite MCP endpoint.

    Returns the ``result`` payload on success, raises ``RuntimeError`` on error.
    """
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": _TOOL_NAME,
                "arguments": method_params,
            },
        }
    ).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(
        _MCP_ENDPOINT,
        data=payload,
        headers=headers,
        method="POST",
    )

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
                if "error" in data:
                    raise RuntimeError(
                        f"scite MCP error: {data['error']}"
                    )
                return data.get("result", {})
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < _MAX_RETRIES:
                logger.warning("scite rate-limited (429) — retry %d/%d", attempt, _MAX_RETRIES)
                time.sleep(_RETRY_DELAY * attempt)
                continue
            raise
        except (urllib.error.URLError, OSError) as exc:
            if attempt < _MAX_RETRIES:
                logger.warning("scite network error (%s) — retry %d/%d", exc, attempt, _MAX_RETRIES)
                time.sleep(_RETRY_DELAY)
                continue
            raise

    raise RuntimeError("scite MCP call failed after all retries")


def _parse_hit(hit: dict[str, Any]) -> SciteResult:
    """Parse a single entry from ``hits[]`` into a ``SciteResult``."""
    tally: dict[str, Any] = hit.get("tally") or {}

    # Authors: list of {"authorName": "..."} dicts
    raw_authors = hit.get("authors") or []
    authors: list[str] = []
    for a in raw_authors:
        if isinstance(a, dict):
            name = str(a.get("authorName", "") or a.get("name", "")).strip()
        elif isinstance(a, str):
            name = a.strip()
        else:
            name = ""
        if name:
            authors.append(name)

    # Smart Citations
    smart_citations: list[SmartCitation] = []
    for c in hit.get("citations") or []:
        if not isinstance(c, dict):
            continue
        snippet = str(c.get("snippet", "")).strip()
        if not snippet:
            continue
        smart_citations.append(
            SmartCitation(
                source_doi=str(c.get("sourceDoi", "")),
                target_doi=str(c.get("targetDoi", hit.get("doi", ""))),
                snippet=snippet,
                section=str(c.get("section", "")),
                citation_type=str(c.get("type", "")),
            )
        )

    fulltext_excerpts: list[str] = [
        str(ex) for ex in (hit.get("fulltextExcerpts") or []) if ex
    ]

    # Access URL
    access: dict[str, Any] = hit.get("access") or {}
    url = str(access.get("url", "") or hit.get("doi", ""))
    if url and not url.startswith("http"):
        url = f"https://doi.org/{url}"

    return SciteResult(
        doi=str(hit.get("doi", "")),
        title=str(hit.get("title", "")),
        authors=authors,
        journal=str(hit.get("journal", "")),
        year=int(hit.get("year", 0) or 0),
        abstract=str(hit.get("abstract", "")),
        is_oa=bool(hit.get("isOa", False)),
        url=url,
        tally_total=int(tally.get("total", 0) or 0),
        tally_supporting=int(tally.get("supporting", 0) or 0),
        tally_contrasting=int(tally.get("contrasting", 0) or 0),
        tally_mentioning=int(tally.get("mentioning", 0) or 0),
        tally_citing_publications=int(tally.get("citingPublications", 0) or 0),
        retraction_notices=list(hit.get("retraction_notices") or []),
        smart_citations=smart_citations,
        fulltext_excerpts=fulltext_excerpts,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def search_scite(
    query: str,
    *,
    limit: int = 20,
    year_min: int = 0,
    api_key: str = "",
) -> list[SciteResult]:
    """Search scite.ai and return enriched results with Smart Citations.

    Parameters
    ----------
    query:
        Free-text search query.
    limit:
        Maximum number of results to request.
    year_min:
        If > 0, only include papers published this year or later.
    api_key:
        scite API key.  Falls back to ``SCITE_API_KEY`` env var.

    Returns
    -------
    list[SciteResult]
        Results sorted by supporting-citation count (descending).
        Retracted papers are NOT filtered here — use ``filter_retracted()``.
    """
    key = _get_api_key(api_key)
    if not key:
        logger.warning("SCITE_API_KEY not set — scite search skipped")
        return []

    params: dict[str, Any] = {"query": query, "limit": limit}
    if year_min > 0:
        params["yearMin"] = year_min

    try:
        result = _mcp_call(params, key)
    except Exception as exc:
        logger.warning("scite search failed: %s", exc)
        return []

    # MCP result may be wrapped: {"content": [{"type": "text", "text": "..."}]}
    # or a direct search response object.
    raw: dict[str, Any] = {}
    if isinstance(result, dict):
        if "content" in result:
            # Unwrap MCP text envelope
            for item in result.get("content", []):
                if isinstance(item, dict) and item.get("type") == "text":
                    try:
                        raw = json.loads(str(item["text"]))
                    except (json.JSONDecodeError, KeyError):
                        pass
                    break
        else:
            raw = result

    hits_raw = raw.get("hits") or []
    results: list[SciteResult] = []
    for hit in hits_raw:
        if not isinstance(hit, dict):
            continue
        try:
            sr = _parse_hit(hit)
            if year_min > 0 and sr.year > 0 and sr.year < year_min:
                continue
            results.append(sr)
        except Exception as exc:  # noqa: BLE001
            logger.debug("scite: failed to parse hit: %s", exc)

    logger.info("scite returned %d results for %r", len(results), query)

    # Sort by supporting citations (most authoritative evidence first)
    results.sort(key=lambda r: r.tally_supporting, reverse=True)
    return results


def filter_retracted(
    papers: list[Paper],
    *,
    api_key: str = "",
    batch_size: int = 10,
) -> tuple[list[Paper], list[dict[str, str]]]:
    """Check a list of papers against scite's retraction database.

    For each paper with a DOI, queries scite to check ``retraction_notices``.
    Papers with non-empty retraction notices are removed.

    Parameters
    ----------
    papers:
        List of Paper objects to check.  Papers without a DOI are kept as-is.
    api_key:
        scite API key.  Falls back to ``SCITE_API_KEY`` env var.
    batch_size:
        How many DOIs to look up per scite query (used as query string).

    Returns
    -------
    (kept, retraction_log)
        ``kept``: papers that are NOT retracted.
        ``retraction_log``: list of dicts describing each retracted paper.
    """
    key = _get_api_key(api_key)
    if not key:
        logger.warning("SCITE_API_KEY not set — retraction check skipped (all papers kept)")
        return papers, []

    kept: list[Paper] = []
    retraction_log: list[dict[str, str]] = []

    # Papers without DOI pass through unchecked
    papers_with_doi = [(i, p) for i, p in enumerate(papers) if p.doi]
    papers_without_doi = [p for p in papers if not p.doi]

    if not papers_with_doi:
        return papers, []

    # Check in batches via DOI-based query
    doi_to_paper: dict[str, Paper] = {p.doi.lower(): p for _, p in papers_with_doi}
    checked_dois: set[str] = set()

    doi_list = list(doi_to_paper.keys())
    for i in range(0, len(doi_list), batch_size):
        batch = doi_list[i : i + batch_size]
        # Build a query that targets these DOIs
        batch_query = " OR ".join(f'doi:"{d}"' for d in batch)
        try:
            results = search_scite(batch_query, limit=batch_size, api_key=key)
            for sr in results:
                doi_key = sr.doi.lower()
                if doi_key not in doi_to_paper:
                    continue
                checked_dois.add(doi_key)
                paper = doi_to_paper[doi_key]
                if sr.is_retracted:
                    retraction_log.append(
                        {
                            "doi": sr.doi,
                            "title": sr.title or paper.title,
                            "reason": "scite retraction_notices non-empty",
                            "notices": json.dumps(sr.retraction_notices[:2]),
                        }
                    )
                    logger.warning(
                        "RETRACTED paper removed: %s — %s", sr.doi, sr.title
                    )
                else:
                    kept.append(paper)
        except Exception as exc:  # noqa: BLE001
            logger.warning("scite retraction batch check failed: %s — keeping batch", exc)
            kept.extend(doi_to_paper[d] for d in batch if d in doi_to_paper)

    # Any DOI that scite didn't return (not found) → keep (safe default)
    for doi_key, paper in doi_to_paper.items():
        if doi_key not in checked_dois and paper not in kept:
            kept.append(paper)

    # Restore papers without DOI
    kept.extend(papers_without_doi)

    removed = len(papers) - len(kept)
    if removed:
        logger.info("Retraction filter: removed %d retracted paper(s)", removed)

    return kept, retraction_log


def get_smart_citations_for_doi(
    doi: str,
    *,
    api_key: str = "",
    limit: int = 10,
) -> list[SmartCitation]:
    """Retrieve Smart Citation snippets for a specific paper DOI.

    These are real, verbatim quotes from papers that cite the target DOI,
    classified as supporting, contrasting, or mentioning.

    Parameters
    ----------
    doi:
        The DOI of the paper to look up (e.g. ``"10.1056/NEJMoa2107341"``).
    api_key:
        scite API key.  Falls back to ``SCITE_API_KEY`` env var.
    limit:
        Max results to request from scite.

    Returns
    -------
    list[SmartCitation]
        Sorted: supporting first, then contrasting, then mentioning.
    """
    key = _get_api_key(api_key)
    if not key:
        return []

    # Search for the specific DOI
    results = search_scite(f'doi:"{doi}"', limit=limit, api_key=key)
    if not results:
        return []

    # Return Smart Citations from the best match
    all_citations: list[SmartCitation] = []
    for sr in results:
        all_citations.extend(sr.smart_citations)

    # Sort: supporting → contrasting → mentioning
    _order = {"supporting": 0, "contrasting": 1, "mentioning": 2}
    all_citations.sort(key=lambda c: _order.get(c.citation_type, 3))

    return all_citations[:limit]


def scite_results_to_papers(results: list[SciteResult]) -> list[Paper]:
    """Convert a list of SciteResults to Paper objects for pipeline compatibility."""
    return [r.to_paper() for r in results if r.title]
