"""GigaAM-v3 ASR backend for Russian speech recognition.

Model: ai-sage/GigaAM-v3
License: MIT
WER on Russian: ~8.4% (e2e_rnnt revision)
Requires: trust_remote_code=True (custom model code)
Usage: model = AutoModel.from_pretrained("ai-sage/GigaAM-v3", revision="e2e_rnnt", trust_remote_code=True)
       transcription = model.transcribe("example.wav")
"""

import warnings
import os
import tempfile
from pathlib import Path
from typing import Optional

import torch
import torchaudio

from voxlib.asr.base import ASRInterface, TranscriptionResult
from voxlib.config import GigaAMConfig


class GigaAMBackend(ASRInterface):
    """GigaAM-v3 ASR backend using Hugging Face transformers with trust_remote_code.

    Uses the model's built-in .transcribe() method which handles preprocessing internally.
    Loads from local safetensors file (converted from pytorch_model.bin) to avoid
    torch.load vulnerability (CVE-2025-32434).
    """

    MAX_DURATION_SECONDS = 25.0  # Model limit for direct transcribe

    def __init__(self, config: GigaAMConfig):
        self.config = config
        self._model = None
        self._device = torch.device(config.device)

    def _load_model(self):
        """Lazy load GigaAM-v3 model from local safetensors."""
        if self._model is not None:
            return

        try:
            from transformers import AutoModel, AutoConfig
            from safetensors.torch import load_file
        except ImportError as e:
            raise RuntimeError(
                "Required packages not installed. Run: pip install transformers safetensors huggingface_hub"
            ) from e

        # Suppress specific warnings
        warnings.filterwarnings("ignore", category=UserWarning, module="transformers")

        # Download and convert to safetensors if needed
        repo_id = self.config.model_id
        revision = self.config.revision
        safetensors_path = self._get_or_create_safetensors(repo_id, revision)

        # Load model config first (with trust_remote_code)
        config = AutoConfig.from_pretrained(
            repo_id,
            revision=revision,
            trust_remote_code=True,
        )

        # Create model from config (no weights)
        model = AutoModel.from_config(
            config,
            trust_remote_code=True,
            dtype=torch.float16 if self.config.device == "cuda" else torch.float32,
        )

        # Load weights from safetensors
        state_dict = load_file(safetensors_path)
        model.load_state_dict(state_dict, strict=False)

        self._model = model.to(self._device)
        self._model.eval()

    def _get_or_create_safetensors(self, repo_id: str, revision: str) -> str:
        """Download model and convert to safetensors if needed."""
        from huggingface_hub import hf_hub_download
        from safetensors.torch import save_file
        import torch

        # Get the cached bin file path
        bin_path = hf_hub_download(
            repo_id=repo_id,
            filename="pytorch_model.bin",
            revision=revision,
        )

        safetensors_path = Path(bin_path).with_suffix(".safetensors")

        if not os.path.exists(safetensors_path):
            print(f"Converting {bin_path} to safetensors...")
            state_dict = torch.load(bin_path, map_location="cpu", weights_only=True)
            from safetensors.torch import save_file
            save_file(state_dict, safetensors_path)
            print(f"Saved safetensors to: {safetensors_path}")

        return str(safetensors_path)

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
    ):
        """Transcribe audio file to text using GigaAM's built-in transcribe method.

        For files longer than 25 seconds, automatically chunks into segments
        and concatenates results.

        Args:
            audio_path: Path to audio file (WAV, MP3, etc.). The model uses ffmpeg internally
                       to load and resample the audio.
            language: Language code (default: "ru")

        Returns:
            TranscriptionResult with text and metadata.
        """
        self._load_model()

        import time

        start_time = time.time()

        # Check audio duration
        info = torchaudio.info(audio_path)
        duration = info.num_frames / info.sample_rate

        # If short enough, transcribe directly
        if duration <= self.MAX_DURATION_SECONDS:
            with torch.no_grad():
                transcription = self._model.transcribe(audio_path)

            return TranscriptionResult(
                text=transcription.strip(),
                language=language or "ru",
                duration_seconds=time.time() - start_time,
                confidence=None,
                segments=None,
            )

        # Long audio: chunk and transcribe
        print(f"Audio duration: {duration:.1f}s, splitting into chunks...")

        chunk_files = self._chunk_audio(audio_path, max_duration=self.MAX_DURATION_SECONDS)

        print(f"Split into {len(chunk_files)} chunks")

        transcriptions = []
        for i, chunk_path in enumerate(chunk_files):
            print(f"  Transcribing chunk {i+1}/{len(chunk_files)}...")
            with torch.no_grad():
                chunk_text = self._model.transcribe(chunk_path)
            transcriptions.append(chunk_text.strip())
            # Clean up temp chunk file
            os.unlink(chunk_path)

        # Concatenate transcriptions
        full_text = " ".join(transcriptions)

        return TranscriptionResult(
            text=full_text.strip(),
            language=language or "ru",
            duration_seconds=time.time() - start_time,
            confidence=None,
            segments=None,
        )

    def _chunk_audio(self, audio_path: str, max_duration: float) -> list:
        """Split audio file into chunks of max_duration seconds.

        Returns list of paths to temporary WAV chunk files.
        """
        # Load audio
        waveform, sample_rate = torchaudio.load(audio_path)

        # Convert to mono
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)

        # Resample to 16kHz if needed
        target_sr = 16000
        if sample_rate != target_sr:
            resampler = torchaudio.transforms.Resample(sample_rate, target_sr)
            waveform = resampler(waveform)
            sample_rate = target_sr

        chunk_files = []

        start = 0
        overlap_samples = int(0.5 * 16000)  # 0.5s overlap

        while start < waveform.shape[1]:
            end = min(start + int(max_duration * 16000), waveform.shape[1])
            chunk = waveform[:, start:end]

            if chunk.shape[1] < 16000 * 0.5:  # Skip very short chunks
                break

            # Save chunk to temp file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                chunk_path = tmp.name

            torchaudio.save(chunk_path, chunk, 16000)
            chunk_files.append(chunk_path)

            start += int(max_duration * 16000) - overlap_samples

        return chunk_files

    def transcribe_batch(
        self,
        audio_paths: list[str],
        language: Optional[str] = None,
    ) -> list:
        """Transcribe multiple audio files."""
        return [self.transcribe(path, language) for path in audio_paths]

