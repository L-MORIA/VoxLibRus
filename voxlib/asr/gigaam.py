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
            from safetensors.torch import load_file, save_file
            from huggingface_hub import hf_hub_download
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
            save_file(state_dict, safetensors_path)
            print(f"Saved safetensors to: {safetensors_path}")

        return str(safetensors_path)

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
    ):
        """Transcribe audio file to text using GigaAM's built-in transcribe method.

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

        # Use model's built-in transcribe method (handles audio loading via ffmpeg)
        with torch.no_grad():
            transcription = self._model.transcribe(audio_path)

        duration = time.time() - start_time

        return TranscriptionResult(
            text=transcription.strip(),
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