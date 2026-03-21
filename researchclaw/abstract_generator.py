"""Conference abstract generator from pipeline paper output.

Extracts and synthesizes a structured or unstructured conference abstract
from `paper_final.md` without requiring an LLM call. Reuses scoring and
extraction utilities from the poster generator.

Supported formats:
- **Structured**: Background / Objectives / Methods / Results / Conclusions
- **Unstructured**: Single flowing paragraph

Usage:
    from researchclaw.abstract_generator import generate_abstract
    abstract = generate_abstract(
        paper_md=paper_text,
        style="structured",
        max_words=300,
    )
"""

from __future__ import annotations

import re
from pathlib import Path

# Reuse proven extractors from poster generator
from researchclaw.poster_generator import (
    _parse_sections,
    _extract_results_findings,
    _extract_sentences,
    _truncate_bullet,
)


# ---------------------------------------------------------------------------
# Section mapping: paper heading keywords → abstract slot
# ---------------------------------------------------------------------------

_ABSTRACT_SLOTS = {
    "background": frozenset([
        "introduction", "introducción", "introduccion", "background",
        "antecedentes", "motivation", "clinical", "scientific",
        "knowledge gap", "current state", "state of evidence",
        "related work",
    ]),
    "objectives": frozenset([
        "objective", "objetivos", "objetivo", "objectives", "purpose",
        "aim", "aims", "review question", "hipótesis", "hipotesis",
    ]),
    "methods": frozenset([
        "method", "methods", "métodos", "metodos", "material",
        "search strategy", "eligibility", "prisma framework",
        "picos", "data collection", "data extraction", "study selection",
        "quality assessment", "risk-of-bias", "data analysis",
        "problem formulation", "experimental setup", "experiments",
        "diseño",
    ]),
    "results": frozenset([
        "results", "resultados", "hallazgos", "findings", "outcomes",
        "prisma flow", "study characteristics", "summary table",
        "included studies", "efficacy", "safety", "interpretation",
    ]),
    "conclusions": frozenset([
        "conclusion", "conclusions", "conclusión", "conclusiones",
        "discussion", "discusión", "discusion", "implications",
        "implicaciones", "limitations", "limitaciones",
    ]),
}

# Target sentence count per slot (for structured mode)
_SLOT_SENTENCE_TARGETS = {
    "background": 2,
    "objectives": 1,
    "methods":    2,
    "results":    3,
    "conclusions": 2,
}

# Ordered slot names for output
_SLOT_ORDER = ["background", "objectives", "methods", "results", "conclusions"]


# ---------------------------------------------------------------------------
# Heading classification
# ---------------------------------------------------------------------------

def _match_heading_to_abstract_slot(heading: str) -> str | None:
    """Return the abstract slot name for a paper heading, or None."""
    h = heading.lower().strip()
    h = re.sub(r"^\d+\.\s*", "", h)
    h = h.replace("**", "").strip()
    for slot_name, keywords in _ABSTRACT_SLOTS.items():
        if any(k in h for k in keywords):
            return slot_name
    return None


# ---------------------------------------------------------------------------
# Sentence extraction per slot
# ---------------------------------------------------------------------------

def _extract_slot_sentences(
    text: str,
    slot: str,
    max_sentences: int = 3,
) -> list[str]:
    """Extract the best sentences for a given abstract slot.

    Uses the finding-aware scorer for Results; generic sentence
    extraction for other slots.
    """
    if slot == "results":
        findings = _extract_results_findings(text, max_findings=max_sentences)
        if findings:
            return findings

    sentences = _extract_sentences(text, max_count=max_sentences * 2)

    # For non-Results slots, apply light scoring to prefer informative sentences
    if slot == "background":
        # Prefer sentences about disease/problem, prevalence, current treatment
        scored = []
        for s in sentences:
            score = 0.0
            sl = s.lower()
            if re.search(r"\b(chronic|disease|condition|disorder|prevalence|incidence|affect)\b", sl):
                score += 2.0
            if re.search(r"\b(treatment|therapy|intervention|standard|conventional)\b", sl):
                score += 1.5
            if re.search(r"\b(limited|gap|unclear|unknown|poorly|insufficient)\b", sl):
                score += 1.5
            if re.search(r"\b\d+\b", s):
                score += 0.5
            scored.append((score, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        sentences = [s for _, s in scored]

    elif slot == "objectives":
        # Prefer sentences with aim/objective language
        scored = []
        for s in sentences:
            score = 0.0
            sl = s.lower()
            if re.search(r"\b(aim|objective|purpose|evaluate|assess|review|investigate|determine)\b", sl):
                score += 3.0
            if re.search(r"\b(systematic|meta-analysis|efficacy|safety)\b", sl):
                score += 1.5
            scored.append((score, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        sentences = [s for _, s in scored]

    elif slot == "methods":
        # Prefer sentences about search strategy, criteria, design
        scored = []
        for s in sentences:
            score = 0.0
            sl = s.lower()
            if re.search(r"\b(search|database|pubmed|cochrane|scopus|medline)\b", sl):
                score += 2.5
            if re.search(r"\b(inclusion|exclusion|eligib|criteria|PICOS|PRISMA)\b", sl, re.I):
                score += 2.5
            if re.search(r"\b(randomized|controlled|trial|RCT|cohort|study design)\b", sl, re.I):
                score += 2.0
            if re.search(r"\b(risk.of.bias|quality|Newcastle|Cochrane)\b", sl, re.I):
                score += 1.5
            # Deprioritize meta-sentences about the paper structure
            if re.search(r"\b(this\s+section\s+(begins|describes|details|presents|outlines))\b", sl):
                score -= 5.0
            if re.search(r"\b(section\s+\d|described\s+(below|above|in\s+the))\b", sl):
                score -= 3.0
            scored.append((score, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        sentences = [s for _, s in scored]

    elif slot == "conclusions":
        # Prefer sentences with concluding language, implications
        scored = []
        for s in sentences:
            score = 0.0
            sl = s.lower()
            if re.search(r"\b(conclude|suggest|recommend|implication|future|further|need)\b", sl):
                score += 2.0
            if re.search(r"\b(promise|potential|evidence|support|warrant)\b", sl):
                score += 1.5
            # Deprioritize limitation-heavy sentences in conclusions
            if re.search(r"\b(limitation|bias|heterogen|restrict)\b", sl):
                score -= 1.0
            scored.append((score, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        sentences = [s for _, s in scored]

    return sentences[:max_sentences]


# ---------------------------------------------------------------------------
# Citation stripping
# ---------------------------------------------------------------------------

def _strip_citations(text: str) -> str:
    """Remove inline citations for abstract brevity."""
    text = re.sub(r"\s*\([^)]*(?:et al\.|(?:19|20)\d{2})[^)]*\)", "", text)
    text = re.sub(r"\s*\[[\d,\s]+\]", "", text)
    # Clean double spaces and trailing whitespace left by removals
    text = re.sub(r"  +", " ", text)
    return text.strip().rstrip(" .")


# ---------------------------------------------------------------------------
# Word budget control
# ---------------------------------------------------------------------------

def _enforce_word_budget(
    slot_sentences: dict[str, list[str]],
    max_words: int,
    targets: dict[str, int],
) -> dict[str, list[str]]:
    """Trim sentences per slot to fit within total word budget.

    Strategy: keep the target count per slot, then trim from the longest
    slot if still over budget.
    """
    # First pass: keep target sentence count per slot
    trimmed: dict[str, list[str]] = {}
    for slot in _SLOT_ORDER:
        sents = slot_sentences.get(slot, [])
        target = targets.get(slot, 2)
        trimmed[slot] = sents[:target]

    # Count total words
    def _total_words(d: dict[str, list[str]]) -> int:
        return sum(len(s.split()) for sents in d.values() for s in sents)

    # Second pass: if over budget, remove last sentence from longest slot
    attempts = 0
    while _total_words(trimmed) > max_words and attempts < 10:
        longest_slot = max(
            (s for s in _SLOT_ORDER if len(trimmed.get(s, [])) > 1),
            key=lambda s: sum(len(sent.split()) for sent in trimmed[s]),
            default=None,
        )
        if longest_slot is None:
            break
        trimmed[longest_slot] = trimmed[longest_slot][:-1]
        attempts += 1

    return trimmed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_paper_title(paper_md: str) -> str:
    """Extract the paper title from markdown."""
    for line in paper_md.splitlines():
        s = line.strip()
        if s.startswith("## Title"):
            continue
        if s.startswith("# "):
            return s[2:].strip()
    # Fallback: look for content after ## Title
    m = re.search(r"## Title\s*\n+(.+)", paper_md)
    if m:
        return m.group(1).strip()
    return ""


def generate_abstract(
    paper_md: str,
    style: str = "structured",
    max_words: int = 300,
    min_words: int = 200,
) -> dict[str, str | int | dict]:
    """Generate a conference abstract from the paper markdown.

    Parameters
    ----------
    paper_md:   Full paper content in Markdown.
    style:      "structured" (sectioned) or "unstructured" (single paragraph).
    max_words:  Maximum word count target (default 300).
    min_words:  Minimum word count target (default 200).

    Returns
    -------
    dict with keys:
        "title":      Paper title
        "abstract":   The generated abstract text
        "word_count": Actual word count
        "style":      Style used
        "sections":   dict of slot→text (only for structured)
    """
    raw_sections = _parse_sections(paper_md)

    # --- Accumulate text per abstract slot ---
    slot_texts: dict[str, list[str]] = {s: [] for s in _SLOT_ORDER}
    title = extract_paper_title(paper_md)

    for heading, body in raw_sections:
        h_lower = heading.lower().strip()
        # Skip title and abstract sections (we're generating a NEW abstract)
        if h_lower in ("title", "título", "titulo", "abstract", "resumen"):
            continue
        slot = _match_heading_to_abstract_slot(heading)
        if slot:
            slot_texts[slot].append(body)

    # --- Extract best sentences per slot ---
    slot_sentences: dict[str, list[str]] = {}
    for slot in _SLOT_ORDER:
        combined = "\n\n".join(slot_texts[slot])
        if not combined.strip():
            slot_sentences[slot] = []
            continue
        target = _SLOT_SENTENCE_TARGETS[slot]
        # Extract more candidates, then trim
        sents = _extract_slot_sentences(combined, slot, max_sentences=target + 2)
        # Clean citations and markdown, ensure proper sentence endings
        sents = [_strip_citations(s) for s in sents]
        sents = [re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", s) for s in sents]
        sents = [s.strip() for s in sents]
        # Ensure each sentence ends with a period
        sents = [s if s.endswith((".", "!", "?")) else s + "." for s in sents]
        sents = [s for s in sents if s and len(s) > 20]
        slot_sentences[slot] = sents

    # --- Enforce word budget ---
    slot_sentences = _enforce_word_budget(slot_sentences, max_words, _SLOT_SENTENCE_TARGETS)

    # --- Format output ---
    if style == "structured":
        sections_output: dict[str, str] = {}
        parts: list[str] = []
        for slot in _SLOT_ORDER:
            sents = slot_sentences.get(slot, [])
            if not sents:
                continue
            label = slot.capitalize()
            text = " ".join(sents)
            sections_output[slot] = text
            parts.append(f"**{label}**: {text}")
        abstract_text = "\n\n".join(parts)
    else:
        # Unstructured: merge all sentences into one flowing paragraph
        all_sents: list[str] = []
        for slot in _SLOT_ORDER:
            all_sents.extend(slot_sentences.get(slot, []))
        abstract_text = " ".join(all_sents)

    word_count = len(abstract_text.split())

    return {
        "title": title,
        "abstract": abstract_text,
        "word_count": word_count,
        "style": style,
        "sections": sections_output if style == "structured" else {},
    }


def generate_abstract_file(
    paper_md: str,
    output_path: Path,
    style: str = "structured",
    max_words: int = 300,
) -> Path:
    """Generate abstract and write to a markdown file.

    Parameters
    ----------
    paper_md:    Full paper content in Markdown.
    output_path: Where to write the abstract.
    style:       "structured" or "unstructured".
    max_words:   Maximum word count.

    Returns
    -------
    Path to the generated file.
    """
    result = generate_abstract(paper_md, style=style, max_words=max_words)

    lines = [
        f"# {result['title']}\n",
        f"## Conference Abstract ({result['style']}, {result['word_count']} words)\n",
        result["abstract"],
        "",
        f"---\n*Word count: {result['word_count']} | "
        f"Style: {result['style']} | "
        f"Generated from paper by ResearchClaw*\n",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
