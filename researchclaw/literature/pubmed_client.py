"""PubMed / NCBI E-utilities client for biomedical literature search.

Uses stdlib ``urllib`` + ``json`` + ``xml`` — zero extra dependencies.

Public API
----------
- ``search_pubmed(query, limit, year_min)`` → ``list[Paper]``

Rate limits (public, no API key):
  - 3 requests/second → enforced with 0.35s sleep between calls.
  - With NCBI_API_KEY: 10 requests/second.

References:
  - https://www.ncbi.nlm.nih.gov/books/NBK25499/
  - https://www.ncbi.nlm.nih.gov/books/NBK25500/
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

from researchclaw.literature.models import Author, Paper

logger = logging.getLogger(__name__)

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_PMC_OA_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"
_MAX_PER_REQUEST = 50
_MAX_RETRIES = 3
_TIMEOUT_SEC = 20
_RATE_LIMIT_SEC = 0.35  # NCBI public limit: 3 req/s

_last_request_time: float = 0.0
_rate_lock = threading.Lock()


def _rate_wait() -> None:
    """Enforce NCBI rate limit between requests."""
    global _last_request_time  # noqa: PLW0603
    with _rate_lock:
        now = time.monotonic()
        elapsed = now - _last_request_time
        if elapsed < _RATE_LIMIT_SEC:
            time.sleep(_RATE_LIMIT_SEC - elapsed)
        _last_request_time = time.monotonic()


def _ncbi_params() -> dict[str, str]:
    """Return common NCBI params (tool, email, api_key if available)."""
    params: dict[str, str] = {
        "tool": "researchclaw",
        "email": "researchclaw@users.noreply.github.com",
    }
    api_key = os.environ.get("NCBI_API_KEY", "").strip()
    if api_key:
        params["api_key"] = api_key
    return params


def search_pubmed(
    query: str,
    *,
    limit: int = 20,
    year_min: int = 0,
) -> list[Paper]:
    """Search PubMed for papers matching *query*.

    Parameters
    ----------
    query:
        Free-text search query (uses PubMed's default field matching).
    limit:
        Maximum number of results (capped at 50).
    year_min:
        If >0, restrict to papers published in this year or later.

    Returns
    -------
    list[Paper]
        Parsed papers. Empty list on network failure.
    """
    limit = min(limit, _MAX_PER_REQUEST)

    # Step 1: ESearch — get PMIDs
    pmids = _esearch(query, limit=limit, year_min=year_min)
    if not pmids:
        return []

    # Step 2: EFetch — get full records as XML
    papers = _efetch(pmids)

    # Step 3: Check PMC Open Access status (batch)
    _enrich_pmc_oa(papers)

    return papers


def _esearch(query: str, *, limit: int, year_min: int) -> list[str]:
    """Run ESearch and return a list of PMIDs."""
    _rate_wait()

    params = _ncbi_params()
    params.update({
        "db": "pubmed",
        "term": query,
        "retmax": str(limit),
        "retmode": "json",
        "sort": "relevance",
    })
    if year_min > 0:
        params["mindate"] = f"{year_min}/01/01"
        params["maxdate"] = "3000/12/31"
        params["datetype"] = "pdat"

    url = f"{_ESEARCH_URL}?{urllib.parse.urlencode(params)}"
    data = _get_json(url)
    if data is None:
        return []

    result = data.get("esearchresult", {})
    return list(result.get("idlist", []))


def _efetch(pmids: list[str]) -> list[Paper]:
    """Fetch full PubMed article records in XML and parse to Paper objects."""
    _rate_wait()

    params = _ncbi_params()
    params.update({
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    })

    url = f"{_EFETCH_URL}?{urllib.parse.urlencode(params)}"
    xml_text = _get_text(url)
    if not xml_text:
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        logger.warning("Failed to parse PubMed XML response")
        return []

    papers: list[Paper] = []
    for article_el in root.iter("PubmedArticle"):
        try:
            papers.append(_parse_pubmed_article(article_el))
        except Exception:  # noqa: BLE001
            logger.debug("Failed to parse a PubMed article element")
    return papers


def _parse_pubmed_article(article_el: ET.Element) -> Paper:
    """Convert a PubmedArticle XML element to a Paper."""
    medline = article_el.find("MedlineCitation")
    assert medline is not None
    article = medline.find("Article")
    assert article is not None

    # PMID
    pmid_el = medline.find("PMID")
    pmid = pmid_el.text.strip() if pmid_el is not None and pmid_el.text else ""

    # Title
    title_el = article.find("ArticleTitle")
    title = _text_content(title_el).strip() if title_el is not None else ""
    title = re.sub(r"\s+", " ", title)

    # Abstract
    abstract_el = article.find("Abstract")
    abstract = ""
    if abstract_el is not None:
        parts = []
        for abs_text in abstract_el.iter("AbstractText"):
            label = abs_text.get("Label", "")
            text = _text_content(abs_text).strip()
            if label and text:
                parts.append(f"{label}: {text}")
            elif text:
                parts.append(text)
        abstract = " ".join(parts)

    # Authors
    author_list_el = article.find("AuthorList")
    authors: list[Author] = []
    if author_list_el is not None:
        for author_el in author_list_el.findall("Author"):
            last = _el_text(author_el, "LastName")
            fore = _el_text(author_el, "ForeName")
            name = f"{fore} {last}".strip() if (fore or last) else ""
            affiliation = ""
            aff_el = author_el.find(".//Affiliation")
            if aff_el is not None and aff_el.text:
                affiliation = aff_el.text.strip()
            if name:
                authors.append(Author(name=name, affiliation=affiliation))

    # Year
    journal_el = article.find("Journal")
    year = 0
    if journal_el is not None:
        pub_date = journal_el.find(".//PubDate")
        if pub_date is not None:
            year_el = pub_date.find("Year")
            if year_el is not None and year_el.text:
                try:
                    year = int(year_el.text)
                except ValueError:
                    pass
            if year == 0:
                medline_date = _el_text(pub_date, "MedlineDate")
                if medline_date:
                    m = re.search(r"(\d{4})", medline_date)
                    if m:
                        year = int(m.group(1))

    # Venue (journal title)
    venue = ""
    if journal_el is not None:
        venue = _el_text(journal_el, "Title") or _el_text(journal_el, "ISOAbbreviation")

    # DOI and PMC ID from ArticleIdList
    doi = ""
    pmc_id = ""
    pub_data = article_el.find("PubmedData")
    if pub_data is not None:
        for aid in pub_data.iter("ArticleId"):
            id_type = aid.get("IdType", "")
            text = (aid.text or "").strip()
            if id_type == "doi" and text:
                doi = text
            elif id_type == "pmc" and text:
                pmc_id = text

    # URL
    url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""

    return Paper(
        paper_id=f"pubmed-{pmid}",
        title=title,
        authors=tuple(authors),
        year=year,
        abstract=abstract,
        venue=venue,
        citation_count=0,  # PubMed doesn't provide citation counts
        doi=doi,
        arxiv_id="",
        url=url,
        source="pubmed",
    )


def _enrich_pmc_oa(papers: list[Paper]) -> None:
    """Check PMC Open Access status for papers that have a DOI.

    Mutates nothing (Paper is frozen), but logs OA availability.
    This is informational — the Paper URL already points to PubMed.
    """
    dois = [p.doi for p in papers if p.doi]
    if not dois:
        return

    # Check first 5 DOIs to avoid excessive requests
    for doi in dois[:5]:
        _rate_wait()
        params = {"id": f"doi:{doi}"}
        url = f"{_PMC_OA_URL}?{urllib.parse.urlencode(params)}"
        xml_text = _get_text(url)
        if xml_text and "<link" in xml_text:
            logger.info("[pubmed] Open Access available via PMC for DOI %s", doi)


# ------------------------------------------------------------------
# HTTP helpers
# ------------------------------------------------------------------


def _get_json(url: str) -> dict[str, Any] | None:
    """GET *url* and parse JSON response with retry."""
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
                    "[rate-limit] PubMed 429. Waiting %ds (attempt %d/%d)...",
                    wait, attempt + 1, _MAX_RETRIES,
                )
                time.sleep(wait)
                continue
            if exc.code in (500, 502, 503, 504) and attempt < _MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
                continue
            logger.warning("PubMed HTTP %d for %s", exc.code, url)
            return None
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
                continue
            logger.warning("PubMed request failed: %s", exc)
            return None
    return None


def _get_text(url: str) -> str | None:
    """GET *url* and return raw text response with retry."""
    for attempt in range(_MAX_RETRIES):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "ResearchClaw/1.0"},
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < _MAX_RETRIES - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            if exc.code in (500, 502, 503, 504) and attempt < _MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
                continue
            logger.warning("PubMed HTTP %d for %s", exc.code, url)
            return None
        except (urllib.error.URLError, OSError) as exc:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
                continue
            logger.warning("PubMed request failed: %s", exc)
            return None
    return None


# ------------------------------------------------------------------
# XML helpers
# ------------------------------------------------------------------


def _el_text(parent: ET.Element, tag: str) -> str:
    """Return text of first child *tag*, or empty string."""
    el = parent.find(tag)
    if el is not None and el.text:
        return el.text.strip()
    return ""


def _text_content(el: ET.Element) -> str:
    """Return all text content of *el* including tail text of children.

    PubMed XML uses inline markup (e.g. <i>, <sup>) inside titles
    and abstracts. This extracts the concatenated plain text.
    """
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        parts.append(_text_content(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)
