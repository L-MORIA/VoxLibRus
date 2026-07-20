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

            # Patch: ONNX model expects token_type_ids but the tokenizer
            # doesn't provide it. Intercept session.run to inject zeros.
            _orig_session_run = _accentizer.accent_model.session.run

            def _patched_session_run(output_names, input_feed):
                if "token_type_ids" not in input_feed:
                    import numpy as np
                    # Copy to avoid mutating caller's dict
                    input_feed = dict(input_feed)
                    seq_len = input_feed["input_ids"].shape[-1]
                    input_feed["token_type_ids"] = np.zeros(
                        (1, seq_len), dtype=np.int64
                    )
                return _orig_session_run(output_names, input_feed)

            _accentizer.accent_model.session.run = _patched_session_run
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
            # Fall through to next model in the loop (M4: removed redundant continue)

    # All models failed
    logger.warning("RUAccent failed to load with all available models")
    return False


def fix_accents(text: str) -> str:
    """Place stress marks in Russian text.

    Processes text sentence-by-sentence to work around ONNX
    token_type_ids bug on long inputs.

    Args:
        text: Russian text.

    Returns:
        Text with '+' before stressed vowel if available, else original.
    """
    if not text or not text.strip():
        return text
    if not _load_accentizer():
        return text

    # Process sentence-by-sentence to avoid ONNX token_type_ids bug
    # (turbo3.1/tiny models crash on long text with "missing token_type_ids")
    import re as _re
    sentences = _re.split(r'(?<=[.!?…])\s+', text)
    result_parts = []
    for sent in sentences:
        if not sent.strip():
            continue
        try:
            stressed = _accentizer.process_all(sent)  # type: ignore
            result_parts.append(stressed)
        except Exception:
            # ONNX model failed on this sentence — return original
            result_parts.append(sent)
    return " ".join(result_parts)


def is_available() -> bool:
    """Check if RUAccent is loaded."""
    return _load_accentizer()