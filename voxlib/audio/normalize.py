"""Audio loudness normalization for audiobook output."""

import re
import json
from pathlib import Path

import subprocess
import numpy as np


def _apply_noise_gate(audio: np.ndarray, threshold_db: float = -50.0) -> np.ndarray:
    """Apply noise gate to suppress audio below threshold.

    Args:
        audio: Audio samples as float32 array (-1.0 to 1.0)
        threshold_db: Threshold in dB below which audio is muted

    Returns:
        Audio with noise gate applied
    """
    if threshold_db is None:
        return audio

    # Convert dB to linear amplitude
    threshold_linear = 10 ** (threshold_db / 20.0)

    # Compute RMS in small windows to detect speech vs silence
    window_size = 1024  # ~43ms at 24kHz
    hop_size = 256

    # Pad audio to handle edges
    pad_size = window_size // 2
    padded = np.pad(audio, (pad_size, pad_size), mode="reflect")

    gated = np.zeros_like(audio)

    for i in range(0, len(audio), hop_size):
        window_end = min(i + window_size, len(audio))
        window = padded[i:i + window_size]

        # Compute RMS
        rms = np.sqrt(np.mean(window ** 2)) + 1e-10

        if rms >= threshold_linear:
            # Keep original audio
            gated[i:window_end] = audio[i:window_end]
        else:
            # Mute (or heavily attenuate)
            gated[i:window_end] = audio[i:window_end] * 0.001  # -60dB attenuation

    return gated


def loudness_normalize(
    input_path: str,
    output_path: str,
    target_lufs: float = -16.0,
    target_tp: float = -1.0,
    target_lra: float = 11.0,
    dual_mono: bool = True,
    ffmpeg_path: str = "ffmpeg",
    noise_gate_db: float = -50.0,
) -> str:
    """Normalize audio loudness to EBU R128 standard.

    Args:
        input_path: Path to input audio file.
        output_path: Path for normalized output.
        target_lufs: Target integrated loudness (default: -16 LUFS for audiobooks).
        target_tp: Target true peak (default: -1 dBTP).
        target_lra: Target loudness range (default: 11 LU).
        dual_mono: Treat stereo as dual mono for normalization.
        ffmpeg_path: Path to ffmpeg executable.
        noise_gate_db: Noise gate threshold in dB (default: -50 dB).

    Returns:
        Path to normalized audio file.
    """
    input_path = str(Path(input_path).resolve())
    output_path = str(Path(output_path).resolve())

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Use FFmpeg's loudnorm filter (EBU R128)
    # Two-pass normalization for accuracy
    # Pass 1: measure
    cmd_measure = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-af", f"loudnorm=I={target_lufs}:TP={target_tp}:LRA={target_lra}:dual_mono=1:print_format=json",
        "-f", "null", "-",
    ]

    result = subprocess.run(cmd_measure, capture_output=True, text=True, check=True)

    # Parse JSON output from stderr
    json_match = re.search(r"\{.*\}", result.stderr, re.DOTALL)
    if not json_match:
        raise RuntimeError("Could not parse loudnorm JSON output")

    stats = json.loads(json_match.group())

    # Pass 2: normalize using measured values
    cmd_normalize = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-af", (
            f"loudnorm=I={target_lufs}:TP={target_tp}:LRA={target_lra}:"
            f"dual_mono=1:"
            f"measured_I={stats['input_i']}:"
            f"measured_TP={stats['input_tp']}:"
            f"measured_LRA={stats['input_lra']}:"
            f"measured_thresh={stats['input_thresh']}:"
            f"offset={stats['target_offset']}:"
            f"linear=true:print_format=summary"
        ),
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        output_path,
    ]

    result = subprocess.run(cmd_normalize, capture_output=True, text=True, check=True)

    # Apply noise gate post-normalization if requested
    if noise_gate_db is not None and noise_gate_db > -100:
        _apply_noise_gate_post(output_path, noise_gate_db)

    return output_path


def _apply_noise_gate_post(file_path: str, threshold_db: float = -50.0) -> None:
    """Apply noise gate to file in-place using pydub + numpy."""
    try:
        from pydub import AudioSegment
        import numpy as np

        audio = AudioSegment.from_file(file_path)
        samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
        samples = samples / (2**15)  # Normalize to -1.0..1.0

        # Apply noise gate
        gated = _apply_noise_gate(samples, threshold_db)

        # Convert back
        gated = np.clip(gated * (2**15), -2**15, 2**15 - 1).astype(np.int16)
        gated_audio = AudioSegment(
            gated.tobytes(),
            frame_rate=audio.frame_rate,
            sample_width=audio.sample_width,
            channels=audio.channels
        )
        gated_audio.export(file_path, format="mp3", bitrate="192k")
    except ImportError:
        # pydub/numpy not available, skip noise gate
        pass


def loudness_normalize_single_pass(
    input_path: str,
    output_path: str,
    target_lufs: float = -16.0,
    target_tp: float = -1.0,
    target_lra: float = 11.0,
) -> str:
    """Single-pass loudness normalization (faster, less accurate).

    Use for quick processing when two-pass accuracy is not required.
    """
    input_path = str(Path(input_path).resolve())
    output_path = str(Path(output_path).resolve())

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-af", f"loudnorm=I={target_lufs}:TP={target_tp}:LRA={target_lra}:dual_mono=1:linear=true",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)

    return output_path


def get_loudness_stats(input_path: str) -> dict:
    """Get loudness statistics without normalization.

    Returns dict with: input_i, input_tp, input_lra, input_thresh.
    """
    input_path = str(Path(input_path).resolve())

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-af", "loudnorm=I=-16:TP=-1:LRA=11:print_format=json",
        "-f", "null", "-",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)

    json_match = re.search(r"\{.*\}", result.stderr, re.DOTALL)
    if not json_match:
        raise RuntimeError("Could not parse loudnorm JSON output")

    return json.loads(json_match.group())