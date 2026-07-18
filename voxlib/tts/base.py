"""Abstract interface for TTS (text-to-speech) backends."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class VoiceProfile:
    """Represents a cloned voice identity."""
    name: str
    backend: str               # 'qwen3' | 'f5tts'
    ref_audio: str             # Path to processed reference audio
    ref_text: str              # Transcribed reference text
    embedding_path: str = ""   # Path to saved speaker embedding
    meta: dict = field(default_factory=dict)


class TTSInterface(ABC):
    """Interface for text-to-speech models with voice cloning."""

    @abstractmethod
    def clone_voice(self, ref_audio: str, ref_text: str) -> VoiceProfile:
        """Create a voice profile from reference audio + text.

        Args:
            ref_audio: Path to clean reference WAV.
            ref_text: Accurate transcription of reference audio.

        Returns:
            VoiceProfile containing the cloned voice identity.
        """
        ...

    @abstractmethod
    def generate(self, text: str, voice: VoiceProfile, output_path: str) -> Path:
        """Generate speech from text using a cloned voice.

        Args:
            text: Text to synthesize.
            voice: Voice profile from clone_voice().
            output_path: Where to save the generated WAV.

        Returns:
            Path to the generated audio file.
        """
        ...
