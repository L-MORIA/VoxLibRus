# VoxLibRus 🎙️📖

**Озвучка книг клонированным голосом автора. Русский язык. Высокое качество.**

Автор читает **5-30 секунд**, VoxLibRus клонирует голос через **F5-TTS_RUSSIAN** и генерирует аудиокнигу до **300+ страниц** (~9+ часов) с правильной расстановкой ударений через RUAccent.

---

## 🏆 Ключевые технологии

| Компонент | Модель | Качество RU | Лицензия |
|---|---|---|---|
| **ASR** (распознавание) | **GigaAM-v3** (Sber) | 8.4% WER ✅ | MIT |
| **TTS** (клонирование + генерация) | **F5-TTS_RUSSIAN** (+stress marks) | 5/5 ✅ | CC-BY-NC |
| TTS (опционально) | Qwen3-TTS-Base (без stress marks) | 4.5/5 | Apache-2.0 |
| **Ударения** | RUAccent + `+` нотация | ✅ омографы | MIT |

> ⚠️ **Лицензионное предупреждение:** Код проекта распространяется под Apache-2.0.  
> Однако TTS-модель по умолчанию (`F5-TTS_RUSSIAN`) имеет лицензию **CC-BY-NC-4.0** —  
> **не допускает коммерческое использование**. Для коммерческих проектов переключитесь  
> на `Qwen3-TTS-Base` (Apache-2.0) в `config.yaml`: `tts.primary: qwen3`.

---

## 📦 Установка

```bash
git clone https://github.com/L-MORIA/VoxLibRus.git
cd VoxLibRus
uv venv
.venv\Scripts\activate     # Windows
uv pip install -e .
```

## 🚀 Быстрый старт

### Полный пайплайн (одна команда)

```bash
voxlib run \
  --book book.pdf \
  --reference author.wav \
  --output my_audiobook
```

### Поэтапно

```bash
# 1. Извлечь текст из книги
voxlib extract --book book.pdf -o chapters.json

# 2. Транскрибировать референс (ASR)
voxlib transcribe --audio author.wav -o ref_text.txt

# 3. Клонировать голос
voxlib clone --audio author.wav --text ref_text.txt --name my_voice

# 4. Собрать аудиокнигу
voxlib assemble --chapters ./chapters -o audiobook.mp3
```

---

## 🔬 Почему новый проект?

Готовых open-source решений для русской аудиокниги с voice cloning **не существует**:

| Проект | ⭐ | Проблема для RU |
|---|---|---|
| **ebook2audiobook** | 19.5K | XTTS даёт 3/5 качества для RU |
| **GPT-SoVITS** | 59.9K | RU не primary, нет book pipeline |
| **Pandrator** | ~600 | Kokoro без RU, XTTS 3/5 |

VoxLibRus собирает **лучшие компоненты** в один пайплайн.

---

## 🧱 Архитектура

```
book.pdf ──► extractor ──► cleaner ──► accents ──► chunks ──► F5-TTS ──► audiobook.mp3
                              ▲           ▲
                        num2words,    RUAccent
                        quotes,       (+stress)
                        abbrevs

author.wav ──► preprocess ──► GigaAM-v3 ──► clone_voice() ──► voice_profile
                              (ASR 8.4%)
```

Подробно: [ARCHITECTURE.md](./ARCHITECTURE.md)

---

## 📋 CLI команды

| Команда | Описание | Статус |
|---|---|---|
| `voxlib run` | Полный пайплайн | ✅ |
| `voxlib extract` | Извлечение текста из PDF/EPUB/DOCX → chunks.json | ✅ |
| `voxlib transcribe` | ASR транскрипция референса (GigaAM-v3 / Whisper) | ✅ |
| `voxlib clone` | Клонирование голоса из аудио + текст | ✅ |
| `voxlib generate` | Генерация аудио по чанкам | 🚧 |
| `voxlib assemble` | Сборка WAV → MP3/M4B | ✅ |

---

## 📜 Лицензия

- **Основной код**: Apache-2.0
- **F5-TTS_RUSSIAN**: CC-BY-NC (некоммерческое)
- **GigaAM-v3**: MIT
- **RUAccent**: MIT

---

## 🧪 Статус тестов

```
95 passed, 2 skipped  |  ruff: All checks passed
```
