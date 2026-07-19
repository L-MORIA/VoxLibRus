"""Audio loudness normalization for audiobook output."""

import re
import json
from pathlib import Path

import subprocess


def loudness_normalize(
    input_path: str,
    output_path: str,
    target_lufs: float = -16.0,
    target_tp: float = -1.0,
    target_lra: float = 11.0,
    dual_mono: bool = True,
    ffmpeg_path: str = "ffmpeg",
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

    subprocess.run(cmd_normalize, capture_output=True, text=True, check=True)

    return output_path


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

    subprocess.run(cmd, capture_output=True, text=True, check=True)

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
