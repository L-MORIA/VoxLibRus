"""torchaudio → soundfile compatibility shim.

Patches torchaudio.load() and torchaudio.transforms.Resample to use
soundfile + numpy instead of FFmpeg/torchcodec.

This avoids the need for FFmpeg shared DLLs on Windows with torch 2.12.
"""

import numpy as np
import soundfile as sf
import torch
import torchaudio as _ta


def _patched_load(path, *args, **kwargs):
    """Replace torchaudio.load() with soundfile + numpy."""
    data, sr = sf.read(path)
    if data.ndim == 1:
        data = data[np.newaxis, :]  # (channels, samples)
    else:
        data = data.T  # (channels, samples)
    tensor = torch.from_numpy(data.astype(np.float32))
    return tensor, sr


class _PatchedResample(torch.nn.Module):
    """Simple linear resampling to replace torchaudio.transforms.Resample."""

    def __init__(self, orig_freq: int, new_freq: int):
        super().__init__()
        self.orig_freq = orig_freq
        self.new_freq = new_freq

    def forward(self, waveform: torch.Tensor) -> torch.Tensor:
        if self.orig_freq == self.new_freq:
            return waveform
        dtype = waveform.dtype
        arr = waveform.cpu().numpy()
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

    print("[torchaudio_shim] torchaudio patched: load→soundfile, Resample→numpy")
