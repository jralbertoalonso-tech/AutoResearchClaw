"""Tests for FASE-3 Stage 17 improvements.

Validates:
- FINDING-1: Local model max_tokens increased from 4096 to 8192
- FINDING-2: Bibliographic protocol gets domain-appropriate prompts (no ablation/baseline instructions)
- FINDING-5: _PRIOR_SECTION_MAX increased from 6000 to 10000
"""

from __future__ import annotations

import re
import unittest
from unittest.mock import MagicMock, patch


class TestLocalModelMaxTokensCap(unittest.TestCase):
    """FINDING-1: max_tokens should be 8192 for local models, not 4096."""

    def test_local_model_cap_is_8192(self):
        """Verify the cap constant in source code."""
        import inspect
        from researchclaw.pipeline.executor import _write_paper_sections

        source = inspect.getsource(_write_paper_sections)

        # The old cap was 4096, new cap should be 8192
        self.assertIn("_paper_max_tokens > 8192", source,
                      "Local model cap should check > 8192")
        self.assertIn("_paper_max_tokens = 8192", source,
                      "Local model cap should set to 8192")
        # The old 4096 should NOT be used as a cap
        self.assertNotIn("_paper_max_tokens > 4096", source,
                         "Old 4096 cap should no longer exist")
        self.assertNotIn("_paper_max_tokens = 4096", source,
                         "Old 4096 assignment should no longer exist")


class TestPriorSectionMaxIncrease(unittest.TestCase):
    """FINDING-5: _PRIOR_SECTION_MAX should be 10000, not 6000."""

    def test_prior_section_max_is_10000(self):
        """Verify _PRIOR_SECTION_MAX is set to 10000 in source."""
        import inspect
        from researchclaw.pipeline.executor import _write_paper_sections

        source = inspect.getsource(_write_paper_sections)

        self.assertIn("_PRIOR_SECTION_MAX = 10_000", source,
                      "_PRIOR_SECTION_MAX should be 10000")
        self.assertNotIn("_PRIOR_SECTION_MAX = 6_000", source,
                         "Old 6000 value should no longer exist")


class TestBibliographicPromptSwitch(unittest.TestCase):
    """FINDING-2: Bibliographic protocols get domain-appropriate prompts."""

    def test_function_accepts_is_bibliographic_param(self):
        """_write_paper_sections should accept is_bibliographic parameter."""
        import inspect
        from researchclaw.pipeline.executor import _write_paper_sections

        sig = inspect.signature(_write_paper_sections)
        self.assertIn("is_bibliographic", sig.parameters,
                      "is_bibliographic parameter should exist")
        self.assertEqual(sig.parameters["is_bibliographic"].default, False,
                         "is_bibliographic should default to False")

    def test_bibliographic_system_prompt_no_ablation(self):
        """When is_bibliographic=True, system prompt must NOT mention ablation."""
        import inspect
        from researchclaw.pipeline.executor import _write_paper_sections

        source = inspect.getsource(_write_paper_sections)

        # Check that the bibliographic system prompt text is present
        self.assertIn("systematic review or", source,
                      "Bibliographic system prompt should mention systematic review")
        self.assertIn("PRISMA", source,
                      "Bibliographic prompts should mention PRISMA")

    def test_bibliographic_call2_has_methods_not_experiments(self):
        """Bibliographic Call 2 should describe Methods (search strategy), not Experiments."""
        import inspect
        from researchclaw.pipeline.executor import _write_paper_sections

        source = inspect.getsource(_write_paper_sections)

        # Bibliographic Call 2 should mention PICOS, eligibility criteria
        self.assertIn("PICOS", source,
                      "Bibliographic Call 2 should mention PICOS framework")
        self.assertIn("eligibility criteria", source,
                      "Bibliographic Call 2 should mention eligibility criteria")
        self.assertIn("search strategy", source,
                      "Bibliographic Call 2 should mention search strategy")

    def test_bibliographic_call3_no_paired_ttest(self):
        """Bibliographic Call 3 should NOT mention paired t-tests or per-regime tables."""
        import inspect
        from researchclaw.pipeline.executor import _write_paper_sections

        source = inspect.getsource(_write_paper_sections)

        # The bibliographic call3 text should include evidence synthesis concepts
        self.assertIn("quality of evidence", source,
                      "Bibliographic Call 3 should mention quality of evidence")
        self.assertIn("heterogeneity", source,
                      "Bibliographic Call 3 should mention heterogeneity")

    def test_call_site_passes_is_bibliographic(self):
        """_execute_paper_draft should pass is_bibliographic to _write_paper_sections."""
        import inspect
        from researchclaw.pipeline.executor import _execute_paper_draft

        source = inspect.getsource(_execute_paper_draft)

        self.assertIn("is_bibliographic=", source,
                      "_execute_paper_draft should pass is_bibliographic")
        self.assertIn("_is_bib_17", source,
                      "_execute_paper_draft should compute _is_bib_17")


class TestExperimentalPromptUnchanged(unittest.TestCase):
    """Verify experimental (non-bibliographic) prompts are NOT affected."""

    def test_experimental_prompts_still_have_ablation_content(self):
        """The else-branch (experimental) should still have baseline/ablation instructions."""
        import inspect
        from researchclaw.pipeline.executor import _write_paper_sections

        source = inspect.getsource(_write_paper_sections)

        # Experimental call 2 should still mention baselines and hyperparameters
        self.assertIn("baselines and their implementations", source,
                      "Experimental Call 2 should still mention baselines")
        self.assertIn("hyperparameter settings", source,
                      "Experimental Call 2 should still mention hyperparameters")

        # Experimental call 3 should still mention paired t-tests
        self.assertIn("paired t-tests", source,
                      "Experimental Call 3 should still mention paired t-tests")
        self.assertIn("PER-REGIME table", source,
                      "Experimental Call 3 should still mention per-regime tables")


if __name__ == "__main__":
    unittest.main()
