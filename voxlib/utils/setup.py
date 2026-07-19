"""GPU setup and audio compatibility for VoxLibRus.

Must be called before any voxlib modules are imported.

Primary path: CUDA (RTX 5060 Ti, 16 GB VRAM, float32)
Fallback: CPU

Handles:
- RTX 5060 Ti (sm_120 Blackwell) — no cuDNN kernels in PyTorch 2.12
- torch.stft float16 → float32 conversion (cuFFT limitation)
- torchaudio → soundfile patching (no FFmpeg DLLs needed)
"""

import torch

_STFT_PATCHED = False
_original_stft = None


def _patched_stft(*args, **kwargs):
    """Wrapper for torch.stft that converts float16 inputs to float32.

    cuFFT on Blackwell (sm_120) requires power-of-2 sizes for half
    precision STFT. Simply cast to float32 — quality is identical,
    and 32-bit math is fully supported on all CUDA GPUs.
    """
    # The input is the first positional arg or the 'input' kwarg
    inp = kwargs.get("input", args[0] if args else None)
    if inp is not None and inp.dtype == torch.float16:
        inp = inp.to(torch.float32)
        if "input" in kwargs:
            kwargs["input"] = inp
        elif args:
            args = (inp,) + args[1:]
    return _original_stft(*args, **kwargs)


def _patch_torch_stft():
    """Monkey-patch torch.stft to auto-convert float16 → float32."""
    global _STFT_PATCHED, _original_stft
    if _STFT_PATCHED:
        return
    _original_stft = torch.stft
    torch.stft = _patched_stft
    _STFT_PATCHED = True


def pick_device(config_device: str, vram_gb: int = 16) -> str:
    """Choose best device: CUDA if available and enough VRAM, else CPU."""
    if config_device == "cpu":
        return "cpu"
    if not torch.cuda.is_available():
        return "cpu"
    # Check actual available VRAM if configured device is cuda
    if config_device == "cuda":
        actual_vram = torch.cuda.get_device_properties(0).total_memory / 1e9
        if actual_vram < vram_gb:
            print(f"[GPU] WARNING: VRAM {actual_vram:.0f}GB < {vram_gb}GB required — falling back to CPU")
            return "cpu"
    return "cuda"


def setup_gpu_compat():
    """Apply GPU and audio compatibility patches.

    1. Disable cuDNN (only on sm_120 Blackwell — no kernels in PyTorch 2.12)
    2. Patch torch.stft for float16 → float32 (only on sm_120)
    3. Patch torchaudio (soundfile backend instead of torchcodec — always on Windows)

    On CUDA-capable cards with full toolchain support (sm_70–sm_90),
    cuDNN and float16 STFT work normally — no hacks applied.
    """
    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        vram = torch.cuda.get_device_properties(0).total_memory / 1e9
        caps = torch.cuda.get_device_capability(0)
        is_blackwell = caps >= (12, 0)
        print(f"[GPU] {name} — {vram:.0f} GB VRAM (sm_{caps[0]}{caps[1]}, Blackwell={is_blackwell})")

        if is_blackwell:
            # Blackwell (sm_120): no cuDNN kernels, float16 STFT broken
            torch.backends.cudnn.enabled = False
            torch.backends.cudnn.benchmark = False
            _patch_torch_stft()
            print("[GPU] cuDNN off, float32 STFT patched (Blackwell compat)")
        else:
            # Full hardware support — keep defaults
            pass

    # Torchaudio → soundfile (Windows-only — avoids FFmpeg DLL issues)
    import sys
    if sys.platform == "win32":
        from voxlib.utils.torchaudio_shim import apply_patch
        apply_patch()
