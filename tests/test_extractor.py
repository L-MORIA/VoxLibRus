"""Tests for text extraction from book files."""

import pytest
from pathlib import Path
from voxlib.text.extractor import (
    extract,
    ExtractionError,
    UnsupportedFormatError,
    SUPPORTED_EXTENSIONS,
)
from tests.fixtures import ensure_fixtures, get_fixtures


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def _setup():
    """Create test fixtures once per session."""
    ensure_fixtures()


@pytest.fixture
def fixtures() -> dict[str, Path]:
    return get_fixtures()


# ── Supported formats ────────────────────────────────────────


class TestSupportedFormats:
    def test_supported_extensions_are_defined(self):
        assert ".pdf" in SUPPORTED_EXTENSIONS
        assert ".epub" in SUPPORTED_EXTENSIONS
        assert ".docx" in SUPPORTED_EXTENSIONS

    def test_extract_pdf_returns_dict(self, fixtures):
        if ".pdf" not in fixtures:
            pytest.skip("PDF fixture not available")
        result = extract(fixtures[".pdf"])
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_extract_epub_returns_dict(self, fixtures):
        if ".epub" not in fixtures:
            pytest.skip("EPUB fixture not available")
        result = extract(fixtures[".epub"])
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_extract_docx_returns_dict(self, fixtures):
        if ".docx" not in fixtures:
            pytest.skip("DOCX fixture not available")
        result = extract(fixtures[".docx"])
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_chapter_detection_epub(self, fixtures):
        """EPUB should detect chapter title from h1."""
        if ".epub" not in fixtures:
            pytest.skip("EPUB fixture not available")
        result = extract(fixtures[".epub"])
        chapters = " ".join(result.keys())
        assert "Глава" in chapters or "Начало" in chapters
        # Should have the actual content
        all_text = " ".join(result.values())
        assert "абзац" in all_text.lower()
        assert "42" in all_text
        assert "3.14" in all_text

    def test_epub_spine_order_not_manifest(self, tmp_path):
        """EPUB extraction should follow spine order (reading order), not manifest order.
        
        Regression test for: manifest lists 3,1,2 but spine says 1,2,3.
        Extractor must return chapters in spine order: Глава 1, Глава 2, Глава 3.
        """
        # Create the special fixture
        from tests.fixtures import _create_epub_manifest_vs_spine
        epub_path = tmp_path / "epub_spine_test.epub"
        _create_epub_manifest_vs_spine(epub_path)
        
        result = extract(epub_path)
        chapter_titles = list(result.keys())
        
        # Must be in spine order: 1, 2, 3
        assert chapter_titles == ["Глава 1", "Глава 2", "Глава 3"], \
            f"Expected spine order [1,2,3], got {chapter_titles}"


# ── Error handling ───────────────────────────────────────────


class TestErrorHandling:
    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            extract(Path("/nonexistent/book.pdf"))

    def test_unsupported_format_raises(self):
        with pytest.raises(UnsupportedFormatError):
            extract(Path("book.txt"))

    def test_unsupported_format_message(self):
        with pytest.raises(UnsupportedFormatError, match="\\.txt"):
            extract(Path("book.txt"))

    def test_empty_directory_doesnt_crash(self, tmp_path):
        """Non-existent file is handled gracefully."""
        with pytest.raises(FileNotFoundError):
            extract(tmp_path / "ghost.pdf")


# ── Edge cases ───────────────────────────────────────────────


class TestEdgeCases:
    def test_path_as_string(self, fixtures):
        """Function should accept str paths too."""
        if ".epub" not in fixtures:
            pytest.skip("EPUB not available")
        result = extract(str(fixtures[".epub"]))
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_invalid_epub_raises(self, tmp_path):
        """Corrupted EPUB should raise ExtractionError, not hang/crash."""
        epub_path = tmp_path / "corrupted.epub"
        epub_path.write_bytes(b"not a zip file")
        with pytest.raises(ExtractionError):
            extract(epub_path)
