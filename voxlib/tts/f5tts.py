"""F5-TTS_RUSSIAN backend implementation.

Supports voice cloning and stress marks (+ notation) natively.
Model: Misha24-10/F5-TTS_RUSSIAN (F5TTS_v1_Base_accent_tune variant recommended)
License: CC-BY-NC-4.0
"""

import os
import warnings
from pathlib import Path
from typing import Optional

import torch
import soundfile as sf

from voxlib.tts.base import TTSInterface, VoiceProfile, TTSGenerationConfig
from voxlib.config import F5TTSConfig


class F5TTSBackend(TTSInterface):
    """F5-TTS_RUSSIAN backend with native stress marks (+) support.

    Uses the official f5-tts Python package.
    """

    def __init__(self, config: F5TTSConfig):
        self.config = config
        self._model = None
        self._vocoder = None
        self._device = torch.device(config.device)
        self._infer_process = None
        self._preprocess_ref = None
        self._remove_silence = None

    def _load_model(self):
        """Lazy load the F5-TTS model."""
        if self._model is not None:
            return

        # Check if f5-tts is available
        import importlib.util
        if importlib.util.find_spec("f5_tts") is None:
            raise RuntimeError(
                "f5-tts not installed. Run: pip install f5-tts"
            )

        try:
            from f5_tts.model import DiT
            from f5_tts.infer.utils_infer import (
                load_model,
                load_vocoder,
                infer_process,
                preprocess_ref_audio_text,
                remove_silence_for_generated_wav,
            )
        except ImportError as e:
            raise RuntimeError(
                "f5-tts not installed. Run: pip install f5-tts"
            ) from e

        # Load model
        model_cfg = {
            "dim": 1024,
            "depth": 22,
            "heads": 16,
            "ff_mult": 2,
            "text_dim": 512,
            "conv_layers": 4,
            "pe_attn_head": None,
        }

        model = DiT(**model_cfg)
        ckpt_path = self._get_checkpoint_path()

        self._model = load_model(model, ckpt_path, device=self._device)
        self._vocoder = load_vocoder(device=self._device)
        self._infer_process = infer_process
        self._preprocess_ref = preprocess_ref_audio_text
        self._remove_silence = remove_silence_for_generated_wav

    def _get_checkpoint_path(self) -> str:
        """Get path to the model checkpoint based on variant."""
        variant = getattr(self.config, "variant", "F5TTS_v1_Base_accent_tune")

        # Map variant to HF repo file
        variant_map = {
            "F5TTS_v1_Base": "F5TTS_v1_Base/model_240000.pt",
            "F5TTS_v1_Base_accent_tune": "F5TTS_v1_Base_accent_tune/model_last.pt",
            "F5TTS_v1_Base_v2": "F5TTS_v1_Base_v2/model_last.pt",
        }

        from huggingface_hub import hf_hub_download

        repo_id = self.config.model_id  # "Misha24-10/F5-TTS_RUSSIAN"
        filename = variant_map.get(variant, variant_map["F5TTS_v1_Base_accent_tune"])

        return hf_hub_download(repo_id=repo_id, filename=filename)

    def supports_stress_marks(self) -> bool:
        """F5-TTS_RUSSIAN natively supports '+' stress marks."""
        return True

    def clone_voice(
        self,
        ref_audio: str,
        ref_text: str,
        name: Optional[str] = None,
    ) -> "VoiceProfile":
        """Create a voice profile from reference audio + text.

        For F5-TTS, the 'embedding' is just the preprocessed reference audio
        and its transcription, which get passed to the model during generation.
        """
        self._load_model()

        # Preprocess reference audio (resample to 24kHz, trim silence, etc.)
        ref_audio_path = Path(ref_audio)
        if not ref_audio_path.exists():
            raise FileNotFoundError(f"Reference audio not found: {ref_audio}")

        # Preprocess: resample to 24kHz, trim silence, normalize
        processed_audio, processed_text = self._preprocess_ref(
            str(ref_audio_path), ref_text
        )

        # Save processed reference for reuse
        voice_name = name or f"voice_{ref_audio_path.stem}"
        cache_dir = Path(os.environ.get("VOXLIB_CACHE", "~/.voxlib/voices")).expanduser()
        cache_dir.mkdir(parents=True, exist_ok=True)

        processed_audio_path = cache_dir / f"{voice_name}_ref.wav"
        sf.write(str(processed_audio_path), processed_audio, 24000)

        return VoiceProfile(
            name=voice_name,
            backend="f5tts",
            ref_audio=str(processed_audio_path),
            ref_text=processed_text,
            embedding_path="",  # F5-TTS doesn't use separate embeddings
            meta={
                "original_audio": str(ref_audio_path),
                "original_text": ref_text,
                "model_variant": getattr(self.config, "variant", "F5TTS_v1_Base_accent_tune"),
            },
        )

    def generate(
        self,
        text: str,
        voice: "VoiceProfile",
        output_path: str,
        config: Optional["TTSGenerationConfig"] = None,
    ) -> Path:
        """Generate speech from text using cloned voice."""
        self._load_model()

        if voice.backend != "f5tts":
            raise ValueError(f"Voice profile backend mismatch: expected 'f5tts', got '{voice.backend}'")

        cfg = config or TTSGenerationConfig()

        # Preprocess text - handle stress marks if enabled
        processed_text = self._process_text_for_generation(text, cfg)

        # Generate
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            audio = self._infer_process(
                ref_audio=voice.ref_audio,
                ref_text=voice.ref_text,
                gen_text=processed_text,
                model_obj=self._model,
                vocoder=self._vocoder,
                device=self._device,
                speed=cfg.speed,
                cross_fade_duration=cfg.cross_fade_duration,
            )

        # Post-process: remove silence from generated audio
        if self._remove_silence is not None:
            audio = self._remove_silence(audio)

        # Save
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # audio is (1, T) or (T,) tensor/array at 24kHz
        if isinstance(audio, torch.Tensor):
            audio = audio.detach().cpu().numpy()
        if audio.ndim > 1:
            audio = audio.squeeze()

        sf.write(str(output_path), audio, 24000)

        return output_path

    def generate_batch(
        self,
        texts: list[str],
        voice: "VoiceProfile",
        output_dir: str,
        config: Optional["TTSGenerationConfig"] = None,
    ) -> list[Path]:
        """Generate multiple texts in batch."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        results = []
        for i, text in enumerate(texts):
            output_path = output_dir / f"chunk_{i:04d}.wav"
            results.append(self.generate(text, voice, str(output_path), config))
        return results

    def _process_text_for_generation(self, text: str, config: TTSGenerationConfig) -> str:
        """Process text before generation.

        If stress marks are enabled, keep '+' marks for F5-TTS processing.
        Otherwise, strip them.
        """
        if config.apply_stress_marks:
            return text  # F5-TTS understands '+' natively
        else:
            return text.replace("+", "")