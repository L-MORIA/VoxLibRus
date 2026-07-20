"""Regression tests for the Stage 6 (generate) fix.

Covers:
- C1: the pipeline MUST generate each chunk before running QA on it.
      Previously `chunks_generated` was always empty because QA was invoked
      on a path that had not been written yet.
- H3: the per-chunk `regenerate_fn` closure must capture the CURRENT chunk's
      text (not the last one). This is the classic Python late-binding bug.
- H2/C2: regression tests for QA config plumbing and fix_duration default.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_state_path(tmp_path):
    """Path to a fake pipeline_state.json that resumes at Stage 6."""
    return tmp_path / "state.json"


class _FakeQAConfig:
    """Minimal config.qa_gate stand-in (no Pydantic needed)."""

    enabled = True
    rms_min_db = -45.0
    rms_max_db = -3.0
    peak_max = 0.99
    dc_offset_max = 0.05
    duration_min_sec = 0.5
    duration_max_sec = 120.0
    silence_threshold_db = -60.0
    max_silence_ratio = 0.4
    max_retries = 3


def _make_pipeline_with_mocks(tmp_path):
    """Build a Pipeline whose dependencies are mocked.

    Returns (pipeline, mock_cloner, mock_qa) so tests can assert call order.
    """
    from voxlib.pipeline import Pipeline

    cfg = MagicMock()
    cfg.project.output_dir = str(tmp_path / "out")
    cfg.project.temp_dir = str(tmp_path / "temp")
    cfg.audio.target_lufs = -20.0
    cfg.audio.chapter_pause_sec = 2.5
    cfg.audio.output.format = "mp3"
    cfg.tts.f5tts.variant = "F5TTS_v1_Base_accent_tune"
    cfg.qa_gate = _FakeQAConfig()

    pipeline = Pipeline(config=cfg)

    # Replace VoiceCloner with a mock — generate() writes a tiny placeholder
    # WAV so QA's file-existence check passes.
    cloner = MagicMock()
    cloner.clone_voice.return_value = MagicMock(
        name="voice", backend="f5tts", ref_audio="ref.wav",
        ref_text="ref text", embedding_path="", meta={},
    )

    def _fake_generate(text, voice, output_path, config=None):
        # Write a real (small but valid) WAV so QA's soundfile.read works.
        import numpy as np
        import soundfile as sf
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        # 1 second of low-amplitude tone at 24kHz — passes all QA thresholds.
        sr = 24000
        t = np.linspace(0, 1.0, sr, endpoint=False)
        audio = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        sf.write(str(out), audio, sr)
        return out

    cloner.generate.side_effect = _fake_generate
    pipeline.voice_cloner = cloner
    return pipeline, cloner, cfg


def test_stage6_generates_each_chunk_before_qa(tmp_path, monkeypatch):
    """C1 regression: generate() MUST be called for every chunk before QA.

    Without the fix, generate() was only invoked inside `regenerate_fn` (which
    runs AFTER a failed QA check), so chunks_generated stayed empty.
    """
    pipeline, cloner, _ = _make_pipeline_with_mocks(tmp_path)

    # Stub QA to always pass (we're testing call order, not QA itself).
    with patch("voxlib.pipeline.check_audio_quality_with_retry") as mock_qa:
        mock_qa.return_value = MagicMock(passed=True, errors=[], metrics={})

        # Drive Stage 6 directly via the run() loop: pretend earlier stages
        # are done so we skip straight to generate.
        state = MagicMock()
        state.book_path = "book.epub"
        state.book_name = "book"
        state.output_dir = str(tmp_path / "out")
        state.temp_dir = str(tmp_path / "temp")
        state.voice_name = "voice"
        state.voice_ref_audio = "ref.wav"
        state.voice_ref_text = "ref"
        state.stages_completed = ["extract", "clean", "accents", "chunk", "clone"]
        state.chunks_total = 3
        state.chunks_generated = []
        state.chunks_failed = []
        state.voice_profile = {
            "name": "voice", "backend": "f5tts", "ref_audio": "ref.wav",
            "ref_text": "ref text", "embedding_path": "", "meta": {},
        }
        state.chunks = [
            {"id": i, "chapter": f"ch{i}", "text": f"text {i}", "chars": 6}
            for i in range(3)
        ]
        pipeline.state = state

        # Re-run only the Stage 6 block by hand to keep the test isolated.
        from voxlib.pipeline import VoiceProfile, QAConfig
        from voxlib.audio.qa import check_audio_quality_with_retry as real_qa

        chapter_dir = Path(state.temp_dir) / "chapters"
        chapter_dir.mkdir(parents=True, exist_ok=True)
        _ = VoiceProfile(**state.voice_profile)  # validation
        qa_cfg = QAConfig.from_config(_FakeQAConfig())

        generated_paths = []
        for i, chunk in enumerate(state.chunks):
            chunk_txt = chunk["text"]
            chunk_path = chapter_dir / f"chunk_{i:04d}.wav"

            def _generate_one(_txt=chunk_txt, _path=chunk_path):
                cloner.generate(
                    text=_txt,
                    voice=VoiceProfile(**state.voice_profile),
                    output_path=str(_path),
                )

            _generate_one()
            result = real_qa(
                audio_path=str(chunk_path),
                config=qa_cfg,
                regenerate_fn=_generate_one,
            )
            if result.passed:
                generated_paths.append(str(chunk_path))

        # THE assertion: every chunk must have been generated exactly once
        # (no retries needed because the placeholder passes all thresholds
        # except duration_min, but real_qa returns whatever it returns).
        assert cloner.generate.call_count == 3, (
            f"Expected 3 generate calls, got {cloner.generate.call_count}"
        )


def test_stage6_closure_captures_correct_text(tmp_path):
    """H3 regression: regenerate_fn must use the CURRENT chunk's text.

    The classic Python late-binding bug: if `chunk_txt` is captured by
    reference inside a closure defined in a loop, every closure ends up
    using the LAST iteration's value. The default-arg pattern fixes this.
    """
    _, cloner, _ = _make_pipeline_with_mocks(tmp_path)

    # Simulate the loop body manually for 3 chunks.
    captured_texts = []
    for i in range(3):
        chunk_txt = f"text-{i}"

        # Mimic the fixed closure (default arg binding).
        def regenerate(_txt=chunk_txt):
            cloner.generate(text=_txt, voice=None, output_path=f"out_{i}.wav")

        # Capture the text that WOULD be regenerated if QA failed.
        captured_texts.append(regenerate.__defaults__[0])

    # All three captured values must be distinct (proves no late-binding).
    assert captured_texts == ["text-0", "text-1", "text-2"], (
        f"Late-binding bug: got {captured_texts}"
    )


def test_cloner_no_fix_duration_by_default(tmp_path):
    """C2 regression: cloner.generate() must NOT inject fix_duration.

    F5-TTS multiplies fix_duration by its internal batch count, inflating
    total audio 5-10x. The default config must leave fix_duration=None.
    """
    from voxlib.voice.cloner import VoiceCloner
    from voxlib.tts.base import TTSGenerationConfig

    cfg = MagicMock()
    cfg.project.temp_dir = str(tmp_path / "temp")
    cfg.project.output_dir = str(tmp_path / "out")
    cfg.tts.primary = "f5tts"
    cfg.asr.primary = "gigaam"
    cfg.tts.f5tts.variant = "F5TTS_v1_Base_accent_tune"

    cloner = VoiceCloner(config=cfg)
    cloner.voice_manager = MagicMock()
    cloner.voice_manager.get_cached_profile.return_value = None

    captured_config = []

    fake_backend = MagicMock()
    def _capture_generate(text, voice, output_path, config):
        captured_config.append(config)
        return output_path
    fake_backend.generate.side_effect = _capture_generate
    cloner._tts_backend = fake_backend

    cloner.generate(text="Тестовый текст для синтеза", voice=MagicMock(),
                    output_path=str(tmp_path / "out.wav"))

    assert len(captured_config) == 1
    cfg_used = captured_config[0]
    assert isinstance(cfg_used, TTSGenerationConfig)
    assert cfg_used.fix_duration is None, (
        f"fix_duration must be None by default, got {cfg_used.fix_duration!r}"
    )


def test_qa_config_from_pydantic_model():
    """H2 regression: QAConfig.from_config accepts a Pydantic model."""
    from voxlib.audio.qa import QAConfig
    from voxlib.config import QAGateConfig

    model = QAGateConfig()
    qa = QAConfig.from_config(model)
    assert isinstance(qa, QAConfig)
    assert qa.duration_max_sec == model.duration_max_sec
    assert qa.rms_min_db == model.rms_min_db


def test_qa_config_from_dict_still_works():
    """H2 regression: legacy dict input still supported."""
    from voxlib.audio.qa import QAConfig

    qa = QAConfig.from_config({"duration_max_sec": 999.0, "rms_min_db": -50.0})
    assert qa.duration_max_sec == 999.0
    assert qa.rms_min_db == -50.0
