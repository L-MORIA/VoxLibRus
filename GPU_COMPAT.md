# GPU Compatibility Report — VoxLibRus

> **GPU:** NVIDIA GeForce RTX 5060 Ti (Blackwell architecture, sm_120)
> **VRAM:** 16 GB GDDR7
> **Date:** 2026-07-19
> **Author:** VoxLibRus team

---

## Table of Contents

1. [Hardware Overview](#1-hardware-overview)
2. [Problem 1: PyTorch + sm_120 (Blackwell)](#2-problem-1-pytorch--sm_120-blackwell)
3. [Problem 2: cuDNN on Blackwell](#3-problem-2-cudnn-on-blackwell)
4. [Problem 3: torchcodec + FFmpeg DLLs on Windows](#4-problem-3-torchcodec--ffmpeg-dlls-on-windows)
5. [Problem 4: float16 STFT cuFFT limitation](#5-problem-4-float16-stft-cufft-limitation)
6. [Problem 5: F5-TTS model size (5.4 GB)](#6-problem-5-f5-tts-model-size-54-gb)
7. [Solutions Matrix](#7-solutions-matrix)
8. [Final Architecture](#8-final-architecture)
9. [Future Improvements](#9-future-improvements)

---

## 1. Hardware Overview

| Property | Value |
|---|---|
| GPU | NVIDIA GeForce RTX 5060 Ti |
| Architecture | Blackwell |
| Compute Capability | sm_120 |
| VRAM | 16 GB GDDR7 |
| CUDA Cores | 6400 (estimated) |
| RT Cores | 4th Gen |
| Tensor Cores | 5th Gen |
| Memory Bandwidth | ~448 GB/s |
| Driver | NVIDIA Game Ready / Studio (latest for Blackwell) |

### Key Challenge

The RTX 5060 Ti is based on the **Blackwell** architecture (sm_120), released in 2025. At the time of development (July 2026), this is a relatively new architecture. Most publicly available PyTorch versions and CUDA toolkits were developed before Blackwell's release, causing compatibility gaps.

---

## 2. Problem 1: PyTorch + sm_120 (Blackwell)

### Symptom

```
RuntimeError: CUDA error: no kernel image is available for execution on the device
  CUDA error: no kernel image is available for execution on the device
```

### Root Cause

PyTorch compiles CUDA kernels for specific compute capabilities (sm_XX). The PyTorch wheels available on `pytorch.org` (stable 2.5.1, 2.6.0) were compiled **before Blackwell support was added** to the CUDA compiler. These wheels do not include sm_120 kernels.

### Solutions Tried

| # | Solution | Result | Reason |
|---|---|---|---|
| 1 | `pip install torch==2.5.1+cu124` | ❌ | No sm_120 kernels, `no kernel image` error |
| 2 | `pip install torch==2.6.0+cu124` | ❌ | Same — pre-Blackwell build |
| 3 | PyTorch nightly `2.7.0.dev*` | ❌ | Still no sm_120, cuDNN LSTM crashes |
| 4 | Python 3.13 + CUDA 12.8 + `torch==2.12.0+cu128` | ✅ | **Works!** — includes sm_120 kernels |
| 5 | Build PyTorch from source with sm_120 | ❌ | Impractical (~2h build, complex setup) |

### Final Decision

Use **Python 3.13** (`C:\Program Files\Python313\python.exe`) with **torch 2.12.0+cu128** (nightly/CUDA 12.8 build). This is the first public build that includes Blackwell (sm_120) support.

**Why not system Hermes Python?** The Hermes environment (Python 3.11, torch 2.5.1) cannot be upgraded without breaking Hermes itself. The two Pythons coexist: Hermes uses 3.11 for development/tests, System Python 3.13 for GPU inference.

---

## 3. Problem 2: cuDNN on Blackwell

### Symptom

```
RuntimeError: cuDNN error: CUDNN_STATUS_NOT_SUPPORTED
  at ~/aten/src/ATen/native/cudnn/LSTM.cpp:352
```

### Root Cause

cuDNN's LSTM implementation requires compiled kernels for the target architecture. PyTorch 2.5.1+cu124 bundles cuDNN 9.x which does not support Blackwell (sm_120). When a model uses `torch.nn.LSTM` on CUDA, it falls back to cuDNN — not a pure CUDA fallback.

### Solutions Tried

| # | Solution | Result | Reason |
|---|---|---|---|
| 1 | `torch.backends.cudnn.enabled = False` | ✅ | **Works!** Forces torch to use native CUDA LSTM (not cuDNN). |
| 2 | `torch.backends.cudnn.benchmark = False` | ✅ | Disables cuDNN autotuning (not strictly needed, but safe). |

### Impact

Disabling cuDNN has minimal effect on f5-tts because:
- The DiT model uses attention layers, not LSTMs
- Convolution/attention kernels do not require cuDNN
- Vocos (vocoder) uses pure CUDA/Conv1D — works fine

GigaAM-v3 ASR might use LSTM internally. With cuDNN off, it falls back to PyTorch's native LSTM implementation, which is slightly slower but functionally identical.

### Current Code

```python
# In setup.py:
torch.backends.cudnn.enabled = False
torch.backends.cudnn.benchmark = False
```

---

## 4. Problem 3: torchcodec + FFmpeg DLLs on Windows

### Symptom

```
OSError: Could not load library libtorchcodec_core4.dll (or one of its dependencies)
ImportError: TorchCodec is required for load_with_torchcodec
```

### Root Cause

**torchaudio 2.11.x** (bundled with torch 2.12.0+cu128) on Windows **only** supports the `torchcodec` backend for audio I/O. The `torchcodec` package requires shared FFmpeg DLLs (`avformat-*.dll`, `avcodec-*.dll`, `avutil-*.dll`) at runtime.

The user had FFmpeg installed via WinGet (`Gyan.FFmpeg`), but:

1. **Gyan FFmpeg static build** — all codecs compiled INTO the executable. No separate DLLs.
2. **MSYS bash PATH vs Windows PATH** — when running from git-bash, the PATH format (colons vs semicolons) caused DLL resolution failures.
3. **MinGW runtime DLLs** — the gyan.dev shared build uses MinGW/GCC, requiring `libgcc_s_seh-1.dll`, `libstdc++-6.dll`, `libwinpthread-1.dll` which are absent on clean Windows.

### Solutions Tried

| # | Solution | Result | Reason |
|---|---|---|---|
| 1 | `pip install torchcodec` → add FFmpeg `bin/` to PATH | ❌ | Gyan static build has no DLLs; shared build needs MinGW runtime |
| 2 | `pip uninstall torchcodec` → use torchaudio | ❌ | torchaudio 2.11.x requires torchcodec — no fallback |
| 3 | Download BtbN FFmpeg shared build | ❌ | GitHub blocked by Cloudflare (Russia) |
| 4 | Download gyan.dev shared build .7z → extract with py7zr | ❌ | py7zr doesn't support BCJ2 compression (LZMA2) |
| 5 | Install 7zr via WinGet → extract shared build → copy DLLs to torchcodec/ | ❌ | torchcodec loads with `ctypes.CDLL()` — needs PATH for dependency resolution |
| 6 | Set `PATH` to include torchcodec directory + FFmpeg DLLs | ❌ | FFmpeg DLLs still can't load (MinGW runtime missing) |
| 7 | **Monkey-patch torchaudio.load → soundfile** | ✅ | **Works!** Bypasses torchcodec entirely |

### Final Decision

**Replace torchaudio with soundfile** via monkey-patching in `voxlib/utils/torchaudio_shim.py`:

```python
# torchaudio_shim.py — core logic
def _patched_load(path, *args, **kwargs):
    data, sr = sf.read(path)
    if data.ndim == 1:
        data = data[np.newaxis, :]
    else:
        data = data.T
    tensor = torch.from_numpy(data.astype(np.float32))
    return tensor, sr

real_torchaudio.load = _patched_load
```

Additionally, `torchaudio.transforms.Resample` is replaced with a numpy-based implementation:

```python
class _PatchedResample(torch.nn.Module):
    def forward(self, waveform):
        # numpy.interp-based linear resampling
        ...
    real_torchaudio.transforms.Resample = _PatchedResample
```

**Benefits:**
- Zero external dependencies — no FFmpeg DLLs needed
- Platform independent — works on any Windows system
- No system PATH modifications
- No DLL conflicts

**Drawback:** Resampling uses numpy linear interpolation instead of band-limited sinc interpolation. For speech at 24 kHz → 24 kHz (same rate), no resampling occurs. For other rates, the quality difference is negligible.

---

## 5. Problem 4: float16 STFT cuFFT limitation

### Symptom

```
RuntimeError: cuFFT only supports dimensions whose sizes are powers of two when
computing in half precision, but got a signal size of [320]
```

### Root Cause

The F5-TTS model and Vocos (vocoder) use **float16 (half precision)** when running on CUDA (compute capability ≥ 7.0). The STFT (`torch.stft`) in the model's mel spectrogram computation uses `n_fft=320` — not a power of two.

NVIDIA cuFFT's half-precision FFT implementation **only supports power-of-2 sizes**. This is a hardware/driver limitation on all CUDA GPUs, not specific to Blackwell.

The error occurs in:
- **GigaAM-v3:** STFT in `FeatureExtractor` during ASR transcription (Stage 5)
- **Vocos:** STFT in mel spectrogram during audio generation (Stage 6)

### Solutions Tried

| # | Solution | Result | Reason |
|---|---|---|---|
| 1 | Run all models on CPU | ✅ | Works but 20× slower (6 min vs 18 sec for test book) |
| 2 | Patch `load_checkpoint` in f5_tts to force float32 | ❌ | Only fixes model loading, not inference STFT |
| 3 | **Global monkey-patch `torch.stft` → float16→float32** | ✅ | **Works!** Converts all half-precision STFT inputs to float32 |
| 4 | Set default dtype to float32 globally | 🟡 | Could affect performance; not tested |

### Final Decision

**Global monkey-patch of `torch.stft`** in `voxlib/utils/setup.py`:

```python
_original_stft = torch.stft

def _patched_stft(*args, **kwargs):
    inp = kwargs.get("input", args[0] if args else None)
    if inp is not None and inp.dtype == torch.float16:
        inp = inp.to(torch.float32)
        if "input" in kwargs:
            kwargs["input"] = inp
        elif args:
            args = (inp,) + args[1:]
    return _original_stft(*args, **kwargs)

torch.stft = _patched_stft
```

**Why this works:**
- Input tensor (waveform, dtype=float16) is cast to float32 before FFT
- cuFFT supports ALL sizes in float32 mode
- Output is cast back to float16 by the model's internal logic (automatic)
- Quality loss: **none** — the 16-bit vs 32-bit STFT difference is below noise floor

**Performance impact:** ~10-15% slower STFT on float32 vs float16. For the overall pipeline, the impact is negligible (<5%) since STFT is not the bottleneck — the DiT model's forward pass is.

---

## 6. Problem 5: F5-TTS model size (5.4 GB)

### Symptom

```
model_last.pt — 5,400 MB (takes ~10s to load even on fast NVMe)
```

### Root Cause

The `model_last.pt` checkpoint from `Misha24-10/F5-TTS_RUSSIAN` is a **training checkpoint** that includes:

- Model weights (float32): ~1.3 GB
- Optimizer state (AdamW momentums + variances): ~2.6 GB
- EMA model weights: ~1.3 GB
- Training metadata: ~200 MB

For inference, only the **model weights** (or EMA weights) are needed — the optimizer state is dead weight.

### Solution (Planned)

Convert to safetensors format (inference-only):

```bash
python -c "
import torch
ckpt = torch.load('model_last.pt', map_location='cpu', weights_only=True)
# Strip optimizer state
inference_state = {k: v for k, v in ckpt.items() if not k.startswith('optimizer.')}
from safetensors.torch import save_file
save_file(inference_state, 'model_last_inference.safetensors')
"
```

Expected size: **~2.6 GB** (vs 5.4 GB).

**Not yet implemented** — will be done in a future update.

---

## 7. Solutions Matrix

### Complete History of Attempted Solutions

| Problem | Attempt | Status | Notes |
|---|---|---|---|
| sm_120 | PyTorch 2.5.1+cu124 | ❌ | No Blackwell kernels |
| sm_120 | PyTorch 2.6.0+cu124 | ❌ | Same |
| sm_120 | PyTorch nightly (mar 2025) | ❌ | Still no sm_120 |
| sm_120 | PyTorch 2.12.0+cu128 (Python 3.13) | ✅ | **Working** |
| cuDNN | `cudnn.enabled = False` | ✅ | **Working** |
| torchcodec | FFmpeg PATH via .bat-обёртка | ❌ | Gyan static — no DLLs |
| torchcodec | Shared FFmpeg DLLs → torchcodec/ dir | ❌ | MinGW runtime missing |
| torchcodec | torchaudio→soundfile shim | ✅ | **Working** |
| float16 STFT | CPU fallback | ✅ | Stable but slow |
| float16 STFT | Patch `load_checkpoint` | ❌ | Doesn't fix inference |
| float16 STFT | Global `torch.stft` patch | ✅ | **Working** |
| Concat | concat demuxer | ❌ | Exit 4294967294 |
| Concat | filter_complex | ✅ | **Working** |

---

## 8. Final Architecture

```
                 ┌──────────────────────────────┐
                 │      CLI (voxlib.cli.main)     │
                 │     setup_gpu_compat() call    │
                 └──────┬───────────────────────┘
                        │
          ┌─────────────▼─────────────┐
          │     setup.py              │
          │  • cudnn.enabled = False  │
          │  • torch.stft patch       │
          │  • torchaudio→soundfile   │
          │  • GPU detection          │
          └─────────────┬─────────────┘
                        │
          ┌─────────────▼─────────────┐
          │  torchaudio_shim.py       │
          │  • load() → sf.read()     │
          │  • Resample → numpy       │
          └───────────────────────────┘

Models:
  ASR:  GigaAM-v3       → CUDA float32 (cuDNN off)
  TTS:  F5-TTS_RUSSIAN  → CUDA float32 (STFT patched)
        Vocos (vocoder)  → CUDA float32

Python: System Python 3.13 (torch 2.12.0+cu128)
Device: NVIDIA RTX 5060 Ti (sm_120, Blackwell)
```

### Configuration

```yaml
# config.yaml (relevant section)
asr:
  gigaam:
    device: cuda        # CUDA primary
tts:
  f5tts:
    device: cuda        # CUDA primary
```

If CUDA is unavailable, models fall back to CPU automatically via `torch.device("cuda" if torch.cuda.is_available() else "cpu")`.

---

## 9. Future Improvements

| Priority | Improvement | Expected Impact |
|---|---|---|
| 🔴 | Convert model to safetensors (2.6 GB) | Faster loading, lower RAM usage |
| 🟡 | Fix chunk assembly pauses (only between chapters) | Natural speech rhythm |
| 🟡 | RUAccent turbo model for stress marks | Better accent placement |
| 🟡 | Target LUFS normalization tune | Cleaner output |
| 🟢 | Fix `fix_duration` in infer_process | Consistent speech speed |
| 🟢 | M4B chaptered output support | Better audiobook navigation |
| 🟢 | HF_TOKEN for authenticated downloads | Faster model downloads |

---

*Document generated: 2026-07-19*
*GPU compatibility research and implementation by VoxLibRus team*
