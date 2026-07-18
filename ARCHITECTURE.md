# VoxLibRus — Архитектура проекта

> **Версия:** 0.1.0  
> **Дата:** 2026-07-18  
> **Цель:** Создание аудиокниг с клонированием голоса автора (русский язык)

---

## Содержание

1. [Цели и мотивация](#1-цели-и-мотивация)
2. [Общая архитектура](#2-общая-архитектура)
3. [Выбор моделей — обоснование](#3-выбор-моделей--обоснование)
4. [Структура проекта](#4-структура-проекта)
5. [Компоненты](#5-компоненты)
6. [Поток данных](#6-поток-данных)
7. [Конфигурация](#7-конфигурация)
8. [Требования к оборудованию](#8-требования-к-оборудованию)
9. [План реализации](#9-план-реализации)
10. [Риски и митигация](#10-риски-и-митигация)

---

## 1. Цели и мотивация

### 1.1 Проблема
Создание аудиокниги голосом автора требует от автора прочитать **10-50+ часов** текста. Это дорого, долго и физически тяжело.

### 1.2 Решение
Автор читает **1-2 страницы (5-10 мин)**, мы:
1. Транскрибируем запись с высокой точностью (GigaAM-v3)
2. Клонируем голос (Qwen3-TTS-CustomVoice)
3. Генерируем всю книгу клонированным голосом (до 300 стр, ~9+ часов аудио)

### 1.3 Почему новый проект, а не форк существующего

| Проект | Почему не подходит |
|---|---|
| **ebook2audiobook** (19.5K⭐) | XTTS-v2 даёт 3/5 качества для RU. Замена бэкенда = переписывание архитектуры |
| **GPT-SoVITS** (59.9K⭐) | RU не primary. Нет book pipeline. Сложная интеграция |
| **Pandrator** (589⭐) | Kokoro без RU. XTTS 3/5. Молодой, сырой |
| **OmniVoice-Studio** (8.6K⭐) | Китайский фокус. RU под вопросом |

**Вывод:** готового проекта для русского языка с отличным качеством — **нет**. VoxLibRus заполняет эту нишу.

---

## 2. Общая архитектура

```
┌─────────────────────────────────────────────────────────────────────┐
│                         VoxLibRus Pipeline                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────┐    ┌──────────────┐    ┌───────────────────┐      │
│  │ 1. Текст    │───▶│ 2. Очистка   │───▶│ 3. Фрагментация   │      │
│  │ (PDF/EPUB)  │    │ & нормализ.  │    │ по ~1000 символов │      │
│  └─────────────┘    └──────────────┘    └─────────┬─────────┘      │
│                                                    │                │
│  ┌─────────────┐    ┌──────────────┐               │                │
│  │ 4. Референс │───▶│ 5. ASR       │               │                │
│  │ (WAV 5-10м) │    │ GigaAM-v3    │               │                │
│  └─────────────┘    └──────┬───────┘               │                │
│                            │                       │                │
│                            ▼                       ▼                │
│  ┌──────────────────────────────────────────────────────┐          │
│  │              6. Voice Cloning                        │          │
│  │  Qwen3-TTS-CustomVoice: ref_audio + ref_text         │          │
│  │  → Speaker Embedding / Fine-tune                     │          │
│  └──────────────────────┬───────────────────────────────┘          │
│                         │                                          │
│                         ▼                                          │
│  ┌──────────────────────────────────────────────────────┐          │
│  │              7. TTS Generation                       │          │
│  │  Для каждого фрагмента:                              │          │
│  │  Qwen3-TTS (cloned voice) → .wav                     │          │
│  │  Resume: сохраняет прогресс в JSON                   │          │
│  └──────────────────────┬───────────────────────────────┘          │
│                         │                                          │
│                         ▼                                          │
│  ┌──────────────────────────────────────────────────────┐          │
│  │              8. Постобработка                        │          │
│  │  Нормализация громкости (LUFS -16)                   │          │
│  │  Паузы между главами (2-3 сек)                       │          │
│  │  Склейка → MP3 + M4B с метаданными                   │          │
│  └──────────────────────────────────────────────────────┘          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Выбор моделей — обоснование

### 3.1 ASR-слой: распознавание речи автора

#### Основной: GigaAM-v3 (ai-sage) — 🏆 PRIMARY

| Метрика | GigaAM-v3 RNNT | Whisper-large-v3 |
|---|---|---|
| **WER Open Datasets** | **2.6%** 🔥 | 12.0% |
| **WER Natural Speech** | **6.9%** 🔥 | 13.6% |
| **WER Callcenter** | **9.5%** 🔥 | 23.9% |
| **Средний WER** | **8.4%** 🏆 | **25.1%** ❌ |
| Параметры | **220M** ⚡ | 3B (тяжёлый) |
| VRAM | **~1-2 GB** ✅ | ~6-8 GB ❌ |
| Русский | **700К часов** 🏆 | Общий датасет |
| Пунктуация | ✅ e2e_rnnt | ❌ (нужен пост-процессинг) |
| Лицензия | MIT | MIT |

**Обоснование:** GigaAM-v3 в **3 раза точнее** Whisper на русском языке. При voice cloning точность транскрипции референса критична — ошибки в референсном тексте напрямую ухудшают качество клонирования. Дополнительно: модель в 10 раз легче, работает быстрее, ставит пунктуацию автоматически.

**Резерв:** Whisper-large-v3 — если GigaAM не справится с нестандартным аудио (музыка, эхо).

---

### 3.2 TTS-слой: клонирование голоса и генерация

#### Основной: Qwen3-TTS-12Hz-1.7B-Base (Qwen/Alibaba) — 🏆 PRIMARY

| Характеристика | Qwen3-TTS-Base | Qwen3-TTS-CustomVoice | F5-TTS_RUSSIAN |
|---|---|---|---|
| **Русский язык** | ✅ Native (10 языков) | ✅ Native | ✅ Native |
| **Voice cloning** | ✅ **от 3 секунд** 🔥 | ❌ **9 фикс. голосов** | ✅ от 10 секунд |
| **Naturalness (RU)** | **4.5/5** | 4.5/5 | **5/5** 🏆 |
| **Expressiveness** | **5/5** 🏆 | **5/5** 🏆 | **5/5** 🏆 |
| **Скорость GPU** | ~15 сек/фрагмент | ~15 сек/фрагмент | **~2.3 сек/фрагмент** ⚡ |
| **Multi-speaker** | ❌ (требует доработки) | ✅ **до 4 голосов** | ❌ |
| **Streaming** | ✅ 97ms latency | ✅ 97ms latency | ❌ |
| **Лицензия** | **Apache-2.0** ✅ | **Apache-2.0** ✅ | CC-BY-NC ❌ |
| **VRAM** | ~6-8 GB | ~6-8 GB | ~4-6 GB |
| **Интеграция** | **4/5** | **4/5** | 1/5 |
| **HF загрузки** | **2.15M** 🏆 | **2.43M** 🏆 | 92K |

**Обоснование выбора Qwen3-TTS-Base как PRIMARY:**

1. **Voice cloning из произвольного аудио** — Base имеет метод `generate_voice_clone(text, language, ref_audio, ref_text)`, CustomVoice принимает только 9 предустановленных speaker name.
2. **Лицензия Apache-2.0** — можно использовать коммерчески.
3. **Voice cloning от 3 секунд** — достаточно даже очень короткой записи.
4. **End-to-end архитектура** — нет каскадных ошибок.
5. **Зрелость** — 2.15M загрузок, команда Qwen (Alibaba).

**CustomVoice** оставлен как опциональный бэкенд для сценариев:
- Нужны встроенные голоса без клонирования
- Нужно управление эмоциями через instruct
- Multi-speaker режим (до 4 голосов в диалоге)

#### Дополнительный бэкенд: F5-TTS_RUSSIAN (Misha24-10) — 🏆 SECONDARY

**Обоснование:** Единственное преимущество F5-TTS_RUSSIAN — **чуть выше качество (5/5 vs 4.5/5)** и **скорость (2.3s vs 15s)**. Если не требуется multi-speaker и коммерческая лицензия не важна — можно переключиться на F5-TTS для максимального качества.

**Стратегия:** Абстракция TTSBackend, переключение через config.yaml.

---

### 3.3 Сравнение полных конфигураций

| Конфигурация | Качество RU | Voice Clone | Лицензия | VRAM | Скорость | Multi-speaker |
|---|---|---|---|---|---|---|
| **🏆 VoxLib** (GigaAM + Qwen3-TTS) | 4.5/5 | ✅ 3 сек | **Apache-2.0** | ~8-10 GB | Средняя | ✅ до 4 |
| VoxLib (GigaAM + F5-TTS) | **5/5** 🏆 | ✅ 10 сек | CC-BY-NC ❌ | ~6-8 GB | **Быстрая** ⚡ | ❌ |
| Whisper + XTTS (ebook2audiobook) | 3/5 | ✅ 30 сек | Apache-2.0 | ~10-14 GB | Медленная | ❌ |
| Только F5-TTS_RUSSIAN | **5/5** | ✅ 10 сек | CC-BY-NC | ~4-6 GB | **Быстрая** | ❌ |

---

## 4. Структура проекта

```
F:/VoxLibRus/
│
├── README.md                          # Описание проекта
├── ARCHITECTURE.md                    # Данный документ
├── config.yaml                        # Конфигурация (модели, пути, параметры)
├── requirements.txt                   # Зависимости
├── pyproject.toml                     # Python-пакет
├── .gitignore
│
├── voxlib/                            # Главный пакет
│   ├── __init__.py
│   │
│   ├── config.py                      # Загрузка и валидация config.yaml
│   │
│   ├── pipeline.py                    # Оркестратор: последовательный запуск этапов
│   │
│   ├── text/                          # === ТЕКСТОВЫЙ СЛОЙ ===
│   │   ├── __init__.py
│   │   ├── extractor.py               # Извлечение текста из PDF/EPUB/DOCX
│   │   │   └── extract(path) -> dict[chapter_title, text]
│   │   ├── cleaner.py                 # Очистка русского текста
│   │   │   └── clean(text) -> text
│   │   │   # Числа→пропись, кавычки, аббревиатуры, ё
│   │   ├── accents.py                 # Расстановка ударений (RUAccent)
│   │   │   └── fix_accents(text) -> text
│   │   │   # Для омографов: за́мок/замо́к. https://github.com/Den4ikAI/ruaccent
│   │   └── chunker.py                 # Умная фрагментация
│   │       └── chunk(text_by_chapters) -> list[{id, chapter, text, chars}]
│   │       # По абзацам, 500-1500 символов, с перекрытием 50 символов
│   │
│   ├── asr/                           # === ASR СЛОЙ (распознавание) ===
│   │   ├── __init__.py
│   │   ├── base.py                    # ASRInterface (abstract)
│   │   │   └── transcribe(audio_path) -> str
│   │   ├── gigaam.py                  # GigaAM-v3 (PRIMARY)
│   │   │   # ai-sage/GigaAM-v3, revision="e2e_rnnt"
│   │   │   # WER 8.4%, 220M params, MIT
│   │   └── whisper.py                 # Whisper-large-v3 (FALLBACK)
│   │       # openai/whisper-large-v3, WER 25.1%
│   │
│   ├── tts/                           # === TTS СЛОЙ (генерация) ===
│   │   ├── __init__.py
│   │   ├── base.py                    # TTSInterface (abstract)
│   │   │   ├── clone_voice(ref_audio, ref_text) -> voice_profile
│   │   │   └── generate(text, voice_profile, output_path)
│   │   ├── qwen3.py                   # Qwen3-TTS-CustomVoice (PRIMARY)
│   │   │   # Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
│   │   │   # Apache-2.0, voice clone 3s, native RU, multi-speaker 4
│   │   └── f5tts.py                   # F5-TTS_RUSSIAN (SECONDARY)
│   │       # Misha24-10/F5-TTS_RUSSIAN, CC-BY-NC
│   │       # Качество 5/5, скорость 2.3s
│   │
│   ├── voice/                         # === УПРАВЛЕНИЕ ГОЛОСАМИ ===
│   │   ├── __init__.py
│   │   ├── cloner.py                  # Процесс клонирования: ASR → TTS
│   │   │   └── full_clone_pipeline(ref_audio, ref_text_hint)
│   │   └── manager.py                 # Сохранение/загрузка голосов
│   │       └── save/load/list_speaker_profiles()
│   │       # ~/.voxlib/speakers/*.json + эмбеддинги
│   │
│   ├── audio/                         # === АУДИО СЛОЙ ===
│   │   ├── __init__.py
│   │   ├── preprocess.py              # Препроцессинг референса
│   │   │   └── prepare_reference(input_path) -> clean_path
│   │   │   # Resample 24kHz, denoise, trim silence, normalize
│   │   ├── normalize.py               # Нормализация громкости
│   │   │   └── loudness_normalize(input_dir, target_lufs=-16)
│   │   │   # EBU R128, интегральная громкость
│   │   └── assemble.py                # Сборка аудиокниги
│   │       ├── merge_chapters(chapter_files, pauses=2.0) -> merged
│   │       ├── export_mp3(input, output, bitrate=192k)
│   │       └── export_m4b(input, chapters_meta, output)
│   │
│   ├── utils/                         # === УТИЛИТЫ ===
│   │   ├── __init__.py
│   │   ├── gpu.py                     # Управление VRAM
│   │   │   └── clear_cache(), get_vram(), optimize_memory()
│   │   └── resume.py                  # Прогресс-трекер
│   │       ├── save_progress(resume_path, state)
│   │       └── get_pending(chunks, resume_path) -> list
│   │       # JSON-файл: {done: [id1, id2, ...], failed: [{id, error}]}
│   │
│   └── cli/                           # === CLI ИНТЕРФЕЙС ===
│       ├── __init__.py
│       └── main.py                    # Typer/Click CLI
│       # voxlib --book book.pdf --reference author.wav --output book
│       # Подкоманды: extract, transcribe, clone, generate, assemble
│
├── tests/
│   ├── test_extractor.py
│   ├── test_cleaner.py
│   ├── test_chunker.py
│   └── test_config.py
│
└── docs/
    ├── architecture.md
    └── usage.md
```

---

## 5. Компоненты — детальное описание

### 5.1 text/ — Текстовый слой

**Назначение:** Подготовка текста книги для TTS.

**extractor.py:**
```
Вход: book.pdf / book.epub / book.docx
Выход: {"Глава 1": "текст...", "Глава 2": "текст..."}
Библиотеки: pdfplumber (PDF), ebooklib (EPUB), markitdown (DOCX)
```

**cleaner.py — критически важно для русского TTS:**
```
- Числа → пропись (num2words lang='ru'):
  "123" → "сто двадцать три"
  "25-й" → "двадцать пятый"
  "3.14" → "три целых четырнадцать сотых"
- Кавычки: "«»" (ёлочки) → единый стиль
- Тире: "—" (длинное) для прямой речи
- Аббревиатуры: "т.е." → "то есть", "и т.д." → "и так далее"
- Буква "ё" — нормализация
- Спецсимволы: удаление лишних
```

**chunker.py:**
```
- Фрагменты по 500-1500 символов
- Естественные границы: конец абзаца > конец предложения > конец фразы
- Перекрытие 50 символов для контекста
- Каждый фрагмент отделяется от TTS для генерации
- Размер: ~1000 символов = ~10-15 секунд аудио = оптимальный баланс
```

### 5.2 asr/ — ASR слой

**Назначение:** Точная транскрипция референсной записи автора.

**base.py:**
```python
class ASRInterface(ABC):
    @abstractmethod
    def transcribe(self, audio_path: str) -> str:
        """Возвращает текст с пунктуацией"""
```

**gigaam.py (PRIMARY):**
```python
class GigaAMASR(ASRInterface):
    model_id = "ai-sage/GigaAM-v3"
    revision = "e2e_rnnt"  # end-to-end с пунктуацией
    # 220M params, MIT, WER 8.4% RU
    # Использует transformers + trust_remote_code=True
```

**whisper.py (FALLBACK):**
```python
class WhisperASR(ASRInterface):
    model_id = "openai/whisper-large-v3"
    # 3B params, WER 25.1% RU (3x хуже GigaAM)
    # Используется, если GigaAM выдаёт ошибку
```

### 5.3 tts/ — TTS слой

**Назначение:** Клонирование голоса и генерация аудио.

**base.py:**
```python
class TTSInterface(ABC):
    @abstractmethod
    def clone_voice(self, ref_audio: str, ref_text: str) -> VoiceProfile:
        """Создать голосовой профиль из референса"""

    @abstractmethod
    def generate(self, text: str, voice: VoiceProfile, output_path: str):
        """Сгенерировать аудио текста голосом из профиля"""
```

**qwen3.py (PRIMARY):**
```python
class Qwen3TTS(TTSInterface):
    model_id = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
    # Voice clone: от 3 секунд аудио
    # Native Russian
    # Multi-speaker: до 4 голосов
    # Streaming: первый пакет за 97ms
    # End-to-end LM архитектура
    # 6-8 GB VRAM
    # Apache-2.0
```

**f5tts.py (SECONDARY):**
```python
class F5TTSBackend(TTSInterface):
    model_id = "Misha24-10/F5-TTS_RUSSIAN"
    # Voice clone: от 10 секунд
    # Naturalness: 5/5 (лучший для RU)
    # Speed: 2.3s GPU (быстрее Qwen3)
    # CC-BY-NC license
    # Сложная интеграция (1/5)
```

### 5.4 audio/ — Аудио слой

**preprocess.py — подготовка референса:**
```
- Resample: любое → 24kHz (как требует Qwen3-TTS)
- Denoise: noisereduce (спектральное шумоподавление)
- Trim silence: pydub (по краям)
- Normalize peak: -3dB (чтобы не было клиппинга)
- Выход: WAV 24kHz mono 16-bit
```

**normalize.py — постобработка:**
```
- LUFS интегральная громкость: -16 LUFS (стандарт для аудиокниг)
- Пиковая громкость: -1dB
- loudness_normalize() через pyloudnorm или ffmpeg loudnorm
```

**assemble.py — сборка:**
```
- Паузы между главами: 2-3 сек тишины
- Склейка: pydub.concat()
- Экспорт MP3: ffmpeg -c:a libmp3lame -b:a 192k
- Экспорт M4B: ffmpeg + chapter metadata (опционально)
```

### 5.5 utils/resume.py — прогресс-трекер

**Критически важно для книг 300+ страниц (9+ часов генерации).**

```json
{
  "book_name": "Война и мир",
  "tts_backend": "qwen3",
  "voice_profile": "author_ivanov",
  "total_chunks": 450,
  "done": [1, 2, 3, ..., 127],
  "failed": [
    {"id": 128, "error": "CUDA OOM", "retry_count": 1}
  ],
  "started_at": "2026-07-18T10:00:00",
  "last_updated": "2026-07-18T11:23:45"
}
```

При перезапуске:
- `done` фрагменты пропускаются
- `failed` повторяются (max 3 попытки)
- Продолжается со следующего необработанного

---

## 6. Поток данных

```
Этап 1: Извлечение текста
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
book.pdf ──► extractor.py ──► raw_texts (dict глав)
              │
              ▼
           cleaner.py ──► clean_texts (числа→пропись, типографика)
              │
              ▼
           accents.py ──► fix_accents() ← RUAccent
              │           (за́мок/замо́к, му́ка/мука́)
              ▼
           chunker.py ──► chunks.json
                          [{id: 1, chapter: "Глава 1", text: "...", chars: 987},
                           {id: 2, chapter: "Глава 1", text: "...", chars: 1042},
                           ...]

Этап 2: Транскрипция референса
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
author.wav ──► preprocess.py ──► clean_author.wav
                  │
                  ▼
              GigaAM-v3 (e2e_rnnt, WER 8.4%) ──► reference_text.txt
                  │
              [если ошибка] ──► Qwen3-ASR-1.7B (fallback, легче Whisper)
                  │                      
                  ▼
          ⚠️ Ручная верификация текста (шаг между transcribe и clone)
          Пользователь правит ошибки распознавания → reference_text.verified.txt
          Без этой проверки ошибки транскрипции переходят в voice clone.

Этап 3: Клонирование голоса
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
clean_author.wav + reference_text.verified.txt
        │
        ▼
Qwen3-TTS-Base.generate_voice_clone() ──► voice_profile/
                                            ├── embedding.pt
                                            └── meta.json

Этап 4: Генерация книги
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
chunks.json + voice_profile ──► generator.py
                                   │
                            for each chunk:
                              Qwen3-TTS-Base → chapters/{id}.wav
                                   │
                              save_progress(resume.json)
                                   │
                              [Audio QA: детект тишины, клиппинга,
                               аномальной длительности]
                                   │
                                   ▼
                              chapters/
                              ├── 0001.wav
                              ├── 0002.wav
                              └── ...

Этап 5: Сборка аудиокниги
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
chapters/ ──► normalize.py (LUFS -16) ──► normalized/
                  │
                  ▼
              assemble.py ──► audiobook.mp3 / audiobook.m4b
```

---

## 7. Конфигурация

**config.yaml (итоговая версия):**
```yaml
project:
  name: VoxLibRus
  output_dir: ./output
  temp_dir: ./temp

book:
  extract:
    pdf_engine: pdfplumber
    epub_engine: ebooklib
    docx_engine: markitdown

reference:
  target_sample_rate: 24000
  noise_reduce: true
  trim_silence: true
  normalize_peak_db: -3

asr:
  primary: gigaam             # gigaam | whisper
  gigaam:
    model_id: ai-sage/GigaAM-v3
    revision: e2e_rnnt        # e2e_rnnt | e2e_ctc | ctc | rnnt | ssl
    device: cuda
  whisper:
    model_id: openai/whisper-large-v3
    device: cuda
    language: ru
  # Замена тяжелого Whisper-fallback на легкий Qwen3-ASR:
  # model_id: Qwen/Qwen3-ASR-1.7B (1.7B vs 3B)

tts:
  primary: qwen3              # qwen3 | f5tts
  qwen3:
    # Base — voice cloning из референса (3 сек) + генерация (PRIMARY)
    model_id: Qwen/Qwen3-TTS-12Hz-1.7B-Base
    device: cuda
    language: ru
    streaming: false          # false для батч-генерации книги
    # CustomVoice — 9 встроенных голосов + управление эмоциями (опц.)
    # model_id: Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
  f5tts:
    model_id: Misha24-10/F5-TTS_RUSSIAN
    device: cuda
    ref_audio_sample_rate: 24000

voice:
  profiles_dir: ~/.voxlib/speakers

generation:
  chunk_max_chars: 1000
  chunk_overlap_chars: 50
  save_every_n: 10
  clear_cache_every_n: 20
  max_retries: 3
  retry_delay: 5

audio:
  target_lufs: -16
  peak_dbfs: -1
  chapter_pause_sec: 2.5
  output:
    format: mp3               # mp3 | m4b | both
    mp3_bitrate: 192
```

---

## 8. Требования к оборудованию

### Минимальные (CPU-only, медленно):
| Компонент | Требование |
|---|---|
| CPU | 8+ ядер |
| RAM | 32 GB |
| VRAM | N/A (CPU) |
| Диск | 20 GB свободно |
| Время (300 стр) | > 50 часов |

### Рекомендуемые (GPU):
| Компонент | Требование |
|---|---|
| GPU | **6+ GB VRAM** (RTX 3060+) |
| CUDA | Compute Capability 7.0+ |
| RAM | 16 GB |
| Диск | 20 GB (модели ~5 GB + аудио ~10 GB) |
| **RTX 5060 Ti (16GB)** | ✅ Отлично |

### Оценка времени на RTX 5060 Ti (300 стр, ~80K слов):

| Этап | Время |
|---|---|
| Извлечение текста (PDF→фрагменты) | ~1-2 мин |
| Транскрипция референса (5-10 мин) | ~30 сек |
| Клонирование голоса | ~1-2 мин |
| **Генерация (Qwen3-TTS, ~600 фрагментов)** | **~2-3 часа** |
| **Генерация (F5-TTS_RUSSIAN, ~600 фрагментов)** | **~25-40 мин** |
| Постобработка + склейка | ~5-10 мин |
| **Итого (Qwen3)** | **~3 часа** |
| **Итого (F5-TTS)** | **~1 час** |

---

## 9. План реализации

### Этап 1: Базовый скелет (1 день)
- [ ] Структура проекта, pyproject.toml, requirements.txt
- [ ] config.py — загрузка конфигурации
- [ ] CLI main.py — базовая команда `voxlib`

### Этап 2: Текстовый слой (1 день)
- [ ] extractor.py — извлечение из PDF (+ тесты)
- [ ] extractor.py — EPUB, DOCX (+ тесты)
- [ ] cleaner.py — нормализация русского текста (+ тесты)
- [ ] chunker.py — фрагментация (+ тесты)

### Этап 3: ASR слой (1-2 дня)
- [ ] base.py — ASRInterface
- [ ] gigaam.py — GigaAM-v3 интеграция
- [ ] whisper.py — fallback
- [ ] Тест: транскрипция тестового аудио

### Этап 4: TTS слой — Qwen3 (2-3 дня)
- [ ] base.py — TTSInterface
- [ ] qwen3.py — Qwen3-TTS-CustomVoice
- [ ] voice/manager.py — управление голосовыми профилями
- [ ] voice/cloner.py — полный процесс клонирования
- [ ] audio/preprocess.py — подготовка референса
- [ ] Тест: клонирование + короткая генерация

### Этап 5: TTS слой — F5-TTS (1 день, опционально)
- [ ] f5tts.py — F5-TTS_RUSSIAN интеграция
- [ ] Переключение бэкендов через config

### Этап 6: Генерация книги (2 дня)
- [ ] generator.py с resume-механизмом
- [ ] utils/resume.py — прогресс-трекер
- [ ] utils/gpu.py — управление VRAM
- [ ] Пакетная обработка всей книги
- [ ] Тест: генерация 50 фрагментов

### Этап 7: Постобработка и сборка (1 день)
- [ ] audio/normalize.py — LUFS нормализация
- [ ] audio/assemble.py — склейка + экспорт
- [ ] Тест: сборка audiobook из 10 фрагментов

### Этап 8: Интеграция и тестирование (1-2 дня)
- [ ] pipeline.py — полный пайплайн
- [ ] CLI: voxlib run --book ... --reference ...
- [ ] Full test: книга 20 стр → audiobook
- [ ] README, примеры, документация

---

## 10. Риски и митигация

| Риск | P | I | Митигация |
|---|---|---|---|
| **Qwen3-TTS не устанавливается на Windows** | Средний | Высокий | Использовать портативную сборку timoncool/Qwen3-TTS_portable_rus |
| **GigaAM-v3 не работает через transformers** | Низкий | Средний | Fallback на Qwen3-ASR-1.7B (1.7B, Apache-2.0) — легче Whisper (3B) и не требует pyannote/torchcodec |
| **VRAM не хватает (Qwen3 ~6-8GB + GigaAM ~1-2GB)** | Средний | Средний | Последовательная загрузка: GigaAM → выгрузить → Qwen3. CPU-offload для текст. слоя |
| **Качество voice cloning хуже ожидаемого** | Средний | Высокий | F5-TTS как альтернативный бэкенд. Улучшить препроцессинг референса |
| **Генерация прерывается (отвал GPU, крах)** | Низкий | Средний | Resume-файл: потеря макс 1 фрагмента |
| **TTS генерирует «мусорный» чанк (тишина/клиппинг)** | Средний | Средний | **Audio QA** после каждого чанка: детект тишины, клиппинга, аномальной длительности |
| **Ошибки транскрипции референса → плохой clone** | Средний | Высокий | **Ручная верификация** reference_text.txt перед clone (шаг в CLI) |
| **Омографы без ударений (за́мок/замо́к)** | Высокий | Средний | **RUAccent** в текстовом пайплайне (обязательно, независимо от бэкенда) |
| **Опечатка в config.yaml → KeyError в рантайме** | Средний | Средний | **Pydantic-валидация** при старте: понятные сообщения об ошибках |
| **Лицензия CC-BY-NC для F5-TTS (некоммерческая)** | Низкий | Средний | Runtime-проверка: флаг commercial_use в config → блокировка f5tts. Основной — Qwen3 (Apache-2.0) |

---

## Приложение A: Зависимости

```txt
# Core
torch>=2.1.0
torchaudio>=2.1.0

# Text processing
pdfplumber>=0.10.0
ebooklib>=0.18
markitdown>=0.1.0
beautifulsoup4>=4.12
lxml>=5.0
num2words>=0.5.12

# ASR
transformers>=4.40.0
# GigaAM-v3: trust_remote_code=True (обрабатывается в коде)
# Whisper: встроен в transformers

# TTS - Qwen3-TTS
# Установка через pip из репозитория или transformers

# TTS - F5-TTS (опционально)
# f5-tts>=1.0.0

# Audio processing
pydub>=0.25.1
librosa>=0.10.0
soundfile>=0.12.1
noisereduce>=3.0.0
pyloudnorm>=0.1.1

# CLI
typer>=0.12.0
rich>=13.0.0
pyyaml>=6.0
tqdm>=4.66.0

# Testing
pytest>=8.0.0
pytest-cov>=4.1.0
```

## Приложение B: Быстрый старт (концепт)

```bash
# Установка (Windows — основная платформа)
cd F:\VoxLibRus
uv venv
.venv\Scripts\activate
uv pip install -e ".[qwen3]"  # или .[f5tts] для F5-TTS

# Или через pip:
python -m venv .venv
.venv\Scripts\activate
pip install -e .

# Одношаговый пайплайн
voxlib run ^
  --book book.pdf ^
  --reference author_sample.wav ^
  --output audiobook

# Поэтапно
voxlib extract --book book.pdf
voxlib transcribe --reference author.wav
voxlib clone --reference author.wav --ref-text reference.txt
voxlib generate --book-chunks chunks.json
voxlib assemble --output audiobook.mp3
```

---
