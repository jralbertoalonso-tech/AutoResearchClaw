"""Tests for the conference abstract generator.

Covers:
- _match_heading_to_abstract_slot: heading classification
- _extract_slot_sentences: per-slot extraction with scoring
- _strip_citations: citation removal
- _enforce_word_budget: budget trimming
- generate_abstract: structured and unstructured modes
- generate_abstract_file: file output
- extract_paper_title: title extraction
"""

from __future__ import annotations

import unittest
from pathlib import Path

from researchclaw.abstract_generator import (
    generate_abstract,
    generate_abstract_file,
    extract_paper_title,
    _match_heading_to_abstract_slot,
    _extract_slot_sentences,
    _strip_citations,
    _enforce_word_budget,
    _SLOT_ORDER,
    _SLOT_SENTENCE_TARGETS,
    _ABSTRACT_SLOTS,
)


# ---------------------------------------------------------------------------
# Sample paper
# ---------------------------------------------------------------------------

_SAMPLE_PAPER = """\
## Title
CurcuMIX: Efficacy of Curcumin in Pediatric UC

## Abstract
This is the existing abstract that should be ignored.

## Introduction
Pediatric ulcerative colitis (UC) is a chronic inflammatory bowel disease
affecting approximately 1 in 10,000 children worldwide [1]. The disease
can significantly impact quality of life and long-term health outcomes [2].
Traditional treatments include corticosteroids and immunomodulators, but
their side effects remain a concern, particularly in younger patients [3].

### Knowledge Gap
The efficacy and safety of curcumin in pediatric UC remain poorly understood.

## Objective
This systematic review aims to evaluate the efficacy and safety of curcumin
and Qing Dai in treating pediatric ulcerative colitis.

## Methods
A systematic search was conducted in PubMed, Cochrane Library, and Scopus
from inception to April 2023. Inclusion criteria followed the PICOS framework:
population (children 0-18 with UC), intervention (curcumin or Qing Dai),
comparator (placebo or standard treatment). Risk of bias was assessed using
the Cochrane Risk of Bias 2 tool.

### Data Analysis
Meta-analysis was performed using random-effects models when heterogeneity
was acceptable (I2 < 75%).

## Results
Twenty RCTs met the inclusion criteria. Curcumin showed a 30% reduction
in disease activity scores compared to placebo (p<0.05). Adverse events
occurred in 12% of the curcumin group versus 18% in controls. Safety
profiles were generally favorable across all studies.

### Efficacy
Two RCTs reported statistically significant improvements in symptom scores.

## Discussion
Curcumin shows modest but consistent efficacy in reducing UC symptoms.
These findings support its potential as an adjunctive therapy.

## Limitations
The search was limited to English-language databases. Publication bias
may affect the results.

## Conclusion
Curcumin shows promise as an adjunctive therapy for pediatric UC.
Further larger RCTs with standardized protocols are needed to confirm
these findings and establish optimal dosing.
"""


# ---------------------------------------------------------------------------
# Tests for _match_heading_to_abstract_slot
# ---------------------------------------------------------------------------

class TestMatchHeadingToAbstractSlot(unittest.TestCase):

    def test_introduction_maps_to_background(self):
        self.assertEqual(_match_heading_to_abstract_slot("Introduction"), "background")

    def test_motivation_maps_to_background(self):
        self.assertEqual(_match_heading_to_abstract_slot("Motivation"), "background")

    def test_objective_maps_to_objectives(self):
        self.assertEqual(_match_heading_to_abstract_slot("Objective"), "objectives")

    def test_methods_maps_to_methods(self):
        self.assertEqual(_match_heading_to_abstract_slot("Methods"), "methods")

    def test_results_maps_to_results(self):
        self.assertEqual(_match_heading_to_abstract_slot("Results"), "results")

    def test_conclusion_maps_to_conclusions(self):
        self.assertEqual(_match_heading_to_abstract_slot("Conclusion"), "conclusions")

    def test_discussion_maps_to_conclusions(self):
        self.assertEqual(_match_heading_to_abstract_slot("Discussion"), "conclusions")

    def test_title_returns_none(self):
        self.assertIsNone(_match_heading_to_abstract_slot("Title"))

    def test_abstract_returns_none(self):
        self.assertIsNone(_match_heading_to_abstract_slot("Abstract"))

    def test_spanish_headings(self):
        self.assertEqual(_match_heading_to_abstract_slot("Introducción"), "background")
        self.assertEqual(_match_heading_to_abstract_slot("Métodos"), "methods")
        self.assertEqual(_match_heading_to_abstract_slot("Resultados"), "results")
        self.assertEqual(_match_heading_to_abstract_slot("Conclusiones"), "conclusions")

    def test_numbered_heading(self):
        self.assertEqual(_match_heading_to_abstract_slot("5. **Methods**"), "methods")


# ---------------------------------------------------------------------------
# Tests for _strip_citations
# ---------------------------------------------------------------------------

class TestStripCitations(unittest.TestCase):

    def test_strips_bracket_citations(self):
        result = _strip_citations("Some claim [1, 2, 3].")
        self.assertNotIn("[", result)

    def test_strips_author_year(self):
        result = _strip_citations("Curcumin is effective (Smith et al., 2021).")
        self.assertNotIn("Smith", result)

    def test_cleans_double_spaces(self):
        result = _strip_citations("A [1] B [2] C.")
        self.assertNotIn("  ", result)

    def test_preserves_content(self):
        result = _strip_citations("Pure text without citations.")
        self.assertEqual(result, "Pure text without citations")


# ---------------------------------------------------------------------------
# Tests for _extract_slot_sentences
# ---------------------------------------------------------------------------

class TestExtractSlotSentences(unittest.TestCase):

    def test_results_uses_finding_scorer(self):
        text = (
            "The table includes columns: Author, Year, Design.\n"
            "Curcumin reduced symptoms by 30% compared to placebo (p<0.05)."
        )
        sents = _extract_slot_sentences(text, "results", max_sentences=1)
        self.assertTrue(len(sents) >= 1)
        # Should pick the finding, not the table description
        self.assertNotIn("table includes", sents[0].lower())

    def test_background_prefers_disease_context(self):
        text = (
            "The software was installed correctly.\n"
            "Pediatric UC is a chronic inflammatory disease affecting 1 in 10,000 children."
        )
        sents = _extract_slot_sentences(text, "background", max_sentences=1)
        self.assertTrue(any("chronic" in s.lower() or "disease" in s.lower() for s in sents))

    def test_objectives_prefers_aim_language(self):
        text = (
            "Data was collected from three databases.\n"
            "This review aims to evaluate the efficacy of curcumin in pediatric UC."
        )
        sents = _extract_slot_sentences(text, "objectives", max_sentences=1)
        self.assertTrue(any("aim" in s.lower() or "evaluate" in s.lower() for s in sents))

    def test_methods_deprioritizes_meta_sentences(self):
        text = (
            "This section begins with a detailed overview.\n"
            "A systematic search was conducted in PubMed and Cochrane Library."
        )
        sents = _extract_slot_sentences(text, "methods", max_sentences=1)
        # Should pick the concrete method, not the meta-sentence
        if sents:
            self.assertNotIn("this section begins", sents[0].lower())


# ---------------------------------------------------------------------------
# Tests for _enforce_word_budget
# ---------------------------------------------------------------------------

class TestEnforceWordBudget(unittest.TestCase):

    def test_trims_to_budget(self):
        slot_sentences = {
            "background": ["Word " * 50 + "end."] * 3,
            "objectives": ["Word " * 30 + "end."],
            "methods": ["Word " * 50 + "end."] * 3,
            "results": ["Word " * 40 + "end."] * 3,
            "conclusions": ["Word " * 40 + "end."] * 2,
        }
        result = _enforce_word_budget(slot_sentences, max_words=200, targets=_SLOT_SENTENCE_TARGETS)
        total = sum(len(s.split()) for sents in result.values() for s in sents)
        self.assertLessEqual(total, 250)  # budget + some tolerance

    def test_preserves_all_slots(self):
        slot_sentences = {s: ["Short sentence."] for s in _SLOT_ORDER}
        result = _enforce_word_budget(slot_sentences, max_words=100, targets=_SLOT_SENTENCE_TARGETS)
        for slot in _SLOT_ORDER:
            self.assertIn(slot, result)


# ---------------------------------------------------------------------------
# Tests for extract_paper_title
# ---------------------------------------------------------------------------

class TestExtractPaperTitle(unittest.TestCase):

    def test_extracts_from_h2_title(self):
        title = extract_paper_title("## Title\nMy Paper Title\n\n## Abstract")
        self.assertEqual(title, "My Paper Title")

    def test_extracts_from_h1(self):
        title = extract_paper_title("# My Paper Title\n\nContent")
        self.assertEqual(title, "My Paper Title")

    def test_empty_paper(self):
        title = extract_paper_title("")
        self.assertEqual(title, "")


# ---------------------------------------------------------------------------
# Tests for generate_abstract
# ---------------------------------------------------------------------------

class TestGenerateAbstract(unittest.TestCase):

    def test_structured_has_all_slots(self):
        result = generate_abstract(_SAMPLE_PAPER, style="structured")
        for slot in _SLOT_ORDER:
            self.assertIn(f"**{slot.capitalize()}**", result["abstract"],
                          f"Missing {slot} section in structured abstract")

    def test_word_count_within_budget(self):
        result = generate_abstract(_SAMPLE_PAPER, style="structured", max_words=300)
        self.assertLessEqual(result["word_count"], 350)  # some tolerance
        self.assertGreater(result["word_count"], 50)

    def test_unstructured_is_single_block(self):
        result = generate_abstract(_SAMPLE_PAPER, style="unstructured")
        self.assertNotIn("**Background**", result["abstract"])

    def test_extracts_title(self):
        result = generate_abstract(_SAMPLE_PAPER)
        self.assertIn("CurcuMIX", result["title"])

    def test_returns_dict_with_expected_keys(self):
        result = generate_abstract(_SAMPLE_PAPER)
        self.assertIn("title", result)
        self.assertIn("abstract", result)
        self.assertIn("word_count", result)
        self.assertIn("style", result)
        self.assertIn("sections", result)

    def test_results_not_generic(self):
        """Results section should contain concrete findings, not table descriptions."""
        result = generate_abstract(_SAMPLE_PAPER, style="structured")
        results_text = result["sections"].get("results", "")
        self.assertNotIn("table includes", results_text.lower())
        self.assertNotIn("following columns", results_text.lower())

    def test_conclusions_present(self):
        result = generate_abstract(_SAMPLE_PAPER, style="structured")
        conclusions = result["sections"].get("conclusions", "")
        self.assertGreater(len(conclusions), 20)

    def test_no_citations_in_output(self):
        result = generate_abstract(_SAMPLE_PAPER)
        self.assertNotIn("[1]", result["abstract"])
        self.assertNotIn("[2]", result["abstract"])
        self.assertNotIn("et al.", result["abstract"])

    def test_empty_paper(self):
        result = generate_abstract("")
        self.assertEqual(result["word_count"], 0)

    def test_strict_word_limit(self):
        result = generate_abstract(_SAMPLE_PAPER, max_words=150)
        self.assertLessEqual(result["word_count"], 200)  # tolerance


# ---------------------------------------------------------------------------
# Tests for generate_abstract_file
# ---------------------------------------------------------------------------

class TestGenerateAbstractFile(unittest.TestCase):

    def test_creates_file(self):
        out = Path("/tmp/test_abstract_gen.md")
        out.unlink(missing_ok=True)
        result = generate_abstract_file(_SAMPLE_PAPER, out)
        self.assertTrue(result.exists())
        content = result.read_text()
        self.assertIn("Conference Abstract", content)
        self.assertIn("Word count:", content)

    def test_structured_file_has_sections(self):
        out = Path("/tmp/test_abstract_structured.md")
        result = generate_abstract_file(_SAMPLE_PAPER, out, style="structured")
        content = result.read_text()
        self.assertIn("**Background**", content)
        self.assertIn("**Results**", content)

    def test_unstructured_file(self):
        out = Path("/tmp/test_abstract_unstructured.md")
        result = generate_abstract_file(_SAMPLE_PAPER, out, style="unstructured")
        content = result.read_text()
        self.assertNotIn("**Background**", content)


# ---------------------------------------------------------------------------
# Tests for slot coverage
# ---------------------------------------------------------------------------

class TestAbstractSlotCoverage(unittest.TestCase):

    def test_all_slot_names_in_order(self):
        self.assertEqual(_SLOT_ORDER, ["background", "objectives", "methods",
                                        "results", "conclusions"])

    def test_all_slots_have_keywords(self):
        for slot in _SLOT_ORDER:
            self.assertIn(slot, _ABSTRACT_SLOTS)
            self.assertGreater(len(_ABSTRACT_SLOTS[slot]), 0)

    def test_all_slots_have_targets(self):
        for slot in _SLOT_ORDER:
            self.assertIn(slot, _SLOT_SENTENCE_TARGETS)
            self.assertGreater(_SLOT_SENTENCE_TARGETS[slot], 0)


if __name__ == "__main__":
    unittest.main()
