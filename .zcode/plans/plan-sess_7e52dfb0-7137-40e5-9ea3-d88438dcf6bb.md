# План исправления VoxLibRus — аудит + проблема генерации чанков

## 🎯 Root cause проблемы «чанки не генерируются»

После коммита `671f285 feat: P1-7 Audio QA Gate` Stage 6 в `voxlib/pipeline.py` сломан:

1. **Первичная генерация вообще не вызывается.** Код передаёт в `check_audio_quality_with_retry` путь к файлу `chunk_{i:04d}.wav`, который **ещё не создан**. QA сразу возвращает `File not found`, затем дёргает `regenerate_fn` (позднее закрытие переменной `chunk_text` — тоже баг), но даже если он что-то генерирует — сломанный `fix_duration` делает чанк в ~400 c вместо 5 c, QA бракует по длительности, цикл повторяется `max_retries` раз и теряет результат (`chunks_generated=[]`).

2. **`fix_duration` умножается на число batches внутри F5-TTS.** В `f5_tts/infer/utils_infer.py:404` F5 разбивает gen_text на batches по формуле от длительности референса, и `fix_duration` применяется **к каждому** batch отдельно. Для чанка 823 символа и референса 10 c → 4 batches × 69.6 c ≈ 278 c (наблюдаем 424 c). Для референса 47 c `max_chars` становится **отрицательным** → F5 ломается полностью.

3. **`VoiceProfileManager.save_profile` хеширует уже обработанный audio**, а не оригинал → между запусками с одним `irina_ref.wav` попадание в кэш почти невозможно (каждая перегенерация processed_audio даёт новый hash из-за ffmpeg nondeterminism), а `cloner.clone_voice` пытается попасть в кэш по **оригинальному** пути. Несоответствие.

## 📋 Сводка аудита (всего 18 проблем)

### CRITICAL (блокируют генерацию)
- **C1** `pipeline.py:286-303` — Stage 6: нет первичной генерации перед QA + позднее связывание `chunk_text` в замыкании (берётся последний chunk для всех).
- **C2** `cloner.py:188-220` + `f5tts.py:251` — `fix_duration` для всего чанка передаётся в F5-TTS и умножается на число batches. Решение: **не передавать `fix_duration`** (F5 по умолчанию считает длительность по тексту через `ref_audio_len / ref_text_len * gen_text_len`), либо масштабировать на число batches.
- **C3** `cloner.py:123 vs manager.py:138` — кэш-хеш считается по разным файлам (оригинал vs processed). Cache miss почти гарантирован.

### HIGH
- **H1** `cli/main.py:32-83` — дубликаты `_parse_chapter_range`, `_filter_chapters`, `_parse_skip_stages` (определены дважды).
- **H2** `pipeline.py:267-268, 278, 296` — `qa_gate` отсутствует в `config.yaml` и в Pydantic-модели `Config` (а `extra="forbid"`). `getattr(self.config, "qa_gate", {})` всегда `{}`. QA всегда "enabled" с дефолтами `max_duration=20s` — это и блокирует длинные чанки.
- **H3** `pipeline.py:286` — `regenerate_chunk` замыкает `chunk_text` по ссылке, но цикл переопределяет переменную → все регенерации используют текст **последнего** чанка (позднее связывание Python closures).
- **H4** `pipeline.py:316-319` — Stage 7 (normalize) вызывает `loudness_normalize(path, ..., target_lufs=-16.0)`, хотя `QUALITY.md`/`config.audio.target_lufs = -20.0`. Хардкод игнорирует конфиг.
- **H5** `qa.py:33-34` — `dc_offset_max` объявлен дважды в `QAConfig` (строки 26 и 33) — дублирующее поле.
- **H6** `assemble.py:269` — `split_audiobook_by_chapters` использует глобальный `_FFMPEG` вместо переданного `ffmpeg` (после `_validate_ffmpeg_path`).
- **H7** `cloner.py:165` — `self._get_tts_backend()` вызывается, но результат не используется (мёртвый код, прогрев модели).

### MEDIUM
- **M1** `cloner.py:106-117` — варнинг про >30 сек референса, но pipeline продолжает работу с длинным референсом и ломается (нет жёсткой валидации/авто-trim).
- **M2** `pipeline.py:151` — `_save_state` пишет в `state.temp_dir`, но директория может ещё не существовать на моменте clone/extract (есть `mkdir` в save() — ОК, но создаёт скрытую зависимость).
- **M3** `manager.py:69, 124-125` — `except Exception: pass` полностью глушит ошибки чтения кэша (включая PermissionError и реальные повреждения JSON).
- **M4** `accents.py:81` — голый `continue` после if/else — мёртвая ветка (после else уже есть continue-семантика).
- **M5** `cleaner.py:96-132` — `_ABBREVIATIONS["г."]` и `["гг."]` без контекста раскрываются всегда («г.» → «год» даже в «г. Москва»).
- **M6** `cloner.py:171` — `backend="f5tts"` захардкожен даже если clone_config.tts_backend = "qwen3".

### LOW
- **L1** `cli/main.py:144-151` — параметры `chapters`, `skip_stages`, `workers`, `resume`, `dry_run` парсятся, но **не передаются** в `run_audiobook`.
- **L2** `pipeline.py:265` — `chunk_dir` объявлен внутри `else`, а `chapter_dir` снаружи — оба одинаковые, дублирование.

## 🔧 План исправлений (по приоритетам)

### Фаза 1 — чиним генерацию (CRITICAL)
1. **`voxlib/pipeline.py` Stage 6 (C1, H2, H3, L2):**
   - Перед циклом QA — **сгенерировать** чанк через `self.voice_cloner.generate(...)`.
   - Заменить `regenerate_chunk` замыкание на default-arg: `def regenerate_chunk(_txt=chunk_text, _path=chunk_path):` (фикс позднего связывания).
   - Удалить дублирование `chapter_dir`/`chunk_dir` (L2).
   - Сделать `qa_gate` настоящим полем `Config` (новая `QAConfigModel`) + добавить секцию в `config.yaml` с реалистичными порогами для аудиокниг (`duration_max_sec: 120`, `enabled: true`).

2. **`voxlib/tts/f5tts.py` + `voxlib/voice/cloner.py` (C2):**
   - По умолчанию **не передавать `fix_duration`** в `infer_process` (None) — F5 сам считает длительность по формуле `ref_audio_len/ref_text_len × gen_text_len`, что и есть желаемое поведение.
   - Оставить `fix_duration` как опциональный рычаг, но в `_calc_fix_duration` умножать на оценку batches ИЛИ документировать, что значение применяется к каждому batch.
   - В `cloner.generate()` по умолчанию передавать `TTSGenerationConfig()` **без** `fix_duration`, а не с авто-расчётом.

3. **`voxlib/voice/manager.py` (C3):**
   - В `save_profile` хеш считать от **оригинального** аудио (параметр уже есть `original_audio`), а не от `profile.ref_audio` (processed). Привести в соответствие с тем, что делает `get_cached_profile` в `cloner.py`.

### Фаза 2 — приоритетные баги (HIGH)
4. **`voxlib/cli/main.py` (H1, L1):** удалить дубликаты функций; прокинуть `force_restart`/`voice_ref_text`/`config_path` корректно (уже есть); опционально — `--reference-text` опция.
5. **`voxlib/audio/qa.py` (H5):** удалить дубликат поля `dc_offset_max`.
6. **`voxlib/audio/normalize.py` (H4):** `pipeline.Stage 7` должен читать `target_lufs` из `config.audio.target_lufs` (-20), а не хардкод -16.
7. **`voxlib/audio/assemble.py` (H6):** `split_audiobook_by_chapters` — использовать локальный `ffmpeg`.
8. **`voxlib/voice/cloner.py` (H7, M6):** убрать мёртвый `_get_tts_backend()` в `clone_voice`; сделать `backend` из `clone_config.tts_backend`.

### Фаза 3 —robustness (MEDIUM/LOW)
9. `manager.py:69,124` — логировать вместо `pass`.
10. `accents.py:81` — убрать мёртвый `continue`.
11. `cloner.py:112-117` — оставить warning, но явно сообщать, что модель будет копировать темп референса.

### Фаза 4 — валидация
12. Прогнать `pytest tests/` (кроме случаев с опциональными dep `num2words`/`ebooklib`).
13. Добавить 2 регрессионных теста:
    - `test_pipeline_stage6_generates_before_qa` — мок QA, проверка что `generate` вызван.
    - `test_cloner_no_fix_duration_by_default` — что без явного config `fix_duration=None`.

## 📊 Ожидаемый эффект
- Чанки для `irina_ref_short.wav` будут генерироваться за ~10–20 c вместо 400+ c (F5 сам посчитает длительность по тексту).
- QA gate получит реалистичные пороги (`duration_max_sec: 120`) из конфига.
- Кэш голосовых профилей начнёт реально попадать (один и тот же `irina_ref.wav` + текст → тот же профиль).
- Resume pipeline станет работать после прерванного Stage 6.

## ⚠️ Что НЕ трогаю
- Формулу F5-TTS для `max_chars` (она в чужом пакете — не патчим vendored код без необходимости).
- Архитектуру модулей — только баги.
- GPU/CUDA-специфику.

## Готов к выполнению после одобрения.