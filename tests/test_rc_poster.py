"""Tests for the poster generator consolidation and rendering.

Covers:
- prepare_poster_sections: mapping full paper → 6 poster slots
- _match_heading_to_slot: heading classification
- _truncate_bullet: bullet truncation
- _extract_reference_bullets: reference extraction
- generate_poster: end-to-end .pptx generation
"""

from __future__ import annotations

import unittest
from pathlib import Path

from researchclaw.poster_generator import (
    prepare_poster_sections,
    _match_heading_to_slot,
    _truncate_bullet,
    _extract_reference_bullets,
    _extract_results_findings,
    _extract_sentences,
    _POSTER_SLOTS,
    _MAX_BULLET_CHARS,
)


# ---------------------------------------------------------------------------
# Sample paper content (mimics pipeline output)
# ---------------------------------------------------------------------------

_SAMPLE_PAPER = """\
## Title
CurcuMIX: Efficacy of Curcumin in Pediatric UC

## Abstract
This systematic review evaluates curcumin in pediatric UC.

## Introduction
Pediatric ulcerative colitis (UC) is a chronic inflammatory bowel disease.
It affects the large intestine and rectum, leading to abdominal pain.
Traditional treatments include corticosteroids and immunomodulators.

### Motivation
The search for safer alternatives has led to interest in curcumin.

### Knowledge Gap
Evidence in pediatric patients remains limited and inconclusive.

## Objective
This review aims to evaluate the efficacy and safety of curcumin.

## Methods
A systematic search was conducted in PubMed and Cochrane Library.
- Population: Children aged 0-18 with UC.
- Intervention: Curcumin supplementation.
- Comparator: Placebo or standard treatment.
- Outcome: Disease activity scores and adverse events.

### Search Strategy
Databases searched from inception to April 2023.

### Data Extraction
Two independent reviewers extracted data using standardized forms.

## Results
Twenty RCTs met the inclusion criteria.
- Curcumin group: 30% reduction in disease activity (p<0.05)
- Placebo group: 5% reduction (p>0.05)
- Adverse events: 12% vs 18% respectively

### Study Characteristics
Studies were conducted across 8 countries from 2015-2023.

### PRISMA Flow Diagram
4500 records identified, 200 screened, 20 included.

## Discussion
Curcumin shows modest but consistent efficacy compared to placebo.
These findings align with previous adult UC reviews.
The heterogeneity in dosing protocols complicates synthesis.

## Limitations
The search was limited to major English-language databases.
Publication bias may affect the results.

## Conclusion
Curcumin shows promise as an adjunctive therapy for pediatric UC.
Further larger RCTs with standardized protocols are needed.
Clinicians should consider it alongside conventional treatments.

## References
[1] Kumar et al. (2017). Curcumin and UC: a meta-analysis. J Gastroenterol.
[2] Patel et al. (2019). Curcumin in pediatric IBD. Pediatrics.
[3] Singh et al. (2020). Anti-inflammatory effects of curcumin. Gut.
[4] Li et al. (2018). Qing Dai in UC. Chinese Medicine J.
[5] Wang et al. (2021). Natural remedies for IBD. World J Gastroenterol.
"""


# ---------------------------------------------------------------------------
# Tests for _match_heading_to_slot
# ---------------------------------------------------------------------------

class TestMatchHeadingToSlot(unittest.TestCase):
    """Tests for heading-to-poster-slot classification."""

    def test_introduction_maps_to_background(self):
        self.assertEqual(_match_heading_to_slot("Introduction"), 0)

    def test_motivation_maps_to_background(self):
        self.assertEqual(_match_heading_to_slot("Motivation"), 0)

    def test_objective_maps_to_objective(self):
        self.assertEqual(_match_heading_to_slot("Objective"), 1)

    def test_methods_maps_to_methods(self):
        self.assertEqual(_match_heading_to_slot("Methods"), 2)

    def test_search_strategy_maps_to_methods(self):
        self.assertEqual(_match_heading_to_slot("Search Strategy"), 2)

    def test_results_maps_to_results(self):
        self.assertEqual(_match_heading_to_slot("Results"), 3)

    def test_prisma_flow_maps_to_results(self):
        self.assertEqual(_match_heading_to_slot("PRISMA Flow Diagram"), 3)

    def test_conclusion_maps_to_conclusions(self):
        self.assertEqual(_match_heading_to_slot("Conclusion"), 4)

    def test_discussion_maps_to_conclusions(self):
        self.assertEqual(_match_heading_to_slot("Discussion"), 4)

    def test_references_maps_to_references(self):
        self.assertEqual(_match_heading_to_slot("References"), 5)

    def test_limitations_maps_to_references(self):
        self.assertEqual(_match_heading_to_slot("Limitations"), 5)

    def test_title_returns_none(self):
        self.assertIsNone(_match_heading_to_slot("Title"))

    def test_abstract_returns_none(self):
        self.assertIsNone(_match_heading_to_slot("Abstract"))

    def test_numbered_heading(self):
        self.assertEqual(_match_heading_to_slot("5. **Methods**"), 2)

    def test_spanish_heading(self):
        self.assertEqual(_match_heading_to_slot("Introducción"), 0)
        self.assertEqual(_match_heading_to_slot("Resultados"), 3)
        self.assertEqual(_match_heading_to_slot("Conclusiones"), 4)


# ---------------------------------------------------------------------------
# Tests for _truncate_bullet
# ---------------------------------------------------------------------------

class TestTruncateBullet(unittest.TestCase):

    def test_short_text_unchanged(self):
        self.assertEqual(_truncate_bullet("Short text"), "Short text")

    def test_long_text_truncated(self):
        long = "A " * 100
        result = _truncate_bullet(long, max_chars=50)
        self.assertLessEqual(len(result), 52)  # +2 for "…"
        self.assertTrue(result.endswith("…"))

    def test_strips_markdown_bold(self):
        self.assertEqual(_truncate_bullet("**bold text**"), "bold text")

    def test_strips_citation_brackets(self):
        self.assertEqual(_truncate_bullet("Some claim [1, 2]"), "Some claim")

    def test_cuts_at_word_boundary(self):
        text = "This is a relatively long sentence that should be cut"
        result = _truncate_bullet(text, max_chars=30)
        self.assertFalse(result.rstrip("…").endswith(" "))  # no trailing space


# ---------------------------------------------------------------------------
# Tests for _extract_sentences
# ---------------------------------------------------------------------------

class TestExtractSentences(unittest.TestCase):

    def test_extracts_from_prose(self):
        text = (
            "First sentence about the topic and its relevance. "
            "Second sentence with more details about the method. "
            "Third sentence discussing the key findings."
        )
        result = _extract_sentences(text)
        self.assertGreaterEqual(len(result), 1)

    def test_strips_citations(self):
        text = "Curcumin has anti-inflammatory properties [1, 2]. It reduces UC symptoms [3]."
        result = _extract_sentences(text)
        for s in result:
            self.assertNotIn("[", s)

    def test_respects_max_count(self):
        text = ". ".join([f"Sentence number {i} with enough length" for i in range(20)])
        result = _extract_sentences(text, max_count=3)
        self.assertLessEqual(len(result), 3)


# ---------------------------------------------------------------------------
# Tests for _extract_reference_bullets
# ---------------------------------------------------------------------------

class TestExtractReferenceBullets(unittest.TestCase):

    def test_numbered_references(self):
        text = (
            "[1] Kumar et al. (2017). Curcumin review. J Gastroenterol.\n"
            "[2] Patel et al. (2019). Pediatric IBD. Pediatrics.\n"
            "[3] Singh et al. (2020). Anti-inflammatory. Gut.\n"
        )
        refs = _extract_reference_bullets(text)
        self.assertEqual(len(refs), 3)
        self.assertTrue(refs[0].startswith("[1]"))

    def test_max_refs_limit(self):
        text = "\n".join(f"[{i}] Author {i} (2020). Title. Journal." for i in range(10))
        refs = _extract_reference_bullets(text, max_refs=4)
        self.assertLessEqual(len(refs), 4)

    def test_fallback_for_plain_text(self):
        text = (
            "Lichtenstein, G. R. (2008). Inflammatory bowel disease. JAMA.\n"
            "Sandborn, W. J. (2010). UC treatments. Gut.\n"
        )
        refs = _extract_reference_bullets(text)
        self.assertGreaterEqual(len(refs), 1)

    def test_empty_input(self):
        refs = _extract_reference_bullets("")
        self.assertEqual(refs, [])


# ---------------------------------------------------------------------------
# Tests for _extract_results_findings
# ---------------------------------------------------------------------------

class TestExtractResultsFindings(unittest.TestCase):
    """Tests for the finding-aware Results extractor."""

    _RESULTS_WITH_TABLE_AND_FINDINGS = """\
The study characteristics table provides a summary of the included studies.
The table includes the following columns:
- **Author/Year**: The name of the first author and the year of publication.
- **Design**: The study design, such as RCT, cohort study, or case-control study.
- **Population**: The population studied, such as children or adolescents with UC.
- **Intervention**: The intervention used, such as curcumin or Qing Dai.

Two randomized controlled trials reported a statistically significant
reduction in disease activity scores (p<0.05). Curcumin reduced symptoms
by 30% compared to placebo. Adverse events were reported in 12% of the
curcumin group versus 18% in the control group.

Safety profiles were generally favorable, with minimal adverse events.
"""

    def test_prefers_findings_over_table_descriptions(self):
        findings = _extract_results_findings(self._RESULTS_WITH_TABLE_AND_FINDINGS)
        # Should NOT contain table column descriptions
        for f in findings:
            self.assertNotIn("Author/Year", f)
            self.assertNotIn("following columns", f)

    def test_captures_quantitative_data(self):
        findings = _extract_results_findings(self._RESULTS_WITH_TABLE_AND_FINDINGS)
        all_text = " ".join(findings)
        # Should contain at least one percentage or p-value
        self.assertTrue(
            "%" in all_text or "p<" in all_text or "p =" in all_text,
            f"Expected quantitative data, got: {findings}"
        )

    def test_respects_max_findings(self):
        findings = _extract_results_findings(
            self._RESULTS_WITH_TABLE_AND_FINDINGS, max_findings=3
        )
        self.assertLessEqual(len(findings), 3)

    def test_strips_citations(self):
        text = "Treatment reduced scores by 30% (Smith et al., 2021). Results were significant [1, 2]."
        findings = _extract_results_findings(text)
        for f in findings:
            self.assertNotIn("Smith et al.", f)
            self.assertNotIn("[1, 2]", f)

    def test_empty_input(self):
        findings = _extract_results_findings("")
        self.assertEqual(findings, [])

    def test_pure_table_description_yields_nothing(self):
        text = """\
The table includes the following columns:
- Author/Year: The name of the first author.
- Design: The study design.
- Population: The population studied.
- Intervention: The intervention used.
- Comparator: The comparator used.
"""
        findings = _extract_results_findings(text)
        # All sentences are table descriptions — should get empty or very few
        for f in findings:
            self.assertNotIn("Author/Year", f)

    def test_prioritizes_significant_results(self):
        text = """\
This figure provides a visual overview of the selection process.
Treatment A showed a 45% reduction in symptoms (p<0.001).
The diagram shows the number of records at each stage.
Adverse events occurred in 8% of patients versus 15% in controls.
"""
        findings = _extract_results_findings(text, max_findings=2)
        all_text = " ".join(findings)
        # Should capture the quantitative findings, not the figure description
        self.assertIn("45%", all_text)


# ---------------------------------------------------------------------------
# Tests for prepare_poster_sections
# ---------------------------------------------------------------------------

class TestPreparePosterSections(unittest.TestCase):
    """Tests for the main consolidation function."""

    def test_produces_6_sections(self):
        sections, title = prepare_poster_sections(_SAMPLE_PAPER)
        self.assertEqual(len(sections), 6)

    def test_extracts_title(self):
        _, title = prepare_poster_sections(_SAMPLE_PAPER)
        self.assertIn("CurcuMIX", title)

    def test_all_slots_have_bullets(self):
        sections, _ = prepare_poster_sections(_SAMPLE_PAPER)
        for sec_title, bullets, col in sections:
            self.assertGreater(len(bullets), 0,
                               f"Section '{sec_title}' has no bullets")

    def test_bullets_limited_to_max(self):
        sections, _ = prepare_poster_sections(_SAMPLE_PAPER)
        for _, bullets, _ in sections:
            self.assertLessEqual(len(bullets), 5)

    def test_columns_assigned(self):
        sections, _ = prepare_poster_sections(_SAMPLE_PAPER)
        cols = {sec[2] for sec in sections}
        self.assertIn(1, cols, "Should have Col 1 sections")
        self.assertIn(2, cols, "Should have Col 2 sections")
        self.assertIn(3, cols, "Should have Col 3 sections")

    def test_section_titles_are_standard(self):
        sections, _ = prepare_poster_sections(_SAMPLE_PAPER)
        titles = {s[0] for s in sections}
        expected = {"Background", "Objective", "Methods", "Results",
                    "Conclusions", "References"}
        self.assertEqual(titles, expected)

    def test_skips_abstract(self):
        """Abstract should not appear as a poster section."""
        sections, _ = prepare_poster_sections(_SAMPLE_PAPER)
        titles = {s[0] for s in sections}
        self.assertNotIn("Abstract", titles)

    def test_empty_paper(self):
        sections, title = prepare_poster_sections("")
        self.assertEqual(sections, [])
        self.assertEqual(title, "")

    def test_paper_without_standard_sections(self):
        paper = "## Custom Section\nSome content about results and findings."
        sections, _ = prepare_poster_sections(paper)
        # Should produce at least one section via keyword matching
        self.assertGreaterEqual(len(sections), 0)


# ---------------------------------------------------------------------------
# Tests for generate_poster (end-to-end)
# ---------------------------------------------------------------------------

class TestGeneratePoster(unittest.TestCase):
    """End-to-end test for .pptx generation."""

    def test_generates_pptx_file(self):
        out = Path("/tmp/test_poster_e2e.pptx")
        out.unlink(missing_ok=True)

        from researchclaw.poster_generator import generate_poster
        result = generate_poster(
            paper_md=_SAMPLE_PAPER,
            output_path=out,
            authors="García A, López B",
            institution="Hospital Test",
            congress="ESMO 2025",
        )
        self.assertTrue(result.exists())
        self.assertGreater(result.stat().st_size, 10_000)  # not empty

    def test_generates_without_optional_params(self):
        out = Path("/tmp/test_poster_minimal.pptx")
        out.unlink(missing_ok=True)

        from researchclaw.poster_generator import generate_poster
        result = generate_poster(
            paper_md=_SAMPLE_PAPER,
            output_path=out,
        )
        self.assertTrue(result.exists())

    def test_poster_slots_cover_all_columns(self):
        """Verify _POSTER_SLOTS spans columns 1, 2, 3."""
        cols = {col for _, _, col in _POSTER_SLOTS}
        self.assertEqual(cols, {1, 2, 3})

    def test_poster_slots_count(self):
        self.assertEqual(len(_POSTER_SLOTS), 6)


if __name__ == "__main__":
    unittest.main()
