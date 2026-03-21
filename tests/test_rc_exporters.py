# pyright: reportPrivateUsage=false
"""Tests for the three optional export generators: docx, pdf, pptx.

Test strategy
-------------
1. **Pure-function tests** — No external deps; always run.
   Cover BibTeX→APA conversion, Markdown helpers, content classification,
   and text-processing utilities in all three modules.

2. **ImportError guard tests** — Simulate missing deps via sys.modules patching.
   Verify that generate_*() raises a clear ImportError (not AttributeError or
   silent failure) when the underlying library is patched as absent.

3. **Integration tests** — Guarded by skipif markers.
   Each class is skipped when its dep is not installed; in the standard dev
   environment all three deps ARE installed so these always run and produce
   real binary output files.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Dep availability flags
# ---------------------------------------------------------------------------

try:
    import docx as _docx_lib  # noqa: F401
    _DOCX_AVAILABLE = True
except ImportError:
    _DOCX_AVAILABLE = False

try:
    import fpdf as _fpdf_lib  # noqa: F401
    _FPDF_AVAILABLE = True
except ImportError:
    _FPDF_AVAILABLE = False

try:
    import pptx as _pptx_lib  # noqa: F401
    _PPTX_AVAILABLE = True
except ImportError:
    _PPTX_AVAILABLE = False


# ---------------------------------------------------------------------------
# Fixtures / shared test data
# ---------------------------------------------------------------------------

_SAMPLE_MD = """\
# Test Research Paper

## Introduction

This paper investigates the effects of intervention X on outcome Y in a
randomised controlled trial. **Key findings** are summarised below.

## Methods

We conducted a systematic review following **PRISMA 2020** guidelines.
Databases searched: PubMed, Embase, Cochrane Library.

## Results

The intervention showed significant effects (p < 0.05, HR = 0.72, IC 95%).

- Outcome A improved by 30%
- Outcome B improved by 20%
- Adverse events were minimal

## Discussion

These results suggest that intervention X is effective across all subgroups.

## Conclusion

The evidence supports wide adoption of intervention X in clinical practice.
"""

_CEIM_MD = """\
# Informe de Auditoría CEIm

## Checklist de Auditoría CEIm

| Ítem | Estado | Comentario |
|------|--------|------------|
| 1 ⭐ | ✅     | Correcto   |
| 2    | ⚠️    | Pendiente  |
| 3    | ❌     | Incompleto |

## BLOQUE A — Documentación

BLOQUE A — Información general del estudio.

## DICTAMEN

Se recomienda **ACEPTAR** el protocolo con las observaciones menores.
"""

_SAMPLE_BIB = r"""
@article{doe2023,
    author  = {Doe, John and Smith, Jane},
    title   = {Machine Learning in Medicine: A Review},
    journal = {Nature Medicine},
    year    = {2023},
    volume  = {29},
    number  = {3},
    pages   = {100--110},
    doi     = {10.1038/s41591-023-0001-1},
}

@article{jones2022,
    author  = {Jones, Alice},
    title   = {Deep Learning for Clinical Prediction},
    journal = {The Lancet Digital Health},
    year    = {2022},
    volume  = {4},
    pages   = {e100--e108},
}
"""


# ===========================================================================
# 1. PURE-FUNCTION TESTS — docx_generator (no python-docx needed)
# ===========================================================================


class TestBibtexToApa:
    """bibtex_to_apa_bibliography is pure Python — no python-docx needed."""

    def test_empty_string_returns_empty_list(self) -> None:
        from researchclaw.docx_generator import bibtex_to_apa_bibliography

        assert bibtex_to_apa_bibliography("") == []

    def test_whitespace_string_returns_empty_list(self) -> None:
        from researchclaw.docx_generator import bibtex_to_apa_bibliography

        assert bibtex_to_apa_bibliography("   \n  ") == []

    def test_two_articles_return_two_entries(self) -> None:
        from researchclaw.docx_generator import bibtex_to_apa_bibliography

        result = bibtex_to_apa_bibliography(_SAMPLE_BIB)
        assert len(result) == 2

    def test_result_is_list_of_strings(self) -> None:
        from researchclaw.docx_generator import bibtex_to_apa_bibliography

        result = bibtex_to_apa_bibliography(_SAMPLE_BIB)
        assert all(isinstance(r, str) for r in result)

    def test_author_formatted_apa_with_ampersand(self) -> None:
        from researchclaw.docx_generator import bibtex_to_apa_bibliography

        result = bibtex_to_apa_bibliography(_SAMPLE_BIB)
        first = result[0]
        # "Doe, John and Smith, Jane" → "Doe, J., & Smith, J."
        assert "Doe" in first
        assert "&" in first
        assert "Smith" in first

    def test_doi_included_in_output(self) -> None:
        from researchclaw.docx_generator import bibtex_to_apa_bibliography

        result = bibtex_to_apa_bibliography(_SAMPLE_BIB)
        assert any("10.1038" in r for r in result)

    def test_year_in_parentheses(self) -> None:
        from researchclaw.docx_generator import bibtex_to_apa_bibliography

        result = bibtex_to_apa_bibliography(_SAMPLE_BIB)
        assert any("(2023)" in r for r in result)
        assert any("(2022)" in r for r in result)

    def test_comment_entries_skipped(self) -> None:
        from researchclaw.docx_generator import bibtex_to_apa_bibliography

        bib_with_comment = "@comment{this is a comment}\n" + _SAMPLE_BIB
        result = bibtex_to_apa_bibliography(bib_with_comment)
        assert len(result) == 2  # @comment must not be counted

    def test_malformed_entry_does_not_raise(self) -> None:
        from researchclaw.docx_generator import bibtex_to_apa_bibliography

        # Unclosed brace — parser should skip gracefully
        bad_bib = "@article{bad_one,\n  author={Missing brace\n"
        try:
            result = bibtex_to_apa_bibliography(bad_bib)
            assert isinstance(result, list)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"bibtex_to_apa_bibliography raised unexpectedly: {exc}")

    def test_no_doi_no_url_still_produces_entry(self) -> None:
        from researchclaw.docx_generator import bibtex_to_apa_bibliography

        bib = (
            "@article{nodoi,\n"
            "  author={Author, A.},\n"
            "  title={A Title},\n"
            "  year={2020},\n"
            "  journal={Some Journal},\n"
            "}"
        )
        result = bibtex_to_apa_bibliography(bib)
        assert len(result) == 1
        assert "A Title" in result[0]


class TestApaAuthors:
    """_apa_authors: Last, First and First Last formats."""

    def test_last_first_format(self) -> None:
        from researchclaw.docx_generator import _apa_authors

        result = _apa_authors("Doe, John")
        assert result == "Doe, J."

    def test_first_last_format(self) -> None:
        from researchclaw.docx_generator import _apa_authors

        result = _apa_authors("John Doe")
        assert "Doe" in result

    def test_two_authors_has_ampersand(self) -> None:
        from researchclaw.docx_generator import _apa_authors

        result = _apa_authors("Doe, John and Smith, Jane")
        assert "&" in result
        assert "Doe" in result
        assert "Smith" in result

    def test_single_word_name(self) -> None:
        from researchclaw.docx_generator import _apa_authors

        result = _apa_authors("Madonna")
        assert result == "Madonna"

    def test_empty_returns_unknown_author(self) -> None:
        from researchclaw.docx_generator import _apa_authors

        assert _apa_authors("") == "Unknown Author"


class TestClassifyContent:
    """_classify_content returns 'ceim' or 'general'."""

    def test_checklist_ceim_marker_detected(self) -> None:
        from researchclaw.docx_generator import _classify_content

        assert _classify_content("## Checklist de Auditoría CEIm\n\nBLOQUE A —") == "ceim"

    def test_dictamen_marker_detected(self) -> None:
        from researchclaw.docx_generator import _classify_content

        assert _classify_content("DICTAMEN: ACEPTAR") == "ceim"

    def test_rechazar_marker_detected(self) -> None:
        from researchclaw.docx_generator import _classify_content

        assert _classify_content("Resolución: RECHAZAR") == "ceim"

    def test_general_research_text_not_ceim(self) -> None:
        from researchclaw.docx_generator import _classify_content

        assert _classify_content("## Introduction\n\nThis is a research paper.") == "general"

    def test_empty_string_is_general(self) -> None:
        from researchclaw.docx_generator import _classify_content

        assert _classify_content("") == "general"


class TestStripInlineMd:
    def test_bold_markers_removed(self) -> None:
        from researchclaw.docx_generator import _strip_inline_md

        assert _strip_inline_md("**bold text**") == "bold text"

    def test_italic_markers_removed(self) -> None:
        from researchclaw.docx_generator import _strip_inline_md

        assert _strip_inline_md("*italic*") == "italic"

    def test_code_markers_removed(self) -> None:
        from researchclaw.docx_generator import _strip_inline_md

        assert _strip_inline_md("`code`") == "code"

    def test_plain_text_unchanged(self) -> None:
        from researchclaw.docx_generator import _strip_inline_md

        assert _strip_inline_md("plain text") == "plain text"

    def test_mixed_markers_all_removed(self) -> None:
        from researchclaw.docx_generator import _strip_inline_md

        result = _strip_inline_md("**bold** and *italic* and `code`")
        assert "**" not in result
        assert "*" not in result
        assert "`" not in result


class TestParseMdTableDocx:
    def test_basic_table_two_rows(self) -> None:
        from researchclaw.docx_generator import _parse_md_table

        lines = [
            "| Header A | Header B |",
            "|----------|----------|",
            "| Cell 1   | Cell 2   |",
        ]
        rows = _parse_md_table(lines)
        assert len(rows) == 2  # separator skipped
        assert rows[0][0] == "Header A"
        assert rows[1][0] == "Cell 1"

    def test_separator_row_skipped(self) -> None:
        from researchclaw.docx_generator import _parse_md_table

        lines = ["|A|B|", "|--|--|", "|1|2|"]
        rows = _parse_md_table(lines)
        assert len(rows) == 2

    def test_empty_lines_returns_empty(self) -> None:
        from researchclaw.docx_generator import _parse_md_table

        assert _parse_md_table([]) == []


# ===========================================================================
# 2. PURE-FUNCTION TESTS — pdf_generator (no fpdf2 needed)
# ===========================================================================


class TestPdfSafe:
    def test_em_dash_to_hyphen(self) -> None:
        from researchclaw.pdf_generator import _safe

        assert _safe("before \u2014 after") == "before - after"

    def test_checkmark_emoji_converted(self) -> None:
        from researchclaw.pdf_generator import _safe

        assert _safe("\u2705") == "[OK]"

    def test_cross_emoji_converted(self) -> None:
        from researchclaw.pdf_generator import _safe

        assert _safe("\u274c") == "[X]"

    def test_warning_emoji_converted(self) -> None:
        from researchclaw.pdf_generator import _safe

        # ⚠ (U+26A0) → [AVISO]; variation selector U+FE0F → ""
        result = _safe("\u26a0\ufe0f")
        assert "[AVISO]" in result

    def test_plain_ascii_unchanged(self) -> None:
        from researchclaw.pdf_generator import _safe

        assert _safe("hello world 123") == "hello world 123"

    def test_ellipsis_converted(self) -> None:
        from researchclaw.pdf_generator import _safe

        assert _safe("wait\u2026") == "wait..."


class TestPdfStripMd:
    def test_bold_removed(self) -> None:
        from researchclaw.pdf_generator import _strip_md

        assert _strip_md("**bold**") == "bold"

    def test_h2_prefix_removed(self) -> None:
        from researchclaw.pdf_generator import _strip_md

        assert _strip_md("## Introduction") == "Introduction"

    def test_h3_prefix_removed(self) -> None:
        from researchclaw.pdf_generator import _strip_md

        assert _strip_md("### Subsection") == "Subsection"

    def test_plain_text_unchanged(self) -> None:
        from researchclaw.pdf_generator import _strip_md

        assert _strip_md("just text") == "just text"


class TestPdfHasBold:
    def test_detects_bold(self) -> None:
        from researchclaw.pdf_generator import _has_bold

        assert _has_bold("This is **bold** text") is True

    def test_no_bold(self) -> None:
        from researchclaw.pdf_generator import _has_bold

        assert _has_bold("This has no bold") is False


class TestDictamenColor:
    def test_aceptar_returns_green(self) -> None:
        from researchclaw.pdf_generator import _COL_GREEN_BG, _dictamen_color

        assert _dictamen_color("Se recomienda ACEPTAR el protocolo.") == _COL_GREEN_BG

    def test_rechazar_returns_red(self) -> None:
        from researchclaw.pdf_generator import _COL_RED_BG, _dictamen_color

        assert _dictamen_color("RECHAZAR la solicitud.") == _COL_RED_BG

    def test_aclaraciones_returns_orange(self) -> None:
        from researchclaw.pdf_generator import _COL_ORANGE_BG, _dictamen_color

        assert _dictamen_color("Requiere ACLARACIONES adicionales.") == _COL_ORANGE_BG

    def test_neutral_text_returns_none(self) -> None:
        from researchclaw.pdf_generator import _dictamen_color

        assert _dictamen_color("This is a normal sentence.") is None

    def test_aceptar_and_rechazar_in_same_line_returns_red(self) -> None:
        from researchclaw.pdf_generator import _COL_RED_BG, _dictamen_color

        # "RECHAZAR" wins when both words present in the text
        result = _dictamen_color("No ACEPTAR sino RECHAZAR.")
        assert result == _COL_RED_BG


class TestParseMdTablePdf:
    def test_basic_table(self) -> None:
        from researchclaw.pdf_generator import _parse_md_table

        lines = [
            "| A | B |",
            "|---|---|",
            "| 1 | 2 |",
        ]
        rows = _parse_md_table(lines)
        assert len(rows) == 2
        assert rows[0][0] == "A"

    def test_separator_skipped(self) -> None:
        from researchclaw.pdf_generator import _parse_md_table

        lines = ["|X|Y|", "|--|--|", "|a|b|"]
        rows = _parse_md_table(lines)
        assert len(rows) == 2


# ===========================================================================
# 3. PURE-FUNCTION TESTS — pptx_generator (no python-pptx needed)
# ===========================================================================


class TestParseSections:
    def test_two_sections_extracted(self) -> None:
        from researchclaw.pptx_generator import _parse_sections

        md = "## Introduction\n\nSome text.\n\n## Methods\n\nMethodology."
        sections = _parse_sections(md)
        assert len(sections) == 2
        assert sections[0][0] == "Introduction"
        assert "Some text" in sections[0][1]
        assert sections[1][0] == "Methods"

    def test_empty_text_returns_empty_list(self) -> None:
        from researchclaw.pptx_generator import _parse_sections

        assert _parse_sections("") == []

    def test_h3_also_extracted(self) -> None:
        from researchclaw.pptx_generator import _parse_sections

        md = "### Subsection\n\nContent."
        sections = _parse_sections(md)
        assert len(sections) == 1
        assert sections[0][0] == "Subsection"

    def test_body_content_captured(self) -> None:
        from researchclaw.pptx_generator import _parse_sections

        md = "## Results\n\n- Finding A\n- Finding B\n"
        sections = _parse_sections(md)
        assert "Finding A" in sections[0][1]
        assert "Finding B" in sections[0][1]


class TestExtractBullets:
    def test_bullet_list_extracted(self) -> None:
        from researchclaw.pptx_generator import _extract_bullets

        text = "- Point A\n- Point B\n- Point C"
        bullets = _extract_bullets(text, max_bullets=5)
        assert len(bullets) == 3
        assert "Point A" in bullets

    def test_max_bullets_respected(self) -> None:
        from researchclaw.pptx_generator import _extract_bullets

        text = "- A\n- B\n- C\n- D\n- E\n- G\n- H"
        bullets = _extract_bullets(text, max_bullets=3)
        assert len(bullets) == 3

    def test_no_bullets_splits_by_sentence(self) -> None:
        from researchclaw.pptx_generator import _extract_bullets

        text = "First sentence here. Second sentence here. Third sentence here."
        bullets = _extract_bullets(text, max_bullets=5)
        assert len(bullets) >= 1

    def test_asterisk_bullets_also_extracted(self) -> None:
        from researchclaw.pptx_generator import _extract_bullets

        text = "* Item one\n* Item two"
        bullets = _extract_bullets(text, max_bullets=5)
        assert "Item one" in bullets


class TestTruncate:
    def test_short_text_unchanged(self) -> None:
        from researchclaw.pptx_generator import _truncate

        assert _truncate("short", 90) == "short"

    def test_long_text_truncated_with_ellipsis(self) -> None:
        from researchclaw.pptx_generator import _truncate

        text = "a" * 100
        result = _truncate(text, 90)
        assert len(result) == 90
        assert result.endswith("…")

    def test_exact_length_unchanged(self) -> None:
        from researchclaw.pptx_generator import _truncate

        text = "a" * 90
        assert _truncate(text, 90) == text


class TestSimplifyBullet:
    def test_neoplasia_maligna_replaced(self) -> None:
        from researchclaw.pptx_generator import _simplify_bullet

        result = _simplify_bullet("La neoplasia maligna avanzó rápidamente.")
        assert "neoplasia maligna" not in result.lower()
        assert "cáncer" in result.lower()

    def test_quimioterapia_replaced(self) -> None:
        from researchclaw.pptx_generator import _simplify_bullet

        result = _simplify_bullet("Requiere quimioterapia adjuvante.")
        assert "quimioterapia" not in result.lower()

    def test_plain_text_trailing_dot_stripped(self) -> None:
        # _simplify_bullet always applies .strip(" ,;.") at the end,
        # so trailing punctuation is removed even when no replacements occur.
        from researchclaw.pptx_generator import _simplify_bullet

        result = _simplify_bullet("Regular clinical outcome observed.")
        assert result == "Regular clinical outcome observed"

    def test_hr_abbreviation_replaced(self) -> None:
        # HR → "riesgo relativo" is a documented replacement.
        from researchclaw.pptx_generator import _simplify_bullet

        result = _simplify_bullet("The HR was 0.72.")
        assert "riesgo relativo" in result.lower()


# ===========================================================================
# 4. IMPORTERROR GUARD TESTS — simulate missing deps
# ===========================================================================


class TestImportErrorGuards:
    """generate_*() must raise a clear ImportError when the dep is absent.

    Uses sys.modules patching: setting sys.modules[name] = None makes Python
    treat the module as explicitly absent and raise ImportError on import.
    monkeypatch restores the original state after each test.
    """

    def test_generate_docx_raises_with_helpful_message(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setitem(sys.modules, "docx", None)
        from researchclaw.docx_generator import generate_docx

        with pytest.raises(ImportError, match="python-docx"):
            generate_docx("# Test", tmp_path / "out.docx")

    def test_generate_pdf_raises_with_helpful_message(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setitem(sys.modules, "fpdf", None)
        from researchclaw.pdf_generator import generate_pdf

        with pytest.raises(ImportError, match="fpdf2"):
            generate_pdf("# Test", tmp_path / "out.pdf")

    def test_generate_pptx_raises_with_helpful_message(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setitem(sys.modules, "pptx", None)
        from researchclaw.pptx_generator import generate_pptx

        with pytest.raises(ImportError, match="python-pptx"):
            generate_pptx("# Test", tmp_path / "out.pptx")

    def test_docx_pure_functions_unaffected_by_missing_dep(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pure functions (bibtex_to_apa_bibliography) must work even if
        python-docx is absent — they are pure Python with no deps."""
        monkeypatch.setitem(sys.modules, "docx", None)
        from researchclaw.docx_generator import bibtex_to_apa_bibliography

        result = bibtex_to_apa_bibliography(_SAMPLE_BIB)
        assert len(result) == 2  # pure Python path — must still work


# ===========================================================================
# 5. INTEGRATION TESTS — require actual deps installed
# ===========================================================================


@pytest.mark.skipif(not _DOCX_AVAILABLE, reason="python-docx not installed")
class TestDocxGeneration:
    """End-to-end: generate_docx produces a valid, non-empty .docx file."""

    def test_generates_docx_file(self, tmp_path: Path) -> None:
        from researchclaw.docx_generator import generate_docx

        out = generate_docx(_SAMPLE_MD, tmp_path / "paper.docx")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_returns_output_path(self, tmp_path: Path) -> None:
        from researchclaw.docx_generator import generate_docx

        expected = tmp_path / "report.docx"
        result = generate_docx(_SAMPLE_MD, expected)
        assert result == expected

    def test_docx_is_valid_zip(self, tmp_path: Path) -> None:
        """DOCX files are ZIP archives — validate magic bytes."""
        from researchclaw.docx_generator import generate_docx

        out = generate_docx(_SAMPLE_MD, tmp_path / "valid.docx")
        assert zipfile.is_zipfile(out)

    def test_ceim_content_produces_docx(self, tmp_path: Path) -> None:
        from researchclaw.docx_generator import generate_docx

        out = generate_docx(_CEIM_MD, tmp_path / "ceim.docx")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_creates_parent_dirs_automatically(self, tmp_path: Path) -> None:
        from researchclaw.docx_generator import generate_docx

        deep = tmp_path / "a" / "b" / "c" / "report.docx"
        out = generate_docx(_SAMPLE_MD, deep)
        assert out.exists()

    def test_with_bib_text_produces_docx(self, tmp_path: Path) -> None:
        from researchclaw.docx_generator import generate_docx

        md_with_refs = _SAMPLE_MD + "\n\n## References\n\nBibliography here.\n"
        out = generate_docx(md_with_refs, tmp_path / "bib.docx", bib_text=_SAMPLE_BIB)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_custom_title_and_version(self, tmp_path: Path) -> None:
        from researchclaw.docx_generator import generate_docx

        out = generate_docx(
            _SAMPLE_MD,
            tmp_path / "titled.docx",
            title="Custom Title",
            version="v2.0",
            short_title="CT",
        )
        assert out.exists()

    def test_empty_markdown_does_not_raise(self, tmp_path: Path) -> None:
        from researchclaw.docx_generator import generate_docx

        out = generate_docx("", tmp_path / "empty.docx")
        assert out.exists()


@pytest.mark.skipif(not _FPDF_AVAILABLE, reason="fpdf2 not installed")
class TestPdfGeneration:
    """End-to-end: generate_pdf produces a valid, non-empty .pdf file."""

    def test_generates_pdf_file(self, tmp_path: Path) -> None:
        from researchclaw.pdf_generator import generate_pdf

        out = generate_pdf(_SAMPLE_MD, tmp_path / "paper.pdf")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_returns_output_path(self, tmp_path: Path) -> None:
        from researchclaw.pdf_generator import generate_pdf

        expected = tmp_path / "report.pdf"
        result = generate_pdf(_SAMPLE_MD, expected)
        assert result == expected

    def test_pdf_magic_bytes(self, tmp_path: Path) -> None:
        """PDF files must start with the %PDF magic string."""
        from researchclaw.pdf_generator import generate_pdf

        out = generate_pdf(_SAMPLE_MD, tmp_path / "magic.pdf")
        assert out.read_bytes()[:4] == b"%PDF"

    def test_ceim_content_produces_pdf(self, tmp_path: Path) -> None:
        from researchclaw.pdf_generator import generate_pdf

        out = generate_pdf(_CEIM_MD, tmp_path / "ceim.pdf")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_creates_parent_dirs_automatically(self, tmp_path: Path) -> None:
        from researchclaw.pdf_generator import generate_pdf

        deep = tmp_path / "x" / "y" / "report.pdf"
        out = generate_pdf(_SAMPLE_MD, deep)
        assert out.exists()

    def test_with_bib_text_produces_pdf(self, tmp_path: Path) -> None:
        from researchclaw.pdf_generator import generate_pdf

        md_with_refs = _SAMPLE_MD + "\n\n## References\n\nBibliography.\n"
        out = generate_pdf(md_with_refs, tmp_path / "bib.pdf", bib_text=_SAMPLE_BIB)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_custom_title_and_version(self, tmp_path: Path) -> None:
        from researchclaw.pdf_generator import generate_pdf

        out = generate_pdf(
            _SAMPLE_MD,
            tmp_path / "titled.pdf",
            title="Custom Title",
            version="v2.0",
            short_title="CT",
        )
        assert out.exists()


@pytest.mark.skipif(not _PPTX_AVAILABLE, reason="python-pptx not installed")
class TestPptxGeneration:
    """End-to-end: generate_pptx produces a valid, non-empty .pptx file."""

    def test_generates_pptx_file(self, tmp_path: Path) -> None:
        from researchclaw.pptx_generator import generate_pptx

        out = generate_pptx(_SAMPLE_MD, tmp_path / "pres.pptx")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_returns_output_path(self, tmp_path: Path) -> None:
        from researchclaw.pptx_generator import generate_pptx

        expected = tmp_path / "presentation.pptx"
        result = generate_pptx(_SAMPLE_MD, expected)
        assert result == expected

    def test_pptx_is_valid_zip(self, tmp_path: Path) -> None:
        """PPTX files are ZIP archives — validate magic bytes."""
        from researchclaw.pptx_generator import generate_pptx

        out = generate_pptx(_SAMPLE_MD, tmp_path / "valid.pptx")
        assert zipfile.is_zipfile(out)

    def test_creates_parent_dirs_automatically(self, tmp_path: Path) -> None:
        from researchclaw.pptx_generator import generate_pptx

        deep = tmp_path / "slides" / "out.pptx"
        out = generate_pptx(_SAMPLE_MD, deep)
        assert out.exists()

    def test_audience_comite_cientifico(self, tmp_path: Path) -> None:
        from researchclaw.pptx_generator import generate_pptx

        out = generate_pptx(
            _SAMPLE_MD,
            tmp_path / "comite.pptx",
            audience="Comité Científico / Congresos",
        )
        assert out.exists()

    def test_audience_pacientes_y_familias(self, tmp_path: Path) -> None:
        from researchclaw.pptx_generator import generate_pptx

        out = generate_pptx(
            _SAMPLE_MD,
            tmp_path / "pacientes.pptx",
            audience="Pacientes y Familias",
        )
        assert out.exists()

    def test_audience_colegas_medicos(self, tmp_path: Path) -> None:
        from researchclaw.pptx_generator import generate_pptx

        out = generate_pptx(
            _SAMPLE_MD,
            tmp_path / "colegas.pptx",
            audience="Colegas Médicos / Sesión Clínica",
        )
        assert out.exists()

    def test_n_slides_parameter(self, tmp_path: Path) -> None:
        from researchclaw.pptx_generator import generate_pptx

        out = generate_pptx(_SAMPLE_MD, tmp_path / "slides8.pptx", n_slides=8)
        assert out.exists()

    def test_custom_sources_note(self, tmp_path: Path) -> None:
        from researchclaw.pptx_generator import generate_pptx

        out = generate_pptx(
            _SAMPLE_MD,
            tmp_path / "sourced.pptx",
            sources_note="Fuente: PubMed · OpenAlex",
        )
        assert out.exists()

    def test_minimal_markdown_no_sections(self, tmp_path: Path) -> None:
        """Fallback: plain text without ## headers produces a valid PPTX."""
        from researchclaw.pptx_generator import generate_pptx

        out = generate_pptx(
            "Just a paragraph of text with no headers at all.",
            tmp_path / "minimal.pptx",
        )
        assert out.exists()
