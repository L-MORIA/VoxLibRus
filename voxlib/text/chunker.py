"""Smart text chunking for TTS generation.

Splits book text into fragments of ~500-1500 characters
at natural boundaries (paragraphs, sentences).
"""

import re
from typing import Any, Dict, List

# ── Types ────────────────────────────────────────────────────

Chunk = Dict[str, Any]
"""{
    "id": int,
    "chapter": str,
    "text": str,
    "chars": int,
    "chunk_index": int,   # index within chapter
    "chapter_chunks": int  # total chunks in this chapter
}"""


# ── Defaults ─────────────────────────────────────────────────

DEFAULT_MAX_CHARS = 1000
DEFAULT_MIN_CHARS = 500
DEFAULT_OVERLAP = 50


# ── Sentence splitting ───────────────────────────────────────

# Natural break priority
_PARAGRAPH_BREAK = re.compile(r'\n\s*\n')           # Double newline
_SENTENCE_BREAK = re.compile(r'(?<=[.!?…])\s+')     # After sentence end
_CLAUSE_BREAK = re.compile(r'(?<=[,;:—–-])\s+')     # After clause


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences, preserving punctuation."""
    # Normalize whitespace first
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return []

    # Split on sentence boundaries
    parts = _SENTENCE_BREAK.split(text)
    # Filter empty and merge very short fragments
    result = []
    for part in parts:
        part = part.strip()
        if part:
            result.append(part)
    return result


def _find_break_point(text: str, target: int, max_chars: int) -> int:
    """Find the best position to break text, preferring natural boundaries.

    Priority:
    1. Paragraph break (double newline)
    2. Sentence end (. ! ?)
    3. Clause break (, ; :)
    4. Word boundary (space)
    5. Hard character limit
    """
    search_start = max(target // 2, min(target - 50, max_chars - 200))
    search_text = text[:max_chars]

    # 1. Paragraph breaks (highest priority)
    for m in _PARAGRAPH_BREAK.finditer(search_text):
        pos = m.end()
        if search_start <= pos <= max_chars:
            return pos

    # 2. Sentence breaks
    for m in _SENTENCE_BREAK.finditer(search_text):
        pos = m.end()
        if search_start <= pos <= max_chars:
            return pos

    # 3. Clause breaks
    for m in _CLAUSE_BREAK.finditer(search_text):
        pos = m.end()
        if search_start <= pos <= max_chars:
            return pos

    # 4. Word boundary (space)
    last_space = text.rfind(' ', search_start, max_chars)
    if last_space > search_start:
        return last_space + 1

    # 5. Hard limit
    return max_chars


# ── Chunking logic ───────────────────────────────────────────


def chunk_text(
    chapters: Dict[str, str],
    max_chars: int = DEFAULT_MAX_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> List[Chunk]:
    """Split book text into fragments suitable for TTS.

    Args:
        chapters: Dict mapping chapter title -> chapter text.
        max_chars: Maximum characters per chunk (default: 1000).
        min_chars: Minimum characters per chunk (default: 500).
        overlap: Characters of overlap with previous chunk (default: 50).

    Returns:
        List of Chunk dicts with id, chapter, text, chars metadata.
    """
    chunks: List[Chunk] = []
    chunk_id = 0

    for chapter_title, chapter_text in chapters.items():
        if not chapter_text.strip():
            continue

        # Split chapter into rough segments by paragraph
        segments = _split_chapter_into_segments(chapter_text, max_chars)

        # Accumulate segments into chunks
        buffer = ""
        chapter_chunks = []

        for segment in segments:
            # If segment alone exceeds max_chars, split it
            if len(segment) > max_chars:
                # Flush current buffer first
                if buffer:
                    chunk_id += 1
                    c = _make_chunk(chunk_id, chapter_title, buffer.strip())
                    chunks.append(c)
                    chapter_chunks.append(c)
                    buffer = ""

                # Split long segment
                remaining = segment
                while len(remaining) > max_chars:
                    break_pos = _find_break_point(remaining, max_chars // 2, max_chars)
                    part = remaining[:break_pos].strip()
                    chunk_id += 1
                    c = _make_chunk(chunk_id, chapter_title, part)
                    chunks.append(c)
                    chapter_chunks.append(c)
                    # For overlap, find word boundary to avoid cutting words
                    overlap_start = _find_overlap_start(remaining, break_pos, overlap)
                    remaining = remaining[overlap_start:].strip()

                if remaining:
                    buffer = remaining
                continue

            # If adding segment exceeds max_chars, flush buffer first
            if buffer and len(buffer) + len(segment) + 1 > max_chars:
                if len(buffer) >= min_chars or not segment:
                    chunk_id += 1
                    c = _make_chunk(chunk_id, chapter_title, buffer.strip())
                    chunks.append(c)
                    chapter_chunks.append(c)
                    buffer = segment
                else:
                    # Buffer too small, keep accumulating
                    buffer += " " + segment
            else:
                buffer = (buffer + " " + segment).strip() if buffer else segment

        # Flush remaining buffer
        if buffer.strip():
            chunk_id += 1
            c = _make_chunk(chunk_id, chapter_title, buffer.strip())
            chunks.append(c)
            chapter_chunks.append(c)

        # Update chapter chunk counts
        total = len(chapter_chunks)
        for c in chapter_chunks:
            c["chapter_chunks"] = total

    return chunks


def _find_overlap_start(text: str, break_pos: int, overlap: int) -> int:
    """Find overlap start position that doesn't cut words.

    Searches backwards from break_pos - overlap to find a space.
    """
    target = max(0, break_pos - overlap)
    # Find nearest space before target
    space_pos = text.rfind(' ', 0, target)
    if space_pos > 0:
        return space_pos + 1
    # If no space found, use target (might cut word but avoids negative)
    return target


def _split_chapter_into_segments(text: str, max_chars: int) -> List[str]:
    """Split chapter text into segments at paragraph or sentence boundaries."""
    # Try paragraph breaks first
    paragraphs = _PARAGRAPH_BREAK.split(text)

    segments = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # If paragraph is short, keep as one segment
        if len(para) <= max_chars:
            segments.append(para)
        else:
            # Split long paragraph into sentences
            sentences = _split_sentences(para)
            segments.extend(sentences)

    return segments


def _make_chunk(chunk_id: int, chapter: str, text: str) -> Chunk:
    """Create a chunk dict with metadata."""
    return {
        "id": chunk_id,
        "chapter": chapter,
        "text": text,
        "chars": len(text),
    }


# ── Convenience ──────────────────────────────────────────────


def chunks_to_json(chunks: List[Chunk]) -> str:
    """Serialize chunks to JSON string."""
    import json
    return json.dumps(chunks, ensure_ascii=False, indent=2)
