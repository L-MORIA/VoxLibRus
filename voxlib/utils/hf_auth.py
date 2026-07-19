"""Hugging Face Hub authentication utilities for VoxLibRus.

Provides automatic token discovery and authenticated downloads.
"""

import os
from pathlib import Path
from typing import Optional

from huggingface_hub import hf_hub_download, login


def ensure_hf_auth() -> bool:
    """Ensure Hugging Face authentication is set up.

    Searches for token in order:
    1. HF_TOKEN environment variable
    2. HUGGINGFACE_HUB_TOKEN environment variable
    3. ~/.huggingface/token file
    4. ~/.config/huggingface/token file

    Returns:
        True if authentication was successful, False otherwise.
    """
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")

    if not token:
        for path in [
            Path.home() / ".huggingface" / "token",
            Path.home() / ".config" / "huggingface" / "token",
        ]:
            if path.exists():
                token = path.read_text().strip()
                break

    if token:
        try:
            login(token=token, add_to_git_credential=False)
            return True
        except Exception as e:
            print(f"Warning: HF login failed: {e}")
            return False

    return False


def hf_hub_download_with_auth(
    repo_id: str,
    filename: str,
    revision: Optional[str] = None,
    **kwargs,
) -> str:
    """Download a file from Hugging Face Hub with automatic authentication.

    This is a wrapper around hf_hub_download that automatically handles
    authentication by calling ensure_hf_auth() before downloading.

    Args:
        repo_id: Hugging Face repository ID (e.g., "ai-sage/GigaAM-v3")
        filename: Name of the file to download
        revision: Optional git revision/commit hash
        **kwargs: Additional arguments passed to hf_hub_download

    Returns:
        Local path to the downloaded file.

    Raises:
        RuntimeError: If download fails.
    """
    ensure_hf_auth()

    from huggingface_hub import hf_hub_download

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    if not token:
        for path in [
            Path.home() / ".huggingface" / "token",
            Path.home() / ".config" / "huggingface" / "token",
        ]:
            if path.exists():
                token = path.read_text().strip()
                break

    try:
        return hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            revision=revision,
            token=token or None,
            **kwargs,
        )
    except Exception as e:
        raise RuntimeError(f"Failed to download {filename} from {repo_id}: {e}") from e