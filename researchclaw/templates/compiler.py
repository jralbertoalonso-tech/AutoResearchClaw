"""LaTeX compilation and error repair utilities (IMP-18).

Provides ``compile_latex()`` which attempts ``pdflatex`` compilation,
parses the log for common errors, applies automated fixes, and retries
up to 3 times.  Designed to run inside ``_package_deliverables()`` so
that the final paper.tex in ``deliverables/`` is compile-tested.

Key additions
-------------
* ``sanitize_missing_images()`` — proactive pre-compilation pass that
  removes ``\\begin{figure}...\\end{figure}`` blocks (and bare
  ``\\includegraphics`` lines) whose image files do not exist on disk.
  Writes a ``paper.sanitized.tex`` and returns a report.  Called
  automatically by ``compile_latex()`` before the first pdflatex run.

If pdflatex is not installed the module gracefully returns a failure
report without raising.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Image extensions tried when a \includegraphics path has no extension.
_IMAGE_EXTENSIONS: tuple[str, ...] = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg")

# Regex: full \begin{figure[*]}...\end{figure[*]} block (DOTALL).
_FIGURE_BLOCK_RE = re.compile(
    r"(\\begin\{figure\*?\}.*?\\end\{figure\*?\})",
    re.DOTALL,
)

# Regex: \includegraphics[optional opts]{path}
_INCLUDEGRAPHICS_RE = re.compile(
    r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}"
)


@dataclass
class CompileResult:
    """Outcome of a LaTeX compilation attempt."""

    success: bool
    log_excerpt: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fixes_applied: list[str] = field(default_factory=list)
    attempts: int = 0


# ---------------------------------------------------------------------------
# Pre-compilation image sanitizer
# ---------------------------------------------------------------------------

def _resolve_image_path(raw: str, work_dir: Path) -> Path | None:
    """Return the resolved Path of an image if it exists, else None.

    Handles:
    * Absolute paths
    * Paths relative to *work_dir*
    * Paths without extension — tries _IMAGE_EXTENSIONS in order
    """
    raw = raw.strip()
    candidate = Path(raw) if Path(raw).is_absolute() else work_dir / raw
    if candidate.exists():
        return candidate
    # Extension-less: try known image extensions
    if not candidate.suffix:
        for ext in _IMAGE_EXTENSIONS:
            with_ext = candidate.with_suffix(ext)
            if with_ext.exists():
                return with_ext
    return None


def sanitize_missing_images(
    tex_text: str,
    work_dir: Path,
) -> tuple[str, list[str]]:
    """Remove figure environments and bare \\includegraphics lines whose
    referenced image files do not exist on disk.

    Strategy
    --------
    1.  Find every ``\\begin{figure[*]}...\\end{figure[*]}`` block.
    2.  Extract all ``\\includegraphics{path}`` references inside it.
    3.  If **any** referenced image is missing → comment out the whole
        block (preserves line count so log line numbers stay useful).
    4.  After block processing, scan the remaining text for bare
        ``\\includegraphics`` lines not inside a figure environment and
        comment them out too.
    5.  Returns ``(sanitized_text, removed_descriptions)``.

    This function is idempotent and safe to call even when all images
    exist — in that case it returns the original text unchanged.
    """
    removed: list[str] = []
    sanitized = tex_text

    # --- Pass 1: figure environments ---
    def _process_figure_block(m: re.Match[str]) -> str:
        block = m.group(1)
        refs = _INCLUDEGRAPHICS_RE.findall(block)
        missing = [r for r in refs if _resolve_image_path(r, work_dir) is None]
        if not missing:
            return block  # all images exist — keep block untouched
        # Comment out every line in the block
        commented_lines = [
            f"% [sanitized — missing image: {', '.join(missing)}]"
            if i == 0
            else f"% {line}"
            for i, line in enumerate(block.split("\n"))
        ]
        desc = (
            f"Removed figure block containing missing image(s): "
            + ", ".join(missing)
        )
        removed.append(desc)
        logger.warning("sanitize_missing_images: %s", desc)
        return "\n".join(commented_lines)

    sanitized = _FIGURE_BLOCK_RE.sub(_process_figure_block, sanitized)

    # --- Pass 2: bare \includegraphics outside figure environments ---
    # Guard: skip matches that are already on a LaTeX-commented line (starts with %)
    # to avoid double-processing lines that Pass 1 already commented out.
    def _process_bare_includegraphics(m: re.Match[str]) -> str:
        # Find the start of the current line in the sanitized string
        line_start = sanitized.rfind("\n", 0, m.start()) + 1
        line_prefix = sanitized[line_start:m.start()]
        if line_prefix.lstrip().startswith("%"):
            return m.group(0)  # already commented — leave as-is
        raw_path = m.group(1)
        if _resolve_image_path(raw_path, work_dir) is not None:
            return m.group(0)  # exists — leave untouched
        desc = f"Commented out bare \\includegraphics for missing: {raw_path}"
        removed.append(desc)
        logger.warning("sanitize_missing_images: %s", desc)
        return f"% [sanitized — missing image: {raw_path}]  % {m.group(0)}"

    sanitized = _INCLUDEGRAPHICS_RE.sub(_process_bare_includegraphics, sanitized)

    return sanitized, removed


# ---------------------------------------------------------------------------
# Pre-compilation Unicode sanitizer
# ---------------------------------------------------------------------------

# Map of Unicode characters → LaTeX replacements.  Covers Greek letters,
# common mathematical symbols, accented Latin characters that pdflatex
# can't handle without \usepackage[utf8]{inputenc} + fontenc, and misc
# typographic symbols that LLMs frequently emit.
_UNICODE_TO_LATEX: dict[str, str] = {
    # Greek lowercase
    "\u03b1": r"$\alpha$",    "\u03b2": r"$\beta$",     "\u03b3": r"$\gamma$",
    "\u03b4": r"$\delta$",    "\u03b5": r"$\epsilon$",   "\u03b6": r"$\zeta$",
    "\u03b7": r"$\eta$",      "\u03b8": r"$\theta$",     "\u03b9": r"$\iota$",
    "\u03ba": r"$\kappa$",    "\u03bb": r"$\lambda$",    "\u03bc": r"$\mu$",
    "\u03bd": r"$\nu$",       "\u03be": r"$\xi$",        "\u03c0": r"$\pi$",
    "\u03c1": r"$\rho$",      "\u03c3": r"$\sigma$",     "\u03c4": r"$\tau$",
    "\u03c5": r"$\upsilon$",  "\u03c6": r"$\phi$",       "\u03c7": r"$\chi$",
    "\u03c8": r"$\psi$",      "\u03c9": r"$\omega$",
    # Greek uppercase
    "\u0393": r"$\Gamma$",    "\u0394": r"$\Delta$",     "\u0398": r"$\Theta$",
    "\u039b": r"$\Lambda$",   "\u039e": r"$\Xi$",        "\u03a0": r"$\Pi$",
    "\u03a3": r"$\Sigma$",    "\u03a6": r"$\Phi$",       "\u03a8": r"$\Psi$",
    "\u03a9": r"$\Omega$",
    # Math symbols
    "\u00b1": r"$\pm$",       "\u00d7": r"$\times$",     "\u00f7": r"$\div$",
    "\u2260": r"$\neq$",      "\u2264": r"$\leq$",       "\u2265": r"$\geq$",
    "\u221e": r"$\infty$",    "\u2248": r"$\approx$",    "\u221a": r"$\sqrt{}$",
    "\u2211": r"$\sum$",      "\u220f": r"$\prod$",      "\u222b": r"$\int$",
    "\u2202": r"$\partial$",  "\u2207": r"$\nabla$",     "\u2208": r"$\in$",
    "\u2209": r"$\notin$",    "\u2286": r"$\subseteq$",  "\u2287": r"$\supseteq$",
    "\u2229": r"$\cap$",      "\u222a": r"$\cup$",       "\u2192": r"$\rightarrow$",
    "\u2190": r"$\leftarrow$", "\u21d2": r"$\Rightarrow$",
    "\u2203": r"$\exists$",   "\u2200": r"$\forall$",
    # Typographic
    "\u2013": "--",           "\u2014": "---",            "\u2018": "`",
    "\u2019": "'",            "\u201c": "``",             "\u201d": "''",
    "\u2026": r"\ldots{}",    "\u00a0": "~",              "\u00b0": r"$^\circ$",
    "\u2122": r"\texttrademark{}",
    "\u00ae": r"\textregistered{}",
    "\u00a9": r"\textcopyright{}",
    # Accented Latin that pdflatex may choke on without inputenc
    "\u00e1": r"\'a",  "\u00e9": r"\'e",  "\u00ed": r"\'{\i}",
    "\u00f3": r"\'o",  "\u00fa": r"\'u",  "\u00f1": r"\~n",
    "\u00c1": r"\'A",  "\u00c9": r"\'E",  "\u00cd": r"\'I",
    "\u00d3": r"\'O",  "\u00da": r"\'U",  "\u00d1": r"\~N",
    "\u00e0": r"\`a",  "\u00e8": r"\`e",  "\u00ec": r"\`{\i}",
    "\u00f2": r"\`o",  "\u00f9": r"\`u",
    "\u00e4": r'\"a',  "\u00eb": r'\"e',  "\u00ef": r'\"{\i}',
    "\u00f6": r'\"o',  "\u00fc": r'\"u',
    "\u00e2": r"\^a",  "\u00ea": r"\^e",  "\u00ee": r"\^{\i}",
    "\u00f4": r"\^o",  "\u00fb": r"\^u",
    "\u00e7": r"\c{c}", "\u00c7": r"\c{C}",
    "\u00df": r"\ss{}",
}


def sanitize_unicode(tex_text: str) -> tuple[str, int]:
    """Replace Unicode characters that pdflatex cannot handle.

    Returns ``(sanitized_text, replacement_count)``.

    Strategy:
    1. Apply known character-to-LaTeX mappings from ``_UNICODE_TO_LATEX``.
    2. For any remaining non-ASCII characters outside of known LaTeX commands,
       replace them with a space to prevent fatal compilation errors.

    This function is idempotent and safe: if the text contains no problematic
    characters, it is returned unchanged with count=0.
    """
    count = 0
    result = tex_text

    # Pass 1: known substitutions
    for char, replacement in _UNICODE_TO_LATEX.items():
        if char in result:
            n = result.count(char)
            result = result.replace(char, replacement)
            count += n

    # Pass 2: catch remaining non-ASCII that slipped through.
    # Only replace characters outside printable ASCII (0x20-0x7E) and
    # common whitespace (\n, \r, \t).  Skip characters inside LaTeX
    # command sequences that we just inserted (e.g. $\kappa$).
    chars = list(result)
    for i, ch in enumerate(chars):
        code = ord(ch)
        if code > 0x7E and ch not in ("\n", "\r", "\t"):
            chars[i] = " "
            count += 1
    result = "".join(chars)

    return result, count


def compile_latex(
    tex_path: Path,
    *,
    max_attempts: int = 3,
    timeout: int = 120,
) -> CompileResult:
    """Compile *tex_path* with pdflatex, auto-fixing common errors.

    Parameters
    ----------
    tex_path:
        Path to the ``.tex`` file.  Must be inside a directory that also
        contains ``references.bib`` and any required ``.sty`` files.
    max_attempts:
        Maximum compile→fix cycles.
    timeout:
        Seconds before killing a stuck pdflatex process.

    Returns
    -------
    CompileResult
        Contains success flag, log excerpt, errors found, and fixes applied.
    """
    if not shutil.which("pdflatex"):
        return CompileResult(
            success=False,
            log_excerpt="pdflatex not found on PATH",
            errors=["pdflatex not installed"],
        )

    result = CompileResult(success=False)
    work_dir = tex_path.parent

    # ------------------------------------------------------------------
    # PRE-PASS: proactively sanitize missing images before first attempt.
    # Writes paper.sanitized.tex and compiles that instead, so pdflatex
    # never encounters a missing-file fatal error from a phantom chart.
    # ------------------------------------------------------------------
    try:
        _orig_text = tex_path.read_text(encoding="utf-8")
        _sanitized_text, _removed = sanitize_missing_images(_orig_text, work_dir)
        if _removed:
            _sanitized_path = tex_path.with_suffix(".sanitized.tex")
            _sanitized_path.write_text(_sanitized_text, encoding="utf-8")
            # copy any .bib / .sty so pdflatex finds them via the new filename
            for _aux in work_dir.glob("*.bib"):
                pass  # already in same dir — no copy needed
            tex_path = _sanitized_path
            logger.info(
                "IMP-18: Sanitized %d missing-image reference(s) → compiling %s",
                len(_removed),
                tex_path.name,
            )
            result.fixes_applied.extend(_removed)
    except Exception as _san_exc:  # noqa: BLE001
        logger.warning("IMP-18: Image sanitization pre-pass failed (%s) — proceeding with original", _san_exc)

    # ------------------------------------------------------------------
    # PRE-PASS 2: Unicode sanitization.  pdflatex with default settings
    # cannot handle many Unicode characters (Greek letters, math symbols,
    # smart quotes, accented chars without inputenc).  Replace them with
    # LaTeX equivalents before compilation.
    # ------------------------------------------------------------------
    try:
        _tex_text = tex_path.read_text(encoding="utf-8")
        _sanitized_text, _unicode_count = sanitize_unicode(_tex_text)
        if _unicode_count > 0:
            tex_path.write_text(_sanitized_text, encoding="utf-8")
            logger.info(
                "IMP-18: Sanitized %d Unicode character(s) in %s",
                _unicode_count, tex_path.name,
            )
            result.fixes_applied.append(
                f"Replaced {_unicode_count} Unicode character(s) with LaTeX equivalents"
            )
    except Exception as _uni_exc:  # noqa: BLE001
        logger.warning("IMP-18: Unicode sanitization pre-pass failed (%s) — proceeding", _uni_exc)

    tex_name = tex_path.name

    for attempt in range(1, max_attempts + 1):
        result.attempts = attempt
        try:
            proc = subprocess.run(
                [
                    "pdflatex",
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    tex_name,
                ],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            result.errors.append(f"pdflatex timed out after {timeout}s")
            break
        except FileNotFoundError:
            result.errors.append("pdflatex not found")
            break

        log_text = proc.stdout + "\n" + proc.stderr
        errors, warnings = _parse_log(log_text)
        result.errors = errors
        result.warnings = warnings
        result.log_excerpt = log_text[-2000:] if len(log_text) > 2000 else log_text

        if proc.returncode == 0:
            result.success = True
            # Run bibtex + two more pdflatex passes for bibliography & cross-refs
            bib_stem = tex_name.rsplit(".", 1)[0]
            _run_bibtex(work_dir, bib_stem, timeout=60)
            for _pass in range(2):
                subprocess.run(
                    ["pdflatex", "-interaction=nonstopmode", tex_name],
                    cwd=work_dir,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            logger.info("IMP-18: LaTeX compiled successfully on attempt %d", attempt)
            break

        # Try to auto-fix errors
        tex_text = tex_path.read_text(encoding="utf-8")
        fixed_text, fixes = fix_common_latex_errors(tex_text, errors)
        if fixes:
            result.fixes_applied.extend(fixes)
            tex_path.write_text(fixed_text, encoding="utf-8")
            logger.info(
                "IMP-18: Applied %d fixes on attempt %d: %s",
                len(fixes),
                attempt,
                fixes,
            )
        else:
            # No fixes available — stop retrying
            logger.warning(
                "IMP-18: Compilation failed on attempt %d with %d unfixable errors",
                attempt,
                len(errors),
            )
            break

    return result


def fix_common_latex_errors(
    tex_text: str, errors: list[str]
) -> tuple[str, list[str]]:
    """Apply automated fixes for common LaTeX errors.

    Returns ``(fixed_text, list_of_fix_descriptions)``.
    """
    fixes: list[str] = []
    fixed = tex_text

    for err in errors:
        err_lower = err.lower()

        # Undefined control sequence: remove the offending command
        if "undefined control sequence" in err_lower:
            # Extract the command name from error like "! Undefined control sequence. \foo"
            m = re.search(r"\\([a-zA-Z]+)", err)
            if m:
                cmd = m.group(1)
                # Don't remove standard commands
                _safe_to_remove = {
                    "textsc", "textsl", "mathbb", "mathcal",
                    "bm", "boldsymbol",
                }
                if cmd in _safe_to_remove:
                    # Replace \cmd{text} → text
                    fixed = re.sub(
                        rf"\\{cmd}\{{([^}}]*)\}}", r"\1", fixed
                    )
                    fixes.append(f"Removed undefined \\{cmd}")

        # Missing $ inserted — likely unescaped underscore or caret
        if "missing $ inserted" in err_lower:
            # Find bare underscores outside of math mode and escape them
            # This is a conservative fix — only fixes _text_ patterns
            pass  # Already handled by converter's _convert_inline

        # File not found
        if "file" in err_lower and "not found" in err_lower:
            m = re.search(r"File `([^']+)' not found", err)
            if m:
                missing_file = m.group(1)
                if missing_file.endswith(".sty"):
                    # Comment out the usepackage line
                    pkg = missing_file.replace(".sty", "")
                    fixed = re.sub(
                        rf"\\usepackage(\[[^\]]*\])?\{{{pkg}\}}",
                        f"% IMP-18: Removed missing package {pkg}",
                        fixed,
                    )
                    fixes.append(f"Removed missing package {pkg}")
                elif any(
                    missing_file.lower().endswith(ext)
                    for ext in (".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg")
                ):
                    # Comment out \includegraphics lines referencing missing image.
                    # Matches both \includegraphics{file} and \includegraphics[opts]{file}
                    # Also wraps the whole figure/center environment if the line is inside one.
                    escaped = re.escape(missing_file)
                    fixed = re.sub(
                        rf"([ \t]*)\\includegraphics(\[[^\]]*\])?\{{[^}}]*{escaped}[^}}]*\}}",
                        rf"\1% IMP-18: Removed missing image {missing_file}",
                        fixed,
                    )
                    fixes.append(f"Commented out \\includegraphics for missing file {missing_file}")

        # Too many unprocessed floats
        if "too many unprocessed floats" in err_lower:
            # Add \clearpage before problematic float
            fixed = fixed.replace(
                "\\begin{table}",
                "\\clearpage\n\\begin{table}",
                1,
            )
            fixes.append("Added \\clearpage for float overflow")

        # Misplaced alignment tab &
        if "misplaced alignment tab" in err_lower:
            # Usually from & outside tabular — escape stray &
            pass  # Hard to auto-fix without context

    return fixed, fixes


def _parse_log(log_text: str) -> tuple[list[str], list[str]]:
    """Parse pdflatex log output for errors and warnings."""
    errors: list[str] = []
    warnings: list[str] = []

    for line in log_text.split("\n"):
        line_stripped = line.strip()
        if line_stripped.startswith("!"):
            errors.append(line_stripped)
        elif "LaTeX Warning:" in line_stripped:
            warnings.append(line_stripped)
        elif "Undefined control sequence" in line_stripped:
            errors.append(line_stripped)
        elif "Missing" in line_stripped and "inserted" in line_stripped:
            errors.append(line_stripped)
        elif "File" in line_stripped and "not found" in line_stripped:
            errors.append(line_stripped)

    return errors, warnings


@dataclass
class QualityCheckResult:
    """Results of post-compilation quality checks."""

    unresolved_refs: list[str] = field(default_factory=list)
    unresolved_cites: list[str] = field(default_factory=list)
    overfull_hboxes: list[str] = field(default_factory=list)
    underfull_hboxes: list[str] = field(default_factory=list)
    page_count: int = 0
    orphan_figures: list[str] = field(default_factory=list)
    orphan_labels: list[str] = field(default_factory=list)
    warnings_summary: list[str] = field(default_factory=list)

    @property
    def has_critical_issues(self) -> bool:
        return bool(self.unresolved_refs or self.unresolved_cites)


def check_compiled_quality(
    tex_path: Path,
    *,
    page_limit: int = 10,
) -> QualityCheckResult:
    """Run post-compilation quality checks on a LaTeX document.

    Parses the .log file and .tex source for:
    - Unresolved references (??)
    - Unresolved citations
    - Overfull/underfull hboxes
    - Page count vs limit
    - Orphan figures (defined but never referenced, or vice versa)
    """
    result = QualityCheckResult()
    work_dir = tex_path.parent
    stem = tex_path.stem

    # --- Parse .log file ---
    log_path = work_dir / f"{stem}.log"
    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        for line in log_text.split("\n"):
            line_s = line.strip()
            # Unresolved references
            if "LaTeX Warning: Reference" in line_s and "undefined" in line_s:
                result.unresolved_refs.append(line_s)
            # Unresolved citations
            if "LaTeX Warning: Citation" in line_s and "undefined" in line_s:
                result.unresolved_cites.append(line_s)
            # Overfull hboxes (only flag significant ones > 1pt)
            if "Overfull \\hbox" in line_s:
                m = re.search(r"(\d+\.?\d*)pt", line_s)
                if m and float(m.group(1)) > 1.0:
                    result.overfull_hboxes.append(line_s)
            # Underfull hboxes (badness >= 5000)
            if "Underfull \\hbox" in line_s and "badness" in line_s:
                m = re.search(r"badness (\d+)", line_s)
                if m and int(m.group(1)) >= 5000:
                    result.underfull_hboxes.append(line_s)

    # --- Count pages from .aux or .log ---
    aux_path = work_dir / f"{stem}.aux"
    if aux_path.exists():
        aux_text = aux_path.read_text(encoding="utf-8", errors="replace")
        # Look for \newlabel{LastPage}{{N}{...}}
        m = re.search(r"\\newlabel\{LastPage\}\{\{(\d+)\}", aux_text)
        if m:
            result.page_count = int(m.group(1))
    if result.page_count == 0 and log_path.exists():
        # Fallback: count "Output written on ... (N pages)"
        m = re.search(r"Output written on .* \((\d+) page", log_text)
        if m:
            result.page_count = int(m.group(1))

    # --- Cross-reference validation ---
    tex_text = tex_path.read_text(encoding="utf-8", errors="replace")
    # Find all \label{fig:X}
    fig_labels = set(re.findall(r"\\label\{(fig:[^}]+)\}", tex_text))
    # Find all \ref{fig:X}
    fig_refs = set(re.findall(r"\\ref\{(fig:[^}]+)\}", tex_text))
    # Orphan labels (defined but never referenced)
    result.orphan_labels = sorted(fig_labels - fig_refs)
    # Orphan references (referenced but never defined)
    result.orphan_figures = sorted(fig_refs - fig_labels)

    # --- Build warnings summary ---
    if result.unresolved_refs:
        result.warnings_summary.append(
            f"{len(result.unresolved_refs)} unresolved reference(s)"
        )
    if result.unresolved_cites:
        result.warnings_summary.append(
            f"{len(result.unresolved_cites)} unresolved citation(s)"
        )
    if result.overfull_hboxes:
        result.warnings_summary.append(
            f"{len(result.overfull_hboxes)} overfull hbox(es) > 1pt"
        )
    if result.page_count > page_limit:
        result.warnings_summary.append(
            f"Page count {result.page_count} exceeds limit {page_limit}"
        )
    if result.orphan_figures:
        result.warnings_summary.append(
            f"{len(result.orphan_figures)} referenced but undefined figure(s): "
            + ", ".join(result.orphan_figures[:3])
        )
    if result.orphan_labels:
        result.warnings_summary.append(
            f"{len(result.orphan_labels)} defined but unreferenced figure(s): "
            + ", ".join(result.orphan_labels[:3])
        )

    return result


def _run_bibtex(work_dir: Path, stem: str, timeout: int = 60) -> bool:
    """Run bibtex if the binary exists. Returns True on success."""
    if not shutil.which("bibtex"):
        return False
    try:
        proc = subprocess.run(
            ["bibtex", stem],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
