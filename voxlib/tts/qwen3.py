"""Qwen3-TTS-Base backend for voice cloning and generation.

Model: Qwen/Qwen3-TTS-12Hz-1.7B-Base
License: Apache-2.0
Voice clone: from 3 seconds of reference audio
⚠️ Does NOT support stress marks (+ notation) — GitHub issue #53 open since 2026-01
"""

import warnings
from pathlib import Path
from typing import Optional

import torch
import soundfile as sf

from voxlib.tts.base import TTSInterface, VoiceProfile, TTSGenerationConfig
from voxlib.config import Qwen3Config


class Qwen3TTSBackend(TTSInterface):
    """Qwen3-TTS-Base backend with voice cloning capabilities.

    Uses the official qwen-tts Python package.
    """

    def __init__(self, config: Qwen3Config):
        self.config = config
        self._model = None
        self._device = torch.device(config.device)

    def _load_model(self):
        """Lazy load Qwen3-TTS-Base model."""
        if self._model is not None:
            return

        try:
            import importlib.util
            if importlib.util.find_spec("qwen_tts") is None:
                raise RuntimeError(
                    "qwen-tts not installed. "
                    "Run: pip install git+https://github.com/QwenLM/Qwen3-TTS.git"
                )
            from qwen_tts.inference.qwen3_tts_model import Qwen3TTSModel
        except ImportError as e:
            raise RuntimeError(
                "qwen-tts not installed. "
                "Run: pip install git+https://github.com/QwenLM/Qwen3-TTS.git"
            ) from e

        # Suppress warnings
        warnings.filterwarnings("ignore", category=UserWarning, module="transformers")
        warnings.filterwarnings("ignore", message="torch_dtype is deprecated")

        self._model = Qwen3TTSModel.from_pretrained(
            self.config.model_id,
            device=self.config.device,
        )

    def supports_stress_marks(self) -> bool:
        """Qwen3-TTS does NOT support stress marks (+ notation)."""
        return False

    def clone_voice(
        self,
        ref_audio: str,
        ref_text: str,
        name: Optional[str] = None,
    ) -> "VoiceProfile":
        """Create a voice profile from reference audio + text.

        Uses Qwen3-TTS-Base's create_voice_clone_prompt() which computes
        speaker embedding + speech codes for reuse across chunks.
        """
        self._load_model()

        ref_path = Path(ref_audio)
        if not ref_path.exists():
            raise FileNotFoundError(f"Reference audio not found: {ref_audio}")

        # Create reusable voice clone prompt (ICL mode — requires ref_text)
        prompt_items = self._model.create_voice_clone_prompt(
            ref_audio=ref_audio,
            ref_text=ref_text,
            x_vector_only_mode=False,  # ICL mode for best quality
        )

        voice_name = name or f"voice_{ref_path.stem}"

        return VoiceProfile(
            name=voice_name,
            backend="qwen3",
            ref_audio=ref_audio,
            ref_text=ref_text,
            embedding_path="",  # prompt items stored in meta
            meta={
                "model_id": self.config.model_id,
                "prompt_items": prompt_items,  # stored for reuse
                "x_vector_only_mode": False,
            },
        )

    def generate(
        self,
        text: str,
        voice: "VoiceProfile",
        output_path: str,
        config: Optional["TTSGenerationConfig"] = None,
    ) -> Path:
        """Generate speech from text using cloned voice (Qwen3-TTS-Base).

        Uses pre-computed voice_clone_prompt for consistency across chunks.
        """
        self._load_model()

        if voice.backend != "qwen3":
            raise ValueError(
                f"Voice profile backend mismatch: expected 'qwen3', got '{voice.backend}'"
            )

        cfg = config or TTSGenerationConfig()

        # Retrieve pre-computed prompt from voice profile
        prompt_items = voice.meta.get("prompt_items")
        if prompt_items is None:
            raise ValueError(
                "Voice profile missing prompt_items. Re-run clone_voice()."
            )

        # Process text — strip stress marks since Qwen3 doesn't support them
        processed_text = self._process_text_for_generation(text, cfg)

        # Language: Qwen3 uses language codes like "ru", "en", etc.
        # Qwen3-TTS uses language codes: "ru", "en", etc.
        # Note: The model expects lowercase language codes like "zh", "en", "ru"
        language = self.config.language

        # Qwen3 requires a prompt format - build from the stored prompt items
        with torch.no_grad():
            wavs, sample_rate = self._model.generate_voice_clone(
                text=[processed_text],
                language=[language],
                voice_clone_prompt=prompt_items,
                non_streaming_mode=not self.config.streaming,
            )

        # Save output
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # wavs is list of np.ndarrays
        audio = wavs[0]
        if isinstance(audio, torch.Tensor):
            audio = audio.detach().cpu().numpy()
        if audio.ndim > 1:
            audio = audio.squeeze()

        sf.write(str(output_path), audio, int(sample_rate))

        return output_path

    def generate_batch(
        self,
        texts: list[str],
        voice: "VoiceProfile",
        output_dir: str,
        config: Optional["TTSGenerationConfig"] = None,
    ) -> list[Path]:
        """Generate multiple texts in batch using pre-computed voice prompt."""
        self._load_model()

        if voice.backend != "qwen3":
            raise ValueError(
                f"Voice profile backend mismatch: expected 'qwen3', got '{voice.backend}'"
            )

        cfg = config or TTSGenerationConfig()

        prompt_items = voice.meta.get("prompt_items")
        if prompt_items is None:
            raise ValueError("Voice profile missing prompt_items.")

        # Process texts — strip stress marks
        processed_texts = []
        for text in texts:
            processed_texts.append(self._process_text_for_generation(text, cfg))

        language = self.config.language

        # Generate all texts in batch using the same voice prompt
        with torch.no_grad():
            wavs, sample_rate = self._model.generate_voice_clone(
                text=processed_texts,
                language=[language] * len(processed_texts),
                voice_clone_prompt=prompt_items,
                non_streaming_mode=not self.config.streaming,
            )

        # Save outputs
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        results = []

        for i, audio in enumerate(wavs):
            output_path = output_dir / f"chunk_{i:04d}.wav"
            if isinstance(audio, torch.Tensor):
                audio = audio.detach().cpu().numpy()
            if audio.ndim > 1:
                audio = audio.squeeze()
            sf.write(str(output_path), audio, int(sample_rate))
            results.append(output_path)

        return results

    def _process_text_for_generation(self, text: str, config: TTSGenerationConfig) -> str:
        """Process text before generation.

        Qwen3-TTS does NOT support stress marks, so strip them.
        """
        if config.apply_stress_marks:
            # Qwen3 doesn't understand '+' stress marks
            # Strip them to avoid garbled pronunciation
            return text.replace("+", "")
        return text.replace("+", "")