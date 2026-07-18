"""Integration test: full text pipeline from book to chunks."""

import pytest
from voxlib.text.extractor import extract
from voxlib.text.cleaner import clean_text
from voxlib.text.chunker import chunk_text
from tests.fixtures import ensure_fixtures, get_fixtures


@pytest.fixture(scope="module", autouse=True)
def _setup():
    ensure_fixtures()


class TestFullPipeline:
    def _run_pipeline(self, format: str) -> int:
        """Run extract → clean → chunk for a fixture format. Returns chunk count."""
        fixtures = get_fixtures()
        ext = f".{format}"
        if ext not in fixtures:
            pytest.skip(f"{format.upper()} fixture not available")

        # Step 1: Extract
        chapters = extract(fixtures[ext])
        assert len(chapters) > 0, f"No chapters extracted from {format}"

        # Step 2: Clean each chapter
        cleaned = {}
        for title, text in chapters.items():
            cleaned[title] = clean_text(text)

        # Step 3: Chunk
        chunks = chunk_text(cleaned)
        assert len(chunks) > 0, f"No chunks produced from {format}"

        # Validate all chunks
        for c in chunks:
            assert "id" in c
            assert "chapter" in c
            assert "text" in c
            assert "chars" in c
            assert c["chars"] > 0
            assert c["chars"] <= 1050  # within max_chars + small margin

        return len(chunks)

    def test_pdf_pipeline(self):
        count = self._run_pipeline("pdf")
        print(f"PDF: {count} chunks")

    def test_epub_pipeline(self):
        count = self._run_pipeline("epub")
        print(f"EPUB: {count} chunks")

    def test_cleaner_in_pipeline(self):
        """Verify cleaner normalizes numbers/quotes in extracted text."""
        fixtures = get_fixtures()
        if ".epub" not in fixtures:
            pytest.skip("EPUB not available")

        chapters = extract(fixtures[".epub"])
        for title, text in chapters.items():
            cleaned = clean_text(text)
            # Numbers should be converted to words
            assert "сорок два" in cleaned or "три целых" in cleaned

    def test_chunk_with_cleaner(self):
        """Clean text before chunking → clean chunks."""
        fixtures = get_fixtures()
        if ".epub" not in fixtures:
            pytest.skip("EPUB not available")

        chapters = extract(fixtures[".epub"])
        cleaned = {t: clean_text(txt) for t, txt in chapters.items()}
        chunks = chunk_text(cleaned)

        for c in chunks:
            # Chunks should not have raw quotes
            assert '"' not in c["text"] or "«" in c["text"]
