"""Tests for VoxLibRus configuration module."""

from pathlib import Path
import pytest
from pydantic import ValidationError
from voxlib.config import Config, Qwen3Config


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def cfg() -> Config:
    return Config.from_yaml(Path(__file__).parent.parent / "config.yaml")


# ── Config loading ────────────────────────────────────────────


class TestConfigLoad:
    def test_loads_without_error(self, cfg: Config):
        """Config loads from YAML without raising."""
        assert cfg.project.name == "VoxLibRus"

    def test_asr_primary_is_gigaam(self, cfg: Config):
        assert cfg.asr_primary == "gigaam"

    def test_tts_primary_is_qwen3(self, cfg: Config):
        assert cfg.tts_primary == "qwen3"

    def test_qwen3_model_is_base(self, cfg: Config):
        """Must be Base, NOT CustomVoice — Base supports voice cloning."""
        model = cfg.tts.qwen3.model_id
        assert "Base" in model, f"Expected Base model for voice clone, got: {model}"
        assert "CustomVoice" not in model

    def test_streaming_is_false(self, cfg: Config):
        """Streaming should be off for batch book generation."""
        assert cfg.tts.qwen3.streaming is False

    def test_generation_params(self, cfg: Config):
        assert cfg.generation.chunk_max_chars == 1000
        assert cfg.generation.chunk_overlap_chars == 50
        assert cfg.generation.max_retries == 3
        assert cfg.generation.retry_delay == 5

    def test_audio_params(self, cfg: Config):
        assert cfg.audio.target_lufs == -16.0
        assert cfg.audio.peak_dbfs == -1.0
        assert cfg.audio.chapter_pause_sec == 2.5
        assert cfg.audio.output.format == "mp3"
        assert cfg.audio.output.mp3_bitrate == 192

    def test_profiles_dir_resolves(self, cfg: Config):
        assert cfg.profiles_dir.name == "speakers"
        assert ".voxlib" in str(cfg.profiles_dir)


# ── Pydantic validation ───────────────────────────────────────


class TestPydanticValidation:
    def test_invalid_asr_primary_raises(self):
        with pytest.raises(ValidationError):
            Config(**{"asr": {"primary": "invalid_backend"}})

    def test_invalid_tts_primary_raises(self):
        with pytest.raises(ValidationError):
            Config(**{"tts": {"primary": "invalid_backend"}})

    def test_invalid_output_format_raises(self):
        with pytest.raises(ValidationError):
            Config(**{"audio": {"output": {"format": "wav"}}})

    @pytest.mark.filterwarnings("ignore::UserWarning")  # CustomVoice warning expected
    def test_customvoice_triggers_warning(self):
        """CustomVoice model should produce a warning about no voice clone."""
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Qwen3Config(model_id="Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
            assert len(w) == 1
            assert "CustomVoice" in str(w[0].message)
            assert "NOT arbitrary voice cloning" in str(w[0].message)

    def test_base_model_no_warning(self):
        """Base model should load without warnings."""
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Qwen3Config(model_id="Qwen/Qwen3-TTS-12Hz-1.7B-Base")
            assert len(w) == 0  # no warnings


# ── Edge cases ────────────────────────────────────────────────


class TestEdgeCases:
    def test_missing_yaml_raises(self):
        with pytest.raises(FileNotFoundError):
            Config.from_yaml(Path("/nonexistent/config.yaml"))

    def test_empty_config_uses_defaults(self, tmp_path):
        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")
        assert Config.from_yaml(path).project.name == "VoxLibRus"

    def test_chunk_overlap_must_be_smaller_than_chunk_size(self, tmp_path):
        path = tmp_path / "invalid.yaml"
        path.write_text(
            "generation:\n  chunk_max_chars: 100\n  chunk_overlap_chars: 100\n",
            encoding="utf-8",
        )
        with pytest.raises(ValidationError, match="chunk_overlap_chars"):
            Config.from_yaml(path)
