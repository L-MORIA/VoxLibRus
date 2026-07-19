"""Russian accent/stress placement using RUAccent.

Fixes омографы: за́мок/замо́к, му́ка/мука́, etc.
Timeout-protected — won't hang if HuggingFace is unreachable.
Thread-safe: background thread doesn't leak state after timeout.
Supports multiple model sizes with automatic fallback on OOM.
"""

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_accentizer: Optional[object] = None
_accentizer_available: bool = False
_attempted_load: bool = False
_load_lock = threading.Lock()

# Model sizes in order of preference (turbo3.1 is best for prose, falls back on OOM)
_MODEL_SIZES = ["turbo3.1", "big_poetry", "tiny"]


def _load_accentizer(timeout: float = 8.0) -> bool:
    """Initialize RUAccent with timeout and model fallback on OOM.

    Tries models in order: turbo3.1 -> big_poetry -> tiny
    Falls back to smaller model on OOM.
    Returns True if successful.
    """
    global _accentizer, _accentizer_available, _attempted_load

    with _load_lock:
        if _attempted_load:
            return _accentizer_available
        _attempted_load = True

    # Quick check: is ruaccent installed?
    try:
        import ruaccent  # noqa: F401
    except ImportError:
        logger.info("RUAccent not installed. Run: pip install ruaccent")
        return False

    # Try models in order of preference, falling back on OOM
    for model_size in _MODEL_SIZES:
        result = [False]
        exception = [None]

        def _do_load():
            try:
                from ruaccent import RUAccent
                acc = RUAccent()
                acc.load(omograph_model_size=model_size, use_dictionary=False, device="CPU")
                result[0] = True
                result.append(acc)  # Store accentizer in result[1]
            except Exception as e:
                exception[0] = e

        t = threading.Thread(target=_do_load, daemon=True)
        t.start()
        t.join(timeout=timeout)

        if result[0]:
            # Success - store accentizer atomically
            _accentizer = result[1]
            _accentizer_available = True
            logger.info(f"RUAccent loaded successfully with model '{model_size}'")
            return True
        else:
            # Timeout or failure - check if it was OOM
            if exception[0]:
                error_msg = str(exception[0]).lower()
                if "out of memory" in error_msg or "cuda out of memory" in error_msg or "oom" in error_msg:
                    logger.warning(f"RUAccent OOM with model '{model_size}', trying fallback...")
                    continue  # Try next smaller model
                logger.warning(f"RUAccent load failed with model '{model_size}': {exception[0]}")
            else:
                logger.warning(f"RUAccent load timed out after {timeout}s with model '{model_size}'")
            # Try next model
            continue

    # All models failed
    logger.warning("RUAccent failed to load with all available models")
    return False


def fix_accents(text: str) -> str:
    """Place stress marks in Russian text.

    Args:
        text: Russian text.

    Returns:
        Text with '+' before stressed vowel if available, else original.
    """
    if not text or not text.strip():
        return text
    if not _load_accentizer():
        return text
    try:
        return _accentizer.process_all(text)  # type: ignore
    except Exception as e:
        logger.warning(f"Accent placement failed: {e}")
        return text


def is_available() -> bool:
    """Check if RUAccent is loaded."""
    return _load_accentizer()