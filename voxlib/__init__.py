"""VoxLibRus — Russian audiobook generation with voice cloning."""

import os
from pathlib import Path

__version__ = "0.1.0"

# ── Load .env from project root ────────────────────────────────
# Sets HF_HOME so large models are served from F:\VoxLibRus\models
# instead of the default ~/.cache/huggingface
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _val = _line.split("=", 1)
            _key, _val = _key.strip(), _val.strip().strip("\"'")
            if _key:  # bare minimum — set the var
                os.environ.setdefault(_key, _val)
