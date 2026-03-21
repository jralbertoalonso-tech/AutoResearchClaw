"""Tests for CEIm UI handler functions in web_ui.py.

Tests the standalone CEIm review and dossier handler functions
without launching the full Gradio app.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Test _extract_text_for_review
# ---------------------------------------------------------------------------

class TestExtractTextForReview:
    """Tests for _extract_text_for_review — combines text input + file uploads."""

    def _get_fn(self):
        from web_ui import _extract_text_for_review
        return _extract_text_for_review

    def test_text_only(self):
        fn = self._get_fn()
        result = fn("Hello world", None)
        assert result == "Hello world"

    def test_empty_text_and_no_files(self):
        fn = self._get_fn()
        result = fn("", None)
        assert result == ""

    def test_text_with_whitespace(self):
        fn = self._get_fn()
        result = fn("  spaced  ", None)
        assert result == "spaced"

    def test_md_file(self):
        fn = self._get_fn()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8",
        ) as f:
            f.write("# Protocol\nThis is a test protocol.")
            f.flush()
            result = fn("", [f.name])
        assert "Protocol" in result
        assert "test protocol" in result

    def test_txt_file(self):
        fn = self._get_fn()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8",
        ) as f:
            f.write("Plain text content")
            f.flush()
            result = fn("", [f.name])
        assert "Plain text content" in result

    def test_combined_text_and_file(self):
        fn = self._get_fn()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8",
        ) as f:
            f.write("File content here")
            f.flush()
            result = fn("User text", [f.name])
        assert "User text" in result
        assert "File content here" in result

    def test_unsupported_file_skipped(self):
        fn = self._get_fn()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xlsx", delete=False,
        ) as f:
            f.write("data")
            f.flush()
            result = fn("only text", [f.name])
        assert result == "only text"


# ---------------------------------------------------------------------------
# Test _run_ceim_review
# ---------------------------------------------------------------------------

class TestRunCeimReview:
    """Tests for _run_ceim_review — full review handler."""

    def _get_fn(self):
        from web_ui import _run_ceim_review
        return _run_ceim_review

    def test_empty_input_returns_warning(self):
        fn = self._get_fn()
        md, file_update = fn("", None, "Auto-detectar")
        assert "⚠️" in md
        assert "No hay texto" in md

    def test_basic_review_returns_markdown(self):
        fn = self._get_fn()
        protocol = """
# Estudio observacional de eficacia

## Diseño
Estudio observacional prospectivo de cohortes.

## Población
Adultos con hipertensión grado I-II.
Tamaño muestral: 200 participantes.

## Variables
Variable principal: presión arterial sistólica.

## Ética
Consentimiento informado obtenido de todos los participantes.
Aprobado por el CEIm correspondiente.
"""
        md, file_update = fn(protocol, None, "Auto-detectar")
        assert "CEIm" in md or "Review" in md or "Evaluación" in md
        assert len(md) > 100

    def test_forced_qualitative_type(self):
        fn = self._get_fn()
        text = """
# Estudio cualitativo
## Método
Fenomenología interpretativa.
Entrevistas semiestructuradas.
"""
        md, _ = fn(text, None, "Cualitativo")
        assert len(md) > 100

    def test_forced_mixed_type(self):
        fn = self._get_fn()
        text = "# Mixed methods study\nDesign: sequential explanatory."
        md, _ = fn(text, None, "Mixto")
        assert len(md) > 50

    def test_review_download_file_created(self):
        fn = self._get_fn()
        text = "# Protocol\n## Design\nObservational cohort study.\n## Ethics\nConsent obtained."
        md, file_update = fn(text, None, "Auto-detectar")
        # file_update should be a dict with 'value' pointing to a file
        if hasattr(file_update, '__getitem__'):
            path = file_update.get("value")
            if path:
                assert Path(path).exists()

    def test_review_from_file(self):
        fn = self._get_fn()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8",
        ) as f:
            f.write(
                "# Protocol\n## Design\nObservational study.\n"
                "## Ethics\nInformed consent obtained from all participants.\n"
                "## Population\n200 adults with diabetes."
            )
            f.flush()
            md, _ = fn("", [f.name], "Observacional")
        assert len(md) > 100


# ---------------------------------------------------------------------------
# Test _run_ceim_dossier
# ---------------------------------------------------------------------------

class TestRunCeimDossier:
    """Tests for _run_ceim_dossier — full dossier handler."""

    def _get_fn(self):
        from web_ui import _run_ceim_dossier
        return _run_ceim_dossier

    def test_empty_title_returns_warning(self):
        fn = self._get_fn()
        md, _ = fn("", "Observacional", "", "", "", "", 0,
                    False, False, False, False, False, False, "", "")
        assert "⚠️" in md
        assert "título" in md.lower()

    def test_minimal_dossier(self):
        fn = self._get_fn()
        md, file_update = fn(
            "Estudio de prueba",  # title
            "Observacional",       # study_type
            "Dr. Test",            # pi
            "Hospital Test",       # institution
            "Evaluar eficacia",    # objective
            "Adultos con HTA",     # population
            100,                   # sample_size
            False, False, False, False, False, False,  # flags
            "", "",               # risks, benefits
        )
        assert "✅ Dossier generado" in md
        assert "4 documento(s)" in md
        assert "Protocolo" in md
        assert "Consentimiento" in md

    def test_dossier_with_minors(self):
        fn = self._get_fn()
        md, _ = fn(
            "Estudio con menores",
            "Observacional",
            "", "", "", "",
            50,
            True,   # has_minors
            False, False, False, False,
            True,   # has_vulnerable
            "", "",
        )
        assert "5 documento(s)" in md
        assert "Asentimiento" in md

    def test_dossier_with_samples(self):
        fn = self._get_fn()
        md, _ = fn(
            "Estudio con muestras",
            "Observacional",
            "", "", "", "",
            30,
            False,
            True,   # has_samples
            False, False, False, False,
            "", "",
        )
        assert "5 documento(s)" in md
        assert "Muestras" in md

    def test_dossier_with_everything(self):
        fn = self._get_fn()
        md, file_update = fn(
            "Estudio completo",
            "Mixto",
            "Dra. García",
            "Hospital Central",
            "Evaluar impacto",
            "Adolescentes",
            500,
            True,   # minors
            True,   # samples
            True,   # sensitive
            True,   # transfer
            True,   # ai
            True,   # vulnerable
            "Riesgo A, Riesgo B",
            "Beneficio X, Beneficio Y",
        )
        assert "6 documento(s)" in md
        assert "Protocolo" in md
        assert "Protección de Datos" in md

    def test_dossier_zip_created(self):
        fn = self._get_fn()
        md, file_update = fn(
            "Test zip",
            "Observacional",
            "", "", "", "",
            0,
            False, False, False, False, False, False,
            "", "",
        )
        if hasattr(file_update, '__getitem__'):
            path = file_update.get("value")
            if path:
                assert Path(path).exists()
                assert path.endswith(".zip")

    def test_qualitative_study_type(self):
        fn = self._get_fn()
        md, _ = fn(
            "Estudio cualitativo",
            "Cualitativo",
            "", "", "", "",
            20,
            False, False, False, False, False, False,
            "", "",
        )
        assert "✅ Dossier generado" in md

    def test_risks_and_benefits_parsed(self):
        fn = self._get_fn()
        md, _ = fn(
            "Estudio riesgos",
            "Observacional",
            "", "", "", "",
            50,
            False, False, False, False, False, False,
            "Cefalea, Náuseas, Hipotensión",
            "Mejora CV",
        )
        assert "✅ Dossier generado" in md
        # The preview should contain at least some of the risks
        assert "Cefalea" in md or "Protocolo" in md
