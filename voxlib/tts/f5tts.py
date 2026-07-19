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


def _load_bigvgan_vocoder(device: str) -> "torch.nn.Module":
    """Load BigVGAN v2 vocoder directly, bypassing f5_tts's broken import chain."""
    import sys as _sys
    import f5_tts as _f5
    pkg_dir = Path(_f5.__path__[0])
    bigvgan_dir = pkg_dir / "third_party" / "BigVGAN"
    if bigvgan_dir.exists() and str(bigvgan_dir) not in _sys.path:
        _sys.path.insert(0, str(bigvgan_dir))
    # Now import bigvgan as a top-level module (not via third_party subpackage)
    import bigvgan as _bigvgan

    # Patch: BigVGAN's _from_pretrained requires proxies/resume_download (old API),
    # but newer huggingface_hub doesn't provide them. Make them optional.
    _orig_from_pretrained = _bigvgan.BigVGAN._from_pretrained

    @classmethod  # type: ignore[misc]
    def _patched_from_pretrained(
        cls,
        *,
        model_id: str,
        revision: str = "main",
        cache_dir: Optional[str] = None,
        force_download: bool = False,
        proxies: Optional[dict] = None,
        resume_download: bool = False,
        local_files_only: bool = False,
        token: Optional[str] = None,
        **model_kwargs,
    ):
        return _orig_from_pretrained(
            model_id=model_id,
            revision=revision,
            cache_dir=cache_dir or "",
            force_download=force_download,
            proxies=proxies,
            resume_download=resume_download,
            local_files_only=local_files_only,
            token=token,
            **model_kwargs,
        )

    _bigvgan.BigVGAN._from_pretrained = _patched_from_pretrained

    vocoder = _bigvgan.BigVGAN.from_pretrained(
        str(bigvgan_dir / "pretrained"),
        use_cuda_kernel=False,
    )
    vocoder.remove_weight_norm()
    vocoder = vocoder.eval().to(device)

    # Wrap: BigVGAN uses __call__(mel), not .decode(mel) — add .decode for compat
    _orig_forward = vocoder.forward

    def _decode_wrapper(mel):
        return _orig_forward(mel)

    vocoder.decode = _decode_wrapper
    return vocoder


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

        # Force float32 for CUDA (cuFFT fails with float16 on non-power-of-2 sizes)
        from f5_tts.infer import utils_infer as _utils_infer
        _orig_load_ckpt = _utils_infer.load_checkpoint
        def _patched_ckpt(model, ckpt_path, device, dtype=None, use_ema=True):
            return _orig_load_ckpt(model, ckpt_path, device, dtype=torch.float32, use_ema=use_ema)
        _utils_infer.load_checkpoint = _patched_ckpt

        try:
            from f5_tts.model import DiT
            from f5_tts.infer.utils_infer import (
                load_model,
                load_vocoder,
                infer_process as _orig_infer_process,
                preprocess_ref_audio_text,
                remove_silence_for_generated_wav,
            )
        except ImportError as e:
            raise RuntimeError(
                "f5-tts not installed. Run: pip install f5-tts"
            ) from e

        # Load model
        torch.backends.cudnn.enabled = False  # RTX 5060 Ti (sm120) compat
        model_cfg = {
            "dim": 1024,
            "depth": 22,
            "heads": 16,
            "ff_mult": 2,
            "text_dim": 512,
            "conv_layers": 4,
        }

        ckpt_path = self._get_checkpoint_path()

        self._model = load_model(DiT, model_cfg, ckpt_path, device=str(self._device))
        # Vocoder: Vocos (default, stable) or BigVGAN (experimental, configurable)
        vocoder_name = getattr(self.config, "vocoder", "vocos")
        if vocoder_name == "bigvgan":
            self._vocoder = _load_bigvgan_vocoder(device=str(self._device))
            # BigVGAN requires mel_spec_type="bigvgan" (100 bands vs Vocos' 80)
            def _bigvgan_infer(*args, **kwargs):
                kwargs["mel_spec_type"] = "bigvgan"
                return _orig_infer_process(*args, **kwargs)
            self._infer_process = _bigvgan_infer
        else:
            self._vocoder = load_vocoder(device=str(self._device))
            self._infer_process = _orig_infer_process
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
        repo_id = "Misha24-10/F5-TTS_RUSSIAN"
        filename = variant_map.get(variant, "F5TTS_v1_Base_accent_tune/model_last.pt")

        from huggingface_hub import hf_hub_download
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
                device=str(self._device),
                speed=cfg.speed,
                cross_fade_duration=cfg.cross_fade_duration,
                fix_duration=cfg.fix_duration,  # NEW: P1-3 fixed duration
            )

        # Save
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # audio is a list/array at 24kHz
        if isinstance(audio, (tuple, list)) and len(audio) > 0:
            audio = audio[0]
        if isinstance(audio, torch.Tensor):
            audio = audio.detach().cpu().numpy()
        if hasattr(audio, 'ndim') and audio.ndim > 1:
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