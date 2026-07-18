"""Russian accent/stress placement using RUAccent.

Fixes омографы: за́мок/замо́к, му́ка/мука́, etc.
Timeout-protected — won't hang if HuggingFace is unreachable.
Thread-safe: background thread doesn't leak state after timeout.
"""

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_accentizer: Optional[object] = None
_accentizer_available: bool = False
_attempted_load: bool = False
_load_lock = threading.Lock()


def _load_accentizer(timeout: float = 8.0) -> bool:
    """Initialize RUAccent with timeout. Returns True if successful.

    Uses a lock to prevent concurrent loads, and doesn't read
    state that might be set by a timed-out background thread.
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

    # Try loading with timeout
    result = [False]
    exception = [None]

    def _do_load():
        try:
            from ruaccent import RUAccent
            acc = RUAccent()
            # Try tiny mode first (fast, CPU, ~50MB model)
            acc.load(omograph_model_size="tiny", use_dictionary=False, device="CPU")
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
        logger.info("RUAccent loaded successfully")
        return True
    else:
        # Timeout or failure - do NOT read _accentizer (might be half-set by daemon thread)
        if exception[0]:
            logger.warning(f"RUAccent load failed: {exception[0]}")
        else:
            logger.warning(f"RUAccent load timed out after {timeout}s")
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