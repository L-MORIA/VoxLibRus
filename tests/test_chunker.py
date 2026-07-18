"""Tests for text chunking."""

import pytest

from voxlib.text.chunker import chunk_text, _find_break_point, _split_sentences


# ── Sentence splitting ───────────────────────────────────────


class TestSplitSentences:
    def test_simple_sentences(self):
        result = _split_sentences("Привет мир. Как дела?")
        assert len(result) == 2
        assert "Привет" in result[0]
        assert "Как дела" in result[1]

    def test_exclamation_question(self):
        result = _split_sentences("Стоп! Иди сюда?")
        assert len(result) == 2

    def test_empty_string(self):
        assert _split_sentences("") == []

    def test_whitespace_only(self):
        assert _split_sentences("   ") == []

    def test_ellipsis(self):
        result = _split_sentences("Ну… Ладно.")
        assert len(result) >= 1


# ── Break point finding ──────────────────────────────────────


class TestFindBreakPoint:
    def test_sentence_break(self):
        text = "Привет мир. Как дела. Тестовый текст."
        pos = _find_break_point(text, 15, 30)
        # Should break at sentence boundary (after first sentence)
        assert 10 < pos < 35
        assert "Привет мир" in text[:pos] or pos > 15

    def test_hard_limit(self):
        text = "а" * 200
        pos = _find_break_point(text, 100, 150)
        assert pos <= 150
        assert pos > 0

    def test_clause_break(self):
        text = "Пришёл, увидел, победил. Дальше текст."
        pos = _find_break_point(text, 15, 35)
        # Should prefer sentence or clause break
        assert pos > 15


# ── Full chunking ────────────────────────────────────────────


class TestChunkText:
    def test_single_chapter_single_chunk(self):
        chapters = {"Глава 1": "Короткий текст."}
        result = chunk_text(chapters)
        assert len(result) == 1
        assert result[0]["chapter"] == "Глава 1"
        assert result[0]["id"] == 1
        assert result[0]["chars"] > 0

    def test_multiple_chapters(self):
        chapters = {"Глава 1": "Текст первой главы.", "Глава 2": "Текст второй главы."}
        result = chunk_text(chapters)
        assert len(result) == 2
        assert result[0]["chapter"] == "Глава 1"
        assert result[1]["chapter"] == "Глава 2"

    def test_large_text_splits_into_multiple_chunks(self):
        """A long chapter should produce multiple chunks."""
        text = "Предложение. " * 100  # ~2500 chars
        chapters = {"Глава": text}
        result = chunk_text(chapters, max_chars=1000, min_chars=400)
        assert len(result) >= 2

    def test_chunks_within_max_chars(self):
        """No chunk should exceed max_chars."""
        text = "Предложение. " * 200
        chapters = {"Глава": text}
        result = chunk_text(chapters, max_chars=1000)
        for c in result:
            assert c["chars"] <= 1000, f"Chunk {c['id']} has {c['chars']} chars"

    def test_chunk_ids_sequential(self):
        chapters = {"1": "Текст.", "2": "Текст. " * 20, "3": "Текст."}
        result = chunk_text(chapters, max_chars=500)
        ids = [c["id"] for c in result]
        assert ids == list(range(1, len(result) + 1))

    def test_chapter_chunks_count(self):
        """Each chunk should know how many chunks its chapter has."""
        chapters = {"Глава": "Предложение. " * 30}
        result = chunk_text(chapters, max_chars=300, min_chars=100)
        total = result[-1]["chapter_chunks"]
        assert total == len(result)
        for c in result:
            assert c["chapter_chunks"] == total

    def test_empty_chapters(self):
        result = chunk_text({})
        assert result == []

    def test_empty_text_in_chapter(self):
        result = chunk_text({"Глава": ""})
        assert result == []

    def test_whitespace_only_chapter(self):
        result = chunk_text({"Глава": "   \n\n  "})
        assert result == []


# ── Edge cases ───────────────────────────────────────────────


class TestEdgeCases:
    def test_single_word(self):
        result = chunk_text({"Глава": "Привет"})
        assert len(result) == 1
        assert result[0]["text"] == "Привет"

    def test_exact_boundary(self):
        """Text exactly at max_chars should be one chunk."""
        text = "а" * 1000
        result = chunk_text({"Глава": text}, max_chars=1000)
        assert len(result) == 1
        assert result[0]["chars"] == 1000

    def test_overlap_preserves_text(self):
        """Text with overlap should not lose content."""
        text = "Предложение. " * 30
        chapters = {"Глава": text}
        result = chunk_text(chapters, max_chars=500, overlap=50)
        # Combine all chunks
        combined = " ".join(c["text"] for c in result)
        # Should contain all words approximately
        assert len(combined) >= len(text) * 0.8  # Some overlap but no data loss

    def test_small_buffer_never_makes_an_overlong_chunk(self):
        text = "а" * 200 + "\n\n" + "б" * 900
        result = chunk_text({"Глава": text}, max_chars=1000, min_chars=500)
        assert all(chunk["chars"] <= 1000 for chunk in result)

    @pytest.mark.parametrize("kwargs", [
        {"max_chars": 0},
        {"min_chars": -1},
        {"overlap": -1},
    ])
    def test_invalid_chunking_settings_fail_fast(self, kwargs):
        with pytest.raises(ValueError):
            chunk_text({"Глава": "Текст"}, **kwargs)
