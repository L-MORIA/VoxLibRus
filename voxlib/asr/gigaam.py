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
import numpy as np
import soundfile as sf

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

        torch.backends.cudnn.enabled = False  # RTX 5060 Ti (sm120) compat

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
            dtype=torch.float32,
        )

        # Load weights from safetensors (safe - no pickle execution)
        state_dict = load_file(safetensors_path)
        model.load_state_dict(state_dict, strict=False)

        self._model = model.to(self._device)
        self._model.eval()

    def _get_or_create_safetensors(self, repo_id: str, revision: str) -> str:
        """Download model and convert to safetensors if needed.

        This avoids CVE-2025-32434 by never loading .bin with torch.load.
        """
        from huggingface_hub import hf_hub_download
        from safetensors.torch import save_file
        import torch

        bin_path = hf_hub_download(
            repo_id=repo_id,
            filename="pytorch_model.bin",
            revision=revision,
        )

        safetensors_path = Path(bin_path).with_suffix(".safetensors")

        if not os.path.exists(safetensors_path):
            print(f"Converting {bin_path} to safetensors...")
            # weights_only=True prevents arbitrary code execution (CVE-2025-32434)
            state_dict = torch.load(bin_path, map_location="cpu", weights_only=True)
            from safetensors.torch import save_file
            save_file(state_dict, safetensors_path)
            print(f"Saved safetensors to: {safetensors_path}")

        return str(safetensors_path)

    def _resample(self, data: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        """Resample audio using simple interpolation (avoid scipy/torchaudio)."""
        if orig_sr == target_sr:
            return data
        duration = len(data) / orig_sr
        target_len = int(duration * target_sr)
        # Linear interpolation
        indices = np.linspace(0, len(data) - 1, target_len)
        return np.interp(indices, np.arange(len(data)), data).astype(np.float32)

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
    ):
        """Transcribe audio file to text using GigaAM's built-in transcribe method."""
        self._load_model()

        import time
        start_time = time.time()

        # Check audio duration via soundfile
        snd = sf.SoundFile(audio_path)
        duration = snd.frames / snd.samplerate

        # If short enough, transcribe directly (model uses ffmpeg internally)
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

        # Long audio: chunk via soundfile + numpy
        print(f"Audio duration: {duration:.1f}s, splitting into chunks...")

        data, sr = sf.read(audio_path)
        if data.ndim > 1:
            data = data.mean(axis=1)  # mono
        data = self._resample(data, sr, 16000)

        chunk_files = []
        chunk_samples = int(self.MAX_DURATION_SECONDS * 16000)
        overlap = int(0.5 * 16000)

        start = 0
        while start < len(data):
            end = min(start + chunk_samples, len(data))
            chunk = data[start:end]

            if len(chunk) < 16000 * 0.5:
                break

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                chunk_path = tmp.name
            sf.write(chunk_path, chunk, 16000)
            chunk_files.append(chunk_path)

            start += chunk_samples - overlap

        print(f"Split into {len(chunk_files)} chunks")

        transcriptions = []
        for i, chunk_path in enumerate(chunk_files):
            print(f"  Transcribing chunk {i+1}/{len(chunk_files)}...")
            with torch.no_grad():
                chunk_text = self._model.transcribe(chunk_path)
            transcriptions.append(chunk_text.strip())
            os.unlink(chunk_path)

        full_text = " ".join(transcriptions)

        return TranscriptionResult(
            text=full_text.strip(),
            language=language or "ru",
            duration_seconds=time.time() - start_time,
            confidence=None,
            segments=None,
        )

    def transcribe_batch(
        self,
        audio_paths: list[str],
        language: Optional[str] = None,
    ) -> list:
        """Transcribe multiple audio files."""
        return [self.transcribe(path, language) for path in audio_paths]