"""Tests for ClinicalTrials.gov query sanitization and fallback logic.

Covers Bug D — HTTP 400 on long/non-English queries.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

from researchclaw.literature.clinicaltrials_client import (
    _sanitize_query,
    _shorten_query,
    search_clinicaltrials,
)


class TestSanitizeQuery(unittest.TestCase):
    """Tests for _sanitize_query — query cleaning before API call."""

    def test_short_english_query_unchanged(self):
        q = "curcumin ulcerative colitis"
        result = _sanitize_query(q)
        self.assertEqual(result, q)

    def test_long_query_truncated(self):
        q = "efficacy and safety " * 20  # 400 chars
        result = _sanitize_query(q)
        self.assertLessEqual(len(result), 210)  # _MAX_QUERY_CHARS + some margin for word boundary

    def test_truncation_at_word_boundary(self):
        q = "a " * 150  # 300 chars
        result = _sanitize_query(q)
        self.assertFalse(result.endswith(" "))
        self.assertLessEqual(len(result), 210)

    def test_spanish_accented_chars_preserved(self):
        q = "Eficacia y seguridad de la curcumina en colitis ulcerosa pediátrica"
        result = _sanitize_query(q)
        self.assertIn("Eficacia", result)
        self.assertIn("pediátrica", result)

    def test_guardrails_preamble_stripped(self):
        q = (
            "You are a research assistant.\n"
            "Follow these instructions carefully.\n"
            "\n"
            "Curcumin in ulcerative colitis"
        )
        result = _sanitize_query(q)
        self.assertNotIn("You are a", result)
        self.assertNotIn("Follow these", result)
        self.assertIn("Curcumin", result)

    def test_spanish_preamble_stripped(self):
        q = (
            "Actúa como investigador experto.\n"
            "INSTRUCCIONES: Busca artículos.\n"
            "\n"
            "Eficacia de la curcumina en pediatría"
        )
        result = _sanitize_query(q)
        self.assertNotIn("Actúa como", result)
        self.assertNotIn("INSTRUCCIONES", result)
        self.assertIn("curcumina", result)

    def test_special_chars_removed(self):
        q = 'efficacy "curcumin" [ulcerative colitis] {pediatric}'
        result = _sanitize_query(q)
        # Brackets/braces/quotes should be replaced with spaces
        self.assertNotIn("[", result)
        self.assertNotIn("{", result)
        self.assertNotIn('"', result)
        # Core terms preserved
        self.assertIn("curcumin", result)

    def test_empty_query(self):
        self.assertEqual(_sanitize_query(""), "")
        self.assertEqual(_sanitize_query("   "), "")

    def test_real_production_query(self):
        """Exact query from the production log that caused HTTP 400."""
        q = "Eficacia y seguridad de la curcumina y Qing dai en la colitis ulcerosa en pediatría"
        result = _sanitize_query(q)
        self.assertLessEqual(len(result), 210)
        self.assertIn("curcumina", result)
        self.assertIn("Qing dai", result)


class TestShortenQuery(unittest.TestCase):
    """Tests for _shorten_query — fallback to first N meaningful words."""

    def test_extracts_meaningful_words(self):
        q = "Eficacia y seguridad de la curcumina en colitis ulcerosa"
        result = _shorten_query(q, max_words=4)
        words = result.split()
        self.assertLessEqual(len(words), 4)
        # Stop words like "y", "de", "la", "en" should be removed
        for w in words:
            self.assertNotIn(w.lower(), {"y", "de", "la", "en"})

    def test_english_stop_words_removed(self):
        q = "the efficacy and safety of curcumin in pediatric colitis"
        result = _shorten_query(q, max_words=3)
        words = result.split()
        self.assertLessEqual(len(words), 3)
        self.assertNotIn("the", [w.lower() for w in words])
        self.assertNotIn("and", [w.lower() for w in words])

    def test_very_short_query_returned_as_is(self):
        q = "curcumin"
        result = _shorten_query(q, max_words=4)
        self.assertEqual(result, "curcumin")


class TestSearchClinicaltrials(unittest.TestCase):
    """Integration tests for search_clinicaltrials with mocked HTTP."""

    @patch("researchclaw.literature.clinicaltrials_client._get_json")
    @patch("researchclaw.literature.clinicaltrials_client._rate_wait")
    def test_successful_search(self, _mock_wait, mock_get):
        mock_get.return_value = {"studies": []}
        result = search_clinicaltrials("curcumin colitis", limit=5)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)
        mock_get.assert_called_once()

    @patch("researchclaw.literature.clinicaltrials_client._get_json")
    @patch("researchclaw.literature.clinicaltrials_client._rate_wait")
    def test_query_is_sanitized_before_call(self, _mock_wait, mock_get):
        """Verify the API receives a sanitized query, not the raw input."""
        mock_get.return_value = {"studies": []}
        raw = "You are a research assistant.\n\nCurcumin colitis"
        search_clinicaltrials(raw, limit=5)
        # The URL passed to _get_json should contain the sanitized query
        call_url = mock_get.call_args[0][0]
        self.assertNotIn("You+are+a", call_url)
        self.assertIn("Curcumin", call_url)

    @patch("researchclaw.literature.clinicaltrials_client._get_json")
    @patch("researchclaw.literature.clinicaltrials_client._rate_wait")
    def test_fallback_on_first_failure(self, _mock_wait, mock_get):
        """When first query returns None (400), retry with shortened query."""
        mock_get.side_effect = [None, {"studies": []}]
        result = search_clinicaltrials(
            "Eficacia y seguridad de la curcumina en la colitis ulcerosa", limit=5
        )
        self.assertIsInstance(result, list)
        # Should have been called twice: first sanitized, then shortened
        self.assertEqual(mock_get.call_count, 2)

    @patch("researchclaw.literature.clinicaltrials_client._get_json")
    @patch("researchclaw.literature.clinicaltrials_client._rate_wait")
    def test_empty_query_after_sanitization(self, _mock_wait, mock_get):
        """If sanitization yields empty string, return empty list without calling API."""
        result = search_clinicaltrials("   ", limit=5)
        self.assertEqual(result, [])
        mock_get.assert_not_called()

    @patch("researchclaw.literature.clinicaltrials_client._get_json")
    @patch("researchclaw.literature.clinicaltrials_client._rate_wait")
    def test_both_attempts_fail(self, _mock_wait, mock_get):
        """When both sanitized and shortened queries fail, return empty list."""
        mock_get.return_value = None
        result = search_clinicaltrials(
            "Eficacia y seguridad de la curcumina en colitis", limit=5
        )
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
