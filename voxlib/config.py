"""Configuration management for VoxLibRus — Pydantic-validated."""

from pathlib import Path
from typing import Literal
from pydantic import BaseModel, model_validator, ConfigDict
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


class TTSConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: Literal["qwen3", "f5tts"] = "qwen3"
    qwen3: Qwen3Config = Qwen3Config()
    f5tts: F5TTSConfig = F5TTSConfig()


class VoiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profiles_dir: str = "~/.voxlib/speakers"


class GenerationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_max_chars: int = 1000
    chunk_overlap_chars: int = 50
    save_every_n: int = 10
    clear_cache_every_n: int = 20
    max_retries: int = 3
    retry_delay: int = 5


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
            raw = yaml.safe_load(f)
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
