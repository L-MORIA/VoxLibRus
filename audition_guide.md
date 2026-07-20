# Adobe Audition 2021 — обработка аудиокниги VoxLibRus

## Предварительно: что на входе

Файл из пайплайна: `output/sherlock_bigvgan/sherlock_bigvgan.mp3`
Размер: ~3.2 MB, 24 kHz, моно, ~2.5 мин

## Шаг 1. Открыть файл

`File → Open →` выбрать MP3

## Шаг 2. Effects Rack — сохранить пресет один раз

1. `Window → Effects Rack` (если не открыт)
2. Кликнуть меню гамбургер (≡) в Effects Rack → `Save As Default...`

Добавляем эффекты по порядку (кнопка `+` → `Add`):

### 2.1 Adaptive Noise Reduction (шумодав)
`Effects → Noise Reduction → Adaptive Noise Reduction`
- Preset: `Noise` → `Low` (умеренный, не режет голос)
- Параметры: `Noise Level: -30 dB`, `Reduce By: 12 dB`
- Signal: галка только `Broadband`

### 2.2 Parametric Equalizer (эквалайзер)
`Effects → Filter and EQ → Parametric Equalizer`

| Band | Type | Frequency | Gain | Q (Width) |
|---|---|---|---|---|
| 1 | **High Pass** | **80 Hz** | — | **24 dB/oct** |
| 2 | **Low Shelf** | **150 Hz** | **+1.0 dB** | **0.7** |
| 3 | **Peak** | **3.5 kHz** | **+1.5 dB** | **1.0** |
| 4 | **High Shelf** | **10 kHz** | **+0.5 dB** | **0.7** |

Как выставить:
1. Дважды кликнуть на верхней панели EQ → появятся точки
2. Правая кнопка на точке → `Type` → выбрать тип
3. Перетаскивать или вводить цифры

### 2.3 Multiband Compressor (компрессор)
`Effects → Amplitude and Compression → Multiband Compressor`
- Сбросить все пресеты
- **All bands (кнопка Link внизу):**
  - Threshold: **-30 dB**
  - Ratio: **2.5:1**
  - Attack: **10 ms**
  - Release: **100 ms**
  - Make-up: **+6 dB**

### 2.4 Hard Limiter (лимитер — без клиппинга)
`Effects → Amplitude and Compression → Hard Limiter`
- **Max Amplitude: -3.0 dB**
- **Release: 10 ms**
- Галочка `Link Channels`

### 2.5 Сохранить как пресет

1. В Effects Rack кликнуть гамбургер (≡)
2. `Save Preset...`
3. Назвать: **VoxLibRus Finalize**
4. В следующий раз: открыть MP3 → Effects Rack → гамбургер → `Load Preset` → выбрать

## Шаг 3. Применить и экспортировать

1. `File → Export → Multitrack Mixdown → Entire Session`
ИЛИ (если Waveform view)
2. `File → Export → File...`
3. **Формат:** `MP3`, **320 kbps**, `CBR`, `Joint Stereo`
4. **Sample Rate:** `24000 Hz`
5. Назвать: `sherlock_final.mp3`

## Сравнение «до/после»

| Параметр | До (из пайплайна) | После Audition |
|---|---|---|
| Шум | Есть на паузах | Чистые паузы |
| «Провал» начала чанков | Слышен | Компрессор подтянет |
| Глубина | Плоская | Мягкая теплота |
| Клиппинг | Нет | Нет (лимитер -3 dB) |

## Важно: не переусердствуйте

- **Не делайте >+2 dB на EQ** — появится цифровой «песок»
- **Не режьте шум сильно** (`Reduce By > 15 dB`) — голос станет «стеклянным»
- **Ratio > 3:1** — появится «насос» (breathing)
- **Make-up > +8 dB** — шум поднимется
