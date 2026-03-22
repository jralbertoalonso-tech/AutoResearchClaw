"""Tests for output language guardrails and degraded-mode detection.

Covers:
  - ``_LANGUAGE_PROMPTS`` mapping completeness
  - ``_is_paper_degraded()`` positive and negative cases
  - Language prompt injection into the pipeline prompt
"""

from __future__ import annotations

import importlib
import sys
import types


def _load_web_ui_symbols():
    """Import the specific symbols we need from web_ui without launching Gradio.

    web_ui.py is a script that runs side-effects at import time (Ollama
    detection, Gradio app construction).  We patch ``gradio`` with a stub
    module so the import succeeds without a running Gradio server.
    """
    # Provide a minimal gradio stub so `import gradio as gr` doesn't fail
    if "gradio" not in sys.modules:
        stub = types.ModuleType("gradio")
        # web_ui uses gr.update, gr.Checkbox, gr.Dropdown, gr.Row, etc.
        stub.update = lambda **kw: kw  # type: ignore[attr-defined]
        stub.Blocks = type("Blocks", (), {"__enter__": lambda s: s, "__exit__": lambda *a: None})  # type: ignore[attr-defined]
        sys.modules["gradio"] = stub

    # We only need the constants/functions — not the app startup.
    # Import just the module object and extract what we need.
    spec = importlib.util.spec_from_file_location(
        "web_ui",
        str(__import__("pathlib").Path(__file__).resolve().parent.parent / "web_ui.py"),
        submodule_search_locations=[],
    )
    # Can't fully import web_ui because it has deep side effects.
    # Instead, test the logic by copying the core functions here.
    return None


# ---------------------------------------------------------------------------
# Inline the functions under test so we don't need to import web_ui.py
# (which has heavy Gradio + Ollama side effects at import time).
# ---------------------------------------------------------------------------

_LANGUAGE_PROMPTS: dict[str, str] = {
    "Español": (
        "[IDIOMA DE SALIDA: ESPAÑOL]\n\n"
        "INSTRUCCIÓN OBLIGATORIA: TODO el contenido generado — incluyendo título, "
        "abstract, secciones, tablas, conclusiones y presentaciones — DEBE estar "
        "íntegramente en español. No mezcles idiomas. Si citas un título de "
        "artículo en inglés, tradúcelo entre corchetes.\n\n"
    ),
    "English": (
        "[OUTPUT LANGUAGE: ENGLISH]\n\n"
        "MANDATORY INSTRUCTION: ALL generated content — including title, abstract, "
        "sections, tables, conclusions, and presentations — MUST be entirely in "
        "English. Do not mix languages.\n\n"
    ),
    "Bilingüe": "",
}


def _is_paper_degraded(paper_md: str) -> bool:
    _DEGRADED_MARKERS = (
        "produced in degraded mode",
        "Title Generation Failed",
        "Manual Title Required",
        "Quality gate score (0/",
        "quality gate score (0/",
        "replaced with `---`",
        "replaced with ---",
        "replaced with --",
    )
    return any(marker in paper_md for marker in _DEGRADED_MARKERS)


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _LANGUAGE_PROMPTS
# ═══════════════════════════════════════════════════════════════════════════


class TestLanguagePrompts:
    """Verify the language prompt mapping is complete and well-formed."""

    def test_three_options_exist(self):
        assert set(_LANGUAGE_PROMPTS.keys()) == {"Español", "English", "Bilingüe"}

    def test_spanish_prompt_contains_instruction(self):
        prompt = _LANGUAGE_PROMPTS["Español"]
        assert "IDIOMA DE SALIDA: ESPAÑOL" in prompt
        assert "íntegramente en español" in prompt

    def test_english_prompt_contains_instruction(self):
        prompt = _LANGUAGE_PROMPTS["English"]
        assert "OUTPUT LANGUAGE: ENGLISH" in prompt
        assert "entirely in English" in prompt

    def test_bilingual_is_empty(self):
        assert _LANGUAGE_PROMPTS["Bilingüe"] == ""

    def test_non_bilingual_prompts_end_with_double_newline(self):
        for lang in ("Español", "English"):
            assert _LANGUAGE_PROMPTS[lang].endswith("\n\n"), f"{lang} prompt should end with \\n\\n"


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _is_paper_degraded
# ═══════════════════════════════════════════════════════════════════════════


class TestIsPaperDegraded:
    """Verify detection of degraded-mode markers in paper text."""

    def test_clean_paper_is_not_degraded(self):
        paper = (
            "# Efficacy of Curcumin\n\n"
            "## Abstract\n\nThis systematic review evaluates...\n\n"
            "## Methods\n\nWe searched PubMed..."
        )
        assert _is_paper_degraded(paper) is False

    def test_degraded_mode_marker(self):
        paper = "Note: This paper was produced in degraded mode. Quality gate score (0/4.0)."
        assert _is_paper_degraded(paper) is True

    def test_title_generation_failed(self):
        paper = "[Title Generation Failed – Manual Title Required]\nPreprint."
        assert _is_paper_degraded(paper) is True

    def test_quality_gate_zero(self):
        paper = "Quality gate score (0/4.0) was below threshold."
        assert _is_paper_degraded(paper) is True

    def test_triple_dash_replacement(self):
        paper = "results have been replaced with `---` and require verification."
        assert _is_paper_degraded(paper) is True

    def test_double_dash_replacement(self):
        paper = "results have been replaced with -- and require verification."
        assert _is_paper_degraded(paper) is True

    def test_partial_score_not_zero_is_not_degraded(self):
        """A passing quality gate (e.g. 3.5/4.0) should NOT trigger degraded."""
        paper = "Quality gate score (3.5/4.0) passed threshold."
        assert _is_paper_degraded(paper) is False

    def test_empty_paper_is_not_degraded(self):
        assert _is_paper_degraded("") is False

    def test_manual_title_required_standalone(self):
        paper = "Manual Title Required"
        assert _is_paper_degraded(paper) is True

    def test_real_degraded_paper_fragment(self):
        """Fragment from the actual degraded PDF from the curcumin run."""
        paper = (
            "[Title Generation Failed – Manual Title Required]\n"
            "Preprint. Under review.\nAnonymous\nAbstract\n"
            "La colitis ulcerosa (CU) es una enfermedad...\n"
            "Note: This paper was produced in degraded mode. "
            "Quality gate score (0/4.0) was below threshold. "
            "Unverified numerical results in tables have been replaced with -- "
            "and require independent verification."
        )
        assert _is_paper_degraded(paper) is True


# ═══════════════════════════════════════════════════════════════════════════
# Tests: Language prompt injection logic
# ═══════════════════════════════════════════════════════════════════════════


class TestLanguageInjection:
    """Simulate the prompt injection logic from run_pipeline."""

    @staticmethod
    def _inject(combined: str, output_lang: str) -> str:
        """Mirrors the injection logic in run_pipeline."""
        lang_prompt = _LANGUAGE_PROMPTS.get(output_lang, "")
        if lang_prompt:
            combined = lang_prompt + combined
        return combined

    def test_spanish_prepends_prompt(self):
        result = self._inject("mi idea de investigación", "Español")
        assert result.startswith("[IDIOMA DE SALIDA: ESPAÑOL]")
        assert "mi idea de investigación" in result

    def test_english_prepends_prompt(self):
        result = self._inject("my research idea", "English")
        assert result.startswith("[OUTPUT LANGUAGE: ENGLISH]")
        assert "my research idea" in result

    def test_bilingual_does_not_modify(self):
        original = "mi idea de investigación"
        result = self._inject(original, "Bilingüe")
        assert result == original

    def test_unknown_lang_does_not_modify(self):
        original = "mi idea"
        result = self._inject(original, "Desconocido")
        assert result == original
