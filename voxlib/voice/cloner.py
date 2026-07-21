"""Voice cloning and management for VoxLibRus."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from voxlib.config import Config
from voxlib.tts.base import TTSInterface, VoiceProfile, TTSGenerationConfig
from voxlib.tts.f5tts import F5TTSBackend
from voxlib.asr.base import ASRInterface
from voxlib.voice.manager import VoiceProfileManager


@dataclass
class VoiceCloneConfig:
    """Configuration for voice cloning."""
    asr_backend: str = "gigaam"
    tts_backend: str = "f5tts"
    target_sample_rate: int = 24000
    min_ref_duration: float = 3.0  # seconds
    max_ref_duration: float = 30.0  # seconds


class VoiceCloner:
    """Handles voice cloning pipeline: ASR transcription + TTS voice profile creation."""

    def __init__(self, config: Optional[Config] = None, config_path: Optional[str] = None):
        if config is not None:
            self.config = config
        elif config_path:
            from voxlib.config import Config
            self.config = Config.from_yaml(config_path)
        else:
            from voxlib.config import Config
            self.config = Config.from_yaml()

        # Read backends from actual config, not just defaults
        self.clone_config = VoiceCloneConfig()
        self.clone_config.tts_backend = getattr(self.config.tts, "primary", "f5tts")
        self.clone_config.asr_backend = getattr(self.config.asr, "primary", "gigaam")
        self._tts_backend: Optional[TTSInterface] = None
        self._asr_backend: Optional[ASRInterface] = None
        self.voice_manager = VoiceProfileManager(
            cache_dir=Path(self.config.project.temp_dir) / "voice_profiles",
        )

    # ------------------------------------------------------------------ #
    #  Backend resolution
    # ------------------------------------------------------------------ #

    def _get_tts_backend(self) -> TTSInterface:
        """Lazy load TTS backend."""
        if self._tts_backend is None:
            backend = self.clone_config.tts_backend
            if backend == "f5tts":
                self._tts_backend = F5TTSBackend(self.config.tts.f5tts)
            elif backend == "qwen3":
                from voxlib.tts.qwen3 import Qwen3TTSBackend
                self._tts_backend = Qwen3TTSBackend(self.config.tts.qwen3)
            else:
                raise ValueError(f"Unknown TTS backend: {backend}")
        return self._tts_backend

    def _get_asr_backend(self) -> ASRInterface:
        """Lazy load ASR backend."""
        if self._asr_backend is None:
            backend = self.clone_config.asr_backend
            if backend == "gigaam":
                from voxlib.asr.gigaam import GigaAMBackend
                self._asr_backend = GigaAMBackend(self.config.asr.gigaam)
            elif backend == "whisper":
                from voxlib.asr.whisper import WhisperBackend
                self._asr_backend = WhisperBackend(self.config.asr.whisper)
            else:
                raise ValueError(f"Unknown ASR backend: {backend}")
        return self._asr_backend

    # ------------------------------------------------------------------ #
    #  Voice clone
    # ------------------------------------------------------------------ #

    def clone_voice(
        self,
        ref_audio_path: str,
        ref_text: Optional[str] = None,
        name: Optional[str] = None,
    ) -> VoiceProfile:
        """Create a voice profile from reference audio.

        Args:
            ref_audio_path: Path to reference audio file (author reading 5-30 sec).
            ref_text: Optional transcription. If not provided, ASR runs automatically.
            name: Name for the voice profile (default: derived from audio filename).

        Returns:
            VoiceProfile with cloned voice identity.
        """
        import os
        import soundfile as sf

        ref_audio_path = str(Path(ref_audio_path).resolve())
        if not os.path.exists(ref_audio_path):
            raise FileNotFoundError(f"Reference audio not found: {ref_audio_path}")

        # Validate reference audio duration
        info = sf.info(ref_audio_path)
        duration = info.frames / info.samplerate
        if duration < 3.0:
            import warnings
            warnings.warn(
                f"Reference audio is very short ({duration:.1f}s). "
                "Minimum 3 seconds recommended for good cloning."
            )
        if duration > 30.0:
            import warnings
            warnings.warn(
                f"Reference audio is long ({duration:.1f}s). "
                "Consider using shorter segment (5-30s) for better results."
            )

        # --- Cache check BEFORE expensive preprocess/ASR (P1-6 fix) --- #
        # Only when ref_text is provided — without it we don't have a key.
        ref_text_stripped = ref_text.strip() if ref_text else ""
        cached_profile = None
        if ref_text_stripped:
            cached_profile = self.voice_manager.get_cached_profile(ref_audio_path, ref_text_stripped)
            if cached_profile:
                print(f"Using cached voice profile: {cached_profile.name}")
                return cached_profile

        # --- Preprocess reference audio (resample, denoise, trim) --- #
        # P0-12: path now uses config.project.temp_dir, not cwd-relative "./.voxlib/tmp/"
        voice_refs_dir = Path(self.config.project.temp_dir) / "voice_refs"
        voice_refs_dir.mkdir(parents=True, exist_ok=True)

        from voxlib.audio.preprocess import prepare_reference
        processed_audio_path = prepare_reference(
            input_path=ref_audio_path,
            output_path=str(voice_refs_dir / f"ref_{Path(ref_audio_path).stem}_processed.wav"),
            target_sample_rate=24000,
            trim_silence=True,
            noise_reduce=True,
            normalize_peak_db=-3.0,
        )

        # --- Transcribe if ref_text not provided --- #
        if not ref_text:
            print("Transcribing reference audio...")
            asr_backend = self._get_asr_backend()
            transcription = asr_backend.transcribe(processed_audio_path)
            ref_text = transcription.text
            print(f"Transcribed: {ref_text[:100]}...")
        else:
            if len(ref_text.strip()) < 10:
                import warnings
                warnings.warn(
                    "Provided reference text is very short. "
                    "Consider providing full transcription for best results."
                )

        # --- Cache the result for next time --- #
        # (second check in case another process cached while we were working)
        ref_text_stripped = ref_text.strip()
        cached_profile = self.voice_manager.get_cached_profile(processed_audio_path, ref_text_stripped)
        if cached_profile:
            return cached_profile

        # Ensure TTS backend is loaded (needed for model_variant meta below).
        self._get_tts_backend()
        backend_name = self.clone_config.tts_backend

        voice_profile = VoiceProfile(
            name=name or f"voice_{Path(ref_audio_path).stem}",
            backend=backend_name,  # was hardcoded "f5tts" (M6)
            ref_audio=processed_audio_path,
            ref_text=ref_text_stripped,
            embedding_path="",
            meta={
                "original_audio": ref_audio_path,
                "original_text": ref_text,
                "model_variant": getattr(self.config.tts.f5tts, "variant", "F5TTS_v1_Base_accent_tune"),
            },
        )

        self.voice_manager.save_profile(voice_profile, processed_audio_path, ref_text_stripped)
        return voice_profile

    # ------------------------------------------------------------------ #
    #  Generate
    # ------------------------------------------------------------------ #

    @staticmethod
    def _calc_fix_duration(text: str, chars_per_sec: float = 12.0, margin: float = 1.0) -> float:
        """Estimate speech duration from text length.

        NOTE: This is intentionally NOT used as a default for F5-TTS anymore
        (regression introduced in P1-3 and reverted in C2). F5-TTS's
        `infer_process` applies `fix_duration` to **each internal batch**
        (it re-splits long text via its own chunker), so a value computed for
        the whole chunk inflated total audio 5–10×. We let F5 auto-compute
        duration from `ref_audio_len / ref_text_len * gen_text_len` instead.

        Kept here as a public helper for callers that explicitly want a hint
        (e.g. Qwen3 backend, which has no internal batching).
        """
        clean = text.replace("+", "").strip()
        dur = len(clean) / chars_per_sec + margin
        return max(dur, 2.0)

    def generate(
        self,
        text: str,
        voice: VoiceProfile,
        output_path: str,
        config: Optional["TTSGenerationConfig"] = None,
    ):
        """Generate speech from text using a cloned voice.

        By default no `fix_duration` is set (C2 fix): F5-TTS computes duration
        from the reference audio + text lengths, which is the correct
        behaviour and avoids the ×batches blow-up that produced 400s chunks.
        Pass an explicit `config` with `fix_duration` only when you know the
        backend handles it correctly (single-batch input or Qwen3).
        """
        tts_backend = self._get_tts_backend()
        if config is None:
            config = TTSGenerationConfig()
        return tts_backend.generate(text, voice, output_path, config)

    def generate_batch(
        self,
        texts: list[str],
        voice: VoiceProfile,
        output_dir: str,
        config: Optional["TTSGenerationConfig"] = None,
    ) -> list[str]:
        """Generate multiple texts in batch."""
        tts_backend = self._get_tts_backend()
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        results = []
        for i, text in enumerate(texts):
            output_path = str(output_dir / f"chunk_{i:04d}.wav")
            # Pass through caller config as-is; do NOT inject a per-text
            # fix_duration here (see generate() docstring — C2 regression).
            chunk_cfg = config or TTSGenerationConfig()
            result = tts_backend.generate(text, voice, output_path, chunk_cfg)
            results.append(result)
        return results
