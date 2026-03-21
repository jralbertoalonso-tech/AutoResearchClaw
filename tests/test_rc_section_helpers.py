"""Tests for section splitting, filtering, and section-by-section revision helpers.

Covers:
- FASE-2 (Stage 17): _split_md_sections, _normalize_heading, _filter_allowed_sections
- FASE-1 (Stage 19): _match_reviews_to_sections, _revise_section_by_section
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from researchclaw.pipeline.executor import (
    _split_md_sections,
    _normalize_heading,
    _filter_allowed_sections,
    _match_reviews_to_sections,
    _CALL1_ALLOWED,
    _CALL1A_ALLOWED,
    _CALL1B_ALLOWED,
    _CALL2_ALLOWED_EXP,
    _CALL2_ALLOWED_BIB,
    _CALL3_ALLOWED_EXP,
    _CALL3_ALLOWED_BIB,
)


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_FULL_PAPER = """\
## Title
CurcuMIX: A Systematic Review

## Abstract
This is the abstract of the paper with about 200 words of content.

## Introduction
This is the introduction section with background and rationale.
It discusses the clinical context and knowledge gap.

## Related Work
This section reviews prior systematic reviews and guidelines.

## Method
The search strategy and eligibility criteria are described here.

## Experiments
Experimental setup details including datasets and baselines.

## Results
The main findings are presented here with tables and figures.

## Discussion
Interpretation of key findings and comparison with prior work.

## Limitations
The limitations of the study are discussed here.

## Conclusion
Summary of contributions and future directions.
"""

_CALL1_OUTPUT_WITH_OVERFLOW = """\
## Title
CurcuMIX: A Systematic Review

## Abstract
This is the abstract.

## Introduction
This is a short intro.

## Related Work
Some related work.

## Method
This should NOT be here in Call 1.

## Experiments
This should NOT be here in Call 1.

## Results
This should NOT be here in Call 1.

## Discussion
This should NOT be here in Call 1.

## Limitations
This should NOT be here in Call 1.

## Conclusion
This should NOT be here in Call 1.
"""

_REVIEWS = """\
## Reviewer A
- Strengths: Clear methodology following PRISMA guidelines.
- Weaknesses: The Introduction lacks sufficient background on pediatric UC.
  The Discussion should compare with more recent reviews.
- Actionable: Expand the Introduction with more clinical context.

## Reviewer B
- The Method section should clarify the PICOS framework.
- The Limitations section is too brief — add discussion of publication bias.
- Overall the paper is well-structured but needs more depth in Results.
"""


# ---------------------------------------------------------------------------
# Tests for _split_md_sections
# ---------------------------------------------------------------------------

class TestSplitMdSections(unittest.TestCase):
    """Tests for _split_md_sections markdown splitter."""

    def test_splits_basic_paper(self):
        sections = _split_md_sections(_FULL_PAPER)
        headings = [h for h, _ in sections]
        self.assertIn("Title", headings)
        self.assertIn("Abstract", headings)
        self.assertIn("Introduction", headings)
        self.assertIn("Conclusion", headings)

    def test_preserves_all_sections(self):
        sections = _split_md_sections(_FULL_PAPER)
        # Should have 10 sections (Title through Conclusion)
        named = [(h, t) for h, t in sections if h]
        self.assertEqual(len(named), 10)

    def test_each_section_includes_header(self):
        sections = _split_md_sections(_FULL_PAPER)
        for heading, text in sections:
            if heading:
                self.assertTrue(text.startswith("## "),
                                f"Section '{heading}' should start with '## '")

    def test_empty_input(self):
        sections = _split_md_sections("")
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0], ("", ""))

    def test_no_headers(self):
        sections = _split_md_sections("Just plain text without headers.")
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0][0], "")

    def test_preamble_before_first_header(self):
        text = "Some preamble text\n\n## Title\nActual title"
        sections = _split_md_sections(text)
        # First element should be the preamble
        self.assertEqual(sections[0][0], "")
        self.assertIn("preamble", sections[0][1])
        # Second should be Title
        self.assertEqual(sections[1][0], "Title")

    def test_numbered_headings(self):
        text = "## 5. **Methods**\nContent\n\n## 6. **Results**\nMore content"
        sections = _split_md_sections(text)
        headings = [h for h, _ in sections if h]
        self.assertEqual(len(headings), 2)
        self.assertIn("5. **Methods**", headings)


# ---------------------------------------------------------------------------
# Tests for _normalize_heading
# ---------------------------------------------------------------------------

class TestNormalizeHeading(unittest.TestCase):
    """Tests for heading normalization."""

    def test_basic(self):
        self.assertEqual(_normalize_heading("Introduction"), "introduction")

    def test_numbered(self):
        self.assertEqual(_normalize_heading("5. Methods"), "methods")

    def test_bold(self):
        self.assertEqual(_normalize_heading("**Discussion**"), "discussion")

    def test_numbered_bold(self):
        self.assertEqual(_normalize_heading("7. **Discussion**"), "discussion")

    def test_with_spaces(self):
        self.assertEqual(_normalize_heading("  Related Work  "), "related work")

    def test_title(self):
        self.assertEqual(_normalize_heading("Title"), "title")


# ---------------------------------------------------------------------------
# Tests for _filter_allowed_sections
# ---------------------------------------------------------------------------

class TestFilterAllowedSections(unittest.TestCase):
    """Tests for section filtering in Stage 17 Calls."""

    def test_call1_keeps_only_assigned_sections(self):
        """Call 1 should keep Title, Abstract, Introduction, Related Work."""
        result = _filter_allowed_sections(_CALL1_OUTPUT_WITH_OVERFLOW, _CALL1_ALLOWED)
        self.assertIn("## Title", result)
        self.assertIn("## Abstract", result)
        self.assertIn("## Introduction", result)
        self.assertIn("## Related Work", result)
        # Out-of-scope sections should be removed
        self.assertNotIn("## Method", result)
        self.assertNotIn("## Experiments", result)
        self.assertNotIn("## Results", result)
        self.assertNotIn("## Discussion", result)
        self.assertNotIn("## Limitations", result)
        self.assertNotIn("## Conclusion", result)

    def test_call2_experimental_keeps_method_experiments(self):
        text = "## Method\nContent\n\n## Experiments\nMore\n\n## Results\nShould drop"
        result = _filter_allowed_sections(text, _CALL2_ALLOWED_EXP)
        self.assertIn("## Method", result)
        self.assertIn("## Experiments", result)
        self.assertNotIn("## Results", result)

    def test_call2_bibliographic_keeps_methods_results(self):
        text = "## Methods\nContent\n\n## Results\nMore\n\n## Discussion\nDrop"
        result = _filter_allowed_sections(text, _CALL2_ALLOWED_BIB)
        self.assertIn("## Methods", result)
        self.assertIn("## Results", result)
        self.assertNotIn("## Discussion", result)

    def test_call3_keeps_discussion_limitations_conclusion(self):
        text = "## Discussion\nD\n\n## Limitations\nL\n\n## Conclusion\nC\n\n## Method\nDrop"
        result = _filter_allowed_sections(text, _CALL3_ALLOWED_EXP)
        self.assertIn("## Discussion", result)
        self.assertIn("## Limitations", result)
        self.assertIn("## Conclusion", result)
        self.assertNotIn("## Method", result)

    def test_numbered_bold_sections_matched(self):
        """Sections like '## 5. **Methods**' should match 'methods'."""
        text = "## 5. **Methods**\nContent\n\n## 6. **Results**\nMore"
        result = _filter_allowed_sections(text, _CALL2_ALLOWED_BIB)
        self.assertIn("Methods", result)
        self.assertIn("Results", result)

    def test_empty_output_when_nothing_matches(self):
        text = "## Appendix A\nExtra content"
        result = _filter_allowed_sections(text, _CALL1_ALLOWED)
        # Should return empty or near-empty
        self.assertNotIn("Appendix", result)

    def test_allowed_sets_are_disjoint(self):
        """Call 1, 2, 3 allowed sets should not overlap significantly."""
        overlap_12 = _CALL1_ALLOWED & _CALL2_ALLOWED_EXP
        overlap_13 = _CALL1_ALLOWED & _CALL3_ALLOWED_EXP
        self.assertEqual(len(overlap_12), 0,
                         f"Call 1 and Call 2 (exp) should not overlap: {overlap_12}")
        self.assertEqual(len(overlap_13), 0,
                         f"Call 1 and Call 3 (exp) should not overlap: {overlap_13}")

    def test_filter_preserves_word_count(self):
        """Allowed sections should have their full content preserved."""
        text = "## Title\nMy Title\n\n## Abstract\nThis is a long abstract " + "word " * 100
        result = _filter_allowed_sections(text, _CALL1_ALLOWED)
        self.assertGreater(len(result.split()), 100)


# ---------------------------------------------------------------------------
# Tests for _match_reviews_to_sections
# ---------------------------------------------------------------------------

class TestMatchReviewsToSections(unittest.TestCase):
    """Tests for matching reviewer comments to sections."""

    def test_introduction_feedback_matched(self):
        headings = ["Introduction", "Method", "Discussion", "Limitations"]
        result = _match_reviews_to_sections(_REVIEWS, headings)
        intro = result.get("introduction", "")
        self.assertIn("Introduction", intro,
                       "Introduction-related feedback should match introduction section")

    def test_method_feedback_matched(self):
        headings = ["Introduction", "Method", "Discussion", "Limitations"]
        result = _match_reviews_to_sections(_REVIEWS, headings)
        method = result.get("method", "")
        self.assertIn("PICOS", method,
                       "PICOS feedback should match method section")

    def test_limitations_feedback_captured(self):
        """Feedback mentioning 'Limitations' is captured (may match discussion
        due to 'add discussion of' substring).  The important contract is
        that it's NOT lost — it lands in some section or _general."""
        headings = ["Introduction", "Method", "Discussion", "Limitations"]
        result = _match_reviews_to_sections(_REVIEWS, headings)
        # "publication bias" should appear SOMEWHERE in the matched results
        all_text = " ".join(result.values())
        self.assertIn("publication bias", all_text,
                       "Publication bias feedback should be captured somewhere")

    def test_general_feedback_captured(self):
        headings = ["Introduction", "Method", "Discussion"]
        result = _match_reviews_to_sections(_REVIEWS, headings)
        # Items that don't match specific sections go to _general
        self.assertIn("_general", result)

    def test_empty_reviews(self):
        headings = ["Introduction", "Method"]
        result = _match_reviews_to_sections("", headings)
        self.assertEqual(result["introduction"], "")
        self.assertEqual(result["method"], "")


# ---------------------------------------------------------------------------
# Tests for _revise_section_by_section
# ---------------------------------------------------------------------------

class TestReviseSectionBySection(unittest.TestCase):
    """Tests for section-by-section revision logic."""

    def test_returns_empty_for_unsplittable_text(self):
        """If text has no ## headers, should return empty string."""
        from researchclaw.pipeline.executor import _revise_section_by_section
        mock_llm = MagicMock()
        result = _revise_section_by_section(
            llm=mock_llm,
            draft="Just plain text without headers",
            reviews="Some feedback",
            system_prompt="You are a reviewer",
            max_tokens_per_section=2048,
        )
        self.assertEqual(result, "")
        mock_llm.chat.assert_not_called()

    def test_keeps_original_if_revision_too_short(self):
        """If a section revision is <70% of original, keep original."""
        from researchclaw.pipeline.executor import _revise_section_by_section

        long_intro = "## Introduction\n" + "Word " * 200
        draft = f"## Title\nMy Title\n\n{long_intro}\n\n## Conclusion\nShort conclusion."

        mock_llm = MagicMock()
        # Mock returns very short revision for Intro
        short_response = MagicMock()
        short_response.content = "## Introduction\nToo short."
        # For Conclusion, return adequate length
        ok_response = MagicMock()
        ok_response.content = "## Conclusion\nShort conclusion revised adequately."
        mock_llm.chat.side_effect = [short_response, ok_response]

        result = _revise_section_by_section(
            llm=mock_llm,
            draft=draft,
            reviews="Expand the introduction.",
            system_prompt="Revise",
            max_tokens_per_section=2048,
        )
        # Original long intro should be preserved (fallback)
        self.assertIn("Word " * 10, result)

    def test_revision_succeeds_with_adequate_length(self):
        """If revision meets length threshold, it replaces original."""
        from researchclaw.pipeline.executor import _revise_section_by_section

        draft = "## Title\nTitle\n\n## Abstract\n" + "Original abstract " * 20

        mock_llm = MagicMock()
        response = MagicMock()
        response.content = "## Abstract\n" + "Revised abstract content " * 25
        mock_llm.chat.return_value = response

        result = _revise_section_by_section(
            llm=mock_llm,
            draft=draft,
            reviews="Improve the abstract.",
            system_prompt="Revise",
            max_tokens_per_section=2048,
        )
        self.assertIn("Revised abstract content", result)


# ---------------------------------------------------------------------------
# Integration test: verify Stage 19 code path selection
# ---------------------------------------------------------------------------

class TestStage19CodePath(unittest.TestCase):
    """Verify _execute_paper_revision selects the right strategy."""

    def test_local_model_detected_in_revision(self):
        """_execute_paper_revision source should contain CLOUD_PREFIXES_19."""
        import inspect
        from researchclaw.pipeline.executor import _execute_paper_revision
        source = inspect.getsource(_execute_paper_revision)
        self.assertIn("_CLOUD_PREFIXES_19", source)
        self.assertIn("_is_local_19", source)
        self.assertIn("_revise_section_by_section", source)

    def test_cloud_model_uses_monolithic(self):
        """Cloud models should still use monolithic revision."""
        import inspect
        from researchclaw.pipeline.executor import _execute_paper_revision
        source = inspect.getsource(_execute_paper_revision)
        # The else branch should still have the monolithic code
        self.assertIn("R10-Fix4", source)
        self.assertIn("revision_max_tokens", source)


# ---------------------------------------------------------------------------
# Tests for Call 1 split constants (FASE-5)
# ---------------------------------------------------------------------------

class TestCall1SplitConstants(unittest.TestCase):
    """Verify the Call 1 sub-call allowed sets are correct."""

    def test_call1a_is_title_abstract(self):
        self.assertEqual(_CALL1A_ALLOWED, {"title", "abstract"})

    def test_call1b_is_intro_related_work(self):
        self.assertEqual(_CALL1B_ALLOWED, {"introduction", "related work"})

    def test_split_union_equals_call1(self):
        """1a ∪ 1b should exactly equal _CALL1_ALLOWED."""
        self.assertEqual(_CALL1A_ALLOWED | _CALL1B_ALLOWED, _CALL1_ALLOWED)

    def test_split_sets_disjoint(self):
        """1a and 1b should not overlap."""
        self.assertEqual(len(_CALL1A_ALLOWED & _CALL1B_ALLOWED), 0)

    def test_filter_call1a_removes_intro(self):
        """Filtering with _CALL1A_ALLOWED should remove Introduction."""
        text = "## Title\nMy Title\n\n## Abstract\nAbstract text\n\n## Introduction\nShould be removed"
        result = _filter_allowed_sections(text, _CALL1A_ALLOWED)
        self.assertIn("## Title", result)
        self.assertIn("## Abstract", result)
        self.assertNotIn("## Introduction", result)

    def test_filter_call1b_removes_title(self):
        """Filtering with _CALL1B_ALLOWED should remove Title and Abstract."""
        text = "## Title\nRemove me\n\n## Introduction\nKeep me\n\n## Related Work\nKeep me too"
        result = _filter_allowed_sections(text, _CALL1B_ALLOWED)
        self.assertNotIn("## Title", result)
        self.assertIn("## Introduction", result)
        self.assertIn("## Related Work", result)


class TestCall1SplitCodePath(unittest.TestCase):
    """Verify the split Call 1 code path exists in _write_paper_sections."""

    def test_split_call1_code_present(self):
        """Source should contain FASE-5 split logic."""
        import inspect
        from researchclaw.pipeline.executor import _write_paper_sections
        source = inspect.getsource(_write_paper_sections)
        self.assertIn("_split_call1", source)
        self.assertIn("Call 1a", source)
        self.assertIn("Call 1b", source)
        self.assertIn("_CALL1A_ALLOWED", source)
        self.assertIn("_CALL1B_ALLOWED", source)

    def test_split_only_for_bibliographic_local(self):
        """Split should be conditional on is_bibliographic and _is_likely_local."""
        import inspect
        from researchclaw.pipeline.executor import _write_paper_sections
        source = inspect.getsource(_write_paper_sections)
        self.assertIn("is_bibliographic and _is_likely_local", source)

    def test_call1b_prompt_has_length_requirements(self):
        """Call 1b prompt should demand 800-1000 words for Introduction."""
        import inspect
        from researchclaw.pipeline.executor import _write_paper_sections
        source = inspect.getsource(_write_paper_sections)
        self.assertIn("800-1000 words", source)
        self.assertIn("at least 800 words", source)


if __name__ == "__main__":
    unittest.main()
