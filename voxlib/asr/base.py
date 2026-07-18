"""ASR (Automatic Speech Recognition) base interface."""

from abc import ABC, abstractmethod
from typing import Optional
from dataclasses import dataclass


@dataclass
class TranscriptionResult:
    """Result of ASR transcription."""
    text: str
    language: str
    duration_seconds: float
    confidence: Optional[float] = None
    segments: Optional[list] = None  # For detailed segment info


class ASRInterface(ABC):
    """Abstract interface for ASR backends."""

    @abstractmethod
    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio to text.

        Args:
            audio_path: Path to audio file.
            language: Optional language hint (e.g., "ru", "en").

        Returns:
            TranscriptionResult with text and metadata.
        """
        ...

    @abstractmethod
    def transcribe_batch(
        self,
        audio_paths: list[str],
        language: Optional[str] = None,
    ) -> list[TranscriptionResult]:
        """Transcribe multiple audio files.

        Args:
            audio_paths: List of paths to audio files.
            language: Optional language hint.

        Returns:
            List of TranscriptionResult objects.
        """
        ...