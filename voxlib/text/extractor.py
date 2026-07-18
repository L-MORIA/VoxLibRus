"""Text extraction from PDF, EPUB, and DOCX files.

Returns structured content with chapter detection.
"""

from pathlib import Path
from typing import Dict, List



# ── Types ────────────────────────────────────────────────────

BookContent = Dict[str, str]  # chapter_title -> text


# ── Exceptions ───────────────────────────────────────────────

class ExtractionError(Exception):
    """Raised when text extraction fails."""


class UnsupportedFormatError(ExtractionError):
    """Raised for unsupported file formats."""


# ── Supported extensions ─────────────────────────────────────

SUPPORTED_EXTENSIONS = {".pdf", ".epub", ".docx"}


# ── PDF extraction ───────────────────────────────────────────

def _extract_pdf(path: Path) -> BookContent:
    """Extract text from PDF using pdfplumber."""
    try:
        import pdfplumber
    except ImportError:
        raise ExtractionError("pdfplumber not installed. Run: pip install pdfplumber")

    chapters: BookContent = {}
    current_chapter = "Текст"
    current_lines: List[str] = []

    def _flush():
        nonlocal current_lines, current_chapter
        text = " ".join(current_lines).strip()
        if text:
            # Append if chapter already exists
            if current_chapter in chapters:
                chapters[current_chapter] += "\n\n" + text
            else:
                chapters[current_chapter] = text
        current_lines = []

    def _is_chapter_header(text: str) -> bool:
        """Heuristic: short line, all-caps or starts with 'Глава'/'Chapter'."""
        t = text.strip()
        if not t or len(t) > 200:
            return False
        # Russian/English chapter markers
        if any(t.lower().startswith(x) for x in
               ("глава", "chapter", "часть", "part", "раздел", "section",
                "предисловие", "введение", "эпилог", "послесловие",
                "приложение", "appendix", "пролог", "prologue")):
            return True
        # All-caps headers (typical for book chapters)
        if t.isupper() and len(t) > 3 and len(t) < 100:
            return True
        return False

    with pdfplumber.open(path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            lines = text.split("\n")

            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue

                if _is_chapter_header(stripped):
                    _flush()
                    current_chapter = stripped[:120]  # limit chapter name length
                else:
                    current_lines.append(stripped)

            # Flush per-page footer/header garbage
            if page_num % 5 == 0:
                pass  # Keep accumulating — chapters span pages

        _flush()  # Final flush

    if not chapters:
        # Fallback: whole text as one chapter
        raw = "\n".join(
            page.extract_text() or "" for page in pdf.pages
        )
        chapters = {"Текст": raw.strip()}

    return chapters


# ── EPUB extraction ──────────────────────────────────────────

def _extract_epub(path: Path) -> BookContent:
    """Extract text from EPUB using ebooklib + BeautifulSoup.
    
    Uses spine order (reading order) instead of manifest order.
    """
    try:
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup
    except ImportError:
        raise ExtractionError(
            "ebooklib/beautifulsoup4 not installed. Run: pip install ebooklib beautifulsoup4"
        )

    book = epub.read_epub(str(path))
    chapters: BookContent = {}

    # Get spine order (reading order) - list of (idref, linear)
    spine_items = book.spine

    for item_ref in spine_items:
        # item_ref can be tuple (idref, linear) or just idref string
        if isinstance(item_ref, tuple):
            item_id = item_ref[0]
        else:
            item_id = item_ref

        item = book.get_item_with_id(item_id)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue

        soup = BeautifulSoup(item.get_content(), "html.parser")

        # Remove scripts, styles, nav
        for tag in soup(["script", "style", "nav"]):
            tag.decompose()

        # Try to find chapter title from h1/h2/title
        title_tag = soup.find(["h1", "h2", "title"])
        chapter_title = title_tag.get_text(strip=True)[:120] if title_tag else item.get_name()

        text = soup.get_text(separator="\n", strip=True)
        if text:
            chapters[chapter_title or "Текст"] = text

    if not chapters:
        chapters = {"Текст": ""}

    return chapters


# ── DOCX extraction ──────────────────────────────────────────

def _extract_docx(path: Path) -> BookContent:
    """Extract text from DOCX using markitdown or python-docx."""
    try:
        from markitdown import MarkItDown
    except ImportError:
        try:
            # Fallback to python-docx
            import docx
            doc = docx.Document(str(path))
            chapters: BookContent = {}
            current_chapter = "Текст"
            current_lines: List[str] = []

            for para in doc.paragraphs:
                text = para.text.strip()
                if not text:
                    continue
                style = para.style.name.lower() if para.style else ""
                if "heading" in style or "глава" in style or "heading" in style:
                    if current_lines:
                        chapters[current_chapter] = "\n".join(current_lines)
                    current_chapter = text[:120]
                    current_lines = []
                else:
                    current_lines.append(text)

            if current_lines:
                chapters[current_chapter] = "\n".join(current_lines)
            return chapters if chapters else {"Текст": ""}

        except ImportError:
            raise ExtractionError(
                "markitdown or python-docx not installed. "
                "Run: pip install markitdown  # or python-docx"
            )

    # Use markitdown (handles DOCX natively)
    md = MarkItDown()
    result = md.convert(str(path))
    # Parse markdown output for chapter-like headers
    chapters: BookContent = {}
    current_chapter = "Текст"
    current_lines: List[str] = []

    for line in result.text_content.split("\n"):
        if line.startswith("# ") or line.startswith("## "):
            if current_lines:
                chapters[current_chapter] = "\n".join(current_lines).strip()
            current_chapter = line.lstrip("#").strip()[:120]
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        chapters[current_chapter] = "\n".join(current_lines).strip()
    return chapters if chapters else {"Текст": result.text_content.strip()}


# ── Main entry point ─────────────────────────────────────────


def extract(path: Path) -> BookContent:
    """Extract structured text from a book file.

    Args:
        path: Path to .pdf, .epub, or .docx file.

    Returns:
        Dict mapping chapter titles to their text content.

    Raises:
        FileNotFoundError: if path doesn't exist.
        UnsupportedFormatError: if file format is not supported.
        ExtractionError: if extraction fails.
    """
    path = Path(path)

    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"Unsupported format: {ext}. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    if not path.exists():
        raise FileNotFoundError(f"Book not found: {path}")

    extractors = {
        ".pdf": _extract_pdf,
        ".epub": _extract_epub,
        ".docx": _extract_docx,
    }

    try:
        return extractors[ext](path)
    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(f"Failed to extract text from {path.name}: {e}") from e
