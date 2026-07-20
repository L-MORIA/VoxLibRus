"""Regression tests for voxlib.voice.cloner.

Реальные ASR/TTS модели не гоняем (нужны веса и GPU) — мокаем бэкенды и
проверяем структурную корректность VoiceCloner.
"""

from unittest.mock import MagicMock, patch


class TestClonerTempPath:
    """P0-12: путь для обработанного референсного аудио раньше был
    захардкожен как "./.voxlib/tmp/..." — относительный к текущей рабочей
    директории процесса, а не к config.project.temp_dir. На Windows это
    могло упасть при запуске из директории без прав на запись; в любом
    случае файлы утекали мимо настроенной структуры temp_dir/output_dir.
    """

    def _make_cloner(self, tmp_path):
        from voxlib.voice.cloner import VoiceCloner

        cfg = MagicMock()
        cfg.project.temp_dir = str(tmp_path / "temp")
        cfg.project.output_dir = str(tmp_path / "out")
        cfg.tts.primary = "f5tts"
        cfg.asr.primary = "gigaam"
        cloner = VoiceCloner(config=cfg)
        # Mock the voice_manager so it doesn't try to hash real files
        cloner.voice_manager = MagicMock()
        cloner.voice_manager.get_cached_profile.return_value = None
        cloner.voice_manager.save_profile.return_value = "mocked_hash"
        return cloner, cfg

    def test_processed_ref_path_uses_configured_temp_dir(self, tmp_path, monkeypatch):
        cwd_sentinel = tmp_path / "cwd"
        cwd_sentinel.mkdir()
        monkeypatch.chdir(cwd_sentinel)

        ref_audio = tmp_path / "ref.wav"
        ref_audio.write_bytes(b"stub")

        cloner, cfg = self._make_cloner(tmp_path)

        with patch("voxlib.audio.preprocess.prepare_reference") as mock_prep, \
             patch("soundfile.info") as mock_info, \
             patch("os.path.exists", return_value=True), \
             patch.object(cloner, "_get_asr_backend"), \
             patch.object(cloner, "_get_tts_backend"):
            mock_prep.side_effect = lambda **kw: kw["output_path"]
            mock_info.return_value = MagicMock(frames=24000 * 10, samplerate=24000)

            cloner.clone_voice(
                ref_audio_path=str(ref_audio),
                ref_text="Тестовый референсный текст для проверки клонирования.",
            )

        output_path = mock_prep.call_args.kwargs["output_path"]

        assert output_path.startswith(cfg.project.temp_dir), (
            f"Путь обработанного референса не привязан к config.project.temp_dir: {output_path}"
        )
        assert not output_path.startswith("./"), "Путь всё ещё относительный (регресс P0-12)"
        assert list(cwd_sentinel.iterdir()) == [], "В текущую рабочую директорию не должно ничего утекать"

    def test_voice_refs_dir_created_under_temp_dir(self, tmp_path):
        ref_audio = tmp_path / "ref.wav"
        ref_audio.write_bytes(b"stub")
        cloner, cfg = self._make_cloner(tmp_path)

        with patch("voxlib.audio.preprocess.prepare_reference") as mock_prep, \
             patch("soundfile.info") as mock_info, \
             patch("os.path.exists", return_value=True), \
             patch.object(cloner, "_get_asr_backend"), \
             patch.object(cloner, "_get_tts_backend"):
            mock_prep.side_effect = lambda **kw: kw["output_path"]
            mock_info.return_value = MagicMock(frames=24000 * 10, samplerate=24000)

            cloner.clone_voice(
                ref_audio_path=str(ref_audio),
                ref_text="Тестовый референсный текст для проверки клонирования.",
            )

        from pathlib import Path

        assert (Path(cfg.project.temp_dir) / "voice_refs").is_dir()
