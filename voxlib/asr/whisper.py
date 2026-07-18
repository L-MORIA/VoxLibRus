"""Whisper ASR fallback backend.

Model: openai/whisper-large-v3
License: MIT
WER on Russian: ~25.1%
Fallback for when GigaAM is unavailable.
"""

import warnings
from typing import Optional

import torch
import torchaudio

from voxlib.asr.base import ASRInterface, TranscriptionResult
from voxlib.config import WhisperConfig


class WhisperBackend(ASRInterface):
    """Whisper large-v3 ASR fallback backend."""

    def __init__(self, config: WhisperConfig):
        self.config = config
        self._model = None
        self._processor = None
        self._device = torch.device(config.device)

    def _load_model(self):
        """Lazy load Whisper model."""
        if self._model is not None:
            return

        try:
            from transformers import WhisperForConditionalGeneration, WhisperProcessor
        except ImportError as e:
            raise RuntimeError(
                "transformers not installed. Run: pip install transformers"
            ) from e

        # Suppress warnings
        warnings.filterwarnings("ignore", category=UserWarning, module="transformers")

        self._processor = WhisperProcessor.from_pretrained(
            self.config.model_id,
            language=self.config.language,
        )
        self._model = WhisperForConditionalGeneration.from_pretrained(
            self.config.model_id,
            torch_dtype=torch.float16 if self.config.device == "cuda" else torch.float32,
        ).to(self._device)

        # Set generation config for Russian
        self._model.generation_config.language = self.config.language
        self._model.generation_config.task = "transcribe"

        self._model.eval()

    def _load_audio(self, audio_path: str, target_sr: int = 16000) -> torch.Tensor:
        """Load and resample audio to target sample rate."""
        waveform, sample_rate = torchaudio.load(audio_path)

        # Convert to mono
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)

        # Resample if needed
        if sample_rate != target_sr:
            resampler = torchaudio.transforms.Resample(sample_rate, target_sr)
            waveform = resampler(waveform)

        return waveform.squeeze(0)

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio file to text using Whisper."""
        self._load_model()

        import time
        start_time = time.time()

        # Load audio (Whisper expects 16kHz)
        audio = self._load_audio(audio_path, target_sr=16000)

        # Process with Whisper processor
        inputs = self._processor(
            audio.numpy(),
            sampling_rate=16000,
            return_tensors="pt",
            padding=True,
        )

        input_features = inputs.input_features.to(self._device)

        # Generate transcription
        with torch.no_grad():
            predicted_ids = self._model.generate(
                input_features,
                language=language or self.config.language,
                task="transcribe",
            )

        # Decode
        transcription = self._processor.batch_decode(
            predicted_ids,
            skip_special_tokens=True,
        )[0]

        duration = time.time() - start_time

        return TranscriptionResult(
            text=transcription.strip(),
            language=language or self.config.language,
            duration_seconds=duration,
            confidence=None,  # Whisper doesn't easily provide confidence
            segments=None,
        )

    def transcribe_batch(
        self,
        audio_paths: list[str],
        language: Optional[str] = None,
    ) -> list[TranscriptionResult]:
        """Transcribe multiple audio files."""
        return [self.transcribe(path, language) for path in audio_paths]