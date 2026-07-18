"""Abstract interface for ASR (speech-to-text) backends."""

from abc import ABC, abstractmethod


class ASRInterface(ABC):
    """Interface for speech recognition models."""

    @abstractmethod
    def transcribe(self, audio_path: str) -> str:
        """Transcribe audio file to text with punctuation.

        Args:
            audio_path: Path to WAV audio file (16kHz+ recommended).

        Returns:
            Transcribed text with punctuation and capitalization.
        """
        ...
