"""Audio Quality Assurance Gate for VoxLibRus.

Checks generated audio chunks for quality issues before assembly.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)


@dataclass
class QAConfig:
    """Configuration for Audio Quality Assurance Gate."""
    # Loudness / RMS
    rms_min_db: float = -45.0          # was -30 (too strict, rejected quiet speech)
    rms_max_db: float = -3.0
    # Peak / Clipping
    peak_max: float = 0.99
    # DC Offset
    dc_offset_max: float = 0.05
    # Duration
    duration_min_sec: float = 0.5
    duration_max_sec: float = 120.0    # was 20 (rejected real audiobook chunks)
    # Silence / Dropout
    silence_threshold_db: float = -60.0
    max_silence_ratio: float = 0.4     # was 0.3 (too strict for pauses in prose)
    # Retry
    max_retries: int = 3

    @classmethod
    def from_config(cls, config) -> "QAConfig":
        """Create QAConfig from a dict OR a Pydantic-like config object.

        Accepts either:
        - a plain dict (legacy behaviour, used when `qa_gate` is missing)
        - a pydantic model with the same field names (e.g. voxlib.config.QAGateConfig)
        """
        if config is None:
            return cls()
        # Pydantic v2 models expose .model_dump(); pydantic v1 uses .dict()
        if hasattr(config, "model_dump"):
            config_dict = config.model_dump()
        elif hasattr(config, "dict") and callable(getattr(config, "dict", None)):
            config_dict = config.dict()
        elif isinstance(config, dict):
            config_dict = config
        else:
            # Last resort: read public attributes
            config_dict = {
                k: getattr(config, k)
                for k in (
                    "enabled", "rms_min_db", "rms_max_db", "peak_max",
                    "dc_offset_max", "duration_min_sec", "duration_max_sec",
                    "silence_threshold_db", "max_silence_ratio", "max_retries",
                )
                if hasattr(config, k)
            }
        # `enabled` is consumed by the pipeline, not QAConfig itself.
        config_dict = {k: v for k, v in config_dict.items() if k != "enabled"}
        return cls(
            rms_min_db=config_dict.get("rms_min_db", cls().rms_min_db),
            rms_max_db=config_dict.get("rms_max_db", cls().rms_max_db),
            peak_max=config_dict.get("peak_max", cls().peak_max),
            dc_offset_max=config_dict.get("dc_offset_max", cls().dc_offset_max),
            duration_min_sec=config_dict.get("duration_min_sec", cls().duration_min_sec),
            duration_max_sec=config_dict.get("duration_max_sec", cls().duration_max_sec),
            silence_threshold_db=config_dict.get("silence_threshold_db", cls().silence_threshold_db),
            max_silence_ratio=config_dict.get("max_silence_ratio", cls().max_silence_ratio),
            max_retries=config_dict.get("max_retries", cls().max_retries),
        )


@dataclass
class QAResult:
    """Result of audio quality check."""
    passed: bool
    metrics: dict
    errors: list[str]

    def __bool__(self) -> bool:
        return self.passed


def check_audio_quality(audio_path: str, config: QAConfig, sample_rate: int = 24000) -> QAResult:
    """Check audio file for quality issues.

    Args:
        audio_path: Path to audio file (WAV/MP3).
        config: QAConfig with thresholds.
        sample_rate: Expected sample rate (default 24000 for VoxLibRus).

    Returns:
        QAResult with pass/fail, metrics, and error messages.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        return QAResult(passed=False, metrics={}, errors=[f"File not found: {audio_path}"])

    try:
        audio, sr = sf.read(str(audio_path))
    except Exception as e:
        return QAResult(passed=False, metrics={}, errors=[f"Failed to read audio: {e}"])

    # Convert to mono if stereo
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    # Ensure float32
    if audio.dtype != np.float32:
        audio = audio.astype(np.float32)

    metrics = {}
    errors = []

    # 1. Peak / Clipping
    peak = float(np.max(np.abs(audio)))
    metrics["peak"] = peak
    if peak > config.peak_max:
        errors.append(f"Clipping detected: peak={peak:.3f} > {config.peak_max}")

    # 2. RMS / Loudness
    rms = float(np.sqrt(np.mean(audio**2)) + 1e-10)
    rms_db = 20 * np.log10(rms + 1e-10)
    metrics["rms_db"] = rms_db
    if rms_db < config.rms_min_db:
        errors.append(f"Too quiet: RMS={rms_db:.1f}dB < {config.rms_min_db}dB")
    if rms_db > config.rms_max_db:
        errors.append(f"Too loud: RMS={rms_db:.1f}dB > {config.rms_max_db}dB")

    # 3. DC Offset
    dc = float(np.mean(audio))
    metrics["dc_offset"] = dc
    if abs(dc) > config.dc_offset_max:
        errors.append(f"DC offset: {dc:.4f} > {config.dc_offset_max}")

    # 4. Duration
    duration = len(audio) / sample_rate
    metrics["duration_sec"] = duration
    if duration < config.duration_min_sec:
        errors.append(f"Too short: {duration:.2f}s < {config.duration_min_sec}s")
    if duration > config.duration_max_sec:
        errors.append(f"Too long: {duration:.2f}s > {config.duration_max_sec}s")

    # 5. Silence / Dropout
    silence_thresh = 10 ** (config.silence_threshold_db / 20.0)
    silence_ratio = float(np.mean(np.abs(audio) < silence_thresh))
    metrics["silence_ratio"] = silence_ratio
    if silence_ratio > config.max_silence_ratio:
        errors.append(f"Too much silence: {silence_ratio:.1%} > {config.max_silence_ratio:.0%}")

    passed = len(errors) == 0
    return QAResult(passed=passed, metrics=metrics, errors=errors)


def check_audio_quality_with_retry(
    audio_path: str,
    config: QAConfig,
    sample_rate: int = 24000,
    regenerate_fn=None,
    max_retries: Optional[int] = None,
) -> QAResult:
    """Check audio quality with optional retry via regeneration function.

    Args:
        audio_path: Path to audio file.
        config: QAConfig.
        sample_rate: Expected sample rate.
        regenerate_fn: Optional callable(path) -> None to regenerate audio in-place.
        max_retries: Override config.max_retries.

    Returns:
        Final QAResult (may have passed=False if all retries exhausted).
    """
    if max_retries is None:
        max_retries = config.max_retries

    last_result = None
    for attempt in range(max_retries + 1):
        result = check_audio_quality(audio_path, config)
        if result.passed:
            if attempt > 0:
                logger.info(f"QA passed on retry {attempt}/{max_retries}: {audio_path}")
            return result

        last_result = result
        logger.warning(f"QA failed (attempt {attempt + 1}/{max_retries + 1}): {audio_path} - {result.errors}")

        if attempt < max_retries and regenerate_fn:
            logger.info(f"Regenerating {audio_path} (retry {attempt + 1})...")
            try:
                regenerate_fn()
            except Exception as e:
                logger.error(f"Regeneration failed: {e}")
                break

    logger.error(f"QA failed after {max_retries + 1} attempts: {audio_path} - {last_result.errors}")
    return last_result or QAResult(passed=False, metrics={}, errors=["No result"])