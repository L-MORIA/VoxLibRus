"""Configuration management for VoxLibRus — Pydantic-validated."""

from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator, ConfigDict
import yaml


DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


# ── Вложенные модели ──────────────────────────────────────────

class ReferenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_sample_rate: int = 24000
    noise_reduce: bool = True
    trim_silence: bool = True
    normalize_peak_db: float = -3.0


class GigaAMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = "ai-sage/GigaAM-v3"
    revision: Literal["e2e_rnnt", "e2e_ctc", "ctc", "rnnt", "ssl"] = "e2e_rnnt"
    device: str = "cuda"


class WhisperConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = "openai/whisper-large-v3"
    device: str = "cuda"
    language: str = "ru"


class ASRConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: Literal["gigaam", "whisper"] = "gigaam"
    gigaam: GigaAMConfig = GigaAMConfig()
    whisper: WhisperConfig = WhisperConfig()


class Qwen3Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    device: str = "cuda"
    language: str = "ru"
    streaming: bool = False

    @model_validator(mode="after")
    def warn_if_customvoice(self):
        if "CustomVoice" in self.model_id and "Base" not in self.model_id:
            import warnings
            warnings.warn(
                f"CustomVoice ({self.model_id}) supports only 9 built-in speakers, "
                f"NOT arbitrary voice cloning. Use Qwen3-TTS-*-Base for voice clone."
            )
        return self


class F5TTSConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = "Misha24-10/F5-TTS_RUSSIAN"
    device: str = "cuda"
    ref_audio_sample_rate: int = 24000
    # Варианты: F5TTS_v1_Base | F5TTS_v1_Base_accent_tune | F5TTS_v1_Base_v2
    # accent_tune — с полной разметкой ударений, рекомендуется для качества
    variant: str = "F5TTS_v1_Base_accent_tune"


class TTSConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: Literal["qwen3", "f5tts"] = "f5tts"
    qwen3: Qwen3Config = Qwen3Config()
    f5tts: F5TTSConfig = F5TTSConfig()


class VoiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profiles_dir: str = "~/.voxlib/speakers"


class GenerationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_max_chars: int = Field(default=1000, gt=0)
    chunk_overlap_chars: int = Field(default=50, ge=0)
    save_every_n: int = Field(default=10, gt=0)
    clear_cache_every_n: int = Field(default=20, gt=0)
    max_retries: int = Field(default=3, ge=0)
    retry_delay: int = Field(default=5, ge=0)

    @model_validator(mode="after")
    def validate_chunking(self):
        if self.chunk_overlap_chars >= self.chunk_max_chars:
            raise ValueError("chunk_overlap_chars must be smaller than chunk_max_chars")
        return self


class OutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["mp3", "m4b", "both"] = "mp3"
    mp3_bitrate: int = 192


class AudioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_lufs: float = -16.0
    peak_dbfs: float = -1.0
    chapter_pause_sec: float = 2.5
    output: OutputConfig = OutputConfig()


class BookExtractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pdf_engine: Literal["pdfplumber", "pymupdf"] = "pdfplumber"
    epub_engine: str = "ebooklib"
    docx_engine: str = "markitdown"


class BookConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extract: BookExtractConfig = BookExtractConfig()


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "VoxLibRus"
    output_dir: str = "./output"
    temp_dir: str = "./temp"


# ── Корневая модель ───────────────────────────────────────────


class Config(BaseModel):
    """Полная конфигурация VoxLibRus. Валидируется при загрузке."""

    model_config = ConfigDict(extra="forbid")

    project: ProjectConfig = ProjectConfig()
    book: BookConfig = BookConfig()
    reference: ReferenceConfig = ReferenceConfig()
    asr: ASRConfig = ASRConfig()
    tts: TTSConfig = TTSConfig()
    voice: VoiceConfig = VoiceConfig()
    generation: GenerationConfig = GenerationConfig()
    audio: AudioConfig = AudioConfig()

    @classmethod
    def from_yaml(cls, path: Path = DEFAULT_CONFIG_PATH) -> "Config":
        if not path.exists():
            raise FileNotFoundError(f"Config not found: {path}")
        with open(path, encoding="utf-8") as f:
            raw: Any = yaml.safe_load(f) or {}
        if not isinstance(raw, dict):
            raise ValueError("Config root must be a YAML mapping")
        return cls(**raw)

    # ── Удобные property-шорткаты ──────────────────────────

    @property
    def output_dir(self) -> Path:
        return Path(self.project.output_dir)

    @property
    def temp_dir(self) -> Path:
        return Path(self.project.temp_dir)

    @property
    def profiles_dir(self) -> Path:
        return Path(self.voice.profiles_dir).expanduser()

    @property
    def asr_primary(self) -> str:
        return self.asr.primary

    @property
    def tts_primary(self) -> str:
        return self.tts.primary
