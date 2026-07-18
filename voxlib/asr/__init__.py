"""ASR (Automatic Speech Recognition) backends for VoxLibRus."""

from voxlib.asr.base import ASRInterface, TranscriptionResult
from voxlib.asr.gigaam import GigaAMBackend
from voxlib.asr.whisper import WhisperBackend

__all__ = [
    "ASRInterface",
    "TranscriptionResult",
    "GigaAMBackend",
    "WhisperBackend",
]