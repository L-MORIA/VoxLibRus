"""Abstract interface for TTS (text-to-speech) backends."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class VoiceProfile:
    """Represents a cloned voice identity."""
    name: str
    backend: str               # 'qwen3' | 'f5tts'
    ref_audio: str             # Path to processed reference audio
    ref_text: str              # Transcribed reference text
    embedding_path: str = ""   # Path to saved speaker embedding (for reuse)
    meta: dict = field(default_factory=dict)


@dataclass
class TTSGenerationConfig:
    """Configuration for speech generation."""
    # Stress marks handling
    apply_stress_marks: bool = True      # Whether to process '+' stress marks
    # Speed/temperature controls
    speed: float = 1.0                   # Speech speed multiplier
    temperature: float = 0.7             # Sampling temperature
    top_p: float = 0.9                   # Top-p sampling
    # Duration control (NEW: P1-3)
    fix_duration: Optional[float] = None  # Fixed duration in seconds (None = auto)
    # Voice-specific
    cross_fade_duration: float = 0.1     # Cross-fade between chunks (seconds)


class TTSInterface(ABC):
    """Interface for text-to-speech models with voice cloning."""

    @abstractmethod
    def clone_voice(
        self,
        ref_audio: str,
        ref_text: str,
        name: Optional[str] = None,
    ) -> VoiceProfile:
        """Create a voice profile from reference audio + text.

        Args:
            ref_audio: Path to clean reference WAV (24kHz mono recommended).
            ref_text: Accurate transcription of reference audio.
            name: Optional name for the voice profile.

        Returns:
            VoiceProfile containing the cloned voice identity.
        """
        ...

    @abstractmethod
    def generate(
        self,
        text: str,
        voice: VoiceProfile,
        output_path: str,
        config: Optional[TTSGenerationConfig] = None,
    ) -> Path:
        """Generate speech from text using a cloned voice.

        Args:
            text: Text to synthesize. May contain '+' stress marks
                  (e.g., "молок+о" for molokó).
            voice: Voice profile from clone_voice().
            output_path: Where to save the generated WAV.
            config: Optional generation configuration.

        Returns:
            Path to the generated audio file.
        """
        ...

    @abstractmethod
    def generate_batch(
        self,
        texts: list[str],
        voice: VoiceProfile,
        output_dir: str,
        config: Optional[TTSGenerationConfig] = None,
    ) -> list[Path]:
        """Generate multiple texts in batch for efficiency.

        Args:
            texts: List of texts to synthesize.
            voice: Voice profile from clone_voice().
            output_dir: Directory to save generated WAVs.
            config: Optional generation configuration.

        Returns:
            List of paths to generated audio files in order.
        """
        ...

    def supports_stress_marks(self) -> bool:
        """Whether this backend natively understands '+' stress marks."""
        return False