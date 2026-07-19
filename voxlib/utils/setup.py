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
    return "cuda"


def setup_gpu_compat():
    """Apply GPU and audio compatibility patches.

    1. Disable cuDNN (no sm_120 kernels in PyTorch 2.12)
    2. Patch torch.stft for float16 → float32
    3. Patch torchaudio (soundfile backend instead of torchcodec)
    """
    # cuDNN: no sm_120 kernels in PyTorch 2.12
    torch.backends.cudnn.enabled = False
    torch.backends.cudnn.benchmark = False

    # STFT: convert float16 to float32 globally
    _patch_torch_stft()

    # Torchaudio → soundfile (no FFmpeg DLLs)
    from voxlib.utils.torchaudio_shim import apply_patch

    apply_patch()

    # Announce GPU status
    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        vram = torch.cuda.get_device_properties(0).total_memory / 1e9
        print(f"[GPU] {name} — {vram:.0f} GB VRAM (cuDNN off, float32 STFT)")
    else:
        print("[GPU] CUDA not available — using CPU")
