# VoxLibRus — Статус проекта

> **Дата аудита:** 2026-07-19
> **Ветка:** master (последний коммит: `2e2c905`)
> **Тесты:** 97 passed, 0 failed, 2 skipped
> **Линтер:** ruff — All checks passed

---

## 1. Архитектура проекта

```
VoxLibRus/
├── voxlib/
│   ├── cli/main.py          # Typer CLI (run, extract, transcribe, clone, generate, assemble)
│   ├── config.py            # Pydantic-валидация конфига
│   ├── pipeline.py          # 8-stage orchestrator с resume
│   ├── text/
│   │   ├── extractor.py     # EPUB/PDF/DOCX → текст
│   │   ├── cleaner.py       # числа→пропись, кавычки, аббревиатуры
│   │   ├── accents.py       # RUAccent stress marks (+)
│   │   └── chunker.py       # Фрагментация 500-1000 символов
│   ├── asr/
│   │   ├── base.py          # ASRInterface
│   │   ├── gigaam.py        # GigaAM-v3 (primary, WER 8.4%)
│   │   └── whisper.py       # Whisper-large-v3 (fallback)
│   ├── tts/
│   │   ├── base.py          # TTSInterface
│   │   ├── f5tts.py         # F5-TTS_RUSSIAN (primary, CC-BY-NC)
│   │   └── qwen3.py         # Qwen3-TTS-Base (fallback, Apache-2.0)
│   ├── voice/
│   │   └── cloner.py        # Voice cloning orchestrator
│   └── audio/
│       ├── preprocess.py    # Фильтрация, ресемплинг
│       ├── normalize.py     # EBU R128 loudness normalization
│       └── assemble.py      # MP3/M4B сборка с главами
├── config.yaml              # YAML конфигурация
├── pyproject.toml           # Python package metadata
├── tests/                   # 97 тестов (pytest)
├── ARCHITECTURE.md          # Документация архитектуры
└── README.md                # Основной README
```

---

## 2. Статус компонентов

### 2.1 Text Layer ✅ (88 тестов)

| Модуль | Статус | Описание |
|---|---|---|
| `extractor.py` | ✅ | EPUB (ebooklib), PDF (pdfplumber), DOCX (markitdown) |
| `cleaner.py` | ✅ | normalize_numbers, expand_abbreviations, normalize_quotes, clean_punctuation |
| `accents.py` | ✅ | RUAccent stress marks (`+`), graceful fallback при ошибке загрузки модели |
| `chunker.py` | ✅ | Фрагментация 500-1000 символов, overlap для контекста TTS |

### 2.2 ASR Layer ✅ (1 тест)

| Бэкенд | Статус | WER | Лицензия | Примечание |
|---|---|---|---|---|
| **GigaAM-v3** (primary) | ✅ | 8.4% | MIT | Safetensors, trust_remote_code |
| **Whisper-large-v3** (fallback) | 🟡 Написан | 25.1% | MIT | Не протестирован E2E |

**Проблемы:**
- VAD (pyannote/segmentation-3.0) не используется — требует torch>=2.8, несовместим с Windows torchcodec
- Референс >25s нарезается грубыми окнами без VAD

### 2.3 TTS Layer ✅ (2 теста)

| Бэкенд | Статус | Stress marks | Лицензия | Скорость (CPU) |
|---|---|---|---|---|
| **F5-TTS_RUSSIAN** (primary) | ✅ | `+` поддержка | CC-BY-NC | ~370 сек/чанк |
| **Qwen3-TTS-Base** (fallback) | 🟡 Написан | ❌ стрипятся | Apache-2.0 | ~15 сек/чанк (оценка) |

**Проблемы:**
- Модель `model_last.pt` — 5.4 GB (тренировочный чекпоинт с optimizer states)
- Для inference достаточно ~2.6 GB (можно конвертировать в safetensors)

### 2.4 Voice Cloner ✅

| Этап | Статус |
|---|---|
| preprocess (resample, normalize) | ✅ |
| ASR транскрипция референса | ✅ GigaAM (проверено на автор.mp3) |
| TTS create_voice_clone_prompt | ✅ |
| Сохранение профиля в ~/.voxlib/speakers | ✅ |

### 2.5 Audio Layer ✅

| Модуль | Статус |
|---|---|
| `preprocess.py` | ✅ Ресемплинг, фильтрация |
| `normalize.py` | ✅ EBU R128 (-16 LUFS) |
| `assemble.py` | ✅ MP3 (libmp3lame), M4B с главами |

### 2.6 Pipeline ✅

| Этап | Статус | Описание |
|---|---|---|
| 1. Extract | ✅ | Извлечение текста из книги |
| 2. Clean | ✅ | Очистка и нормализация |
| 3. Accents | ✅ | Расстановка ударений |
| 4. Chunk | ✅ | Фрагментация |
| 5. Voice Clone | ✅ | ASR + создание voice profile |
| 6. Generate | ✅ | TTS генерация аудио |
| 7. Normalize | ✅ | EBU R128 громкость |
| 8. Assemble | ✅ | MP3/M4B сборка |

### 2.7 CLI ✅

| Команда | Статус |
|---|---|
| `voxlib run` | ✅ Полный пайплайн |
| `voxlib extract` | ✅ Извлечение текста |
| `voxlib transcribe` | ✅ ASR транскрипция |
| `voxlib clone` | ✅ Только клонирование |
| `voxlib generate` | ✅ Только генерация |
| `voxlib assemble` | ✅ Только сборка |

---

## 3. E2E тест (подтверждён)

**Команда:** `voxlib run --book test_book.epub --reference author_ref.wav --output my_book --force`

| Этап | Время | Результат |
|---|---|---|
| Text extraction | < 1s | 1 chapter extracted |
| Text cleaning | < 1s | Numbers, quotes, abbreviations |
| Stress marks | < 1s | RUAccent (fallback — модель не найдена) |
| Chunking | < 1s | 1 chunk |
| Voice cloning | < 1s | Transcribed: "Зато неплохо там в окружении..." |
| Generate audio | **6 min 11 sec** (CPU) | 2 batches @ 371 sec/chunk |
| Normalize | < 1s | EBU R128 |
| Assemble | < 1s | MP3 |

**Результат:** `output/test_book/test_book.mp3` (160 KB, ~6 сек)

---

## 4. Отклонения от начального плана

### 4.1 TTS лицензия: Apache-2.0 → CC-BY-NC 🔴

**План:** Apache-2.0 (Qwen3-TTS-Base)
**Факт:** CC-BY-NC (F5-TTS_RUSSIAN)

**Причина:** Qwen3-TTS-Base не поддерживает stress marks (`+`). F5-TTS_RUSSIAN имеет 100% датасет с разметкой ударений, что критически важно для правильного произношения русских слов-омографов (за́мок/замо́к).

**Влияние:** Коммерческое использование ограничено. Для коммерческих проектов нужен Qwen3 (Apache-2.0) — но качество произношения будет хуже.

### 4.2 GPU: CUDA → CPU 🔴

**План:** RTX 5060 Ti, CUDA, 16 GB VRAM
**Факт:** CPU

**Причина:** PyTorch 2.5.1+cu121 не содержит CUDA-ядер для архитектуры Blackwell (sm_120, RTX 5060 Ti). Даже PyTorch 2.6.0+cu124 и nightly 2.7.0.dev+cu124 не имеют поддержки. Python 3.13 имеет torch 2.12.0+cu128 с поддержкой sm_120, но блокируется torchcodec (FFmpeg DLLs на Windows).

**Влияние:** **Критическое.** Генерация 6 сек аудио — 6 минут вместо ~9 секунд. Скорость упадёт в 40× для книг (часовая книга → 40 часов CPU).

### 4.3 VAD: не используется 🟡

**План:** pyannote/segmentation-3.0 для Voice Activity Detection
**Факт:** Грубая нарезка 25-секундными окнами

**Причина:** pyannote-audio 4.0.7 требует torch>=2.8.0, несовместим с Hermes venv (2.5.1+cu121). torchcodec на Windows вызывает ошибки с FFmpeg DLLs.

**Влияние:** ASR транскрипция референса хуже (может захватывать тишину/шумы). Клонирование голоса работает, но точность референсного текста снижена.

### 4.4 Модель 5.4 GB 🟡

**План:** Не предусмотрен
**Факт:** `model_last.pt` весит 5.4 GB (тренировочный чекпоинт)

**Причина:** Скачан полный чекпоинт с optimizer states (3.2 GB лишних)

**Влияние:** Вдвое дольше загрузка модели, больше RAM/VRAM. Лечится конвертацией в safetensors (только weights, ~2.6 GB).

---

## 5. Ключевые проблемы (по приоритету)

### 🔴 P0: GPU не работает (блокирует производительность)

**Симптом:** `RuntimeError: CUDA error: no kernel image is available for execution on the device`

**Корень:** torch 2.5.1+cu121 не имеет ядер для sm_120 (RTX 5060 Ti Blackwell).

**Решение:** 
1. Использовать Python 3.13 (torch 2.12.0+cu128) — уже есть
2. Починить torchcodec: `copy FFmpeg DLLs → torchcodec directory` ИЛИ `winget install FFmpeg` (системный PATH)

**Альтернатива:** Продолжить на CPU. Работает, но медленно.

### 🔴 P1: torchcodec не грузится на Python 3.13

**Симптом:** `OSError: Could not load library libtorchcodec_core4.dll`

**Корень:** torchcodec не находит FFmpeg DLLs (avformat, avcodec). MSYS bash PATH не конвертируется корректно в Windows PATH.

**Решение:** Скопировать DLLs из `C:\Users\User\AppData\Local\Microsoft\WinGet\Packages\...\ffmpeg-8.1-full_build\bin\` в папку torchcodec.

**Обход:** `torchaudio.set_audio_backend("soundfile")` не работает в torchaudio 2.11.x (API удалён).

### 🟡 P2: Модель 5.4 GB

**Симптом:** Долгая загрузка.

**Решение:** `python -c "import torch; m = torch.load('model_last.pt', map_location='cpu'); torch.save(m['ema_model_state_dict'], 'model_last_inference.pt')"`

### 🟡 P3: RUAccent модель не найдена

**Симптом:** `Load model model.onnx failed. File doesn't exist`

**Решение:** Скачать onnx-файлы tiny-модели в `python3.13/site-packages/ruaccent/nn/nn_omograph/tiny/`

**Статус:** Есть fallback — без ударений, но работает.

---

## 6. Статус задач

| Задача | Статус | Комментарий |
|---|---|---|
| test-3: E2E пайплайн | ✅ **Выполнен** | book.epub → voice clone → generate → MP3 |
| test-4: Сборка аудиокниги | ✅ **Выполнена** | MP3 собран (single chunk) |
| GitHub push | ✅ | L-MORIA/VoxLibRus (public) |

---

## 7. Инструкция по запуску

### На Python 3.11 (CPU — медленно, но стабильно)

```bash
cd F:/VoxLibRus
voxlib run --book book.epub --reference reference.wav --output output
```

### На Python 3.13 (GPU — после починки torchcodec)

```bash
cd F:/VoxLibRus
PYTHONPATH="" CUDA_VISIBLE_DEVICES=0 \
  "C:/Program Files/Python313/python.exe" \
  -m voxlib.cli.main run --book book.epub --reference reference.wav --output output --force
```

---

*Документ создан: 2026-07-19*
*Последнее обновление: 2026-07-19*
