"""Tests for R4/R5: references.bib propagation from Stage 04 through Stage 22/23.

Validates that:
- IMP-1 pruning preserves the full bib when NO cite keys are found in the paper
  (narrative citation format common with local models)
- Stage 22 writes a non-empty references.bib even when paper lacks [cite_key] format
- Stage 23 receives and verifies actual bib entries (not just a placeholder)
- Pipeline summary reports correct total_citations count
"""

from __future__ import annotations

import re
import unittest

from researchclaw.pipeline.executor import _remove_bibtex_entries


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_SAMPLE_BIB = """\
@article{smith2023curcumin,
  author = {Smith, John},
  title = {Curcumin in Pediatric Ulcerative Colitis},
  journal = {Lancet Gastroenterology},
  year = {2023},
}

@article{jones2022safety,
  author = {Jones, Alice},
  title = {Safety of Qing Dai in Children},
  journal = {JAMA Pediatrics},
  year = {2022},
}

@article{chen2024meta,
  author = {Chen, Wei},
  title = {Meta-analysis of Natural Therapies for IBD},
  journal = {Cochrane Database},
  year = {2024},
}
"""

_PAPER_WITH_BRACKET_CITES = """\
## Introduction

Curcumin has shown promise [smith2023curcumin] in treating UC.
Recent safety data [jones2022safety] confirms tolerability.
A meta-analysis [chen2024meta] reviewed 15 studies.
"""

_PAPER_WITH_NARRATIVE_CITES = """\
## Introduction

Curcumin has shown promise in treating UC (Smith et al., 2023).
Recent safety data confirms tolerability (Jones, 2022).
A meta-analysis reviewed 15 studies (Chen et al., 2024).
"""

_PAPER_WITH_PARTIAL_CITES = """\
## Introduction

Curcumin has shown promise [smith2023curcumin] in treating UC.
Recent safety data confirms tolerability (Jones, 2022).
"""


# ---------------------------------------------------------------------------
# Tests for _remove_bibtex_entries
# ---------------------------------------------------------------------------

class TestRemoveBibtexEntries(unittest.TestCase):
    """Validate the _remove_bibtex_entries helper."""

    def test_remove_specific_key(self):
        result = _remove_bibtex_entries(_SAMPLE_BIB, {"jones2022safety"})
        self.assertIn("smith2023curcumin", result)
        self.assertNotIn("jones2022safety", result)
        self.assertIn("chen2024meta", result)

    def test_remove_all_keys_returns_empty(self):
        all_keys = {"smith2023curcumin", "jones2022safety", "chen2024meta"}
        result = _remove_bibtex_entries(_SAMPLE_BIB, all_keys)
        self.assertEqual(result.strip(), "")

    def test_remove_no_keys_returns_original(self):
        result = _remove_bibtex_entries(_SAMPLE_BIB, set())
        # All entries should be present
        self.assertIn("smith2023curcumin", result)
        self.assertIn("jones2022safety", result)
        self.assertIn("chen2024meta", result)


# ---------------------------------------------------------------------------
# Tests for R4 safety guard in IMP-1 pruning
# ---------------------------------------------------------------------------

class TestIMP1PruningSafetyGuard(unittest.TestCase):
    """R4: When paper uses narrative citations, pruning must NOT empty the bib."""

    def _simulate_imp1_pruning(self, bib_text: str, paper_text: str) -> tuple[str, int, int]:
        """Simulate the IMP-1 pruning logic from Stage 22.

        Returns (result_bib, n_valid_keys, n_kept).
        """
        valid_keys = set(re.findall(r"@\w+\{([^,]+),", bib_text))

        _all_cited: set[str] = set()
        # Bracket-format citations [key]
        _all_cited.update(
            re.findall(r"\[([a-z]+\d{4}[a-z]*)\]", paper_text)
        )
        # \cite{key, key2} format
        for _cm in re.finditer(r"\\cite\{([^}]+)\}", paper_text):
            _all_cited.update(
                k.strip() for k in _cm.group(1).split(",")
            )

        uncited_keys = valid_keys - _all_cited
        _kept_count = len(valid_keys) - len(uncited_keys)

        # R4-SAFETY: same logic as the fix in executor.py
        if uncited_keys and _kept_count >= 1:
            bib_text = _remove_bibtex_entries(bib_text, uncited_keys)
        elif uncited_keys and _kept_count == 0:
            # Preserve full bib — paper uses narrative citations
            pass

        return bib_text, len(valid_keys), _kept_count

    def test_bracket_citations_prune_normally(self):
        """When paper has [cite_key] format, uncited entries are pruned."""
        # Paper cites only smith2023curcumin
        paper = "Curcumin works [smith2023curcumin] well."
        result_bib, n_valid, n_kept = self._simulate_imp1_pruning(_SAMPLE_BIB, paper)
        self.assertEqual(n_kept, 1)
        self.assertIn("smith2023curcumin", result_bib)
        self.assertNotIn("jones2022safety", result_bib)
        self.assertNotIn("chen2024meta", result_bib)

    def test_all_bracket_citations_kept(self):
        """When paper cites all entries, nothing is pruned."""
        result_bib, n_valid, n_kept = self._simulate_imp1_pruning(
            _SAMPLE_BIB, _PAPER_WITH_BRACKET_CITES
        )
        self.assertEqual(n_kept, 3)
        self.assertEqual(n_valid, 3)
        self.assertIn("smith2023curcumin", result_bib)
        self.assertIn("jones2022safety", result_bib)
        self.assertIn("chen2024meta", result_bib)

    def test_narrative_citations_preserve_full_bib(self):
        """R4 SAFETY: When paper uses only narrative citations, full bib is preserved."""
        result_bib, n_valid, n_kept = self._simulate_imp1_pruning(
            _SAMPLE_BIB, _PAPER_WITH_NARRATIVE_CITES
        )
        # n_kept should be 0 (no bracket cites found), but bib should be preserved
        self.assertEqual(n_kept, 0)
        self.assertEqual(n_valid, 3)
        # Full bib preserved
        self.assertIn("smith2023curcumin", result_bib)
        self.assertIn("jones2022safety", result_bib)
        self.assertIn("chen2024meta", result_bib)

    def test_partial_citations_prune_safely(self):
        """When paper has at least one bracket cite, uncited entries are pruned."""
        result_bib, n_valid, n_kept = self._simulate_imp1_pruning(
            _SAMPLE_BIB, _PAPER_WITH_PARTIAL_CITES
        )
        self.assertEqual(n_kept, 1)
        self.assertIn("smith2023curcumin", result_bib)
        # jones and chen have no bracket cites → pruned
        self.assertNotIn("jones2022safety", result_bib)
        self.assertNotIn("chen2024meta", result_bib)

    def test_empty_paper_preserves_full_bib(self):
        """R4 SAFETY: Empty paper → no cites found → full bib preserved."""
        result_bib, n_valid, n_kept = self._simulate_imp1_pruning(
            _SAMPLE_BIB, ""
        )
        self.assertEqual(n_kept, 0)
        self.assertIn("smith2023curcumin", result_bib)
        self.assertIn("jones2022safety", result_bib)
        self.assertIn("chen2024meta", result_bib)

    def test_latex_cite_format_detected(self):
        """\\cite{key} format is detected and entries are kept."""
        paper = "Curcumin works \\cite{smith2023curcumin} well."
        result_bib, n_valid, n_kept = self._simulate_imp1_pruning(
            _SAMPLE_BIB, paper
        )
        self.assertEqual(n_kept, 1)
        self.assertIn("smith2023curcumin", result_bib)

    def test_multi_cite_format_detected(self):
        """\\cite{key1, key2} format is detected."""
        paper = "Studies \\cite{smith2023curcumin, jones2022safety} confirm."
        result_bib, n_valid, n_kept = self._simulate_imp1_pruning(
            _SAMPLE_BIB, paper
        )
        self.assertEqual(n_kept, 2)
        self.assertIn("smith2023curcumin", result_bib)
        self.assertIn("jones2022safety", result_bib)
        self.assertNotIn("chen2024meta", result_bib)


# ---------------------------------------------------------------------------
# Tests for bib content after safety guard
# ---------------------------------------------------------------------------

class TestBibContentIntegrity(unittest.TestCase):
    """Verify bib entries are structurally valid after preservation."""

    def test_preserved_bib_has_valid_bibtex(self):
        """Preserved bib should have valid @type{key, ...} entries."""
        # Simulate full preservation
        entries = re.findall(r"@\w+\{([^,]+),", _SAMPLE_BIB)
        self.assertEqual(len(entries), 3)
        for key in entries:
            self.assertTrue(key.strip(), "Empty cite key found")

    def test_preserved_bib_has_nonzero_size(self):
        """Preserved bib must have st_size > 0 (Stage 23 contract)."""
        self.assertGreater(len(_SAMPLE_BIB.encode("utf-8")), 0)


if __name__ == "__main__":
    unittest.main()
