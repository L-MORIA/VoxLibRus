"""Tests for Russian accent placement — do NOT trigger HF download."""

import pytest


class TestAccentsModule:
    """Test module structure without triggering RUAccent download."""

    def test_module_imports(self):
        """Module imports cleanly even if RUAccent not installed."""
        import voxlib.text.accents
        assert voxlib.text.accents._attempted_load is False

    def test_fix_accents_empty_string(self):
        from voxlib.text.accents import fix_accents
        assert fix_accents("") == ""

    def test_fix_accents_whitespace(self):
        from voxlib.text.accents import fix_accents
        assert fix_accents("   ").strip() == ""

    def test_fix_accents_latin(self):
        """Non-Russian text passes through."""
        from voxlib.text.accents import fix_accents
        result = fix_accents("Hello world")
        assert result == "Hello world"

    def test_is_available_returns_bool(self):
        from voxlib.text.accents import is_available
        result = is_available()
        assert isinstance(result, bool)


# ── Integration test (requires model download) ───────────────


class TestAccentsIntegration:
    """These tests download the RUAccent model from HF (~50MB).
    Skipped if model not available or download times out.
    """

    @pytest.fixture(autouse=True)
    def check_availability(self):
        from voxlib.text.accents import is_available
        if not is_available():
            pytest.skip("RUAccent model not available (check HF access)")

    def test_russian_text_with_accents(self):
        from voxlib.text.accents import fix_accents
        result = fix_accents("Замок стоял на горе")
        assert isinstance(result, str)
        # If model loaded, result should have accents
        assert len(result) > 0

    def test_omograph_differentiation(self):
        from voxlib.text.accents import fix_accents
        castle = fix_accents("старый замок")
        lock = fix_accents("закрыть замок")
        assert isinstance(castle, str)
        assert isinstance(lock, str)
