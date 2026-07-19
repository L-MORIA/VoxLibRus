"""Audio preprocessing for reference voice audio."""

import subprocess
from pathlib import Path


def _validate_numeric_param(name: str, value: float, min_val: float = -100.0, max_val: float = 100.0) -> float:
    """Validate numeric parameter for FFmpeg filter safety."""
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric, got {type(value).__name__}")
    if value < min_val or value > max_val:
        raise ValueError(f"{name} must be between {min_val} and {max_val}, got {value}")
    return float(value)


def prepare_reference(
    input_path: str,
    output_path: str,
    target_sample_rate: int = 24000,
    target_channels: int = 1,
    normalize_peak_db: float = -3.0,
    trim_silence: bool = True,
    noise_reduce: bool = True,
    ffmpeg_path: str = "ffmpeg",
) -> str:
    """Preprocess reference audio for voice cloning.

    Args:
        input_path: Path to input audio file (any format).
        output_path: Path for output WAV file.
        target_sample_rate: Target sample rate (default: 24000 for F5-TTS/Qwen3-TTS).
        target_channels: Target number of channels (1 = mono).
        normalize_peak_db: Normalize peak to this dB level (-3.0 recommended).
        trim_silence: Remove leading/trailing silence.
        noise_reduce: Apply spectral noise reduction.
        ffmpeg_path: Path to ffmpeg executable.

    Returns:
        Path to processed reference audio.
    """
    input_path = str(Path(input_path).resolve())
    output_path = str(Path(output_path).resolve())

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Validate numeric parameter to prevent command injection
    normalize_peak_db = _validate_numeric_param("normalize_peak_db", normalize_peak_db, -60.0, 0.0)

    # Build FFmpeg filter chain
    filters = []

    # Resample
    if target_sample_rate:
        filters.append(f"aresample={target_sample_rate}")

    # Channel conversion
    if target_channels == 1:
        filters.append("pan=mono|c0=0.5*c0+0.5*c1")
    elif target_channels == 2:
        filters.append("pan=stereo|c0=c0|c1=c1")

    # Trim silence
    if trim_silence:
        filters.append("silenceremove=start_periods=1:start_threshold=-50dB:start_duration=0.5")

    # Noise reduction (basic spectral gating)
    if noise_reduce:
        # Using FFmpeg's afftdn (spectral noise reduction)
        filters.append("afftdn=nf=-25")

    # Normalize peak
    if normalize_peak_db is not None:
        # First normalize to target peak, then apply limiter
        filters.append(f"volume={normalize_peak_db}dB")
        # Soft limiter to prevent clipping
        filters.append("alimiter=limit=0.89")

    # Build FFmpeg command
    filter_str = ",".join(filters)
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-af", filter_str,
        "-c:a", "pcm_s16le",
        "-ar", str(target_sample_rate) if target_sample_rate else "",
        "-ac", "1",
        output_path,
    ]

    # Filter out empty strings
    cmd = [c for c in cmd if c]

    subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True)

    return output_path


def prepare_reference_pydub(
    input_path: str,
    output_path: str,
    target_sample_rate: int = 24000,
    normalize_peak_db: float = -3.0,
    trim_silence: bool = True,
) -> str:
    """Alternative using pydub (no FFmpeg subprocess)."""
    from pydub import AudioSegment

    audio = AudioSegment.from_file(input_path)

    # Resample
    if audio.frame_rate != target_sample_rate:
        audio = audio.set_frame_rate(target_sample_rate)

    # Mono
    if audio.channels != 1:
        audio = audio.set_channels(1)

    # Trim silence
    if trim_silence:
        # Remove leading/trailing silence
        non_silent = audio.strip_silence(silence_len=500, silence_thresh=-50)
        if non_silent:
            audio = non_silent

    # Noise reduction - not available in pydub, skip
    # Would need noisereduce library

    # Normalize peak
    if normalize_peak_db is not None:
        audio = audio.apply_gain(normalize_peak_db - audio.max_dBFS)

    # Export
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    audio.export(output_path, format="wav")

    return output_path