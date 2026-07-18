"""Voice cloning and management for VoxLibRus."""

from dataclasses import dataclass
from typing import Optional

from voxlib.config import Config
from voxlib.tts.base import TTSInterface, VoiceProfile, TTSGenerationConfig
from voxlib.tts.f5tts import F5TTSBackend
from voxlib.asr.base import ASRInterface


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

        self.clone_config = VoiceCloneConfig()
        self._tts_backend: Optional[TTSInterface] = None
        self._asr_backend: Optional[ASRInterface] = None

    def _get_tts_backend(self) -> TTSInterface:
        """Lazy load TTS backend."""
        if self._tts_backend is None:
            if self.clone_config.tts_backend == "f5tts":
                self._tts_backend = F5TTSBackend(self.config.tts.f5tts)
            else:
                raise ValueError(f"Unknown TTS backend: {self.clone_config.tts_backend}")
        return self._tts_backend

    def _get_asr_backend(self) -> ASRInterface:
        """Lazy load ASR backend."""
        if self._asr_backend is None:
            if self.clone_config.asr_backend == "gigaam":
                from voxlib.asr.gigaam import GigaAMBackend
                self._asr_backend = GigaAMBackend(self.config.asr.gigaam)
            elif self.clone_config.asr_backend == "whisper":
                from voxlib.asr.whisper import WhisperBackend
                self._asr_backend = WhisperBackend(self.config.asr.whisper)
            else:
                raise ValueError(f"Unknown ASR backend: {self.clone_config.asr_backend}")
        return self._asr_backend

    def clone_voice(
        self,
        ref_audio_path: str,
        ref_text: Optional[str] = None,
        name: Optional[str] = None,
    ) -> VoiceProfile:
        """Create a voice profile from reference audio.

        Args:
            ref_audio_path: Path to reference audio file (author reading 5-30 sec).
            ref_text: Optional transcription of reference audio. If not provided,
                     will be transcribed automatically using ASR.
            name: Name for the voice profile (default: derived from audio filename).

        Returns:
            VoiceProfile with cloned voice identity.
        """
        import os
        from pathlib import Path
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

        # Prepare reference audio (resample, denoise, trim)

        from voxlib.audio.preprocess import prepare_reference
        processed_audio_path = prepare_reference(
            input_path=ref_audio_path,
            output_path=f"./.voxlib/tmp/ref_{Path(ref_audio_path).stem}_processed.wav",
            target_sample_rate=24000,
            trim_silence=True,
            noise_reduce=True,
            normalize_peak_db=-3.0,
        )

        # Transcribe if ref_text not provided
        if not ref_text:
            print("Transcribing reference audio...")
            asr_backend = self._get_asr_backend()
            transcription = asr_backend.transcribe(processed_audio_path)
            ref_text = transcription.text
            print(f"Transcribed: {ref_text[:100]}...")
        else:
            # Use provided text but validate it's reasonable
            if len(ref_text.strip()) < 10:
                import warnings
                warnings.warn(
                    "Provided reference text is very short. "
                    "Consider providing full transcription for best results."
                )

        # Create voice profile
        # Get TTS backend
        self._get_tts_backend()

        # Create voice profile (for F5-TTS, this stores the processed reference)
        voice_profile = VoiceProfile(
            name=name or f"voice_{Path(ref_audio_path).stem}",
            backend="f5tts",
            ref_audio=processed_audio_path,
            ref_text=ref_text.strip(),
            embedding_path="",  # F5-TTS uses reference audio directly
            meta={
                "original_audio": ref_audio_path,
                "original_text": ref_text,
                "model_variant": "F5TTS_v1_Base_accent_tune",
            },
        )

        return voice_profile

    def generate(
        self,
        text: str,
        voice: VoiceProfile,
        output_path: str,
        config: Optional["TTSGenerationConfig"] = None,
    ):
        """Generate speech from text using a cloned voice.

        Args:
            text: Text to synthesize. Can contain '+' stress marks for F5-TTS.
            voice: Voice profile from clone_voice().
            output_path: Output audio file path.
            config: Optional generation config.

        Returns:
            Path to generated audio file.
        """
        tts_backend = self._get_tts_backend()
        return tts_backend.generate(text, voice, output_path, config)

    def generate_batch(
        self,
        texts: list[str],
        voice: VoiceProfile,
        output_dir: str,
        config: Optional["TTSGenerationConfig"] = None,
    ) -> list[str]:
        """Generate multiple texts in batch.

        Args:
            texts: List of texts to synthesize.
            voice: Voice profile from clone_voice().
            output_dir: Directory for output files.
            config: Optional generation config.

        Returns:
            List of output file paths.
        """
        from pathlib import Path
        tts_backend = self._get_tts_backend()
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        results = []
        for i, text in enumerate(texts):
            output_path = str(output_dir / f"chunk_{i:04d}.wav")
            result = tts_backend.generate(text, voice, output_path, config)
            results.append(result)
        return results