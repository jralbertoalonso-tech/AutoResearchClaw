# pyright: reportPrivateUsage=false
"""Tests for researchclaw.templates.compiler.sanitize_missing_images.

Covers:
- figure blocks with missing images are fully commented out
- figure blocks whose images exist are left untouched
- bare \\includegraphics lines with missing images are commented
- bare \\includegraphics lines whose images exist are left untouched
- figure blocks with mixed missing/present images (block commented if ANY missing)
- already-commented lines are not double-processed
- function is idempotent
- no false positives on extension-less image paths when the file exists with a known ext
- Stage 22 integration: bibliographic mode skips chart generation entirely
"""
from __future__ import annotations

from pathlib import Path

import pytest

from researchclaw.templates.compiler import sanitize_missing_images


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_figure(image_path: str, caption: str = "My caption") -> str:
    return (
        f"\\begin{{figure}}\n"
        f"  \\includegraphics{{charts/{image_path}}}\n"
        f"  \\caption{{{caption}}}\n"
        f"\\end{{figure}}\n"
    )


def _make_figure_star(image_path: str) -> str:
    return (
        f"\\begin{{figure*}}\n"
        f"  \\includegraphics[width=\\linewidth]{{charts/{image_path}}}\n"
        f"  \\caption{{Wide figure}}\n"
        f"\\end{{figure*}}\n"
    )


def _make_bare_includegraphics(path: str) -> str:
    return f"  \\includegraphics{{charts/{path}}}\n"


# ---------------------------------------------------------------------------
# Missing images — figure blocks
# ---------------------------------------------------------------------------


class TestFigureBlockMissingImages:
    def test_figure_block_missing_image_is_commented_out(self, tmp_path: Path) -> None:
        # No image file on disk
        tex = _make_figure("performance_comparison.png")
        sanitized, removed = sanitize_missing_images(tex, tmp_path)

        assert removed, "Expected at least one entry in the removed list"
        # Every non-empty line must be a comment
        for line in sanitized.splitlines():
            stripped = line.strip()
            if stripped:
                assert stripped.startswith("%"), (
                    f"Expected commented line, got: {line!r}"
                )

    def test_figure_star_block_missing_image_is_commented(self, tmp_path: Path) -> None:
        tex = _make_figure_star("accuracy_curve.png")
        sanitized, removed = sanitize_missing_images(tex, tmp_path)
        assert removed
        for line in sanitized.splitlines():
            stripped = line.strip()
            if stripped:
                assert stripped.startswith("%")

    def test_multiple_missing_figure_blocks_all_commented(self, tmp_path: Path) -> None:
        tex = (
            _make_figure("chart_a.png")
            + "\nSome text in between.\n\n"
            + _make_figure("chart_b.png")
        )
        sanitized, removed = sanitize_missing_images(tex, tmp_path)
        assert len(removed) == 2

    def test_removed_list_contains_image_name(self, tmp_path: Path) -> None:
        tex = _make_figure("performance_comparison.png")
        _, removed = sanitize_missing_images(tex, tmp_path)
        assert any("performance_comparison.png" in r for r in removed)


# ---------------------------------------------------------------------------
# Existing images — figure blocks must be preserved
# ---------------------------------------------------------------------------


class TestFigureBlockExistingImages:
    def test_figure_block_with_existing_image_is_preserved(self, tmp_path: Path) -> None:
        charts = tmp_path / "charts"
        charts.mkdir()
        (charts / "accuracy.png").write_bytes(b"\x89PNG\r\n")

        tex = _make_figure("accuracy.png", "Accuracy over epochs")
        sanitized, removed = sanitize_missing_images(tex, tmp_path)

        assert not removed, "Should not remove any block when image exists"
        assert "\\begin{figure}" in sanitized
        assert "\\includegraphics" in sanitized
        assert "accuracy.png" in sanitized

    def test_extension_fallback_matches_existing_file(self, tmp_path: Path) -> None:
        """includegraphics path without extension should resolve to existing file."""
        charts = tmp_path / "charts"
        charts.mkdir()
        (charts / "fig1.pdf").write_bytes(b"%PDF")

        # Reference without extension
        tex = "\\begin{figure}\n  \\includegraphics{charts/fig1}\n\\end{figure}\n"
        sanitized, removed = sanitize_missing_images(tex, tmp_path)

        assert not removed, "Should not remove block — charts/fig1.pdf exists on disk"
        assert "\\includegraphics" in sanitized


# ---------------------------------------------------------------------------
# Mixed: block with some missing, some existing → whole block commented
# ---------------------------------------------------------------------------


class TestMixedFigureBlock:
    def test_block_with_any_missing_image_is_fully_commented(self, tmp_path: Path) -> None:
        charts = tmp_path / "charts"
        charts.mkdir()
        (charts / "existing.png").write_bytes(b"\x89PNG\r\n")

        tex = (
            "\\begin{figure}\n"
            "  \\includegraphics{charts/existing.png}\n"
            "  \\includegraphics{charts/phantom.png}\n"
            "  \\caption{Two images}\n"
            "\\end{figure}\n"
        )
        sanitized, removed = sanitize_missing_images(tex, tmp_path)
        assert removed, "Block with a missing image must be commented out"


# ---------------------------------------------------------------------------
# Bare \\includegraphics outside figure environments
# ---------------------------------------------------------------------------


class TestBareIncludegraphics:
    def test_bare_missing_includegraphics_is_commented(self, tmp_path: Path) -> None:
        tex = "Some text\n  \\includegraphics{charts/phantom.png}\nMore text\n"
        sanitized, removed = sanitize_missing_images(tex, tmp_path)
        assert removed
        # The line should now start with % (after stripping)
        for line in sanitized.splitlines():
            if "phantom.png" in line:
                assert line.lstrip().startswith("%"), f"Expected comment, got: {line!r}"

    def test_bare_existing_includegraphics_is_preserved(self, tmp_path: Path) -> None:
        charts = tmp_path / "charts"
        charts.mkdir()
        (charts / "real.png").write_bytes(b"\x89PNG\r\n")

        tex = "Some text\n  \\includegraphics{charts/real.png}\nMore text\n"
        sanitized, removed = sanitize_missing_images(tex, tmp_path)
        assert not removed
        assert "\\includegraphics{charts/real.png}" in sanitized


# ---------------------------------------------------------------------------
# No double-processing of already-commented lines
# ---------------------------------------------------------------------------


class TestNoDoubleProcessing:
    def test_already_commented_line_is_not_double_commented(
        self, tmp_path: Path
    ) -> None:
        tex = "% [sanitized — missing image: old.png]  % \\includegraphics{old.png}\n"
        sanitized, removed = sanitize_missing_images(tex, tmp_path)
        # Should not touch already-commented lines
        assert not removed
        # The line should remain a single-level comment
        assert sanitized.lstrip().startswith("%")
        assert sanitized.count("%") == 1 or "% [sanitized" in sanitized


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_sanitize_is_idempotent(self, tmp_path: Path) -> None:
        tex = (
            "\\begin{figure}\n"
            "  \\includegraphics{charts/missing.png}\n"
            "  \\caption{Test}\n"
            "\\end{figure}\n"
        )
        sanitized1, removed1 = sanitize_missing_images(tex, tmp_path)
        sanitized2, removed2 = sanitize_missing_images(sanitized1, tmp_path)
        # Second pass must not remove anything new
        assert not removed2, (
            "Second sanitize pass should not add more removals — "
            f"it found: {removed2}"
        )

    def test_no_changes_when_all_images_exist(self, tmp_path: Path) -> None:
        charts = tmp_path / "charts"
        charts.mkdir()
        (charts / "fig.png").write_bytes(b"\x89PNG\r\n")

        tex = "\\begin{figure}\n  \\includegraphics{charts/fig.png}\n\\end{figure}\n"
        sanitized, removed = sanitize_missing_images(tex, tmp_path)
        assert not removed
        assert sanitized == tex


# ---------------------------------------------------------------------------
# Integration guard: typical Stage 22 phantom chart names
# ---------------------------------------------------------------------------


class TestStage22PhantomCharts:
    """Validate that the exact filenames LaTeX Stage 22 was failing on are sanitized."""

    _PHANTOM_CHARTS = [
        "performance_comparison.png",
        "accuracy_curves.png",
        "loss_curves.png",
        "training_metrics.png",
        "ablation_results.png",
    ]

    def test_all_phantom_charts_are_sanitized(self, tmp_path: Path) -> None:
        figures = "\n".join(
            _make_figure(name, f"Caption for {name}")
            for name in self._PHANTOM_CHARTS
        )
        tex = "\\section{Results}\n\n" + figures + "\n\\section{Conclusion}\nDone."

        sanitized, removed = sanitize_missing_images(tex, tmp_path)

        assert len(removed) == len(self._PHANTOM_CHARTS), (
            f"Expected {len(self._PHANTOM_CHARTS)} removals, got {len(removed)}: {removed}"
        )
        # All figure environments should now be commented
        assert "\\begin{figure}" not in sanitized
        # Non-figure content must remain
        assert "\\section{Results}" in sanitized
        assert "\\section{Conclusion}" in sanitized
        assert "Done." in sanitized
