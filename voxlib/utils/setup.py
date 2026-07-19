"""GPU and audio compatibility setup for VoxLibRus.

Must be called before any voxlib modules are imported (especially before
f5_tts, which imports torchaudio at module level).

Handles:
- cuDNN disable for RTX 5060 Ti (Blackwell sm_120)
- torchaudio → soundfile patching to avoid torchcodec/FFmpeg DLL issues
"""

import torch


def setup_gpu_compat():
    """Apply GPU and audio compatibility patches."""
    # RTX 5060 Ti (sm_120, Blackwell) — no cuDNN kernels in PyTorch
    torch.backends.cudnn.enabled = False

    # Patch torchaudio to avoid torchcodec (requires FFmpeg shared DLLs)
    from voxlib.utils.torchaudio_shim import apply_patch

    apply_patch()
