# VoxLibRus

## Быстрый старт

```bash
pip install -e ".[dev]"
pip install num2words ebooklib pdfplumber
pytest tests/ -q
```

## CI/CD

Проект использует GitHub Actions для автоматической проверки:

- **Ruff** — линтинг и форматирование Python-кода
- **MyPy** — статическая проверка типов
- **Pytest** — запуск тестов (102+, все зеленые)

### Pre-commit hooks

```bash
pip install pre-commit
pre-commit install
```

После установки хуки будут автоматически проверять код перед каждым коммитом.

## Структура проекта

```
voxlib/          — основной код
tests/           — тесты
.github/workflows/ — CI/CD
```
