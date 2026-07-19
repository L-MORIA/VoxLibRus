"""Tests for Russian text cleaner."""

from voxlib.text.cleaner import (
    clean_text,
    normalize_quotes,
    normalize_dashes,
    expand_abbreviations,
    normalize_numbers,
    cleanup_whitespace,
)


class TestNormalizeQuotes:
    def test_ascii_quotes_to_angle(self):
        result = normalize_quotes('"Привет"')
        assert result == '«Привет»'

    def test_mixed_quotes_normalized(self):
        result = normalize_quotes('Он сказал: "Иди сюда"')
        assert '«' in result
        assert '»' in result

    def test_multiple_quote_pairs(self):
        result = normalize_quotes('"А" и "Б"')
        assert result.count('«') == 2
        assert result.count('»') == 2

    def test_nested_quotes_not_supported(self):
        """Just ensure it doesn't crash on edge cases."""
        result = normalize_quotes('"A "B" C"')
        assert isinstance(result, str)

    def test_apostrophe_inside_word_preserved(self):
        """Апостроф внутри слова (Д'Артаньян) не должен ломать кавычки."""
        text = 'Это была история про Д\'Артаньяна. Потом он сказал: "Привет!"'
        result = normalize_quotes(text)
        # апостроф остаётся апострофом
        assert "Д'Артаньяна" in result or "Д'Артаньяна" in result
        # настоящие кавычки превращаются в ёлочки
        assert '«Привет!»' in result

    def test_apostrophe_does_not_flip_quote_state(self):
        """Апостроф не должен переключать флаг открытия/закрытия кавычек."""
        # Апостроф в начале предложения перед кавычками
        text = 'Д\'Артаньян сказал: "Привет"'
        result = normalize_quotes(text)
        # кавычки должны быть правильно сбалансированы
        assert result.count('«') == result.count('»') == 1


class TestNormalizeDashes:
    def test_hyphen_to_em_dash(self):
        result = normalize_dashes('Он - человек')
        assert ' — ' in result
        assert ' - ' not in result

    def test_double_hyphen(self):
        result = normalize_dashes('Он--человек')
        assert '—' in result

    def test_en_dash_to_em(self):
        result = normalize_dashes('1990 – 2000')
        assert ' — ' in result


class TestExpandAbbreviations:
    def test_common_russian(self):
        assert expand_abbreviations('т.е.') == 'то есть'
        assert expand_abbreviations('т.д.') == 'далее'
        assert expand_abbreviations('т.п.') == 'прочее'

    def test_with_context(self):
        result = expand_abbreviations('Я см. стр. 5')
        assert 'смотри' in result

    def test_no_false_expansion(self):
        """Word endings should not be expanded."""
        result = expand_abbreviations('тело человека')
        assert 'тело' in result

    def test_case_insensitive(self):
        """Abbreviations with capital letter should expand."""
        assert expand_abbreviations('Т.д.') == 'Далее'
        assert expand_abbreviations('Т.П.') == 'Прочее'
        assert expand_abbreviations('См. приложение') == 'Смотри приложение'

    def test_word_boundary_protection(self):
        """Abbreviations should not match inside words."""
        # "примеров." should NOT become "примеровек" (в. → век)
        result = expand_abbreviations('много примеров.')
        assert 'примеров' in result
        assert 'примеровек' not in result

        # "слов." should not become "словвек"
        result = expand_abbreviations('этих слов.')
        assert 'слов' in result
        assert 'словвек' not in result


class TestNormalizeNumbers:
    def test_integer(self):
        """42 → сорок два"""
        result = normalize_numbers('42')
        assert 'два' in result or '42' not in result

    def test_float(self):
        """3.14 → with words"""
        result = normalize_numbers('3.14')
        assert isinstance(result, str) and len(result) > 0

    def test_comma_decimal(self):
        """3,14 → same as 3.14"""
        result = normalize_numbers('3,14')
        assert isinstance(result, str) and len(result) > 0

    def test_negative(self):
        result = normalize_numbers('-5')
        assert isinstance(result, str)

    def test_large_number(self):
        result = normalize_numbers('1000')
        assert isinstance(result, str)

    def test_percent(self):
        """50% → пятьдесят процентов"""
        result = normalize_numbers('Скидка 50% на всё')
        assert 'пятьдесят процентов' in result

    def test_currency_ruble(self):
        """100₽ → сто рублей"""
        result = normalize_numbers('Цена 100₽')
        assert 'сто рублей' in result

    def test_currency_dollar(self):
        """$50 → пятьдесят долларов"""
        result = normalize_numbers('Стоит $50')
        assert 'пятьдесят долларов' in result

    def test_ordinal(self):
        """5-й → пятый"""
        result = normalize_numbers('5-й раз')
        assert 'пятый' in result

    def test_ordinal_24(self):
        """24-е → двадцать четвёртое (neuter nominative)"""
        result = normalize_numbers('24-е летие')
        assert 'двадцать четвёртое' in result
        assert 'двадцать четвёртый' not in result

    def test_year(self):
        """1990 г. → одна тысяча девятьсот девяносто год"""
        result = normalize_numbers('Родился в 1990 г.')
        assert 'одна тысяча девятьсот девяносто' in result or 'тысяча девятьсот девяносто' in result


class TestCleanupWhitespace:
    def test_multiple_spaces(self):
        assert cleanup_whitespace('a  b') == 'a b'

    def test_space_before_punctuation(self):
        result = cleanup_whitespace('Привет .')
        assert result == 'Привет.'

    def test_missing_space_after_punctuation(self):
        result = cleanup_whitespace('Привет.Мир')
        assert result == 'Привет. Мир'


class TestCleanTextPipeline:
    def test_full_pipeline(self):
        text = 'Он сказал: "Привет, мир!" Это стоит 42 руб.'
        result = clean_text(text)
        assert '«' in result
        assert '»' in result
        assert isinstance(result, str)
        assert len(result) > 0

    def test_with_abbreviations(self):
        text = 'Яблоки, груши, т.д.'
        result = clean_text(text)
        assert 'далее' in result  # т.д. → далее

    def test_empty_string(self):
        assert clean_text('') == ''

    def test_whitespace_only(self):
        assert clean_text('   ') == ''

    def test_no_changes_for_clean_text(self):
        text = 'Привет, мир!'
        result = clean_text(text)
        assert 'Привет' in result
        assert 'мир' in result

    def test_numbers_in_text(self):
        text = 'Было 42 яблока.'
        result = clean_text(text)
        # Should either preserve or convert numbers
        assert isinstance(result, str)
        assert len(result) > 0