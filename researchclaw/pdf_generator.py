"""Generador de PDF elegante desde Markdown usando fpdf2.

Produce documentos A4 con:
  - Portada con título, fecha y marca ResearchClaw
  - Encabezado y pie de página en todas las hojas
  - Títulos H1/H2/H3 con jerarquía visual
  - Párrafos con soporte de negrita inline (**texto**)
  - Listas de bullets
  - Tablas Markdown renderizadas con cabecera coloreada
  - Salto de página automático ante secciones H1

Uso:
    from researchclaw.pdf_generator import generate_pdf
    path = generate_pdf(markdown_text, output_path, title="Mi informe")
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path


# ---------------------------------------------------------------------------
# Fuente Unicode: busca Arial del sistema macOS o usa Helvetica con fallback
# ---------------------------------------------------------------------------

_FONT_PATHS = [
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),   # macOS (Intel)
    Path("/Library/Fonts/Arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),  # Linux
]
_UNICODE_FONT_PATH: Path | None = next(
    (p for p in _FONT_PATHS if p.exists()), None
)
_UNICODE_FONT_PATH_BOLD: Path | None = next(
    (p for p in [
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        Path("/Library/Fonts/Arial Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ] if p.exists()), None
)
_USE_UNICODE_FONT = _UNICODE_FONT_PATH is not None

# Mapa de caracteres Unicode → ASCII para el fallback (helvetica sin unicode)
_UNICODE_FALLBACK: dict[str, str] = {
    "\u2014": "-",   # em dash —
    "\u2013": "-",   # en dash –
    "\u2019": "'",   # right single quote
    "\u2018": "'",   # left single quote
    "\u201c": '"',   # left double quote
    "\u201d": '"',   # right double quote
    "\u2026": "...", # ellipsis
    "\u00b0": "°",   # degree (latin-1, OK)
    "\u2192": "->",  # right arrow →
    "\u2190": "<-",  # left arrow ←
    "\u00b1": "+/-", # plus minus ±
    "\u2265": ">=",  # >=
    "\u2264": "<=",  # <=
    "\u00d7": "x",   # multiplication ×
    "\u03b1": "alpha",
    # Emojis → texto
    "\u2705": "[OK]",       # ✅
    "\u26a0": "[AVISO]",    # ⚠
    "\ufe0f": "",           # variation selector-16 (⚠️ modifier)
    "\u274c": "[X]",        # ❌
    "\u2b50": "*",          # ⭐
    "\U0001f4cb": "",       # 📋
    "\U0001f9ea": "",       # 🧪
    "\U0001f4d6": "",       # 📖
    "\U0001f3db": "",       # 🏛
    "\U0001f512": "",       # 🔒
}


def _safe(text: str) -> str:
    """Convierte caracteres fuera de Latin-1 a equivalentes ASCII seguros."""
    # Siempre reemplazar todos los caracteres del mapa (incluye emojis BMP y ASCII)
    for k, v in _UNICODE_FALLBACK.items():
        text = text.replace(k, v)
    if _USE_UNICODE_FONT:
        return text
    # Sin fuente Unicode: forzar Latin-1
    return text.encode("latin-1", errors="replace").decode("latin-1")


# ---------------------------------------------------------------------------
# Paleta
# ---------------------------------------------------------------------------

_COL_DARK_BLUE  = (30,  55,  100)   # portada, H1
_COL_MID_BLUE   = (46, 116, 181)    # H2, H3, línea cabecera
_COL_TABLE_HEAD = (214, 234, 248)   # fondo cabecera tabla
_COL_TABLE_ALT  = (242, 242, 242)   # filas alternas
_COL_BODY       = (40,  40,  40)    # texto normal
_COL_GREY       = (130, 130, 130)   # footer / watermark
_COL_WHITE      = (255, 255, 255)
_COL_GREEN_BG   = (217, 234, 211)   # ACEPTAR
_COL_ORANGE_BG  = (252, 229, 205)   # ACLARACIONES
_COL_RED_BG     = (252, 228, 214)   # RECHAZAR


# ---------------------------------------------------------------------------
# Clase FPDF extendida con header/footer
# ---------------------------------------------------------------------------

def _make_pdf_class():
    """Devuelve la clase FPDF2 con header y footer personalizados."""
    from fpdf import FPDF  # type: ignore[import]

    class ResearchClawPDF(FPDF):
        def __init__(
            self,
            doc_title: str = "ResearchClaw",
            doc_version: str = "Version 1.0",
            short_title: str = "",
        ):
            super().__init__(orientation="P", unit="mm", format="A4")
            self.doc_title   = doc_title
            self.doc_version = doc_version
            self.short_title = short_title or doc_title[:40]
            # Márgenes estándar 2.5 cm (25 mm en todos los lados)
            self.set_margins(25, 25, 25)
            self.set_auto_page_break(auto=True, margin=24)
            # Alias para total de páginas ("{nb}" se reemplaza al hacer output)
            self.alias_nb_pages("{nb}")
            # Registrar fuente Unicode si está disponible
            if _USE_UNICODE_FONT and _UNICODE_FONT_PATH:
                self.add_font("Arial", "", str(_UNICODE_FONT_PATH))
                if _UNICODE_FONT_PATH_BOLD:
                    self.add_font("Arial", "B", str(_UNICODE_FONT_PATH_BOLD))
                else:
                    self.add_font("Arial", "B", str(_UNICODE_FONT_PATH))
                self.add_font("Arial", "I", str(_UNICODE_FONT_PATH))
                self._body_font = "Arial"
            else:
                self._body_font = "helvetica"

        def header(self):
            if self.page_no() == 1:
                return  # portada sin cabecera
            self.set_font(self._body_font, "B", 8)
            self.set_text_color(*_COL_MID_BLUE)
            self.cell(0, 5, _safe(self.doc_title[:80]), align="L")
            self.ln(1)
            self.set_draw_color(*_COL_MID_BLUE)
            self.set_line_width(0.3)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
            self.ln(4)
            self.set_text_color(*_COL_BODY)

        def footer(self):
            if self.page_no() == 1:
                return
            self.set_y(-14)
            self.set_draw_color(*_COL_MID_BLUE)
            self.set_line_width(0.3)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
            self.ln(1.5)
            self.set_font(self._body_font, "", 8)
            self.set_text_color(*_COL_GREY)
            eff_w = self.w - self.l_margin - self.r_margin  # ~160 mm
            col   = eff_w / 3
            today = date.today().strftime("%d/%m/%Y")
            # Izquierda: título corto
            self.cell(col, 5, _safe(self.short_title[:35]), align="L")
            # Centro: versión · fecha
            self.cell(col, 5, _safe(f"{self.doc_version}  .  {today}"), align="C")
            # Derecha: Página X de {nb}  (fpdf2 reemplaza {nb} por total páginas)
            self.cell(col, 5, _safe(f"Pagina {self.page_no()} de {{nb}}"), align="R")

    return ResearchClawPDF


# ---------------------------------------------------------------------------
# Utilidades de texto
# ---------------------------------------------------------------------------

def _strip_md(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"^#+\s*", "", text)
    return text.strip()


def _has_bold(text: str) -> bool:
    return "**" in text


def _write_inline_bold(pdf, text: str, base_size: int, base_color: tuple) -> None:
    """Escribe texto con soporte de **negrita** inline."""
    parts = re.split(r"(\*\*[^*]+\*\*)", text)
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            pdf.set_font(pdf._body_font, "B", base_size)
            pdf.set_text_color(*base_color)
            pdf.write(7, _safe(part[2:-2]))
        else:
            pdf.set_font(pdf._body_font, "", base_size)
            pdf.set_text_color(*base_color)
            pdf.write(7, _safe(part))
    pdf.ln()


def _parse_md_table(lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in lines:
        if re.match(r"^\s*\|[-:| ]+\|\s*$", line):
            continue
        cells = [_strip_md(c.strip()) for c in line.strip().strip("|").split("|")]
        if cells:
            rows.append(cells)
    return rows


def _dictamen_color(text: str) -> tuple | None:
    """Devuelve color de fondo para la línea de dictamen, o None."""
    t = text.upper()
    if "ACEPTAR" in t and "RECHAZAR" not in t:
        return _COL_GREEN_BG
    if "RECHAZAR" in t:
        return _COL_RED_BG
    if "ACLARACIONES" in t:
        return _COL_ORANGE_BG
    return None


# ---------------------------------------------------------------------------
# Portada
# ---------------------------------------------------------------------------

def _add_cover(pdf, title: str, subtitle: str) -> None:
    pdf.add_page()

    # Banda superior azul oscuro
    pdf.set_fill_color(*_COL_DARK_BLUE)
    pdf.rect(0, 0, 210, 40, "F")

    # Título en la banda
    pdf.set_y(10)
    pdf.set_font(pdf._body_font, "B", 14)
    pdf.set_text_color(*_COL_WHITE)
    pdf.cell(0, 8, _safe("ResearchClaw - IA Medica Autonoma"), align="C")
    pdf.ln(10)
    pdf.set_font(pdf._body_font, "", 10)
    pdf.cell(0, 6, _safe("Plataforma de Investigacion Cientifica Autonoma"), align="C")

    # Título del documento
    pdf.set_y(80)
    pdf.set_font(pdf._body_font, "B", 20)
    pdf.set_text_color(*_COL_DARK_BLUE)
    # Dividir título largo en líneas
    pdf.set_x(20)
    pdf.multi_cell(170, 10, _safe(title), align="C")

    # Subtítulo
    pdf.ln(6)
    pdf.set_font(pdf._body_font, "I", 12)
    pdf.set_text_color(*_COL_MID_BLUE)
    pdf.cell(0, 8, _safe(subtitle), align="C")

    # Fecha
    pdf.ln(10)
    pdf.set_font(pdf._body_font, "", 10)
    pdf.set_text_color(*_COL_GREY)
    pdf.cell(0, 6, _safe(f"Generado el {date.today().strftime('%d/%m/%Y')}"), align="C")

    # Banda inferior
    pdf.set_y(260)
    pdf.set_fill_color(*_COL_MID_BLUE)
    pdf.rect(0, 265, 210, 32, "F")
    pdf.set_y(272)
    pdf.set_font(pdf._body_font, "I", 9)
    pdf.set_text_color(*_COL_WHITE)
    pdf.cell(0, 6, _safe("Documento generado automaticamente - Confidencial"), align="C")


# ---------------------------------------------------------------------------
# Renderizador de tabla
# ---------------------------------------------------------------------------

def _add_table(pdf, rows: list[list[str]], effective_width: float) -> None:
    if not rows:
        return
    n_cols = max(len(r) for r in rows)
    col_w = effective_width / n_cols

    for i, row in enumerate(rows):
        # Calcular altura de fila (por si hay texto largo)
        max_h = 7
        row_height = max_h

        for j, cell in enumerate(row[:n_cols]):
            x = pdf.get_x()
            y = pdf.get_y()

            # Color de fondo
            if i == 0:
                pdf.set_fill_color(*_COL_TABLE_HEAD)
            elif i % 2 == 0:
                pdf.set_fill_color(*_COL_TABLE_ALT)
            else:
                pdf.set_fill_color(*_COL_WHITE)

            # Detectar color dictamen en columna de estado
            if i > 0 and j == 1:
                if "✅" in cell:
                    pdf.set_fill_color(217, 234, 211)
                elif "⚠" in cell:
                    pdf.set_fill_color(255, 242, 204)
                elif "❌" in cell:
                    pdf.set_fill_color(252, 228, 214)

            pdf.set_font(pdf._body_font, "B" if i == 0 else "", 8)
            pdf.set_text_color(*(_COL_DARK_BLUE if i == 0 else _COL_BODY))

            # Truncar celdas largas
            display = _safe(cell[:60] + ("..." if len(cell) > 60 else ""))
            pdf.cell(col_w, row_height, display, border=1, fill=True)

        pdf.ln(row_height)

    pdf.ln(4)


# ---------------------------------------------------------------------------
# Función pública principal
# ---------------------------------------------------------------------------

_REFERENCES_HEADINGS_PDF = frozenset({
    "references", "referencias", "bibliography", "bibliografía",
    "referencias bibliográficas", "works cited", "literature cited",
})


def generate_pdf(
    markdown_text: str,
    output_path: Path,
    title: str = "Informe ResearchClaw",
    version: str = "Versión 1.0",
    short_title: str = "",
    bib_text: str = "",
) -> Path:
    """Genera un PDF A4 profesional a partir del Markdown del informe.

    Parameters
    ----------
    markdown_text:
        Contenido en Markdown.
    output_path:
        Ruta donde guardar el .pdf.
    title:
        Título a mostrar en la portada.
    version:
        Texto de versión para el pie (ej. "Versión 1.0").
    short_title:
        Título corto o código de protocolo para el pie izquierdo.
    bib_text:
        Contenido BibTeX completo (de references.bib).  Cuando se proporciona,
        la sección References se formatea automáticamente en estilo APA-7.
    """
    try:
        from fpdf import FPDF  # type: ignore[import]
    except ImportError as exc:
        raise ImportError("fpdf2 no instalado. Ejecuta: pip install fpdf2") from exc

    ResearchClawPDF = _make_pdf_class()

    # Extraer título H1 si existe
    h1 = re.search(r"^#\s+(.+)$", markdown_text, re.MULTILINE)
    doc_title = h1.group(1).strip() if h1 else title

    # Detectar tipo
    is_ceim = any(m in markdown_text for m in ["DICTAMEN", "Checklist de Auditoría CEIm", "ACEPTAR"])
    subtitle = (
        "Informe de Auditoría Ética — CEIm"
        if is_ceim else
        "Informe de Investigación Científica"
    )

    pdf = ResearchClawPDF(
        doc_title=doc_title,
        doc_version=version,
        short_title=short_title or doc_title[:40],
    )
    pdf.set_title(doc_title)
    pdf.set_author("ResearchClaw")

    # Portada
    _add_cover(pdf, doc_title, subtitle)

    # Pre-compute APA references if bib_text provided
    from researchclaw.docx_generator import bibtex_to_apa_bibliography as _bib_to_apa
    _apa_refs: list[str] = _bib_to_apa(bib_text) if bib_text else []

    # Contenido: página 2 en adelante
    pdf.add_page()
    effective_w = pdf.w - pdf.l_margin - pdf.r_margin

    lines = markdown_text.splitlines()
    _in_refs_section = False  # track if we are inside a References section
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # H1
        if stripped.startswith("# ") and not stripped.startswith("## "):
            _in_refs_section = False
            i += 1
            continue  # Ya en portada

        # H2
        elif stripped.startswith("## "):
            heading_raw = _strip_md(stripped[3:])
            text = _safe(heading_raw)
            # Detect References section
            _in_refs_section = heading_raw.strip().lower() in _REFERENCES_HEADINGS_PDF
            pdf.set_font(pdf._body_font, "B", 14)
            pdf.set_text_color(*_COL_DARK_BLUE)
            pdf.set_fill_color(*_COL_TABLE_HEAD)
            pdf.cell(0, 9, text, fill=True, ln=True)
            pdf.ln(2)
            # If references section and APA refs available, render them immediately
            if _in_refs_section and _apa_refs:
                for ref_idx, ref in enumerate(_apa_refs):
                    pdf.set_font(pdf._body_font, "", 10)
                    pdf.set_text_color(*_COL_BODY)
                    # Hanging indent for APA: first line at margin, continuation indented
                    pdf.set_x(pdf.l_margin)
                    pdf.multi_cell(effective_w, 6, _safe(ref))
                    pdf.ln(2)
                i += 1
                continue

        # H3
        elif stripped.startswith("### "):
            text = _safe(_strip_md(stripped[4:]))
            pdf.set_font(pdf._body_font, "B", 11)
            pdf.set_text_color(*_COL_MID_BLUE)
            pdf.cell(0, 7, text, ln=True)
            pdf.ln(1)

        # Tabla Markdown: acumular hasta el fin de la tabla
        elif stripped.startswith("|"):
            table_block: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_block.append(lines[i])
                i += 1
            rows = _parse_md_table(table_block)
            _add_table(pdf, rows, effective_w)
            continue

        # Separador horizontal
        elif stripped.startswith("---"):
            pdf.set_draw_color(*_COL_MID_BLUE)
            pdf.set_line_width(0.3)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(4)

        # Bullet
        elif stripped.startswith(("- ", "* ")):
            text = _safe(_strip_md(stripped[2:]))
            pdf.set_font(pdf._body_font, "", 11)
            pdf.set_text_color(*_COL_BODY)
            pdf.set_x(pdf.l_margin + 5)
            pdf.cell(4, 7, "-")
            pdf.set_x(pdf.l_margin + 9)
            pdf.multi_cell(effective_w - 9, 7, text)

        # Línea vacía
        elif not stripped:
            pdf.ln(3)

        # Párrafo normal (con soporte de **bold** y dictamen coloreado)
        else:
            text = _strip_md(stripped)
            if not text:
                i += 1
                continue

            # Skip body text of references section when APA is rendered above
            if _in_refs_section and _apa_refs:
                i += 1
                continue

            bg = _dictamen_color(stripped) if is_ceim else None
            if bg:
                pdf.set_fill_color(*bg)
                pdf.set_font(pdf._body_font, "B", 11)
                pdf.set_text_color(*_COL_DARK_BLUE)
                pdf.multi_cell(0, 8, _safe(f"  {text}  "), fill=True)
                pdf.ln(2)
            elif _has_bold(stripped):
                _write_inline_bold(pdf, stripped, 11, _COL_BODY)
            else:
                pdf.set_font(pdf._body_font, "", 11)
                pdf.set_text_color(*_COL_BODY)
                pdf.multi_cell(0, 7, _safe(text))

        i += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))
    return output_path
