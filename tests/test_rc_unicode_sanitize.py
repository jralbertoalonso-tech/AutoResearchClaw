"""Tests for Unicode sanitization in LaTeX compilation.

Covers the sanitize_unicode() function that replaces Unicode characters
pdflatex cannot handle with their LaTeX equivalents.
"""

from __future__ import annotations

import unittest

from researchclaw.templates.compiler import sanitize_unicode, _UNICODE_TO_LATEX


class TestSanitizeUnicodeGreek(unittest.TestCase):
    """Greek letters must be replaced with LaTeX math-mode commands."""

    def test_kappa_replaced(self):
        """The exact character that caused the production failure."""
        text = r"The coefficient \kappa{} was... wait, raw: κ appears here."
        result, count = sanitize_unicode(text)
        self.assertNotIn("\u03ba", result)
        self.assertIn("$\\kappa$", result)
        self.assertGreaterEqual(count, 1)

    def test_alpha_beta_gamma(self):
        text = "Values: α=0.05, β=0.8, γ=1.2"
        result, count = sanitize_unicode(text)
        self.assertIn("$\\alpha$", result)
        self.assertIn("$\\beta$", result)
        self.assertIn("$\\gamma$", result)
        self.assertEqual(count, 3)

    def test_uppercase_greek(self):
        text = "Matrices Σ and Ω and Δ"
        result, count = sanitize_unicode(text)
        self.assertIn("$\\Sigma$", result)
        self.assertIn("$\\Omega$", result)
        self.assertIn("$\\Delta$", result)
        self.assertEqual(count, 3)

    def test_pi_sigma_theta(self):
        text = "π radians, σ deviation, θ angle"
        result, count = sanitize_unicode(text)
        self.assertIn("$\\pi$", result)
        self.assertIn("$\\sigma$", result)
        self.assertIn("$\\theta$", result)


class TestSanitizeUnicodeMath(unittest.TestCase):
    """Math symbols must be replaced with LaTeX commands."""

    def test_plus_minus(self):
        text = "Result: 3.14 ± 0.05"
        result, count = sanitize_unicode(text)
        self.assertIn("$\\pm$", result)
        self.assertEqual(count, 1)

    def test_comparison_operators(self):
        text = "p ≤ 0.05, x ≥ 10, a ≠ b"
        result, count = sanitize_unicode(text)
        self.assertIn("$\\leq$", result)
        self.assertIn("$\\geq$", result)
        self.assertIn("$\\neq$", result)
        self.assertEqual(count, 3)

    def test_times_div(self):
        text = "3 × 4 ÷ 2"
        result, count = sanitize_unicode(text)
        self.assertIn("$\\times$", result)
        self.assertIn("$\\div$", result)

    def test_arrows(self):
        text = "A → B ← C ⇒ D"
        result, count = sanitize_unicode(text)
        self.assertIn("$\\rightarrow$", result)
        self.assertIn("$\\leftarrow$", result)
        self.assertIn("$\\Rightarrow$", result)

    def test_infinity_approx(self):
        text = "n → ∞, x ≈ 3.14"
        result, count = sanitize_unicode(text)
        self.assertIn("$\\infty$", result)
        self.assertIn("$\\approx$", result)


class TestSanitizeUnicodeTypographic(unittest.TestCase):
    """Typographic characters must be replaced with LaTeX equivalents."""

    def test_smart_quotes(self):
        text = "\u201cHello\u201d and \u2018world\u2019"
        result, count = sanitize_unicode(text)
        self.assertIn("``", result)
        self.assertIn("''", result)
        self.assertEqual(count, 4)

    def test_em_en_dash(self):
        text = "pages 1\u20135 and also\u2014importantly"
        result, count = sanitize_unicode(text)
        self.assertIn("--", result)
        self.assertIn("---", result)

    def test_ellipsis(self):
        text = "and so on\u2026"
        result, count = sanitize_unicode(text)
        self.assertIn("\\ldots{}", result)

    def test_degree_symbol(self):
        text = "Temperature: 37°C"
        result, count = sanitize_unicode(text)
        self.assertIn("$^\\circ$", result)

    def test_nbsp(self):
        text = "non\u00a0breaking\u00a0space"
        result, count = sanitize_unicode(text)
        self.assertIn("~", result)


class TestSanitizeUnicodeAccented(unittest.TestCase):
    """Accented Latin characters common in medical/Spanish text."""

    def test_spanish_accents(self):
        text = "Eficacia y seguridad de la curcumina en pediatría"
        result, count = sanitize_unicode(text)
        self.assertNotIn("í", result)
        self.assertIn("\\'", result)  # LaTeX accent command

    def test_french_accents(self):
        text = "résumé and naïve and café"
        result, count = sanitize_unicode(text)
        self.assertNotIn("é", result)
        self.assertNotIn("ï", result)

    def test_german_umlauts(self):
        text = "über and Straße"
        result, count = sanitize_unicode(text)
        self.assertNotIn("ü", result)
        self.assertNotIn("ß", result)
        self.assertIn('\\"u', result)
        self.assertIn("\\ss{}", result)

    def test_cedilla(self):
        text = "façade and garçon"
        result, count = sanitize_unicode(text)
        self.assertNotIn("ç", result)
        self.assertIn("\\c{c}", result)


class TestSanitizeUnicodeEdgeCases(unittest.TestCase):
    """Edge cases and safety properties."""

    def test_pure_ascii_unchanged(self):
        text = "This is pure ASCII text with $\\alpha$ already in LaTeX."
        result, count = sanitize_unicode(text)
        self.assertEqual(result, text)
        self.assertEqual(count, 0)

    def test_empty_string(self):
        result, count = sanitize_unicode("")
        self.assertEqual(result, "")
        self.assertEqual(count, 0)

    def test_idempotent(self):
        """Running sanitize_unicode twice should give the same result."""
        text = "α ± β → γ, p ≤ 0.05, κ coefficient"
        result1, count1 = sanitize_unicode(text)
        result2, count2 = sanitize_unicode(result1)
        self.assertEqual(result1, result2)
        self.assertEqual(count2, 0)

    def test_unknown_unicode_replaced_with_space(self):
        """Characters not in the mapping should become spaces, not crash."""
        text = "Some text with \u4e2d\u6587 (Chinese) chars"
        result, count = sanitize_unicode(text)
        self.assertNotIn("\u4e2d", result)
        self.assertNotIn("\u6587", result)
        self.assertGreaterEqual(count, 2)

    def test_preserves_newlines_and_tabs(self):
        text = "Line 1\nLine 2\tTabbed"
        result, count = sanitize_unicode(text)
        self.assertEqual(result, text)
        self.assertEqual(count, 0)

    def test_mixed_content(self):
        """Realistic LaTeX content with mixed Unicode."""
        text = (
            "\\begin{abstract}\n"
            "We study the effect of κ-casein on β-lactoglobulin "
            "at temperatures ≥ 37°C (p ≤ 0.05, α = 0.01). "
            "Results show a ± 5\\% improvement.\n"
            "\\end{abstract}"
        )
        result, count = sanitize_unicode(text)
        # LaTeX structure preserved
        self.assertIn("\\begin{abstract}", result)
        self.assertIn("\\end{abstract}", result)
        # Unicode replaced
        self.assertNotIn("κ", result)
        self.assertNotIn("β", result)
        self.assertNotIn("≥", result)
        self.assertIn("$\\kappa$", result)
        self.assertIn("$\\beta$", result)

    def test_mapping_count(self):
        """Verify we have a reasonable number of mappings."""
        self.assertGreaterEqual(len(_UNICODE_TO_LATEX), 80,
                                "Should have at least 80 Unicode→LaTeX mappings")


class TestSanitizeUnicodeInCompiler(unittest.TestCase):
    """Verify integration with compile_latex."""

    def test_compile_latex_calls_sanitize(self):
        """compile_latex source should reference sanitize_unicode."""
        import inspect
        from researchclaw.templates.compiler import compile_latex
        source = inspect.getsource(compile_latex)
        self.assertIn("sanitize_unicode", source)
        self.assertIn("Unicode", source)


if __name__ == "__main__":
    unittest.main()
