"""torchaudio → soundfile compatibility shim.

Patches torchaudio.load() and torchaudio.transforms.Resample to use
soundfile + numpy/scipy instead of FFmpeg/torchcodec.

This avoids the need for FFmpeg shared DLLs on Windows with torch 2.12.
"""

import warnings
import numpy as np
import soundfile as sf
import torch
import torchaudio as _ta


def _patched_load(path, *args, **kwargs):
    """Replace torchaudio.load() with soundfile + numpy.

    Supports frame_offset and num_frames for partial loading.
    Falls back without warning for normal usage.
    """
    frame_offset = kwargs.pop("frame_offset", 0)
    num_frames = kwargs.pop("num_frames", -1)

    data, sr = sf.read(path, start=frame_offset,
                       stop=frame_offset + num_frames if num_frames > 0 else None)
    if data.ndim == 1:
        data = data[np.newaxis, :]  # (1, samples)
    else:
        data = data.T  # (channels, samples)

    tensor = torch.from_numpy(data.astype(np.float32))

    # Warn if unsupported kwargs were passed
    if kwargs:
        warnings.warn(f"[torchaudio_shim] Ignored torchaudio.load() kwargs: {set(kwargs.keys())}")

    return tensor, sr


class _PatchedResample(torch.nn.Module):
    """Resampling with anti-aliasing filter using scipy.signal.resample_poly.

    Replaces torchaudio.transforms.Resample which requires torchcodec.
    Uses polyphase resampling with proper anti-aliasing (vs np.interp).
    """

    def __init__(self, orig_freq: int, new_freq: int):
        super().__init__()
        self.orig_freq = orig_freq
        self.new_freq = new_freq

    def forward(self, waveform: torch.Tensor) -> torch.Tensor:
        if self.orig_freq == self.new_freq:
            return waveform
        dtype = waveform.dtype
        arr = waveform.cpu().numpy()

        try:
            from scipy.signal import resample_poly
            # Polyphase resampling with built-in anti-aliasing filter
            resampled = resample_poly(arr, self.new_freq, self.orig_freq, axis=-1)
        except ImportError:
            # Fallback: no scipy — use simple linear interpolation (no filter)
            orig_len = arr.shape[-1]
            new_len = int(round(orig_len * self.new_freq / self.orig_freq))
            resampled = np.zeros((*arr.shape[:-1], new_len), dtype=np.float32)
            for i in range(arr.shape[0]):
                resampled[i] = np.interp(
                    np.linspace(0, orig_len - 1, new_len),
                    np.arange(orig_len),
                    arr[i],
                )
        return torch.from_numpy(resampled).to(dtype=dtype, device=waveform.device)


def apply_patch():
    """Apply torchaudio compatibility patch.

    Call this BEFORE importing any f5_tts modules.
    Only replaces load() and Resample — leaves the rest of torchaudio intact.
    """
    # Patch torchaudio.load — soundfile doesn't need FFmpeg
    _ta.load = _patched_load

    # Patch only Resample in torchaudio.transforms, keep everything else
    if hasattr(_ta, "transforms"):
        _ta.transforms.Resample = _PatchedResample

    print("[torchaudio_shim] torchaudio patched: load→soundfile, Resample→polyphase")
