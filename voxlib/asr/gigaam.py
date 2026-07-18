"""GigaAM-v3 ASR backend for Russian speech recognition.

Model: ai-sage/GigaAM-v3
License: MIT
WER on Russian: ~8.4%
Requires: trust_remote_code=True (custom model code)
"""

import warnings
from typing import Optional

import torch
import torchaudio

from voxlib.asr.base import ASRInterface, TranscriptionResult
from voxlib.config import GigaAMConfig


class GigaAMBackend(ASRInterface):
    """GigaAM-v3 ASR backend using Hugging Face transformers."""

    def __init__(self, config: GigaAMConfig):
        self.config = config
        self._model = None
        self._processor = None
        self._device = torch.device(config.device)

    def _load_model(self):
        """Lazy load GigaAM-v3 model."""
        if self._model is not None:
            return

        try:
            from transformers import AutoModelForCTC, AutoProcessor
        except ImportError as e:
            raise RuntimeError(
                "transformers not installed. Run: pip install transformers"
            ) from e

        # Suppress specific warnings
        warnings.filterwarnings("ignore", category=UserWarning, module="transformers")

        # GigaAM-v3 requires trust_remote_code=True
        self._processor = AutoProcessor.from_pretrained(
            self.config.model_id,
            revision=self.config.revision,
            trust_remote_code=True,
        )
        self._model = AutoModelForCTC.from_pretrained(
            self.config.model_id,
            revision=self.config.revision,
            trust_remote_code=True,
            torch_dtype=torch.float16 if self.config.device == "cuda" else torch.float32,
        ).to(self._device)

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
        """Transcribe audio file to text."""
        self._load_model()

        import time
        start_time = time.time()

        # Load audio (GigaAM expects 16kHz)
        audio = self._load_audio(audio_path, target_sr=16000)

        # Process with GigaAM processor
        inputs = self._processor(
            audio.numpy(),
            sampling_rate=16000,
            return_tensors="pt",
            padding=True,
        )

        input_values = inputs.input_values.to(self._device)
        attention_mask = inputs.attention_mask.to(self._device) if inputs.attention_mask is not None else None

        # Generate transcription
        with torch.no_grad():
            logits = self._model(input_values, attention_mask=attention_mask).logits

        # Decode
        predicted_ids = torch.argmax(logits, dim=-1)
        transcription = self._processor.batch_decode(predicted_ids)[0]

        duration = time.time() - start_time

        return TranscriptionResult(
            text=transcription.strip(),
            language=language or "ru",
            duration_seconds=duration,
            confidence=None,  # GigaAM doesn't provide confidence scores
            segments=None,
        )

    def transcribe_batch(
        self,
        audio_paths: list[str],
        language: Optional[str] = None,
    ) -> list[TranscriptionResult]:
        """Transcribe multiple audio files."""
        return [self.transcribe(path, language) for path in audio_paths]